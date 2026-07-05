"""全文搜索索引模块 — 使用 tantivy 替代线性扫描。

tantivy 是 Rust 实现的全文搜索引擎（类似 Lucene），提供：
  - BM25 相关度评分（替代手工 substring 匹配）
  - 倒排索引（替代 O(n) 逐条扫描脚本文件）
  - 内置 CJK 分词（中文按字符切分，无需额外分词器）

索引策略：
  - 索引存储在 output/.search_index/ 目录
  - 首次搜索时自动构建索引；后续通过 history.json 的 mtime 判断是否需要重建
  - 索引字段：episode_number, title, repo_names, script_text, audio_path, ...
  - 搜索使用 parse_query_lenient 容错解析（处理特殊字符）

降级策略：
  - tantivy 不可用或索引损坏时，自动回退到线性扫描
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

try:
    import tantivy
    _TANTIVY_AVAILABLE = True
except ImportError:
    _TANTIVY_AVAILABLE = False

from src.logger import get_logger

logger = get_logger(__name__)


class SearchIndex:
    """基于 tantivy 的全文搜索索引。

    用法：
        idx = SearchIndex(project_root)
        results = idx.search("python fastapi", limit=10)
    """

    def __init__(self, project_root: Path | str):
        self.project_root = Path(project_root)
        self.index_path = self.project_root / "output" / ".search_index"
        self.history_path = self.project_root / "output" / "episodes_history.json"
        self.scripts_dir = self.project_root / "output" / "scripts"
        self._index: Any = None
        self._searcher: Any = None
        self._indexed_count: int = 0

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 50) -> list[dict]:
        """搜索节目，返回按相关度排序的结果列表。

        每条结果包含：
            episode_number, title, repo_names, duration_seconds,
            total_chars, audio_path, published_at,
            matched_in — 命中字段 ("title" | "repo" | "script")
            snippet — 命中片段
            score — BM25 相关度分数

        降级策略：
            1. tantivy 不可用 → 线性扫描
            2. tantivy 搜索异常 → 线性扫描
            3. tantivy 返回 0 结果（CJK 分词限制） → 线性扫描补查
        """
        if not _TANTIVY_AVAILABLE:
            return self._fallback_search(query, limit)

        try:
            self._ensure_index()
            if self._index is None:
                return self._fallback_search(query, limit)

            results = self._tantivy_search(query, limit)
            # tantivy CJK 分词可能导致多字中文词查不到（如"语音合成"），
            # 此时用线性扫描补查（substring 匹配不受分词限制）
            if not results:
                return self._fallback_search(query, limit)
            return results
        except Exception as e:
            logger.error(f"tantivy 搜索失败，回退线性扫描: {e}")
            return self._fallback_search(query, limit)

    def rebuild(self) -> int:
        """强制重建索引，返回索引文档数。"""
        if not _TANTIVY_AVAILABLE:
            return 0
        return self._build_index()

    # ------------------------------------------------------------------
    # 索引管理
    # ------------------------------------------------------------------
    def _ensure_index(self) -> None:
        """确保索引存在且是最新的（按 history.json mtime 判断）。"""
        if self._needs_rebuild():
            self._build_index()

    def _needs_rebuild(self) -> bool:
        """判断是否需要重建索引。"""
        # 索引目录不存在 → 需要构建
        if not self.index_path.exists():
            return True

        # history.json 不存在 → 无法构建
        if not self.history_path.exists():
            return True

        # 索引已加载且 history 未更新 → 不需要
        if self._index is not None and self._searcher is not None:
            history_mtime = self.history_path.stat().st_mtime
            meta_path = self.index_path / ".meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta.get("history_mtime", 0) >= history_mtime:
                        return False
                except (json.JSONDecodeError, OSError):
                    pass

        # 尝试打开已有索引
        try:
            self._index = tantivy.Index.open(str(self.index_path))
            self._index.reload()
            self._searcher = self._index.searcher()
            # 检查索引中的文档数是否与 history 一致
            history = self._load_history()
            if self._searcher.num_docs == len(history):
                return False
        except Exception as e:
            logger.warning("索引操作失败: %s", e)

        return True

    def _build_index(self) -> int:
        """构建 tantivy 索引。"""
        # 清理旧索引
        if self.index_path.exists():
            shutil.rmtree(self.index_path)
        self.index_path.mkdir(parents=True, exist_ok=True)

        # 定义 Schema
        schema_builder = tantivy.SchemaBuilder()
        schema_builder.add_integer_field("episode_number", stored=True)
        schema_builder.add_text_field("title", stored=True, tokenizer_name="default")
        schema_builder.add_text_field("repo_names", stored=True, tokenizer_name="default")
        schema_builder.add_text_field("script_text", stored=True, tokenizer_name="default")
        schema_builder.add_text_field("audio_path", stored=True, tokenizer_name="default")
        schema_builder.add_float_field("duration_seconds", stored=True)
        schema_builder.add_integer_field("total_chars", stored=True)
        schema_builder.add_text_field("published_at", stored=True, tokenizer_name="default")
        schema = schema_builder.build()

        # 创建索引
        self._index = tantivy.Index(schema, path=str(self.index_path))
        writer = self._index.writer()

        # 加载历史数据
        history = self._load_history()
        count = 0

        for ep in history:
            ep_num = ep.get("episode_number", 0)
            title = ep.get("title", "")
            repo_names = " · ".join(ep.get("repo_names", []) or [])
            script_text = self._load_script_text(ep_num, title)
            doc = tantivy.Document(
                episode_number=ep_num,
                title=title,
                repo_names=repo_names,
                script_text=script_text,
                audio_path=ep.get("audio_path", ""),
                duration_seconds=float(ep.get("duration_seconds", 0)),
                total_chars=int(ep.get("total_chars", 0)),
                published_at=ep.get("published_at", ""),
            )
            writer.add_document(doc)
            count += 1

        writer.commit()
        # 释放 writer（tantivy 要求同一时刻只有一个 writer）
        del writer

        # 写入元数据
        meta_path = self.index_path / ".meta.json"
        history_mtime = self.history_path.stat().st_mtime if self.history_path.exists() else 0
        meta_path.write_text(
            json.dumps({"history_mtime": history_mtime, "doc_count": count}),
            encoding="utf-8",
        )

        # 重新加载索引
        self._index.reload()
        self._searcher = self._index.searcher()
        self._indexed_count = count
        logger.info(f"索引构建完成: {count} 条文档")
        return count

    # ------------------------------------------------------------------
    # tantivy 搜索
    # ------------------------------------------------------------------
    def _tantivy_search(self, query: str, limit: int) -> list[dict]:
        """使用 tantivy 执行全文搜索。"""
        q_lower = query.lower()
        # 使用 lenient 解析（容错：处理中文、特殊字符）
        # parse_query_lenient 返回 (Query, [parsing_errors])
        try:
            parsed, _errors = self._index.parse_query_lenient(query)
        except Exception as e:
            logger.warning("索引操作失败: %s", e)
            parsed = self._index.parse_query(query)

        results_hits = self._searcher.search(parsed, limit=limit)
        results = []

        for score, doc_address in results_hits.hits:
            doc = self._searcher.doc(doc_address)
            # tantivy Document: doc["field"] 返回 list，doc.get_first("field") 返回首个值
            def _get(field: str, default=""):
                """安全获取文档字段值。"""
                try:
                    vals = doc[field]
                    return vals[0] if vals else default
                except (KeyError, IndexError):
                    return default

            ep_num = int(_get("episode_number", 0))
            title = str(_get("title", ""))
            repo_names_str = str(_get("repo_names", ""))
            script_text = str(_get("script_text", ""))
            audio_path = str(_get("audio_path", ""))
            duration = float(_get("duration_seconds", 0.0))
            total_chars = int(_get("total_chars", 0))
            published_at = str(_get("published_at", ""))

            # 确定 matched_in 优先级（保持与旧实现一致：title > repo > script）
            matched_in = None
            snippet = ""
            if q_lower in title.lower():
                matched_in = "title"
                snippet = title
            elif q_lower in repo_names_str.lower():
                matched_in = "repo"
                snippet = repo_names_str
            elif q_lower in script_text.lower():
                matched_in = "script"
                snippet = self._extract_snippet(script_text, q_lower)

            # 如果 substring 未命中但 tantivy BM25 命中（分词匹配），
            # 仍按优先级标记命中字段
            if not matched_in:
                if title:
                    matched_in = "title"
                    snippet = title
                elif repo_names_str:
                    matched_in = "repo"
                    snippet = repo_names_str
                else:
                    matched_in = "script"
                    snippet = script_text[:120] if script_text else ""

            repo_names_list = repo_names_str.split(" · ") if repo_names_str else []

            results.append({
                "episode_number": ep_num,
                "title": title,
                "repo_names": repo_names_list,
                "duration_seconds": duration,
                "total_chars": total_chars,
                "audio_path": audio_path,
                "published_at": published_at,
                "matched_in": matched_in,
                "snippet": snippet,
                "score": float(score),
            })

        # 排序：matched_in 优先级 → BM25 分数 → episode_number
        priority = {"title": 0, "repo": 1, "script": 2}
        results.sort(key=lambda r: (
            priority.get(r["matched_in"], 9),
            -r.get("score", 0),
            -r["episode_number"],
        ))

        return results[:limit]

    # ------------------------------------------------------------------
    # 降级：线性扫描（与旧实现一致）
    # ------------------------------------------------------------------
    def _fallback_search(self, query: str, limit: int) -> list[dict]:
        """tantivy 不可用时的线性扫描降级方案。"""
        history = self._load_history()
        q_lower = query.lower()
        results = []

        for ep in history:
            ep_num = ep.get("episode_number", 0)
            title = ep.get("title", "")
            repo_names = ep.get("repo_names", []) or []

            matched_in = None
            snippet = ""

            if q_lower in title.lower():
                matched_in = "title"
                snippet = title
            elif any(q_lower in (r or "").lower() for r in repo_names):
                matched_in = "repo"
                snippet = " · ".join(repo_names)
            else:
                script_text = self._load_script_text(ep_num, title)
                if script_text and q_lower in script_text.lower():
                    matched_in = "script"
                    snippet = self._extract_snippet(script_text, q_lower)

            if matched_in:
                results.append({
                    "episode_number": ep_num,
                    "title": title,
                    "repo_names": repo_names,
                    "duration_seconds": ep.get("duration_seconds", 0),
                    "total_chars": ep.get("total_chars", 0),
                    "audio_path": ep.get("audio_path", ""),
                    "published_at": ep.get("published_at", ""),
                    "matched_in": matched_in,
                    "snippet": snippet,
                    "score": 0.0,
                })

        priority = {"title": 0, "repo": 1, "script": 2}
        results.sort(key=lambda r: (priority.get(r["matched_in"], 9), -r["episode_number"]))
        return results[:limit]

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _load_history(self) -> list[dict]:
        """加载 episode history。"""
        if not self.history_path.exists():
            return []
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _load_script_text(self, ep_num: int, ep_title: str) -> str:
        """加载脚本文本。"""
        if not self.scripts_dir.exists():
            return ""
        scripts = sorted(
            self.scripts_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for s in scripts:
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                continue
            if data.get("episode_number") == ep_num:
                return self._script_to_text(data)
            if "episode_number" not in data and ep_title and data.get("title") == ep_title:
                return self._script_to_text(data)
        return ""

    @staticmethod
    def _script_to_text(data: dict) -> str:
        """将脚本 JSON 的所有段落文本拼接为纯文本。"""
        segments = data.get("segments", [])
        return "\n".join(seg.get("text", "") for seg in segments)

    @staticmethod
    def _extract_snippet(full_text: str, q_lower: str) -> str:
        """提取关键词周围的上下文片段。"""
        idx = full_text.lower().find(q_lower)
        if idx < 0:
            return full_text[:120] if full_text else ""
        start = max(0, idx - 60)
        end = min(len(full_text), idx + len(q_lower) + 60)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(full_text) else ""
        return prefix + full_text[start:end] + suffix
