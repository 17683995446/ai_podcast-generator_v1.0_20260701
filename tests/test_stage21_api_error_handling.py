"""Stage 21 单元测试：API 错误处理 & 路由 HTTP 测试。

覆盖范围：
  1. 全局错误处理器（404/500/405）—— API 返回 JSON，页面返回 HTML
  2. 输入验证 —— 无效 style / count / repo_urls / topic
  3. SEO 路由 —— robots.txt / sitemap.xml
  4. 页面路由 —— 5 个页面均返回 200
  5. 静态文件服务 —— CSS / JS 路径
  6. json_ok / json_error 响应格式标准化
  7. 输入验证函数单元测试（_validate_repo_urls / _validate_topic）
  8. 边界条件 —— 空请求体 / 非法 JSON / 缺失字段

运行：python -m pytest tests/test_stage21_api_error_handling.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 在导入 dashboard 模块前设置 immediate 模式
os.environ["HUEY_IMMEDIATE"] = "1"

from dashboard import create_app
from dashboard.utils import json_ok, json_error
from dashboard.routes.tasks import (
    _validate_repo_urls,
    _validate_topic,
    _VALID_STYLES,
    _MAX_TOPIC_LENGTH,
    _MAX_REPO_URLS,
    _MAX_COUNT,
    _MIN_COUNT,
)


# ═══════════════════════════════════════════════════════════════
# 测试夹具
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def app():
    """创建 Flask 测试应用。"""
    return create_app()


@pytest.fixture
def client(app):
    """创建测试客户端。"""
    return app.test_client()


@pytest.fixture(autouse=True)
def _mock_start_task():
    """自动 mock task_manager.start_task，防止测试启动真实子进程。

    所有调用 /api/run 或 /api/batch 且通过输入验证的请求，
    都会触发 task_manager.start_task() 来 spawn 子进程。
    测试中我们只验证 HTTP 响应，不需要真正执行子进程。
    """
    from dashboard.task_manager import task_manager
    with patch.object(task_manager, "start_task") as mock:
        mock.return_value = None
        yield mock


@pytest.fixture(autouse=True)
def reset_task_state():
    """每个测试前重置任务状态，避免任务冲突。"""
    from dashboard.huey_app import reset_progress
    reset_progress()
    yield
    reset_progress()


# ═══════════════════════════════════════════════════════════════
# 1. 全局错误处理器测试
# ═══════════════════════════════════════════════════════════════


class TestErrorHandlers:
    """全局错误处理器（404/500/405）测试。"""

    def test_404_page_returns_html(self, client):
        """不存在的页面路径应返回 404 HTML。"""
        resp = client.get("/nonexistent-page")
        assert resp.status_code == 404
        assert resp.mimetype == "text/html"
        body = resp.get_data(as_text=True)
        assert "404" in body
        assert "页面未找到" in body
        # 应包含返回首页链接
        assert 'href="/"' in body

    def test_404_api_returns_json(self, client):
        """不存在的 API 路径应返回 404 JSON。"""
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is False
        assert "不存在" in data["error"]

    def test_405_api_returns_json(self, client):
        """API 路由使用错误方法应返回 405 JSON。"""
        # /api/stats 是 GET 路由，用 POST 应触发 405
        resp = client.post("/api/stats")
        assert resp.status_code == 405
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is False
        assert "允许" in data["error"]

    def test_405_page_returns_text(self, client):
        """页面路由使用错误方法应返回 405。"""
        resp = client.post("/")
        assert resp.status_code == 405

    def test_500_api_returns_json(self, app):
        """API 路由抛异常时应返回 500 JSON。"""
        # 临时注册一个会抛异常的测试路由
        @app.route("/api/test-500")
        def _raise_error():
            raise RuntimeError("故意触发 500")

        # 确保 Flask 不传播异常，而是走 errorhandler
        app.config["TESTING"] = False
        app.config["PROPAGATE_EXCEPTIONS"] = False
        client = app.test_client()
        resp = client.get("/api/test-500")
        assert resp.status_code == 500
        assert resp.is_json
        data = resp.get_json()
        assert data["ok"] is False
        assert "内部错误" in data["error"]


# ═══════════════════════════════════════════════════════════════
# 2. 输入验证 —— 任务 API
# ═══════════════════════════════════════════════════════════════


class TestTaskInputValidation:
    """任务 API 输入验证测试。"""

    def test_invalid_style_returns_400(self, client):
        """无效的播客风格应返回 400。"""
        resp = client.post(
            "/api/run",
            json={"style": "nonexistent-style"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["ok"] is False
        assert "风格" in data["error"]

    def test_valid_styles_accepted(self, client):
        """所有合法风格应通过验证（dry_run 避免实际执行）。"""
        for style in _VALID_STYLES:
            resp = client.post(
                "/api/run",
                json={"style": style, "dry_run": True},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True

    def test_invalid_count_too_large(self, client):
        """count 超过上限应返回 400。"""
        resp = client.post(
            "/api/batch",
            json={"count": _MAX_COUNT + 1, "dry_run": True},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "count" in data["error"]

    def test_invalid_count_too_small(self, client):
        """count 小于下限应返回 400。"""
        resp = client.post(
            "/api/batch",
            json={"count": _MIN_COUNT - 1, "dry_run": True},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "count" in data["error"]

    def test_invalid_count_zero(self, client):
        """count=0 应返回 400。"""
        resp = client.post(
            "/api/batch",
            json={"count": 0, "dry_run": True},
        )
        assert resp.status_code == 400

    def test_invalid_count_negative(self, client):
        """count 为负数应返回 400。"""
        resp = client.post(
            "/api/batch",
            json={"count": -5, "dry_run": True},
        )
        assert resp.status_code == 400

    def test_count_non_integer(self, client):
        """count 为字符串应返回 400。"""
        resp = client.post(
            "/api/batch",
            json={"count": "five", "dry_run": True},
        )
        assert resp.status_code == 400

    def test_count_boundary_values(self, client):
        """count 边界值（1 和 _MAX_COUNT）应通过验证。"""
        for count in [_MIN_COUNT, _MAX_COUNT]:
            resp = client.post(
                "/api/batch",
                json={"count": count, "dry_run": True},
            )
            assert resp.status_code == 200

    def test_invalid_repo_url_not_github(self, client):
        """非 github.com 的 URL 应返回 400。"""
        resp = client.post(
            "/api/run",
            json={
                "repo_urls": ["https://gitlab.com/test/repo"],
                "dry_run": True,
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "无效的仓库 URL" in data["error"]

    def test_invalid_repo_url_not_string(self, client):
        """repo_urls 包含非字符串应返回 400。"""
        resp = client.post(
            "/api/run",
            json={
                "repo_urls": [12345],
                "dry_run": True,
            },
        )
        assert resp.status_code == 400

    def test_repo_urls_too_many(self, client):
        """repo_urls 超过上限应返回 400。"""
        urls = [
            f"https://github.com/user/repo{i}"
            for i in range(_MAX_REPO_URLS + 1)
        ]
        resp = client.post(
            "/api/run",
            json={"repo_urls": urls, "dry_run": True},
        )
        assert resp.status_code == 400
        assert "超过" in resp.get_json()["error"]

    def test_repo_urls_not_list(self, client):
        """repo_urls 不是列表应返回 400。"""
        resp = client.post(
            "/api/run",
            json={"repo_urls": "https://github.com/test/repo", "dry_run": True},
        )
        assert resp.status_code == 400

    def test_topic_too_long(self, client):
        """topic 超过长度限制应返回 400。"""
        long_topic = "a" * (_MAX_TOPIC_LENGTH + 1)
        resp = client.post(
            "/api/run",
            json={"topic": long_topic, "dry_run": True},
        )
        assert resp.status_code == 400
        assert "过长" in resp.get_json()["error"]

    def test_topic_boundary_length(self, client):
        """topic 正好达到上限应通过验证。"""
        topic = "a" * _MAX_TOPIC_LENGTH
        resp = client.post(
            "/api/run",
            json={"topic": topic, "dry_run": True},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# 3. 输入验证函数单元测试
# ═══════════════════════════════════════════════════════════════


class TestValidationFunctions:
    """_validate_repo_urls / _validate_topic 单元测试。"""

    @pytest.fixture(autouse=True)
    def app_ctx(self, app):
        """为验证函数测试提供应用上下文（json_error 需要 jsonify）。"""
        with app.app_context():
            yield

    def test_validate_repo_urls_empty(self):
        """空列表应通过验证。"""
        urls, err = _validate_repo_urls([])
        assert urls == []
        assert err is None

    def test_validate_repo_urls_none(self):
        """None 应通过验证（返回空列表）。"""
        urls, err = _validate_repo_urls(None)
        assert urls == []
        assert err is None

    def test_validate_repo_urls_valid(self):
        """合法 GitHub URL 应通过验证。"""
        test_urls = [
            "https://github.com/user/repo1",
            "https://github.com/org/repo2",
        ]
        urls, err = _validate_repo_urls(test_urls)
        assert urls == test_urls
        assert err is None

    def test_validate_repo_urls_not_list(self):
        """非列表类型应返回错误。"""
        urls, err = _validate_repo_urls("not-a-list")
        assert urls is None
        assert err is not None

    def test_validate_repo_urls_non_string_element(self):
        """列表含非字符串元素应返回错误。"""
        urls, err = _validate_repo_urls([123])
        assert urls is None
        assert err is not None

    def test_validate_repo_urls_wrong_domain(self):
        """非 github.com URL 应返回错误。"""
        urls, err = _validate_repo_urls(["https://bitbucket.org/test/repo"])
        assert urls is None
        assert err is not None

    def test_validate_repo_urls_exceeds_max(self):
        """超过上限应返回错误。"""
        urls = [
            f"https://github.com/u/r{i}" for i in range(_MAX_REPO_URLS + 1)
        ]
        result, err = _validate_repo_urls(urls)
        assert result is None
        assert err is not None

    def test_validate_topic_empty(self):
        """空字符串应通过验证。"""
        topic, err = _validate_topic("")
        assert topic == ""
        assert err is None

    def test_validate_topic_none(self):
        """None 应通过验证。"""
        topic, err = _validate_topic(None)
        assert topic == ""
        assert err is None

    def test_validate_topic_valid(self):
        """合法主题应通过验证。"""
        topic, err = _validate_topic("machine learning")
        assert topic == "machine learning"
        assert err is None

    def test_validate_topic_non_string(self):
        """非字符串类型应返回错误。"""
        topic, err = _validate_topic(123)
        assert topic is None
        assert err is not None

    def test_validate_topic_too_long(self):
        """超长主题应返回错误。"""
        long_topic = "x" * (_MAX_TOPIC_LENGTH + 1)
        topic, err = _validate_topic(long_topic)
        assert topic is None
        assert err is not None

    def test_validate_topic_boundary(self):
        """正好达到上限的应通过验证。"""
        topic = "x" * _MAX_TOPIC_LENGTH
        result, err = _validate_topic(topic)
        assert result == topic
        assert err is None


# ═══════════════════════════════════════════════════════════════
# 4. SEO 路由测试
# ═══════════════════════════════════════════════════════════════


class TestSEORoutes:
    """SEO 相关路由测试。"""

    def test_robots_txt(self, client):
        """robots.txt 应返回纯文本。"""
        resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert resp.mimetype == "text/plain"
        content = resp.get_data(as_text=True)
        assert "User-agent" in content
        assert "Allow" in content or "Disallow" in content

    def test_sitemap_xml(self, client):
        """sitemap.xml 应返回 XML 格式。"""
        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert resp.mimetype == "application/xml"
        content = resp.get_data(as_text=True)
        assert "<?xml" in content
        assert "<urlset" in content
        assert "<url>" in content
        assert "<loc>" in content
        assert "<priority>" in content
        # 应包含主要页面
        assert "/" in content
        assert "/episodes" in content
        assert "/analysis" in content


# ═══════════════════════════════════════════════════════════════
# 5. 页面路由测试
# ═══════════════════════════════════════════════════════════════


class TestPageRoutes:
    """5 个页面路由均返回 200。"""

    @pytest.mark.parametrize(
        "path",
        ["/", "/episodes", "/analysis", "/config", "/search"],
    )
    def test_page_returns_200(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.mimetype == "text/html"

    def test_dashboard_has_meta_tags(self, client):
        """首页应包含 SEO meta 标签。"""
        resp = client.get("/")
        body = resp.get_data(as_text=True)
        assert '<meta name="description"' in body
        assert '<meta property="og:' in body

    def test_pages_have_skip_link(self, client):
        """页面应包含无障碍 skip-link。"""
        for path in ["/", "/episodes", "/analysis", "/config", "/search"]:
            resp = client.get(path)
            body = resp.get_data(as_text=True)
            assert "skip-link" in body or "skip-link" in body.lower(), (
                f"{path} 缺少 skip-link"
            )

    def test_pages_have_main_landmark(self, client):
        """页面应包含 <main> 语义标签。"""
        for path in ["/", "/episodes", "/analysis", "/config", "/search"]:
            resp = client.get(path)
            body = resp.get_data(as_text=True)
            assert "<main" in body, f"{path} 缺少 <main> 标签"


# ═══════════════════════════════════════════════════════════════
# 6. 静态文件服务测试
# ═══════════════════════════════════════════════════════════════


class TestStaticFiles:
    """CSS / JS 静态文件路由测试。"""

    def test_css_route(self, client):
        """CSS 路由应返回 CSS 文件。"""
        resp = client.get("/css/theme.css")
        assert resp.status_code == 200
        assert resp.mimetype == "text/css"

    def test_js_route(self, client):
        """JS 路由应返回 JS 文件。"""
        resp = client.get("/js/router.js")
        assert resp.status_code == 200
        assert resp.mimetype == "text/javascript" or resp.mimetype == "application/javascript"

    def test_static_route(self, client):
        """/static/ 路径应正常返回文件。"""
        resp = client.get("/static/css/theme.css")
        assert resp.status_code == 200

    def test_nonexistent_css_returns_404(self, client):
        """不存在的 CSS 文件应返回 404。"""
        resp = client.get("/css/nonexistent.css")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# 7. json_ok / json_error 格式测试
# ═══════════════════════════════════════════════════════════════


class TestResponseFormat:
    """json_ok / json_error 响应格式标准化测试。"""

    def test_json_ok_basic(self, app):
        """json_ok 应返回 ok=True。"""
        with app.app_context():
            from flask import jsonify
            resp = json_ok({"episodes": []})
            data = resp.get_json()
            assert data["ok"] is True
            assert data["data"] == {"episodes": []}

    def test_json_ok_with_extra(self, app):
        """json_ok 支持额外字段。"""
        with app.app_context():
            resp = json_ok(message="任务已启动")
            data = resp.get_json()
            assert data["ok"] is True
            assert data["message"] == "任务已启动"

    def test_json_error_basic(self, app):
        """json_error 应返回 ok=False 和错误消息。"""
        with app.app_context():
            resp, status = json_error("参数缺失", 400)
            data = resp.get_json()
            assert data["ok"] is False
            assert data["error"] == "参数缺失"
            assert status == 400

    def test_json_error_default_status(self, app):
        """json_error 默认状态码应为 400。"""
        with app.app_context():
            _, status = json_error("默认错误")
            assert status == 400

    def test_json_error_with_extra(self, app):
        """json_error 支持额外字段。"""
        with app.app_context():
            resp, status = json_error("已有任务运行中", 409, action="cancel")
            data = resp.get_json()
            assert data["ok"] is False
            assert data["action"] == "cancel"
            assert status == 409


# ═══════════════════════════════════════════════════════════════
# 8. 边界条件测试
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界条件测试。"""

    def test_run_with_empty_body(self, client):
        """空请求体应使用默认值（dry_run=False，但无 repo_urls 时可能触发任务）。"""
        # 不传 dry_run 会尝试启动真实任务，这里用 dry_run=True
        resp = client.post("/api/run", json={"dry_run": True})
        assert resp.status_code == 200

    def test_run_with_no_json(self, client):
        """无 JSON 体的请求应不崩溃（get_json(silent=True) 返回 None → {}）。"""
        resp = client.post("/api/run", data="not-json", content_type="text/plain")
        # 无 JSON 时使用默认值，style="casual" 合法，dry_run 默认 False
        # 可能返回 200（任务启动）或 409（已有任务）
        assert resp.status_code in (200, 409)

    def test_run_with_null_body(self, client):
        """请求体为 null 应使用默认值。"""
        resp = client.post("/api/run", json=None)
        assert resp.status_code in (200, 409, 400)

    def test_batch_with_no_count(self, client):
        """batch 不传 count 应使用默认值 5。"""
        resp = client.post("/api/batch", json={"dry_run": True})
        assert resp.status_code == 200

    def test_task_status_returns_running_field(self, client):
        """task/status 应返回 running 字段。"""
        resp = client.get("/api/task/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "running" in data
        assert "log" in data

    def test_task_cancel_when_idle(self, client):
        """无任务运行时取消应返回 400。"""
        # 确保无任务运行
        from dashboard.huey_app import reset_progress
        reset_progress()
        resp = client.post("/api/task/cancel")
        assert resp.status_code == 400

    def test_task_reset_always_succeeds(self, client):
        """task/reset 应始终成功。"""
        resp = client.post("/api/task/reset")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True


# ═══════════════════════════════════════════════════════════════
# 9. API 响应一致性测试
# ═══════════════════════════════════════════════════════════════


class TestAPIResponseConsistency:
    """验证所有 API 端点响应格式一致。"""

    def test_stats_endpoint_format(self, client):
        """/api/stats 应返回正确的统计字段。"""
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        required_fields = {"episodes", "total_duration_min", "total_chars", "total_size_mb"}
        assert required_fields.issubset(set(data.keys()))

    def test_episodes_endpoint_returns_list(self, client):
        """/api/episodes 应返回列表。"""
        resp = client.get("/api/episodes")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_config_endpoint_structure(self, client):
        """/api/config 应返回 config 和 env 两个字段。"""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "config" in data
        assert "env" in data

    def test_search_without_query_returns_400(self, client):
        """搜索不带 q 参数应返回 400。"""
        resp = client.get("/api/search")
        assert resp.status_code == 400

    def test_search_with_query_returns_ok(self, client):
        """搜索带 q 参数应返回 ok=True。"""
        resp = client.get("/api/search?q=python")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "results" in data["data"] or "data" in data

    def test_feed_endpoint(self, client):
        """/api/feed 应返回 RSS XML 或 404。"""
        resp = client.get("/api/feed")
        # feed.xml 可能存在也可能不存在
        if resp.status_code == 200:
            assert resp.mimetype == "application/rss+xml"
        elif resp.status_code == 404:
            data = resp.get_json()
            assert data["ok"] is False
