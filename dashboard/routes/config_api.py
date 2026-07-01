"""配置查看 API。"""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..config import load_config, load_env

config_bp = Blueprint("config", __name__)


@config_bp.route("/config")
def get_config():
    return jsonify({
        "config": load_config(),
        "env": load_env(),
    })
