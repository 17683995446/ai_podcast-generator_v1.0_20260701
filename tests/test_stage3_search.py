"""Stage 3 单元测试：验证 tantivy 全文搜索索引。

覆盖范围：
  1. SearchIndex — 索引构建、搜索、降级策略
  2. 降级搜索 — 线性扫描兜底
  3. 工具方法 — snippet 提取、脚本文本拼接

运行：python -m pytest tests/test_stage3_search.py -v
"""
import sys
import json
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.search_index import SearchIndex, _TANTIVY_AVAILABLE


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def create_test_data(root: Path) -> None:
    """在指定目录创建测试用的 history 和 scripts 数据。"""
    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建 episodes_history.json
    history = [
        {
            "episode_number": 1,
            "title": "Python FastAPI 播客",
            "repo_names": ["tiangolo/fastapi", "encode/django"],
            "duration_seconds": 300.5,
            "total_chars": 5000,
            "audio_path": "output/episodes/ep01.mp3",
            "published_at": "2024-01-01",
        },
        {
            "episode_number": 2,
            "title": "Rust 性能优化",
            "repo_names": ["tokio-rs/tokio", "serde-rs/serde"],
            "duration_seconds": 250.0,
            "total_chars": 4000,
            "audio_path": "output/episodes/ep02.mp3",
            "published_at": "2024-01-08",
        },
        {
            "episode_number": 3,
            "title": "Go 微服务架构",
            "repo_names": ["gin-gonic/gin", "spf13/cobra"],
            "duration_seconds": 280.0,
            "total_chars": 4500,
            "audio_path": "output/episodes/ep03.mp3",
            "published_at": "2024-01-15",
        },
    ]
    (output_dir / "episodes_history.json").write_text(
        json.dumps(history, ensure_ascii=False), encoding="utf-8"
    )

    # 创建脚本文件
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    script_1 = {
        "episode_number": 1,
        "title": "Python FastAPI 播客",
        "segments": [
            {"speaker": "Host", "text": "今天我们来聊聊 FastAPI 这个 Python Web 框架。", "emotion": "excited"},
            {"speaker": "Guest", "text": "FastAPI 基于 Starlette 和 Pydantic，性能非常出色。", "emotion": "neutral"},
            {"speaker": "Host", "text": "它的异步支持怎么样？", "emotion": "curious"},
        ],
    }
    (scripts_dir / "script_001.json").write_text(
        json.dumps(script_1, ensure_ascii=False), encoding="utf-8"
    )

    script_2 = {
        "episode_number": 2,
        "title": "Rust 性能优化",
        "segments": [
            {"speaker": "Host", "text": "Rust 的内存安全特性太棒了。", "emotion": "excited"},
            {"speaker": "Guest", "text": "Tokio 异步运行时是 Rust 生态的核心。", "emotion": "neutral"},
        ],
    }
    (scripts_dir / "script_002.json").write_text(
        json.dumps(script_2, ensure_ascii=False), encoding="utf-8"
    )

    script_3 = {
        "episode_number": 3,
        "title": "Go 微服务架构",
        "segments": [
            {"speaker": "Host", "text": "Go 语言的并发模型非常适合微服务。", "emotion": "excited"},
            {"speaker": "Guest", "text": "Gin 框架是 Go 中最流行的 Web 框架之一。", "emotion": "neutral"},
        ],
    }
    (scripts_dir / "script_003.json").write_text(
        json.dumps(script_3, ensure_ascii=False), encoding="utf-8"
    )


# ═══════════════════════════════════════════════════════════════
# 1. SearchIndex 测试
# ═══════════════════════════════════════════════════════════════


