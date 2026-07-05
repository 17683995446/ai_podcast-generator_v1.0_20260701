"""节目相关 API。"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify

from ..config import ANALYSES_DIR, SCRIPTS_DIR, load_history
from ..utils import json_error

episodes_bp = Blueprint("episodes", __name__)


@episodes_bp.route("/episodes")
def list_episodes():
    history = load_history()
    episodes = []
    for ep in history:
        # 构造新 dict，避免修改原始数据
        item = {**ep}
        audio_path = item.get("audio_path", "")
        item["audio_filename"] = Path(audio_path).name if audio_path else ""
        item["pub_date"] = item.get("published_at", "")
        episodes.append(item)
    # 最新的在前
    return jsonify(list(reversed(episodes)))


@episodes_bp.route("/episode/<int:ep_num>/script")
def get_script(ep_num: int):
    history = load_history()
    ep_title = None
    for ep in history:
        if ep.get("episode_number") == ep_num:
            ep_title = ep.get("title")
            break
    else:
        return json_error("期数不存在", 404)

    # 按创建时间倒序遍历脚本文件
    scripts = sorted(SCRIPTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for s in scripts:
        try:
            data = json.loads(s.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            continue
        # 优先按 episode_number 匹配（脚本 JSON 含该字段时）
        if data.get("episode_number") == ep_num:
            return jsonify(data)
        # 脚本不含 episode_number 字段时，回退到标题匹配
        if "episode_number" not in data and ep_title and data.get("title") == ep_title:
            return jsonify(data)
    return json_error("脚本文件未找到", 404)


@episodes_bp.route("/episode/<int:ep_num>/analysis")
def get_analysis(ep_num: int):
    """返回某期节目的项目深度分析数据。"""
    history = load_history()
    ep = None
    for e in history:
        if e["episode_number"] == ep_num:
            ep = e
            break
    if not ep:
        return json_error("期数不存在", 404)

    # 从 output/analyses/ 目录查找匹配的分析文件
    if not ANALYSES_DIR.exists():
        return json_error("无分析数据", 404)

    # 优先按 episode_number 匹配，回退到 title 匹配
    for f in sorted(ANALYSES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("episode_number") == ep_num:
                return jsonify(data)
        except (json.JSONDecodeError, ValueError):
            continue
    # 回退到 title 匹配
    for f in sorted(ANALYSES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("title") == ep.get("title"):
                return jsonify(data)
        except (json.JSONDecodeError, ValueError):
            continue
    return json_error("分析数据未找到", 404)
