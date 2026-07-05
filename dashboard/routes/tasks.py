"""任务管理 API。"""
from __future__ import annotations

import sys

from flask import Blueprint, jsonify, request

from ..config import PROJECT_ROOT
from ..task_manager import task_manager
from ..utils import json_ok, json_error

tasks_bp = Blueprint("tasks", __name__)

# ════════════════════════════════════════
# 输入验证常量
# ════════════════════════════════════════
_VALID_STYLES = {"casual", "technical", "debate", "interview"}
_MAX_TOPIC_LENGTH = 200
_MAX_REPO_URLS = 20
_MAX_COUNT = 100
_MIN_COUNT = 1


def _validate_repo_urls(repo_urls):
    """验证仓库 URL 列表，返回 (urls, error_response)。"""
    if not repo_urls:
        return [], None
    if not isinstance(repo_urls, list):
        return None, json_error("repo_urls 必须是列表", 400)
    if len(repo_urls) > _MAX_REPO_URLS:
        return None, json_error(f"仓库 URL 数量不能超过 {_MAX_REPO_URLS} 个", 400)
    for url in repo_urls:
        if not isinstance(url, str) or not url.startswith("https://github.com/"):
            return None, json_error(f"无效的仓库 URL: {url}", 400)
    return repo_urls, None


def _validate_topic(topic):
    """验证主题关键词，返回 (topic, error_response)。"""
    if not topic:
        return "", None
    if not isinstance(topic, str):
        return None, json_error("topic 必须是字符串", 400)
    if len(topic) > _MAX_TOPIC_LENGTH:
        return None, json_error(f"主题关键词过长（最大 {_MAX_TOPIC_LENGTH} 字符）", 400)
    return topic, None


@tasks_bp.route("/run", methods=["POST"])
def run():
    data = request.get_json(silent=True) or {}
    mock_data = data.get("mock_data", False)
    dry_run = data.get("dry_run", False)
    repo_urls = data.get("repo_urls", [])
    topic = data.get("topic", "")
    style = data.get("style", "casual")
    longform = data.get("longform", False)

    # ── 输入验证 ──
    if style not in _VALID_STYLES:
        return json_error(f"无效的播客风格，可选值: {', '.join(sorted(_VALID_STYLES))}", 400)

    repo_urls, err = _validate_repo_urls(repo_urls)
    if err:
        return err

    topic, err = _validate_topic(topic)
    if err:
        return err

    # 构建 CLI 命令
    cmd = [sys.executable, str(PROJECT_ROOT / "main.py"), "run"]
    if mock_data:
        cmd.append("--mock-data")
    if dry_run:
        cmd.append("--dry-run")
    if style:
        cmd.extend(["--style", style])
    if longform:
        cmd.append("--longform")
    for url in repo_urls:
        cmd.extend(["--repo-urls", url])
    if topic:
        cmd.extend(["--topic", topic])

    with task_manager.lock:
        if task_manager.is_running():
            return json_error("已有任务在运行中", 409, action="cancel")
        task_manager.start_task("单期生成", cmd, str(PROJECT_ROOT))
    return json_ok(status="started", command=" ".join(cmd))


@tasks_bp.route("/batch", methods=["POST"])
def batch():
    with task_manager.lock:
        if task_manager.is_running():
            return json_error("已有任务在运行中", 409, action="cancel")
        data = request.get_json(silent=True) or {}
        count = data.get("count", 5)
        mock_data = data.get("mock_data", True)
        dry_run = data.get("dry_run", False)
        resume = data.get("resume", False)

        # ── 输入验证 ──
        if not isinstance(count, int) or count < _MIN_COUNT or count > _MAX_COUNT:
            return json_error(f"count 必须是 {_MIN_COUNT}-{_MAX_COUNT} 的整数", 400)

        cmd = [sys.executable, "main.py", "batch", "--count", str(count)]
        if mock_data:
            cmd.append("--mock-data")
        if dry_run:
            cmd.append("--dry-run")
        if resume:
            cmd.append("--resume")

        task_manager.start_task(f"批量生成 {count} 期", cmd, str(PROJECT_ROOT))
    return json_ok(status="started", command=" ".join(cmd))


@tasks_bp.route("/task/status")
def task_status():
    return jsonify(task_manager.get_status())


@tasks_bp.route("/task/cancel", methods=["POST"])
def task_cancel():
    """取消当前正在运行的任务。"""
    with task_manager.lock:
        cancelled = task_manager.cancel_task()
    if cancelled:
        return json_ok(status="cancelled", message="任务已取消")
    return json_error("当前没有正在运行的任务", 400)


@tasks_bp.route("/task/reset", methods=["POST"])
def task_reset():
    """强制重置任务状态（用于卡死的情况）。"""
    with task_manager.lock:
        task_manager.force_reset()
    return json_ok(status="reset", message="任务状态已重置")
