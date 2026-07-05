"""搜索 API — 跨节目标题、仓库名、脚本内容全文检索。

使用 tantivy 全文搜索引擎（BM25 评分 + 倒排索引）替代线性扫描。
tantivy 不可用时自动降级到线性扫描。
"""
from __future__ import annotations

from flask import Blueprint, request

from ..config import PROJECT_ROOT
from ..utils import json_ok, json_error
from src.search_index import SearchIndex

search_bp = Blueprint("search", __name__)

# 全局 SearchIndex 实例（惰性初始化，跨请求复用索引）
_search_index: SearchIndex | None = None


def _get_search_index() -> SearchIndex:
    """获取或创建全局 SearchIndex 实例。"""
    global _search_index
    if _search_index is None:
        _search_index = SearchIndex(PROJECT_ROOT)
    return _search_index


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
        score — BM25 相关度分数（tantivy 模式下 > 0）
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

    idx = _get_search_index()
    results = idx.search(q, limit=limit)

    return json_ok(results, total=len(results), query=q)
