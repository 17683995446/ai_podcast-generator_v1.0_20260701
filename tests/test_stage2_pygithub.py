"""Stage 2 单元测试：验证 PyGithub 重构后的 deep_extractor.py 和 crawler.py。

覆盖范围：
  1. DeepExtractor — mock 模式、缓存系统、依赖解析器、格式化方法
  2. ReadmeCrawler — 清洗逻辑、mock README
  3. enrich_repo_topics — mock 模式跳过

运行：python -m pytest tests/test_stage2_pygithub.py -v
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.deep_extractor import DeepExtractor
from src.crawler import ReadmeCrawler, enrich_repo_topics
from src.models import GitHubRepo


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def make_config(api_key: str = "", mock_mode: bool = False) -> dict:
    """构建测试用配置。"""
    return {
        "api_keys": {"llm": api_key, "deepseek": "", "github": ""},
        "crawler": {
            "jina_reader_url": "https://r.jina.ai",
            "max_readme_chars": 8000,
            "timeout": 30,
        },
        "llm": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False,
            "temperature": 0.8,
            "max_tokens": 4000,
            "timeout": 120,
        },
        "_mock_mode": mock_mode,
        "project_root": str(Path(__file__).resolve().parent.parent),
    }


def make_repo(name: str = "test/repo") -> GitHubRepo:
    """构建测试用 GitHubRepo。"""
    return GitHubRepo(
        name=name,
        url=f"https://github.com/{name}",
        description="A test repository for unit testing",
        stars=1000,
        language="Python",
        topics=["python", "testing"],
        readme_markdown="# Test Repo\n\nThis is a test README.",
    )


# ═══════════════════════════════════════════════════════════════
# 1. DeepExtractor 测试
# ═══════════════════════════════════════════════════════════════


class TestDeepExtractor:
    """测试深度提取器（PyGithub 重构后）。"""

    def test_mock_mode_extract(self):
        """mock 模式下 extract 返回完整 Markdown。"""
        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo()

        result = extractor.extract(repo)

        assert "## 仓库结构" in result
        assert "## 依赖清单" in result
        assert "## 最近发布" in result
        assert "## 语言分布" in result
        assert "## 开发动态" in result
        assert "## 健康度" in result

    def test_mock_mode_sets_health_metrics(self):
        """mock 模式下 extract 设置 _last_health_metrics。"""
        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo()

        extractor.extract(repo)

        health = extractor._last_health_metrics
        assert health["commit_count_30d"] == 27
        assert health["contributor_count"] == 5
        assert "health_score" in health
        assert "health_grade" in health

    def test_mock_health_metrics(self):
        """_mock_health_metrics 返回正确的指标。"""
        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)

        health = extractor._mock_health_metrics()

        assert health["commit_count_30d"] == 27
        assert health["contributor_count"] == 5
        assert health["release_count"] == 3
        assert health["open_issues"] == 12
        assert health["closed_issues"] == 48
        assert health["issue_close_rate"] == 80.0
        assert health["commit_activity_trend"] == "活跃"
        assert "health_score" in health
        assert "health_grade" in health
        assert len(health["top_contributors"]) == 3

    def test_cache_set_and_get(self):
        """缓存写入和读取。"""
        config = make_config()
        extractor = DeepExtractor(config)

        key = "test_cache_key"
        data = {"test": "data", "number": 42}
        extractor._cache_set(key, data)

        result = extractor._cache_get(key)
        assert result == data

    def test_cache_ttl_expiry(self):
        """缓存 TTL 过期返回 None。"""
        config = make_config()
        extractor = DeepExtractor(config)
        extractor._cache_ttl = 0  # 立即过期

        key = "test_ttl_key"
        extractor._cache_set(key, {"test": "data"})
        time.sleep(0.1)

        result = extractor._cache_get(key)
        assert result is None

    def test_cache_miss(self):
        """缓存未命中返回 None。"""
        config = make_config()
        extractor = DeepExtractor(config)

        result = extractor._cache_get("nonexistent_key")
        assert result is None

    def test_format_health_metrics(self):
        """_format_health_metrics 正确格式化。"""
        config = make_config()
        extractor = DeepExtractor(config)

        metrics = {
            "commit_count_30d": 30,
            "contributor_count": 10,
            "release_count": 5,
            "open_issues": 20,
            "closed_issues": 80,
            "issue_close_rate": 80.0,
            "last_commit_date": "2024-01-15",
            "last_release_date": "2024-01-10",
            "top_contributors": [
                {"name": "alice", "commits": 50},
                {"name": "bob", "commits": 30},
            ],
            "commit_activity_trend": "活跃",
        }

        result = extractor._format_health_metrics(metrics)
        assert "30天提交数: 30 次" in result
        assert "贡献者: 10 人" in result
        assert "Release 总数: 5 个" in result
        assert "Issue 关闭率: 80.0%" in result
        assert "alice(50)" in result
        assert "bob(30)" in result

    def test_format_health_metrics_empty(self):
        """空指标返回空字符串。"""
        config = make_config()
        extractor = DeepExtractor(config)

        result = extractor._format_health_metrics({})
        assert result == ""

    def test_parse_requirements(self):
        """解析 requirements.txt。"""
        config = make_config()
        extractor = DeepExtractor(config)

        content = "flask>=2.0\nrequests\n# comment\nopenai==1.0\n-r base.txt\n"
        result = extractor._parse_requirements(content)
        assert "Python" in result
        assert "flask" in result["Python"]
        assert "requests" in result["Python"]
        assert "openai" in result["Python"]
        assert "# comment" not in result["Python"]

    def test_parse_package_json(self):
        """解析 package.json。"""
        config = make_config()
        extractor = DeepExtractor(config)

        content = '{"dependencies": {"react": "^18.0.0", "axios": "^1.0.0"}, "devDependencies": {"jest": "^29.0.0"}}'
        result = extractor._parse_package_json(content)
        assert "npm" in result
        assert "react" in result["npm"]
        assert "axios" in result["npm"]
        assert "Dev" in result
        assert "jest" in result["Dev"]

    def test_parse_pyproject(self):
        """解析 pyproject.toml [project.dependencies]。"""
        config = make_config()
        extractor = DeepExtractor(config)

        content = """[project.dependencies]
