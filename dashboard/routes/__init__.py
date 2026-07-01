"""蓝图注册。"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """注册所有 API 蓝图。"""
    from .stats import stats_bp
    from .episodes import episodes_bp
    from .config_api import config_bp
    from .tasks import tasks_bp
    from .media import media_bp
    from .qa import qa_bp
    from .search import search_bp

    app.register_blueprint(stats_bp, url_prefix="/api")
    app.register_blueprint(episodes_bp, url_prefix="/api")
    app.register_blueprint(config_bp, url_prefix="/api")
    app.register_blueprint(tasks_bp, url_prefix="/api")
    app.register_blueprint(media_bp)
    app.register_blueprint(qa_bp, url_prefix="/api/qa")
    app.register_blueprint(search_bp, url_prefix="/api")