class TestSearchIndex:
    """测试 tantivy 全文搜索索引。"""

    def test_build_index(self, tmp_path):
        """索引构建正确。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        count = idx.rebuild()
        assert count == 3

    def test_search_title_match(self, tmp_path):
        """标题匹配搜索。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        results = idx.search("Python", limit=10)
        assert len(results) > 0
        # EP1 标题含 "Python"，应排在前面
        ep1_results = [r for r in results if r["episode_number"] == 1]
        assert len(ep1_results) > 0
        assert ep1_results[0]["matched_in"] == "title"

    def test_search_repo_match(self, tmp_path):
        """仓库名匹配搜索。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        results = idx.search("fastapi", limit=10)
        assert len(results) > 0
        ep1_results = [r for r in results if r["episode_number"] == 1]
        assert len(ep1_results) > 0

    def test_search_script_match(self, tmp_path):
        """脚本全文匹配搜索。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        results = idx.search("Tokio", limit=10)
        assert len(results) > 0
        ep2_results = [r for r in results if r["episode_number"] == 2]
        assert len(ep2_results) > 0
        # "Tokio" 出现在 repo 名称和脚本文本中，优先级 repo > script
        assert ep2_results[0]["matched_in"] in ("script", "title", "repo")

    def test_search_returns_score(self, tmp_path):
        """tantivy 搜索结果包含 BM25 分数。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        results = idx.search("Python", limit=10)
        if _TANTIVY_AVAILABLE and results:
            assert "score" in results[0]
            assert results[0]["score"] >= 0.0

    def test_search_limit(self, tmp_path):
        """limit 参数限制返回数量。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        results = idx.search("框架", limit=1)
        assert len(results) <= 1

    def test_search_empty_query_fallback(self, tmp_path):
        """空查询不会崩溃（由 API 层拦截，但索引层也应安全）。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()
        # tantivy 对空查询可能返回空或报错，都应安全处理
        results = idx.search("", limit=10)
        assert isinstance(results, list)

    def test_search_cjk_fallback(self, tmp_path):
        """CJK 多字词查不到时降级到线性扫描。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        # "微服务" 是 CJK 多字词，tantivy 默认分词可能查不到
        # 应回退到线性扫描并找到 EP3
        results = idx.search("微服务", limit=10)
        ep3_results = [r for r in results if r["episode_number"] == 3]
        assert len(ep3_results) > 0

    def test_rebuild_after_update(self, tmp_path):
        """更新 history 后重建索引。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        idx.rebuild()

        # 添加新节目
        history_path = tmp_path / "output" / "episodes_history.json"
        history = json.loads(history_path.read_text(encoding="utf-8"))
        history.append({
            "episode_number": 4,
            "title": "New Episode",
            "repo_names": ["new/repo"],
            "duration_seconds": 200.0,
            "total_chars": 3000,
            "audio_path": "output/episodes/ep04.mp3",
            "published_at": "2024-01-22",
        })
        history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

        # 重建索引
        count = idx.rebuild()
        assert count == 4

        # 搜索新节目
        results = idx.search("New Episode", limit=10)
        ep4_results = [r for r in results if r["episode_number"] == 4]
        assert len(ep4_results) > 0

    def test_index_persistence(self, tmp_path):
        """索引持久化到磁盘，重新打开可用。"""
        create_test_data(tmp_path)
        idx1 = SearchIndex(tmp_path)
        idx1.rebuild()

        # 创建新实例，应能复用已有索引
        idx2 = SearchIndex(tmp_path)
        results = idx2.search("Python", limit=10)
        assert len(results) > 0


# ═══════════════════════════════════════════════════════════════
# 2. 降级搜索测试
# ═══════════════════════════════════════════════════════════════


class TestFallbackSearch:
    """测试线性扫描降级方案。"""

    def test_fallback_finds_title(self, tmp_path):
        """降级搜索能找到标题匹配。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        results = idx._fallback_search("Python", limit=10)
        assert len(results) > 0
        ep1 = [r for r in results if r["episode_number"] == 1]
        assert len(ep1) > 0
        assert ep1[0]["matched_in"] == "title"

    def test_fallback_finds_repo(self, tmp_path):
        """降级搜索能找到仓库名匹配。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        # "cobra" 只出现在 repo 名 "spf13/cobra" 中，不在标题中
        results = idx._fallback_search("cobra", limit=10)
        assert len(results) > 0
        ep3 = [r for r in results if r["episode_number"] == 3]
        assert len(ep3) > 0
        assert ep3[0]["matched_in"] == "repo"

    def test_fallback_finds_script(self, tmp_path):
        """降级搜索能找到脚本全文匹配。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        results = idx._fallback_search("异步运行时", limit=10)
        assert len(results) > 0
        ep2 = [r for r in results if r["episode_number"] == 2]
        assert len(ep2) > 0
        assert ep2[0]["matched_in"] == "script"
        assert ep2[0]["snippet"]  # 非空 snippet

    def test_fallback_priority_ordering(self, tmp_path):
        """降级搜索结果按 title > repo > script 排序。"""
        create_test_data(tmp_path)
        idx = SearchIndex(tmp_path)
        results = idx._fallback_search("Python", limit=10)
        if len(results) > 1:
            priority = {"title": 0, "repo": 1, "script": 2}
            for i in range(len(results) - 1):
                assert priority.get(results[i]["matched_in"], 9) <= priority.get(results[i + 1]["matched_in"], 9)


# ═══════════════════════════════════════════════════════════════
# 3. 工具方法测试
# ═══════════════════════════════════════════════════════════════


class TestSearchUtils:
    """测试搜索工具方法。"""

    def test_extract_snippet_found(self):
        """snippet 提取包含关键词上下文。"""
        text = "这是一段很长的文本，其中包含了关键词Python，周围还有其他内容。"
        snippet = SearchIndex._extract_snippet(text, "python")
        assert "Python" in snippet

    def test_extract_snippet_not_found(self):
        """关键词不存在时返回文本开头。"""
        text = "这是一段文本，不包含关键词。"
        snippet = SearchIndex._extract_snippet(text, "nonexistent")
        assert snippet  # 非空

    def test_extract_snippet_empty_text(self):
        """空文本返回空字符串。"""
        snippet = SearchIndex._extract_snippet("", "query")
        assert snippet == ""

    def test_script_to_text(self):
        """脚本 JSON 转纯文本。"""
        data = {
            "segments": [
                {"text": "第一段对话"},
                {"text": "第二段对话"},
                {"text": "第三段对话"},
            ]
        }
        text = SearchIndex._script_to_text(data)
        assert "第一段对话" in text
        assert "第二段对话" in text
        assert "第三段对话" in text

    def test_script_to_text_empty(self):
        """空脚本返回空字符串。"""
        text = SearchIndex._script_to_text({})
        assert text == ""


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
