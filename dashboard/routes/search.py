"""搜索 API — 跨节目标题、仓库名、脚本内容全文检索。"""
from __future__ import annotations

import json

from flask import Blueprint, request

from ..config import SCRIPTS_DIR, load_history
from ..utils import json_ok, json_error

search_bp = Blueprint("search", __name__)


@search_bp.route("/search")
def search_episodes():
    """搜索节目。

    查询参数:
        q  — 搜索关键词（必填）
        limit — 返回条数上限（可选，默认 50）

    搜索范围:
        1. 节目标题 (title)
        2. 仓库名称 (repo_names)
        3. 脚本全文 (script segments text)

    返回按相关度排序的结果列表，每条含:
        episode_number, title, repo_names, duration_seconds,
        matched_in — 命中字段 ("title" | "repo" | "script")
        snippet — 命中片段（仅 script 命中时非空）
    """
    q = request.args.get("q") or ""
    # 修复浏览器 URL 参数的 Latin-1 → UTF-8 解码问题
    # （Werkzeug 默认以 Latin-1 解码查询字符串，浏览器发送的 UTF-8 编码会乱码）
    try:
        q = q.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass  # 已是正确的 UTF-8 字符串，无需转换
    q = q.strip()
    if not q:
        return json_error("缺少搜索关键词参数 q", 400)

    limit = request.args.get("limit", 50, type=int)
    limit = max(1, min(limit, 200))

    history = load_history()
    q_lower = q.lower()

    # 预加载脚本索引（惰性：仅当标题/仓库名未命中时才读脚本）
    results = []

    for ep in history:
        ep_num = ep.get("episode_number", 0)
        title = ep.get("title", "")
        repo_names = ep.get("repo_names", []) or []

        matched_in = None
        snippet = ""

        # 优先级 1：标题命中
        if q_lower in title.lower():
            matched_in = "title"
            snippet = title

        # 优先级 2：仓库名命中
        elif any(q_lower in (r or "").lower() for r in repo_names):
            matched_in = "repo"
            snippet = " · ".join(repo_names)

        # 优先级 3：脚本全文命中（按需加载）
        else:
            script_text, script_data = _load_script_text(ep_num, title)
            if script_text and q_lower in script_text.lower():
                matched_in = "script"
                snippet = _extract_snippet(script_text, q_lower, script_data)

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
            })

    # 标题命中排序最前，其次仓库名，最后脚本
    priority = {"title": 0, "repo": 1, "script": 2}
    results.sort(key=lambda r: (priority.get(r["matched_in"], 9), -r["episode_number"]))

    return json_ok(results[:limit], total=len(results), query=q)


# ════════════════════════════════════════
# 内部工具函数
# ════════════════════════════════════════

def _load_script_text(ep_num: int, ep_title: str):
    """惰性加载脚本文本，返回 (纯文本, 原始JSON)。"""
    if not SCRIPTS_DIR.exists():
        return None, None

    scripts = sorted(SCRIPTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for s in scripts:
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            continue

        if data.get("episode_number") == ep_num:
            return _script_to_text(data), data
        if "episode_number" not in data and ep_title and data.get("title") == ep_title:
            return _script_to_text(data), data

    return None, None


def _script_to_text(data: dict) -> str:
    """将脚本 JSON 的所有段落文本拼接为纯文本。"""
    segments = data.get("segments", [])
    return "\n".join(seg.get("text", "") for seg in segments)


def _extract_snippet(full_text: str, q_lower: str, script_data: dict | None) -> str:
    """提取关键词周围的上下文片段（前后各 ~60 字）。"""
    idx = full_text.lower().find(q_lower)
    if idx < 0:
        return ""

    start = max(0, idx - 60)
    end = min(len(full_text), idx + len(q_lower) + 60)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(full_text) else ""
    return prefix + full_text[start:end] + suffix
