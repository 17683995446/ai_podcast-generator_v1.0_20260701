"""RSS Feed + 音频文件服务。"""
from __future__ import annotations

from flask import Blueprint, jsonify, send_file, send_from_directory

from ..config import EPISODES_DIR, FEED_PATH

media_bp = Blueprint("media", __name__)


@media_bp.route("/api/feed")
def feed():
    if FEED_PATH.exists():
        return send_file(str(FEED_PATH), mimetype="application/rss+xml")
    return jsonify({"error": "RSS feed 不存在"}), 404


@media_bp.route("/audio/<path:filename>")
def serve_audio(filename: str):
    return send_from_directory(str(EPISODES_DIR), filename)