flask = ">=2.0"
requests = "^2.31"
openai = "==1.0"

[tool.poetry.dependencies]
python = "^3.10"
pydantic = "^2.0"
"""
        result = extractor._parse_pyproject(content)
        assert "Python" in result
        assert "flask" in result["Python"]
        assert "requests" in result["Python"]
        assert "openai" in result["Python"]

    def test_parse_cargo(self):
        """解析 Cargo.toml [dependencies]。"""
        config = make_config()
        extractor = DeepExtractor(config)

        content = """[dependencies]
serde = "1.0"
tokio = { version = "1.0", features = ["full"] }
reqwest = "0.11"
"""
        result = extractor._parse_cargo(content)
        assert "Rust" in result
        assert "serde" in result["Rust"]
        assert "tokio" in result["Rust"]
        assert "reqwest" in result["Rust"]

    def test_parse_go_mod(self):
        """解析 go.mod require。"""
        config = make_config()
        extractor = DeepExtractor(config)

        content = """module github.com/test/repo

go 1.21

require (
    github.com/gin-gonic/gin v1.9.0
    github.com/stretchr/testify v1.8.0
)

require github.com/spf13/cobra v1.7.0
"""
        result = extractor._parse_go_mod(content)
        assert "Go" in result
        assert "gin" in result["Go"]
        assert "testify" in result["Go"]
        assert "cobra" in result["Go"]


# ═══════════════════════════════════════════════════════════════
# 2. ReadmeCrawler 测试
# ═══════════════════════════════════════════════════════════════


class TestReadmeCrawler:
    """测试 README 抓取器。"""

    def test_clean_removes_images(self):
        """_clean 去除图片标签。"""
        text = "# Title\n\n![logo](https://example.com/logo.png)\n\nContent here."
        result = ReadmeCrawler._clean(text)
        assert "![logo]" not in result
        assert "Content here." in result

    def test_clean_removes_html_comments(self):
        """_clean 去除 HTML 注释。"""
        text = "# Title\n\n<!-- this is a comment -->\n\nContent."
        result = ReadmeCrawler._clean(text)
        assert "<!--" not in result
        assert "this is a comment" not in result

    def test_clean_compresses_blank_lines(self):
        """_clean 压缩多余空行。"""
        text = "# Title\n\n\n\n\nContent."
        result = ReadmeCrawler._clean(text)
        assert "\n\n\n" not in result

    def test_clean_truncates_long_lines(self):
        """_clean 截断超长行。"""
        long_line = "A" * 600
        text = f"# Title\n\n{long_line}"
        result = ReadmeCrawler._clean(text)
        lines = result.split("\n")
        long_lines = [l for l in lines if len(l) > 500]
        for l in long_lines:
            assert l.endswith("...")

    def test_mock_readme(self):
        """_mock_readme 生成模拟 README。"""
        repo = make_repo("test/amazing-project")
        repo.stars = 5000
        repo.language = "Rust"
        repo.topics = ["rust", "cli"]

        result = ReadmeCrawler._mock_readme(repo)
        assert "test/amazing-project" in result
        assert "5000" in result
        assert "Rust" in result
        assert "rust" in result
        assert "cli" in result


# ═══════════════════════════════════════════════════════════════
# 3. enrich_repo_topics 测试
# ═══════════════════════════════════════════════════════════════


class TestEnrichRepoTopics:
    """测试 topics 补充函数。"""

    def test_mock_mode_skips(self):
        """mock 模式下跳过 API 调用。"""
        repo = make_repo()
        repo.topics = []
        enrich_repo_topics(repo, github_token="", mock_mode=True)
        assert repo.topics == []

    def test_existing_topics_skips(self):
        """已有 topics 时跳过 API 调用。"""
        repo = make_repo()
        repo.topics = ["python", "testing"]
        enrich_repo_topics(repo, github_token="", mock_mode=False)
        assert repo.topics == ["python", "testing"]


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
