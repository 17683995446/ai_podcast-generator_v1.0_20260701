"""GitHub 播客工具 · Web 仪表盘 · 应用工厂

Stage 4: create_app() 拆分为聚焦的注册函数，PROJECT_ROOT 集中至 config.py
"""
import sys

from flask import Flask, Response, request, send_from_directory

from .config import PROJECT_ROOT

# 确保 src/ 模块可被导入（routes 中有 from src.xxx import yyy）
sys.path.insert(0, str(PROJECT_ROOT))


def create_app() -> Flask:
    """创建并配置 Flask 应用。"""
    app = Flask(__name__, static_folder=None)
    static_dir = PROJECT_ROOT / "dashboard_static"

    # 注册所有 API 蓝图
    from .routes import register_blueprints
    register_blueprints(app)

    # 启动 Huey 消费者线程（immediate 模式下自动跳过）
    from .huey_app import start_consumer
    start_consumer()

    # 注册页面路由、静态文件路由、SEO 路由、错误处理
    _register_page_routes(app, static_dir)
    _register_static_routes(app, static_dir)
    _register_seo_routes(app)
    _register_error_handlers(app)

    return app


# ════════════════════════════════════════
# 页面路由 — 5 个 HTML 页面 + robots.txt
# ════════════════════════════════════════
def _register_page_routes(app: Flask, static_dir) -> None:
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

    @app.route("/robots.txt")
    def robots():
        return send_from_directory(str(static_dir), "robots.txt", mimetype="text/plain")


# ════════════════════════════════════════
# 静态文件路由 — CSS/JS/images
# ════════════════════════════════════════
def _register_static_routes(app: Flask, static_dir) -> None:
    @app.route("/static/<path:filename>")
    def serve_static(filename):
        return send_from_directory(str(static_dir), filename)

    @app.route("/css/<path:filename>")
    def serve_css(filename):
        return send_from_directory(str(static_dir / "css"), filename)

    @app.route("/js/<path:filename>")
    def serve_js(filename):
        return send_from_directory(str(static_dir / "js"), filename)

    @app.route("/images/<path:filename>")
    def serve_images(filename):
        return send_from_directory(str(static_dir / "images"), filename)


# ════════════════════════════════════════
# SEO 路由 — sitemap.xml 动态生成
# ════════════════════════════════════════
def _register_seo_routes(app: Flask) -> None:
    @app.route("/sitemap.xml")
    def sitemap():
        base = request.host_url.rstrip("/")
        urls = [("/", "1.0"), ("/episodes", "0.8"), ("/analysis", "0.8")]
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        for path, priority in urls:
            xml += f"  <url><loc>{base}{path}</loc><priority>{priority}</priority></url>\n"
        xml += '</urlset>'
        return Response(xml, mimetype="application/xml")


# ════════════════════════════════════════
# 全局错误处理 — API 返回 JSON，页面返回 HTML
# ════════════════════════════════════════
def _register_error_handlers(app: Flask) -> None:
    from flask import render_template_string

    from .utils import json_error

    @app.errorhandler(404)
    def not_found(error):
        """404：API 路由返回 JSON，其他返回友好 HTML 页面。"""
        if request.path.startswith("/api/"):
            return json_error("请求的资源不存在", 404)
        return render_template_string(_ERROR_PAGE_404), 404

    @app.errorhandler(500)
    def server_error(error):
        """500：API 路由返回 JSON，其他返回友好 HTML 页面。"""
        if request.path.startswith("/api/"):
            return json_error("服务器内部错误，请稍后重试", 500)
        return render_template_string(_ERROR_PAGE_500), 500

    @app.errorhandler(405)
    def method_not_allowed(error):
        """405：方法不允许，返回 JSON 提示。"""
        if request.path.startswith("/api/"):
            return json_error("请求方法不被允许", 405)
        return "Method Not Allowed", 405


# ════════════════════════════════════════
# 错误页面 HTML 模板（内联，避免额外文件依赖）
# ════════════════════════════════════════
_ERROR_CSS = """
  <link rel="stylesheet" href="/css/theme.css">
  <link rel="stylesheet" href="/css/layout.css">
  <link rel="stylesheet" href="/css/components.css">
  <link rel="stylesheet" href="/css/ui-optimizations.css">
"""

_ERROR_PAGE_404 = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#0b0d14">
  <title>404 · 页面未找到 · GitHub 播客工具</title>
  <meta name="robots" content="noindex, nofollow">
  {_ERROR_CSS}
</head>
<body>
  <div class="error-page">
    <div class="error-page-content fade-in">
      <div class="error-page-icon">🔍</div>
      <h1 class="error-page-code">404</h1>
      <h2 class="error-page-title">页面未找到</h2>
      <p class="error-page-desc">您访问的页面不存在，可能已被移动或删除。</p>
      <div class="error-page-actions">
        <a href="/" class="btn btn-cta">🏠 返回首页</a>
        <button class="btn btn-secondary" onclick="history.back()" aria-label="返回上一页">⬅ 返回上一页</button>
      </div>
      <div class="error-page-nav">
        <a href="/episodes" class="error-nav-link">📻 节目库</a>
        <a href="/search" class="error-nav-link">🔍 搜索</a>
        <a href="/analysis" class="error-nav-link">🔬 项目分析</a>
        <a href="/config" class="error-nav-link">⚙️ 配置</a>
      </div>
    </div>
  </div>
</body>
</html>"""

_ERROR_PAGE_500 = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#0b0d14">
  <title>500 · 服务器错误 · GitHub 播客工具</title>
  <meta name="robots" content="noindex, nofollow">
  {_ERROR_CSS}
</head>
<body>
  <div class="error-page">
    <div class="error-page-content fade-in">
      <div class="error-page-icon">⚠️</div>
      <h1 class="error-page-code">500</h1>
      <h2 class="error-page-title">服务器错误</h2>
      <p class="error-page-desc">服务器遇到了一些问题，请稍后刷新重试。</p>
      <div class="error-page-actions">
        <a href="/" class="btn btn-cta">🏠 返回首页</a>
        <button class="btn btn-secondary" onclick="location.reload()" aria-label="刷新页面">🔄 刷新页面</button>
      </div>
      <div class="error-page-nav">
        <a href="/episodes" class="error-nav-link">📻 节目库</a>
        <a href="/search" class="error-nav-link">🔍 搜索</a>
        <a href="/analysis" class="error-nav-link">🔬 项目分析</a>
        <a href="/config" class="error-nav-link">⚙️ 配置</a>
      </div>
    </div>
  </div>
</body>
</html>"""
