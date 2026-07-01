"""GitHub 播客工具 · Web 仪表盘 · 应用工厂"""
from flask import Flask
from pathlib import Path
import sys, os

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def create_app() -> Flask:
    """创建并配置 Flask 应用。"""
    app = Flask(__name__, static_folder=None)

    # 注册所有蓝图
    from .routes import register_blueprints
    register_blueprints(app)

    # 页面路由
    from flask import send_from_directory
    static_dir = PROJECT_ROOT / "dashboard_static"

    @app.route("/")
    def page_dashboard():
        return send_from_directory(str(static_dir), "pages/dashboard.html")

    @app.route("/episodes")
    def page_episodes():
        return send_from_directory(str(static_dir), "pages/episodes.html")

    @app.route("/analysis")
    def page_analysis():
        return send_from_directory(str(static_dir), "pages/analysis.html")

    @app.route("/config")
    def page_config():
        return send_from_directory(str(static_dir), "pages/config.html")

    @app.route("/search")
    def page_search():
        return send_from_directory(str(static_dir), "pages/search.html")

    # 静态文件服务（CSS/JS）
    @app.route("/static/<path:filename>")
    def serve_static(filename):
        return send_from_directory(str(static_dir), filename)

    # 直接路径访问 CSS/JS（兼容 HTML 中的 /css/xxx /js/xxx 引用）
    @app.route("/css/<path:filename>")
    def serve_css(filename):
        return send_from_directory(str(static_dir / "css"), filename)

    @app.route("/js/<path:filename>")
    def serve_js(filename):
        return send_from_directory(str(static_dir / "js"), filename)

    return app
