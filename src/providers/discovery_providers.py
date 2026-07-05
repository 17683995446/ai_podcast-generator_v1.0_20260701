"""Discovery Provider 实现 — GitHub Trending / GitHub Search / Repo URL / Mock。

将现有 RepoDiscovery 的不同发现策略适配为独立 Provider 类，
每个 Provider 封装一种发现方式，通过注册表统一管理。

设计原则（第一性原理）：
  1. 策略模式：每种发现方式是一个独立策略，可通过注册表选择
  2. 适配器：不改变 RepoDiscovery 底层实现，仅包装为统一接口
  3. 可扩展：新增发现源（如 HackerNews、ProductHunt）只需实现接口 + 注册
"""
from __future__ import annotations

from typing import Any

from .base import BaseDiscoveryProvider
from .registry import register_discovery_provider
from ..logger import get_logger
from ..models import GitHubRepo

logger = get_logger(__name__)


@register_discovery_provider("github_trending")
class GitHubTrendingDiscoveryProvider(BaseDiscoveryProvider):
    """GitHub Trending 发现 Provider。

    委托给 RepoDiscovery.discover()，使用 RSSHub → Trending API →
    GitHub Search → Mock 的多源 fallback 链。
    """

    @property
    def name(self) -> str:
        return "github_trending"

    def discover(self, config: dict[str, Any]) -> list[GitHubRepo]:
        """通过 GitHub Trending 发现项目。"""
        from ..discovery import RepoDiscovery
        discovery = RepoDiscovery(config)
        return discovery.discover()

    def is_available(self, config: dict[str, Any]) -> bool:
        """Trending 始终可用（有 mock fallback）。"""
        return True


@register_discovery_provider("github_search")
class GitHubSearchDiscoveryProvider(BaseDiscoveryProvider):
    """GitHub 搜索发现 Provider。

    委托给 RepoDiscovery.discover_by_topic()，按关键词搜索项目。
    """

    @property
    def name(self) -> str:
        return "github_search"

    def discover(self, config: dict[str, Any]) -> list[GitHubRepo]:
        """通过 GitHub Search API 按主题发现项目。

        从 config 中读取 _search_topic 字段作为搜索关键词。
        """
        from ..discovery import RepoDiscovery
        topic = config.get("_search_topic", "")
        if not topic:
            logger.warning("github_search provider 需要 config['_search_topic']")
            return []
        discovery = RepoDiscovery(config)
        max_projects = config.get("discovery", {}).get("max_projects", 3)
        return discovery.discover_by_topic(topic, max_projects)

    def is_available(self, config: dict[str, Any]) -> bool:
        """搜索模式需要 GitHub Token 以获得更高 API 配额。"""
        return bool(config.get("api_keys", {}).get("github", ""))


@register_discovery_provider("repo_url")
class RepoURLDiscoveryProvider(BaseDiscoveryProvider):
    """指定仓库 URL 发现 Provider。

    委托给 RepoDiscovery.discover_by_repo_urls()，允许用户指定具体仓库。
    """

    @property
    def name(self) -> str:
        return "repo_url"

    def discover(self, config: dict[str, Any]) -> list[GitHubRepo]:
        """通过用户指定的仓库 URL 列表发现项目。

        从 config 中读取 _repo_urls 字段作为 URL 列表。
        """
        from ..discovery import RepoDiscovery
        repo_urls = config.get("_repo_urls", [])
        if not repo_urls:
            logger.warning("repo_url provider 需要 config['_repo_urls']")
            return []
        discovery = RepoDiscovery(config)
        return discovery.discover_by_repo_urls(repo_urls)

    def is_available(self, config: dict[str, Any]) -> bool:
        """始终可用（只需有 URL 列表）。"""
        return True


@register_discovery_provider("mock")
class MockDiscoveryProvider(BaseDiscoveryProvider):
    """Mock 发现 Provider（生成测试数据，用于 dry-run 和测试）。

    生成内置样例项目列表，不发起任何网络请求。
    """

    # 内置样例项目数据
    _MOCK_REPOS = [
        GitHubRepo(
            name="mock/project-alpha",
            url="https://github.com/mock/project-alpha",
            description="A mock project for testing the pipeline.",
            stars=1500,
            language="Python",
            topics=["testing", "mock", "pipeline"],
        ),
        GitHubRepo(
            name="mock/project-beta",
            url="https://github.com/mock/project-beta",
            description="Another mock project with different characteristics.",
            stars=3200,
            language="Rust",
            topics=["performance", "systems"],
        ),
        GitHubRepo(
            name="mock/project-gamma",
            url="https://github.com/mock/project-gamma",
            description="Third mock project for multi-project testing.",
            stars=800,
            language="Go",
            topics=["microservices", "cloud"],
        ),
    ]

    @property
    def name(self) -> str:
        return "mock"

    def discover(self, config: dict[str, Any]) -> list[GitHubRepo]:
        """返回内置 mock 项目列表。"""
        max_projects = config.get("discovery", {}).get("max_projects", 3)
        repos = [GitHubRepo(
            name=r.name,
            url=r.url,
            description=r.description,
            stars=r.stars,
            language=r.language,
            topics=list(r.topics),
        ) for r in self._MOCK_REPOS[:max_projects]]
        for i, repo in enumerate(repos, 1):
            repo.trending_rank = i
        logger.info("Mock discovery: 返回 %d 个项目", len(repos))
        return repos

    def is_available(self, config: dict[str, Any]) -> bool:
        """Mock 始终可用。"""
        return True
