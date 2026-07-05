"""项目发现模块：从 GitHub Trending / RSSHub 获取前沿项目。

数据源（按优先级 fallback）：
1. RSSHub 公共实例的 GitHub Trending RSS
2. huchenme/github-trending-api 在线 API
3. GitHub Trending 网页直接抓取（备用）
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import feedparser
import requests

from .models import GitHubRepo

from src.logger import get_logger

logger = get_logger(__name__)


class RepoDiscovery:
    """发现 GitHub 热门仓库。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["discovery"]
        self.github_token = config["api_keys"].get("github", "")
        self.allow_mock = bool(config.get("_mock_mode", False))
        self.project_root = config.get("project_root", "")
        # 30 天项目去重黑名单（借鉴 TrendingGithub 的去重机制）
        self._blacklist_path = Path(self.project_root) / "output" / ".project_blacklist.json"
        self._session = requests.Session()
        if self.github_token:
            self._session.headers["Authorization"] = f"token {self.github_token}"
        self._session.headers["User-Agent"] = "github-podcast-tool/0.1"

    def discover(self) -> list[GitHubRepo]:
        """主入口：获取并过滤热门仓库列表。

        Returns:
            经过关键词/Star 数过滤后的 GitHubRepo 列表。
        """
        if self.allow_mock:
            repos = self._fetch_mock()
            repos = self._apply_blacklist_filter(repos)
            repos = self._filter(repos)
            repos = repos[: self.cfg["max_projects"]]
            for i, repo in enumerate(repos, 1):
                repo.trending_rank = i
            return repos
        repos = self._fetch_from_rsshub()
        if not repos:
            repos = self._fetch_from_trending_api()
        if not repos:
            repos = self._fetch_from_github_search()
        if not repos:
            logger.warning("所有真实数据源均不可用，自动回退到内置样例数据")
            repos = self._fetch_mock()

        repos = self._apply_blacklist_filter(repos)
        repos = self._filter(repos)
        repos = repos[: self.cfg["max_projects"]]
        # 重新编号排名
        for i, repo in enumerate(repos, 1):
            repo.trending_rank = i
        return repos

    # ------------------------------------------------------------------
    # 自定义输入模式（借鉴 Twocast 链接/主题输入 + Podcastfy topic 生成）
    # ------------------------------------------------------------------
    def discover_by_repo_urls(self, repo_urls: list[str]) -> list[GitHubRepo]:
        """通过指定的 GitHub 仓库 URL 列表获取项目信息。

        借鉴 Twocast 的链接输入模式，允许用户指定任意 GitHub 仓库。
        """
        repos = []
        for i, url in enumerate(repo_urls, 1):
            # 解析 owner/repo
            url = url.strip().rstrip("/")
            parts = url.replace("https://github.com/", "").split("/")
            if len(parts) < 2:
                continue
            full_name = f"{parts[0]}/{parts[1]}"

            if self.allow_mock:
                repos.append(GitHubRepo(
                    name=full_name,
                    url=url,
                    description=f"用户指定的项目 {full_name}",
                    stars=1000,
                    language="Python",
                    trending_rank=i,
                ))
                continue

            # 通过 GitHub API 获取项目信息
            try:
                resp = self._session.get(
                    f"https://api.github.com/repos/{full_name}", timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    repos.append(GitHubRepo(
                        name=data["full_name"],
                        url=data["html_url"],
                        description=data.get("description", "") or "",
                        stars=data.get("stargazers_count", 0),
                        language=data.get("language", "") or "",
                        topics=data.get("topics", []),
                        trending_rank=i,
                    ))
            except Exception as e:
                logger.error(f"获取 {full_name} 失败: {e}")

        return self._apply_blacklist_filter(repos)

    def discover_by_topic(self, topic: str, count: int = 3) -> list[GitHubRepo]:
        """通过主题关键词搜索 GitHub 项目。

        借鉴 Twocast 的主题输入模式和 Podcastfy 的 topic-based 生成。
        """
        if self.allow_mock:
            return self._apply_blacklist_filter(self._fetch_mock()[:count])

        # 使用 GitHub Search API 按主题搜索
        repos = []
        try:
            params = {
                "q": f"{topic} stars:>100 sort:stars",
                "sort": "stars",
                "order": "desc",
                "per_page": count * 3,  # 多获取一些用于过滤
            }
            resp = self._session.get(
                "https://api.github.com/search/repositories", params=params, timeout=30
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for i, item in enumerate(items[:count], 1):
                    repos.append(GitHubRepo(
                        name=item["full_name"],
                        url=item["html_url"],
                        description=item.get("description", "") or "",
                        stars=item.get("stargazers_count", 0),
                        language=item.get("language", "") or "",
                        topics=item.get("topics", []),
                        trending_rank=i,
                    ))
        except Exception as e:
            logger.error(f"主题搜索失败: {e}")

        if not repos:
            repos = self._fetch_mock()[:count]

        return self._apply_blacklist_filter(repos)

    # ------------------------------------------------------------------
    # 30 天项目去重黑名单（借鉴 TrendingGithub）
    # ------------------------------------------------------------------
    def _load_blacklist(self) -> set[str]:
        """加载 30 天项目黑名单，过滤掉超过 30 天的旧记录。

        黑名单文件格式：{"repo_name": "ISO_date_covered", ...}
        仅返回仍在 30 天黑名单期内的 repo 名称集合。
        """
        if not self._blacklist_path.exists():
            return set()
        try:
            data = json.loads(self._blacklist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return set()
        if not isinstance(data, dict):
            return set()
        cutoff = datetime.utcnow() - timedelta(days=30)
        active: set[str] = set()
        for repo_name, date_str in data.items():
            try:
                covered = datetime.fromisoformat(str(date_str))
            except (ValueError, TypeError):
                continue
            if covered >= cutoff:
                active.add(repo_name)
        return active

    def _update_blacklist(self, repo_names: list[str]) -> None:
        """将项目加入 30 天黑名单（追加新记录，保留已有记录）。"""
        data: dict[str, str] = {}
        if self._blacklist_path.exists():
            try:
                loaded = json.loads(self._blacklist_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = {str(k): str(v) for k, v in loaded.items()}
            except (json.JSONDecodeError, ValueError, OSError):
                data = {}
        today = datetime.utcnow().strftime("%Y-%m-%d")
        for name in repo_names:
            if name:
                data[name] = today
        self._blacklist_path.parent.mkdir(parents=True, exist_ok=True)
        self._blacklist_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _apply_blacklist_filter(self, repos: list[GitHubRepo]) -> list[GitHubRepo]:
        """过滤掉 30 天内已覆盖的项目（在 _filter() 之前调用）。

        如果过滤后结果为空但原始列表非空，则回退到原始列表
        （避免黑名单导致无法生成任何播客）。
        """
        blacklist = self._load_blacklist()
        if not blacklist or not repos:
            return repos
        before = len(repos)
        filtered = [r for r in repos if r.name not in blacklist]
        if before > len(filtered):
            logger.info(f"过滤 {before - len(filtered)} 个近期已覆盖项目")
        # 如果全部被过滤掉，回退到原始列表（带警告）
        if not filtered and repos:
            logger.warning("所有项目均在 30 天黑名单内，回退使用原始列表")
            return repos
        return filtered

    def mark_as_covered(self, repo_names: list[str]) -> None:
        """将项目标记为已覆盖，加入 30 天去重黑名单。

        由 main.py 在单期播客生成完成后调用，防止近期重复覆盖同一项目。
        """
        if not repo_names:
            return
        self._update_blacklist(repo_names)
        logger.info(
            f"已将 {len(repo_names)} 个项目加入 30 天黑名单："
            f"{', '.join(repo_names)}"
        )

    # ------------------------------------------------------------------
    # 数据源 1：RSSHub（首选，结构化 RSS）
    # ------------------------------------------------------------------
    def _fetch_from_rsshub(self) -> list[GitHubRepo]:
        base = self.cfg["rsshub_base_url"].rstrip("/")
        since = self.cfg["trending_since"]
        lang = self.cfg.get("language", "").strip()
        # 路由：/github/trending/:since 或 /github/trending/:language/:since
        if lang:
            path = f"github/trending/{lang}/{since}"
        else:
            path = f"github/trending/{since}"
        url = f"{base}/{path}"

        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"RSSHub 请求失败: {e}")
            return []

        feed = feedparser.parse(resp.content)
        repos: list[GitHubRepo] = []
        for i, entry in enumerate(feed.entries, 1):
            repo = self._parse_rsshub_entry(entry, i)
            if repo:
                repos.append(repo)
        logger.info(f"RSSHub 获取 {len(repos)} 个仓库")
        return repos

    @staticmethod
    def _parse_rsshub_entry(entry: Any, rank: int) -> GitHubRepo | None:
        """解析 RSSHub 单条 entry。

        RSSHub trending entry 的 title 形如 "Owner/Repo",
        link 形如 "https://github.com/Owner/Repo",
        summary 含 description + stars 等信息。
        """
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or "/" not in title or not link:
            return None

        summary = getattr(entry, "summary", "")
        stars = RepoDiscovery._extract_stars(summary)
        language = RepoDiscovery._extract_language(summary)
        return GitHubRepo(
            name=title,
            url=link,
            description=RepoDiscovery._clean_summary(summary),
            stars=stars,
            language=language,
            trending_rank=rank,
        )

    @staticmethod
    def _extract_stars(text: str) -> int:
        m = re.search(r"(\d[\d,]*)\s*stars?", text, re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))
        return 0

    @staticmethod
    def _extract_language(text: str) -> str:
        m = re.search(r"Language:\s*(\S+)", text)
        return m.group(1) if m else ""

    @staticmethod
    def _clean_summary(text: str) -> str:
        """清理 RSSHub summary 中的 HTML/多余标记。"""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:500]

    # ------------------------------------------------------------------
    # 数据源 2：huchenme/github-trending-api（备用）
    # ------------------------------------------------------------------
    def _fetch_from_trending_api(self) -> list[GitHubRepo]:
        url = self.cfg["trending_api_url"]
        params: dict[str, str] = {"since": self.cfg["trending_since"]}
        if self.cfg.get("language"):
            params["language"] = self.cfg["language"]
        try:
            resp = self._session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.error(f"Trending API 请求失败: {e}")
            return []

        repos: list[GitHubRepo] = []
        for i, item in enumerate(data, 1):
            author = item.get("author", "")
            repo_name = item.get("name", "")
            if not author or not repo_name:
                continue
            name = f"{author}/{repo_name}"
            repos.append(
                GitHubRepo(
                    name=name,
                    url=item.get("url", f"https://github.com/{name}"),
                    description=item.get("description", "") or "",
                    stars=item.get("stars", 0),
                    language=item.get("language", "") or "",
                    trending_rank=i,
                )
            )
        logger.info(f"Trending API 获取 {len(repos)} 个仓库")
        return repos

    # ------------------------------------------------------------------
    # 数据源 3：GitHub Search API（最终备用）
    # ------------------------------------------------------------------
    def _fetch_from_github_search(self) -> list[GitHubRepo]:
        """使用 GitHub Search API 按近期 Star 增长排序。"""
        if not self.github_token:
            logger.warning("未配置 GITHUB_TOKEN，跳过 GitHub Search 备用源")
            return []
        # 搜索近 7 天内 created/pushed 的热门仓库
        from datetime import datetime, timedelta

        since_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        query = f"stars:>500 pushed:>{since_date}"
        if self.cfg.get("language"):
            query += f" language:{self.cfg['language']}"
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": 20}
        try:
            resp = self._session.get(
                "https://api.github.com/search/repositories", params=params, timeout=30
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except (requests.RequestException, ValueError) as e:
            logger.error(f"GitHub Search 失败: {e}")
            return []

        repos: list[GitHubRepo] = []
        for i, item in enumerate(items, 1):
            repos.append(
                GitHubRepo(
                    name=item["full_name"],
                    url=item["html_url"],
                    description=item.get("description", "") or "",
                    stars=item.get("stargazers_count", 0),
                    language=item.get("language", "") or "",
                    topics=item.get("topics", []),
                    trending_rank=i,
                )
            )
        logger.info(f"GitHub Search 获取 {len(repos)} 个仓库")
        return repos

    # ------------------------------------------------------------------
    # 数据源 4：内置样例数据（离线测试用）
    # ------------------------------------------------------------------
    def _fetch_mock(self) -> list[GitHubRepo]:
        """返回内置样例仓库（用于无网络/API 的离线测试）。"""
        return [
            GitHubRepo(
                name="commaai/openpilot",
                url="https://github.com/commaai/openpilot",
                description="openpilot is an open source driver assistance system. "
                "它是一个开源的驾驶辅助系统，支持 200+ 车型。",
                stars=45000,
                language="Python",
                topics=["self-driving", "robotics", "ai"],
                trending_rank=1,
            ),
            GitHubRepo(
                name="unclecode/crawl4ai",
                url="https://github.com/unclecode/crawl4ai",
                description="LLM 友好的异步网页爬虫框架，输出干净 Markdown，"
                "适合把网页内容喂给大模型。",
                stars=62000,
                language="Python",
                topics=["crawler", "llm", "web-scraping"],
                trending_rank=2,
            ),
            GitHubRepo(
                name="FunAudioLLM/CosyVoice",
                url="https://github.com/FunAudioLLM/CosyVoice",
                description="阿里通义开源的语音合成大模型，支持多语言、多情感、"
                "零样本音色克隆，Apache-2.0 协议可商用。",
                stars=22000,
                language="Python",
                topics=["tts", "speech-synthesis", "ai"],
                trending_rank=3,
            ),
        ]

    # ------------------------------------------------------------------
    # 批量获取（用于批量生成播客）
    # ------------------------------------------------------------------
    def discover_batch(self, total_count: int) -> list[GitHubRepo]:
        """批量获取大量项目，用于串行生成多期播客。

        通过 GitHub Search API 分页 + 多语言/主题轮询获取大量项目。
        无网络时使用 mock 数据源生成。

        Args:
            total_count: 需要的项目总数。

        Returns:
            去重后的 GitHubRepo 列表。
        """
        if self.allow_mock:
            return self._fetch_mock_batch(total_count)

        repos = self._fetch_batch_from_github_search(total_count)
        if len(repos) < total_count:
            # 补充 trending 数据
            trending = self._fetch_from_rsshub() or self._fetch_from_trending_api()
            existing = {r.name for r in repos}
            for r in trending:
                if r.name not in existing:
                    repos.append(r)
                    existing.add(r.name)
        if len(repos) < total_count:
            # 补充 mock 数据
            mock = self._fetch_mock_batch(total_count - len(repos))
            existing = {r.name for r in repos}
            for r in mock:
                if r.name not in existing:
                    repos.append(r)
                    existing.add(r.name)

        repos = self._filter(repos)
        repos = repos[:total_count]
        for i, repo in enumerate(repos, 1):
            repo.trending_rank = i
        logger.info(f"批量获取 {len(repos)} 个项目（需求 {total_count}）")
        return repos

    def _fetch_batch_from_github_search(self, total_count: int) -> list[GitHubRepo]:
        """通过 GitHub Search API 分页获取大量项目。"""
        if not self.github_token:
            logger.warning("未配置 GITHUB_TOKEN，批量搜索不可用")
            return []

        repos: list[GitHubRepo] = []
        seen: set[str] = set()
        # 多组查询条件轮询，每组最多 1000 条（GitHub Search 限制）
        queries = self._build_batch_queries()
        per_page = min(100, total_count)
        page = 1

        for query in queries:
            if len(repos) >= total_count:
                break
            page = 1
            while len(repos) < total_count and page <= 10:  # GitHub 限制 1000 条
                params = {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_page,
                    "page": page,
                }
                try:
                    resp = self._session.get(
                        "https://api.github.com/search/repositories",
                        params=params,
                        timeout=30,
                    )
                    if resp.status_code != 200:
                        break
                    items = resp.json().get("items", [])
                    if not items:
                        break
                    for item in items:
                        full_name = item["full_name"]
                        if full_name in seen:
                            continue
                        seen.add(full_name)
                        repos.append(
                            GitHubRepo(
                                name=full_name,
                                url=item["html_url"],
                                description=item.get("description", "") or "",
                                stars=item.get("stargazers_count", 0),
                                language=item.get("language", "") or "",
                                topics=item.get("topics", []),
                            )
                        )
                        if len(repos) >= total_count:
                            break
                    page += 1
                except (requests.RequestException, ValueError):
                    break
        logger.info(f"GitHub Search 批量获取 {len(repos)} 个项目")
        return repos

    def _build_batch_queries(self) -> list[str]:
        """构建多组搜索查询，覆盖不同主题以获取多样化项目。"""
        from datetime import datetime, timedelta

        since_date = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
        # 多主题轮询，每个主题可获取最多 1000 条
        topics = ["", "topic:ai", "topic:llm", "topic:machine-learning",
                  "topic:rust", "topic:python", "topic:typescript",
                  "topic:web", "topic:database", "topic:cli"]
        lang = self.cfg.get("language", "").strip()
        queries = []
        for topic in topics:
            q = f"stars:>200 pushed:>{since_date}"
            if topic:
                q += f" {topic}"
            if lang:
                q += f" language:{lang}"
            queries.append(q)
        return queries

    def _fetch_mock_batch(self, count: int) -> list[GitHubRepo]:
        """生成大量 mock 项目数据（用于批量测试）。"""
        import random

        templates = [
            ("ai", "AI/ML", "Python"),
            ("llm", "大模型", "Python"),
            ("web", "Web 框架", "TypeScript"),
            ("rust", "系统工具", "Rust"),
            ("go", "云原生", "Go"),
            ("db", "数据库", "C++"),
            ("devops", "DevOps", "Go"),
            ("security", "安全工具", "Python"),
            ("game", "游戏引擎", "C++"),
            ("blockchain", "区块链", "Rust"),
            ("robotics", "机器人", "C++"),
            ("data", "数据可视化", "Python"),
            ("audio", "音频处理", "Python"),
            ("video", "视频处理", "C++"),
            ("cli", "命令行工具", "Go"),
        ]
        prefixes = ["awesome", "open", "fast", "smart", "hyper", "deep",
                     "nano", "mega", "ultra", "pro", "mini", "lite", "next"]
        suffixes = ["hub", "flow", "kit", "box", "lab", "forge", "craft",
                     "engine", "studio", "works", "wave", "pulse", "sync", "node"]

        repos: list[GitHubRepo] = []
        used_names: set[str] = set()
        attempts = 0
        while len(repos) < count and attempts < count * 5:
            attempts += 1
            tag, tag_cn, lang = random.choice(templates)
            pfx = random.choice(prefixes)
            sfx = random.choice(suffixes)
            owner = random.choice(["openai", "google", "meta", "microsoft",
                                   "apache", "facebook", "uber", "netflix",
                                   "shopify", "gitlab", "coder", "team"])
            name = f"{owner}/{pfx}-{sfx}-{tag}"
            if name in used_names:
                continue
            used_names.add(name)
            stars = random.randint(200, 80000)
            repos.append(GitHubRepo(
                name=name,
                url=f"https://github.com/{name}",
                description=f"一个 {tag_cn} 领域的开源项目，提供高性能的 {sfx} 解决方案，"
                           f"支持快速集成与扩展。社区活跃，持续迭代中。",
                stars=stars,
                language=lang,
                topics=[tag, pfx, sfx],
                trending_rank=len(repos) + 1,
            ))
        logger.info(f"mock 批量生成 {len(repos)} 个项目")
        return repos

    # ------------------------------------------------------------------
    # 过滤
    # ------------------------------------------------------------------
    def _filter(self, repos: list[GitHubRepo]) -> list[GitHubRepo]:
        min_stars = self.cfg.get("min_stars", 0)
        keywords = [k.lower() for k in self.cfg.get("keywords", [])]
        exclude = [k.lower() for k in self.cfg.get("exclude_keywords", [])]
        result: list[GitHubRepo] = []
        for repo in repos:
            if repo.stars < min_stars:
                continue
            text = f"{repo.name} {repo.description}".lower()
            if any(kw in text for kw in exclude):
                continue
            if keywords and not any(kw in text for kw in keywords):
                continue
            result.append(repo)
        logger.info(f"过滤后保留 {len(result)} 个仓库")
        return result
