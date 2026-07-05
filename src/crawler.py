"""内容抓取模块：将 GitHub 仓库 README 转为干净的 Markdown。

使用 Jina Reader（https://r.jina.ai）免费云服务，自动去除网页噪音，
输出 LLM 友好的 Markdown。失败时回退到 GitHub raw README。
GitHub API 调用（README / topics）使用 PyGithub 替代手写 REST 请求。
"""
from __future__ import annotations

import re
from typing import Any

import requests
from github import Github, GithubException

from .models import GitHubRepo

from src.logger import get_logger

logger = get_logger(__name__)


class ReadmeCrawler:
    """抓取并清洗 README 内容。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["crawler"]
        self.jina_url = self.cfg["jina_reader_url"].rstrip("/")
        self.max_chars = self.cfg.get("max_readme_chars", 8000)
        self.timeout = self.cfg.get("timeout", 30)
        self.github_token = config["api_keys"].get("github", "")

        # requests.Session 仍用于 Jina Reader 调用（非 GitHub API）
        self._session = requests.Session()
        if self.github_token:
            self._session.headers["Authorization"] = f"token {self.github_token}"
        self._session.headers["User-Agent"] = "github-podcast-tool/0.1"

        # PyGithub 客户端（用于 GitHub API 调用：README / topics）
        self._gh = (
            Github(self.github_token)
            if self.github_token
            else Github()
        )

    def fetch_readme(self, repo: GitHubRepo) -> str:
        """抓取仓库 README，写入 repo.readme_markdown 并返回。

        优先级：
        1. Jina Reader（最干净，含描述/标题等上下文）
        2. GitHub raw README（多文件名尝试）
        3. GitHub API contents 接口
        4. 内置 mock README（离线测试用）
        """
        content = self._fetch_via_jina(repo.url)
        if not content or len(content) < 50:
            content = self._fetch_via_github_raw(repo)
        if not content or len(content) < 50:
            content = self._mock_readme(repo)
        if not content:
            content = repo.description or f"（无 README，项目描述：{repo.description}）"

        content = self._clean(content)
        content = content[: self.max_chars]
        repo.readme_markdown = content
        return content

    def fetch_all(self, repos: list[GitHubRepo]) -> None:
        """批量抓取多个仓库的 README。"""
        for repo in repos:
            logger.info(f"抓取 README: {repo.name}")
            self.fetch_readme(repo)

    # ------------------------------------------------------------------
    def _fetch_via_jina(self, repo_url: str) -> str:
        """通过 Jina Reader 抓取（免费，输出 Markdown）。"""
        url = f"{self.jina_url}/{repo_url}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.text
            logger.warning(f"Jina Reader 返回 {resp.status_code}")
        except requests.RequestException as e:
            logger.error(f"Jina Reader 请求失败: {e}")
        return ""

    def _fetch_via_github_raw(self, repo: GitHubRepo) -> str:
        """从 GitHub raw 直接获取 README（多种文件名与大小写）。"""
        candidates = [
            "README.md", "readme.md", "Readme.md",
            "README.rst", "README.txt", "README",
            "README.zh.md", "README_CN.md", "README-zh.md",
        ]
        for filename in candidates:
            raw_url = f"https://raw.githubusercontent.com/{repo.name}/HEAD/{filename}"
            try:
                resp = self._session.get(raw_url, timeout=self.timeout)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.text
            except requests.RequestException:
                continue

        # 尝试 GitHub API 获取默认分支 README
        return self._fetch_via_github_api(repo)

    def _fetch_via_github_api(self, repo: GitHubRepo) -> str:
        """通过 PyGithub 获取 README（GitHub API contents 接口）。"""
        try:
            gh_repo = self._gh.get_repo(repo.name)
            readme = gh_repo.get_readme()
            if readme.encoding == "base64":
                return readme.decoded_content.decode("utf-8", errors="replace")
            return readme.content or ""
        except GithubException as e:
            logger.error(f"GitHub API 失败: {e}")
        except Exception as e:
            logger.error(f"GitHub API 失败: {e}")
        return ""

    # ------------------------------------------------------------------
    @staticmethod
    def _clean(text: str) -> str:
        """清洗 Markdown：去除图片、徽章、多余空行。"""
        # 去除图片标签 ![alt](url)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        # 去除 HTML 标签
        text = re.sub(r"<img[^>]*>", "", text)
        text = re.sub(r"<a[^>]*>.*?</a>", "", text, flags=re.DOTALL)
        # 去除徽章行（连续的 ![...](badge) 模式）
        text = re.sub(r"^\s*\[!\[.*?\]\(.*?\)\]\(.*?\).*$", "", text, flags=re.MULTILINE)
        # 去除 HTML 注释
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        # 压缩多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 去除超长行（可能是压缩代码）
        lines = []
        for line in text.split("\n"):
            if len(line) > 500:
                line = line[:500] + "..."
            lines.append(line)
        return "\n".join(lines).strip()


    # ------------------------------------------------------------------
    @staticmethod
    def _mock_readme(repo: GitHubRepo) -> str:
        """离线时生成模拟 README 内容（基于已知信息）。"""
        topics_str = ", ".join(repo.topics) if repo.topics else "未指定"
        return f"""# {repo.name}

{repo.description}

## 简介

{repo.name} 是一个值得关注的开源项目，目前在 GitHub 上拥有 {repo.stars} 颗 Star，
主要编程语言为 {repo.language or '多种'}，标签包括：{topics_str}。

## 核心功能

- 提供高效的技术解决方案，解决实际开发痛点
- 活跃的开源社区维护，持续迭代更新
- 良好的文档与示例，易于上手集成

## 技术亮点

该项目采用现代化的架构设计，注重性能与可扩展性。
社区反馈积极，issue 响应及时，是一个值得长期关注的项目。

## 应用场景

适用于开发者、研究者和企业团队，可在多种场景下发挥作用。
"""


def enrich_repo_topics(repo: GitHubRepo, github_token: str = "", mock_mode: bool = False) -> None:
    """通过 PyGithub 补充仓库的 topics 信息（可选）。"""
    if mock_mode:
        return
    if repo.topics:
        return
    try:
        gh = Github(github_token) if github_token else Github()
        gh_repo = gh.get_repo(repo.name)
        repo.topics = gh_repo.get_topics()
    except GithubException:
        pass
    except Exception as e:
        logger.warning("抓取失败: %s", e)
