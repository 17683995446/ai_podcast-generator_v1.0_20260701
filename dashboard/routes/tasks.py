"""任务管理 API。"""
from __future__ import annotations

import sys

from flask import Blueprint, jsonify, request

from ..config import PROJECT_ROOT
from ..task_manager import task_manager

tasks_bp = Blueprint("tasks", __name__)


@tasks_bp.route("/run", methods=["POST"])
def run():
    data = request.get_json(silent=True) or {}
    mock_data = data.get("mock_data", False)
    dry_run = data.get("dry_run", False)
    repo_urls = data.get("repo_urls", [])
    topic = data.get("topic", "")
    style = data.get("style", "casual")
    longform = data.get("longform", False)

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
            return jsonify({"error": "已有任务在运行中"}), 409
        task_manager.start_task("单期生成", cmd, str(PROJECT_ROOT))
    return jsonify({"status": "started", "command": " ".join(cmd)})


@tasks_bp.route("/batch", methods=["POST"])
def batch():
    with task_manager.lock:
        if task_manager.is_running():
            return jsonify({"error": "已有任务在运行中"}), 409
        data = request.get_json(silent=True) or {}
        count = data.get("count", 5)
        mock_data = data.get("mock_data", True)
        dry_run = data.get("dry_run", False)
        resume = data.get("resume", False)

        cmd = [sys.executable, "main.py", "batch", "--count", str(count)]
        if mock_data:
            cmd.append("--mock-data")
        if dry_run:
            cmd.append("--dry-run")
        if resume:
            cmd.append("--resume")

        task_manager.start_task(f"批量生成 {count} 期", cmd, str(PROJECT_ROOT))
    return jsonify({"status": "started", "command": " ".join(cmd)})


@tasks_bp.route("/task/status")
def task_status():
    return jsonify(task_manager.get_status())


@tasks_bp.route("/task/cancel", methods=["POST"])
def task_cancel():
    """取消当前正在运行的任务。"""
    with task_manager.lock:
        cancelled = task_manager.cancel_task()
    if cancelled:
        return jsonify({"status": "cancelled", "message": "任务已取消"})
    return jsonify({"status": "not_running", "message": "当前没有正在运行的任务"}), 400


@tasks_bp.route("/task/reset", methods=["POST"])
def task_reset():
    """强制重置任务状态（用于卡死的情况）。"""
    with task_manager.lock:
        task_manager.force_reset()
    return jsonify({"status": "reset", "message": "任务状态已重置"})
