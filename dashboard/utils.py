"""API 响应标准化帮助函数。

统一所有路由的 JSON 响应格式，避免散落的 jsonify + 手动构造。
"""
from __future__ import annotations

from flask import jsonify


def json_ok(data=None, **extra):
    """成功响应。

    >>> json_ok({"episodes": []})
    >>> json_ok(message="任务已启动")
    """
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def json_error(message: str, status: int = 400, **extra):
    """错误响应。

    >>> json_error("参数缺失", 400)
    >>> json_error("已有任务运行中", 409, action="cancel")
    """
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def json_or_empty(data: dict | list | None):
    """返回数据或空容器，避免 None 导致前端崩溃。"""
    if data is None:
        return jsonify([]) if isinstance(data, list) else jsonify({})
    return jsonify(data)
