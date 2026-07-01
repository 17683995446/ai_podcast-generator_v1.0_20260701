"""统计 API。"""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..config import load_history
from ..task_manager import task_manager

stats_bp = Blueprint("stats", __name__)


@stats_bp.route("/stats")
def get_stats():
    history = load_history()
    total_duration = sum(ep.get("duration_seconds", 0) for ep in history)
    total_chars = sum(ep.get("total_chars", 0) for ep in history)
    total_size = sum(ep.get("file_size_bytes", 0) for ep in history)
    running = task_manager.is_running()
    recent_log = task_manager.get_log_tail(20)
    return jsonify({
        "episodes": len(history),
        "total_duration_min": round(total_duration / 60, 1),
        "total_chars": total_chars,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "task_running": running,
        "task_log": recent_log,
    })
