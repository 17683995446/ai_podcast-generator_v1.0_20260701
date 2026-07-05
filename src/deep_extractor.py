"""深度内容提取器：超越 README，提取仓库的完整技术画像。

借鉴 GitPodcast 的 Direct repository access 和 Podcastfy 的多源内容提取。
使用 PyGithub 替代手写 GitHub REST API 调用，获得：
  - 类型安全的属性访问（无需手动解析 JSON）
  - 自动分页与速率限制感知
  - 统一的异常处理（GithubException）

提取内容包括：
1. 仓库文件树结构（目录布局）
2. 关键源码文件（入口文件、配置文件、核心模块）
3. 依赖清单（解析 requirements.txt / package.json / pyproject.toml / Cargo.toml / go.mod）
4. 最近 Release Notes（版本更新内容）
5. 主要编程语言分布
6. 开发动态（提交活动、贡献者、提交主题，借鉴 GitStory / GitNarrator）
7. 健康度指标（提交频率、贡献者数、Issue 关闭率等，借鉴 GitHub Intelligence）
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from github import Github, GithubException
from github.Repository import Repository

from src.logger import get_logger

logger = get_logger(__name__)


class DeepExtractor:
    """深度提取 GitHub 仓库的技术画像（使用 PyGithub）。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config.get("crawler", {})
        self.github_token = config["api_keys"].get("github", "")
        self.allow_mock = bool(config.get("_mock_mode", False))

        # PyGithub 客户端：有 token 时认证，无 token 时匿名（受 60 次/小时限制）
        self._gh = (
            Github(self.github_token)
            if self.github_token
            else Github()
        )

        # 文件级 GitHub API 缓存（批量模式下避免重复请求同一仓库）
        self._cache_dir = Path(config["project_root"]) / "output" / ".api_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl = 3600  # 1 小时缓存

        # PyGithub Repository 对象缓存（避免重复 get_repo 调用）
        self._repo_cache: dict[str, Repository] = {}

        # 最近一次 extract() 的健康度指标（供 main.py 复用，避免重复请求）
        self._last_health_metrics: dict = {}

        # 证据收集器：记录每项提取数据的来源
        self._last_evidence: list[dict] = []

        # 代码级分析所需的原始数据（供 CodeAnalyzer 使用）
        self._last_file_tree: list[str] = []
        self._last_source_code: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 公共访问器（替代外部直接访问 _last_* 私有属性）
    # ------------------------------------------------------------------
    def get_last_health_metrics(self) -> dict:
        """获取最近一次提取的健康度指标。

        替代外部直接访问 extractor._last_health_metrics。
        返回副本以防止外部修改内部状态。
        """
        return dict(self._last_health_metrics)

    def get_last_file_tree(self) -> list[str]:
        """获取最近一次提取的文件树。

        替代外部直接访问 extractor._last_file_tree。
        返回副本以防止外部修改内部状态。
        """
        return list(self._last_file_tree)

    def get_last_source_code(self) -> dict[str, str]:
        """获取最近一次提取的源码文件。

        替代外部直接访问 extractor._last_source_code。
        返回副本以防止外部修改内部状态。
        """
        return dict(self._last_source_code)

    # ------------------------------------------------------------------
    # PyGithub 辅助方法
    # ------------------------------------------------------------------
    def _get_repo(self, full_name: str) -> Repository | None:
        """获取 PyGithub Repository 对象（带缓存）。"""
        if full_name in self._repo_cache:
            return self._repo_cache[full_name]
        try:
            repo = self._gh.get_repo(full_name)
            self._repo_cache[full_name] = repo
            return repo
        except GithubException as e:
            logger.error(f"获取仓库 {full_name} 失败: {e}")
            return None

    def _get_file_content(self, repo: Repository, path: str) -> str:
        """获取仓库中指定文件的内容（通过 PyGithub get_contents）。

        替代旧的 raw.githubusercontent.com 请求。
        """
        try:
            content_file = repo.get_contents(path)
            if hasattr(content_file, "decoded_content"):
                return content_file.decoded_content.decode("utf-8", errors="replace")
        except GithubException:
            pass
        return ""

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def extract(self, repo) -> str:
        """提取仓库的深度技术内容，拼装为 LLM 可读的 Markdown。

        Args:
            repo: GitHubRepo 对象（需有 name 和 url 属性）。

        Returns:
            格式化的 Markdown 文本，包含文件树、关键源码、Release Notes 等。
        """
        if self.allow_mock:
            return self._mock_extract(repo)

        gh_repo = self._get_repo(repo.name)
        if gh_repo is None:
            return ""

        parts = []

        # 1. 文件树结构
        tree = self._fetch_file_tree(gh_repo)
        if tree:
            parts.append(f"## 仓库结构\n```\n{tree}\n```")
            self._record_evidence("file_tree", tree[:200], "file_tree", "GitHub API: git_tree(recursive=True)")
            # 存储原始文件路径供 CodeAnalyzer 使用
            self._last_file_tree = self._parse_tree_paths(tree)

        # 2. 关键源码文件
        key_files = self._fetch_key_files(gh_repo)
        for fname, content in key_files:
            if content:
                parts.append(f"### 关键文件: {fname}\n```\n{content[:2000]}\n```")
                self._record_evidence("source_code", fname, "source_code", f"GitHub API: get_contents({fname})")
                # 存储原始源码供 CodeAnalyzer 使用
                self._last_source_code[fname] = content

        # 3. 依赖清单（真实依赖解析）
        deps = self._parse_dependencies(gh_repo)
        if deps:
            parts.append(f"## 依赖清单\n{deps}")
            self._record_evidence("dependencies", deps[:200], "dependency_file", "parsed from requirements.txt/package.json/pyproject.toml/Cargo.toml/go.mod")

        # 4. Release Notes
        releases = self._fetch_releases(gh_repo)
        if releases:
            parts.append(f"## 最近发布\n{releases}")
            self._record_evidence("releases", releases[:200], "release_notes", "GitHub API: get_releases()")

        # 5. 语言分布
        langs = self._fetch_languages(gh_repo)
        if langs:
            parts.append(f"## 语言分布\n{langs}")
            self._record_evidence("languages", langs[:200], "github_stats", "GitHub API: get_languages()")

        # 6. 开发动态（提交历史 / 演进叙述）
        activity = self._fetch_commit_activity(gh_repo)
        if activity:
            parts.append(f"## 开发动态\n{activity}")
            self._record_evidence("commit_activity", activity[:200], "commit_history", "GitHub API: get_commits()")

        # 7. 健康度指标
        health = self._fetch_health_metrics(repo.name, gh_repo)
        self._last_health_metrics = health
        health_md = self._format_health_metrics(health)
        if health_md:
            parts.append(f"## 健康度\n{health_md}")
            self._record_evidence("health_metrics", health_md[:200], "github_stats", "GitHub API: multiple endpoints")

        return "\n\n".join(parts) if parts else ""

    def extract_with_evidence(self, repo) -> tuple[str, list[dict]]:
        """提取深度内容并同时返回证据来源清单。

        Returns:
            (markdown_text, evidence_list) —— evidence_list 中每项为
            {"field": str, "value": str, "source_type": str, "source_detail": str, "confidence": str}
        """
        self._last_evidence = []  # 重置证据收集器
        markdown = self.extract(repo)
        return markdown, list(self._last_evidence)

    def _record_evidence(self, field: str, value: str, source_type: str,
                         source_detail: str, confidence: str = "verified") -> None:
        """记录一条证据到收集器。"""
        self._last_evidence.append({
            "field": field,
            "value": value,
            "source_type": source_type,
            "source_detail": source_detail,
            "confidence": confidence,
        })

    # ------------------------------------------------------------------
    # 文件级 GitHub API 缓存（批量模式下避免重复请求）
    # ------------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        """根据 cache key 生成稳定的缓存文件路径。"""
        key_hash = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{key_hash}.json"

    def _cache_get(self, key: str) -> dict | None:
        """从缓存读取数据，超过 TTL 或不存在则返回 None。"""
        cache_file = self._cache_path(key)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, OSError):
            return None
        timestamp = data.get("_cached_at", 0)
        if time.time() - timestamp > self._cache_ttl:
            return None
        return data.get("payload")

    def _cache_set(self, key: str, data) -> None:
        """将数据写入缓存，附带写入时间戳。"""
        cache_file = self._cache_path(key)
        payload = {"_cached_at": time.time(), "payload": data}
        try:
            cache_file.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as e:
            logger.error(f"缓存写入失败: {e}")

    # ------------------------------------------------------------------
    # GitHub 数据提取（使用 PyGithub）
    # ------------------------------------------------------------------
    def _fetch_file_tree(self, repo: Repository) -> str:
        """获取仓库文件树（仅目录级 + 关键文件）。

        使用 PyGithub get_git_tree(recursive=True) 替代手动 REST API 调用。
        """
        # 尝试默认分支（PyGithub 自动获取 default_branch）
        for branch in [repo.default_branch, "main", "master"]:
            try:
                tree = repo.get_git_tree(branch, recursive=True)
                if tree.tree:
                    return self._format_file_tree(tree.tree)
            except GithubException:
                continue
        return ""

    @staticmethod
    def _format_file_tree(tree_elements) -> str:
        """将 PyGithub GitTreeElement 列表格式化为目录树文本。"""
        key_patterns = [
            r"\.py$", r"\.js$", r"\.ts$", r"\.go$", r"\.rs$",
            r"\.java$", r"\.c$", r"\.cpp$", r"\.h$",
            r"setup\.py$", r"pyproject\.toml$", r"package\.json$",
            r"Cargo\.toml$", r"go\.mod$", r"requirements\.txt$",
            r"Dockerfile$", r"Makefile$", r"\.yml$", r"\.yaml$",
            r"README", r"LICENSE", r"CONTRIBUTING",
        ]

        lines = []
        for item in tree_elements[:200]:
            path = item.path
            item_type = item.type
            depth = path.count("/")
            if depth > 2:
                continue
            if item_type == "tree":
                lines.append(f"📁 {path}/")
            elif any(re.search(p, path, re.IGNORECASE) for p in key_patterns):
                lines.append(f"  📄 {path}")

        return "\n".join(lines[:80])

    @staticmethod
    def _parse_tree_paths(tree_text: str) -> list[str]:
        """从格式化的文件树文本中提取文件路径列表。

        将 "📁 src/" 和 "  📄 src/main.py" 格式解析为路径列表，
        供 CodeAnalyzer 使用。
        """
        paths: list[str] = []
        for line in tree_text.split("\n"):
            line = line.strip()
            if line.startswith("📄"):
                path = line.replace("📄", "").strip()
                if path:
                    paths.append(path)
            elif line.startswith("📁"):
                # 目录路径也加入（CodeAnalyzer 用它检测架构模式）
                path = line.replace("📁", "").strip().rstrip("/")
                if path:
                    paths.append(f"{path}/")
        return paths

    def _fetch_key_files(self, repo: Repository) -> list[tuple[str, str]]:
        """获取关键源码文件内容（入口文件、配置文件）。

        使用 PyGithub get_contents() 替代 raw.githubusercontent.com 请求。
        """
        key_filenames = [
            "setup.py", "pyproject.toml", "package.json", "Cargo.toml",
            "go.mod", "requirements.txt", "Dockerfile", "Makefile",
            "main.py", "app.py", "index.js", "index.ts", "main.go",
            "src/lib.rs", "src/main.rs",
        ]
        results = []
        for fname in key_filenames:
            content = self._get_file_content(repo, fname)
            if content and len(content) > 10:
                results.append((fname, content[:3000]))
                if len(results) >= 3:
                    break
        return results

    def _fetch_releases(self, repo: Repository) -> str:
        """获取最近 3 个 Release Notes。

        使用 PyGithub get_releases() 替代手动 REST API 调用。
        """
        try:
            releases = repo.get_releases()
            lines = []
            count = 0
            for rel in releases:
                if count >= 3:
                    break
                tag = rel.tag_name or ""
                name = rel.title or tag
                body = (rel.body or "")[:500]
                lines.append(f"### {tag}: {name}\n{body}")
                count += 1
            return "\n".join(lines) if lines else ""
        except GithubException as e:
            logger.error(f"Release 获取失败: {e}")
            return ""

    def _fetch_languages(self, repo: Repository) -> str:
        """获取语言分布。

        使用 PyGithub get_languages() 替代手动 REST API 调用。
        """
        try:
            langs = repo.get_languages()
            if not langs:
                return ""
            # P3修复：GitHub API 偶尔返回字符串值，统一转换为 int 防止 TypeError
            safe_langs = {}
            for lang, val in langs.items():
                try:
                    safe_langs[lang] = int(val)
                except (TypeError, ValueError):
                    pass
            if not safe_langs:
                return ""
            total = sum(safe_langs.values())
            lines = []
            for lang, bytes_count in sorted(safe_langs.items(), key=lambda x: -x[1])[:5]:
                pct = bytes_count / total * 100 if total > 0 else 0
                lines.append(f"- {lang}: {pct:.1f}%")
            return "\n".join(lines)
        except GithubException:
            return ""

    # ------------------------------------------------------------------
    # 开发动态：提交历史 / 演进叙述（借鉴 GitStory / GitNarrator）
    # ------------------------------------------------------------------
    def _fetch_commit_activity(self, repo: Repository) -> str:
        """获取近 30 次提交并生成开发动态叙述。

        使用 PyGithub get_commits() 替代手动 REST API 调用。
        """
        try:
            commits = repo.get_commits()[:30]
            commits_list = list(commits)
            if not commits_list:
                return ""

            theme_map = {
                "feat": "功能开发",
                "fix": "Bug修复",
                "docs": "文档",
                "refactor": "重构",
                "perf": "性能优化",
                "test": "测试",
                "chore": "维护",
                "style": "格式",
                "ci": "CI",
                "build": "构建",
                "revert": "回退",
            }
            contributor_counts: dict[str, int] = {}
            themes: dict[str, int] = {}
            last_commit_date = ""

            for c in commits_list:
                commit_obj = c.commit
                # 贡献者：优先 login，回退到 commit.author.name
                author = "unknown"
                if c.author and c.author.login:
                    author = c.author.login
                elif commit_obj.author and commit_obj.author.name:
                    author = commit_obj.author.name
                contributor_counts[author] = contributor_counts.get(author, 0) + 1
                # 提交主题：按 conventional commits 前缀归类
                msg = (commit_obj.message or "").strip()
                first_line = msg.split("\n", 1)[0]
                m = re.match(r"^(\w+)(\([^)]+\))?!?:", first_line)
                label = theme_map.get(m.group(1).lower(), "其他") if m else "其他"
                themes[label] = themes.get(label, 0) + 1
                # 最近提交日期
                if commit_obj.author and commit_obj.author.date:
                    date_str = commit_obj.author.date.isoformat()
                    if date_str > last_commit_date:
                        last_commit_date = date_str

            # 贡献者总数：优先 stats/contributors
            contributor_total = len(contributor_counts)
            try:
                contributors = repo.get_contributors()
                contributor_total = contributors.totalCount
            except Exception as e:
                logger.warning("贡献者获取失败: %s", e)

            theme_parts = [f"{label}({cnt})" for label, cnt in sorted(themes.items(), key=lambda x: -x[1])]
            top_contributors = sorted(contributor_counts.items(), key=lambda x: -x[1])[:3]
            contrib_parts = [f"{name}({cnt}次)" for name, cnt in top_contributors]
            last_date_short = last_commit_date[:10] if last_commit_date else "未知"

            lines = []
            if theme_parts:
                lines.append(f"近{len(commits_list)}次提交主要方向：{'、'.join(theme_parts)}。")
            lines.append(f"核心贡献者：{'、'.join(contrib_parts)}（共{contributor_total}位贡献者）。")
            lines.append(f"最近提交：{last_date_short}")
            return "\n".join(lines)
        except GithubException as e:
            logger.error(f"提交活动获取失败: {e}")
            return ""

    # ------------------------------------------------------------------
    # 真实依赖解析（借鉴 readme-ai）
    # ------------------------------------------------------------------
    def _parse_dependencies(self, repo: Repository) -> str:
        """解析依赖清单文件，提取真实依赖并格式化为 Markdown。

        使用 PyGithub get_contents() 获取文件内容，替代 raw.githubusercontent.com。
        依赖解析逻辑（文本解析）保持不变。
        """
        file_parsers = [
            ("requirements.txt", self._parse_requirements),
            ("package.json", self._parse_package_json),
            ("pyproject.toml", self._parse_pyproject),
            ("Cargo.toml", self._parse_cargo),
            ("go.mod", self._parse_go_mod),
        ]

        deps: dict[str, list[str]] = {}
        for fname, parser in file_parsers:
            content = self._get_file_content(repo, fname)
            if not content:
                continue
            parsed = parser(content)
            for category, items in parsed.items():
                if items:
                    deps.setdefault(category, []).extend(items)

        if not deps:
            return ""

        lines = []
        for category, items in deps.items():
            unique_items = list(dict.fromkeys(items))
            shown = ", ".join(unique_items[:20])
            lines.append(f"- {category}: {shown} ({len(unique_items)}个)")
        return "\n".join(lines)

    def _parse_requirements(self, content: str) -> dict[str, list[str]]:
        """解析 requirements.txt，提取 Python 依赖。"""
        pkgs: list[str] = []
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if " #" in line:
                line = line.split(" #", 1)[0].strip()
            m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
            if m:
                pkgs.append(m.group(1))
        return {"Python": pkgs} if pkgs else {}

    def _parse_package_json(self, content: str) -> dict[str, list[str]]:
        """解析 package.json，提取 dependencies 与 devDependencies。"""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("package.json 解析失败: %s", e)
            return {}
        result: dict[str, list[str]] = {}
        deps = data.get("dependencies") or {}
        if deps:
            result["npm"] = list(deps.keys())
        dev_deps = data.get("devDependencies") or {}
        if dev_deps:
            result["Dev"] = list(dev_deps.keys())
        return result

    def _parse_pyproject(self, content: str) -> dict[str, list[str]]:
        """解析 pyproject.toml 的 [project.dependencies] 段。"""
        pkgs: list[str] = []
        m = re.search(r"\[project\.dependencies\](.*?)(\n\[|\Z)", content, re.DOTALL)
        if m:
            for raw in m.group(1).splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                pm = re.match(r'^"?([A-Za-z0-9_.\-]+)"?', line)
                if pm:
                    pkgs.append(pm.group(1))
        if not pkgs:
            m = re.search(r"\[tool\.poetry\.dependencies\](.*?)(\n\[|\Z)", content, re.DOTALL)
            if m:
                for raw in m.group(1).splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or line.startswith("python"):
                        continue
                    pm = re.match(r'^"?([A-Za-z0-9_.\-]+)"?\s*=', line)
                    if pm:
                        pkgs.append(pm.group(1))
        return {"Python": pkgs} if pkgs else {}

    def _parse_cargo(self, content: str) -> dict[str, list[str]]:
        """解析 Cargo.toml 的 [dependencies] 段。"""
        pkgs: list[str] = []
        m = re.search(r"\[dependencies\](.*?)(\n\[|\Z)", content, re.DOTALL)
        if m:
            for raw in m.group(1).splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                pm = re.match(r"^([A-Za-z0-9_.\-]+)\s*=", line)
                if pm:
                    pkgs.append(pm.group(1))
        return {"Rust": pkgs} if pkgs else {}

    def _parse_go_mod(self, content: str) -> dict[str, list[str]]:
        """解析 go.mod 的 require（单行与块状），保留文档顺序。"""
        pkgs: list[str] = []
        in_block = False
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("//"):
                continue
            if in_block:
                if line.startswith(")"):
                    in_block = False
                    continue
                parts = line.split()
                if parts:
                    pkgs.append(parts[0].split("/")[-1])
                continue
            if re.match(r"^require\s*\(\s*$", line):
                in_block = True
                continue
            m = re.match(r"^require\s+(\S+)\s+v[0-9]", line)
            if m:
                pkgs.append(m.group(1).split("/")[-1])
        return {"Go": pkgs} if pkgs else {}

    # ------------------------------------------------------------------
    # 健康度指标（借鉴 GitHub Intelligence）
    # ------------------------------------------------------------------
    def _fetch_health_metrics(self, full_name: str, gh_repo: Repository | None = None) -> dict:
        """获取仓库健康度指标，返回 dict 供其他模块使用。

        使用 PyGithub 替代手动 REST API 调用。
        保留文件级缓存以避免批量模式下重复请求。
        """
        if self.allow_mock:
            return self._mock_health_metrics()

        # 缓存命中则直接返回
        cache_key = f"health_{full_name}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        if gh_repo is None:
            gh_repo = self._get_repo(full_name)
        if gh_repo is None:
            return self._mock_health_metrics()

        metrics = {
            "commit_count_30d": 0,
            "contributor_count": 0,
            "release_count": 0,
            "open_issues": 0,
            "closed_issues": 0,
            "issue_close_rate": 0.0,
            "last_commit_date": "",
            "last_release_date": "",
            "top_contributors": [],
            "commit_activity_trend": "未知",
        }

        # 仓库基本信息（open_issues_count 是 PyGithub Repository 属性）
        try:
            metrics["open_issues"] = gh_repo.open_issues_count
        except GithubException as e:
            logger.error(f"仓库信息获取失败: {e}")

        # 贡献者列表
        try:
            contributors = gh_repo.get_contributors()
            contrib_list = list(contributors[:100])
            metrics["contributor_count"] = len(contrib_list)
            top = []
            for c in contrib_list[:5]:
                name = c.login or c.name or "unknown"
                top.append({"name": name, "commits": c.contributions})
            metrics["top_contributors"] = top
        except GithubException:
            pass

        # Release 数量与最近发布日期
        try:
            releases = gh_repo.get_releases()
            release_list = list(releases[:100])
            metrics["release_count"] = len(release_list)
            if release_list:
                first = release_list[0]
                if first.published_at:
                    metrics["last_release_date"] = first.published_at.strftime("%Y-%m-%d")
        except GithubException:
            pass

        # 近 30 天提交数与最近提交日期
        since = datetime.now(timezone.utc) - timedelta(days=30)
        try:
            commits = gh_repo.get_commits(since=since)
            commit_list = list(commits[:100])
            metrics["commit_count_30d"] = len(commit_list)
            if commit_list:
                first = commit_list[0]
                if first.commit and first.commit.author and first.commit.author.date:
                    metrics["last_commit_date"] = first.commit.author.date.strftime("%Y-%m-%d")
            cnt = metrics["commit_count_30d"]
            if cnt >= 30:
                metrics["commit_activity_trend"] = "活跃"
            elif cnt >= 10:
                metrics["commit_activity_trend"] = "正常"
            elif cnt >= 1:
                metrics["commit_activity_trend"] = "低活跃"
            else:
                metrics["commit_activity_trend"] = "不活跃"
        except GithubException:
            pass

        # 已关闭 Issue 数（使用 Search API），进而计算 Issue 关闭率
        try:
            query = f"repo:{full_name} is:issue is:closed"
            search_result = self._gh.search_issues(query)
            closed = search_result.totalCount
            metrics["closed_issues"] = closed
            total = metrics["open_issues"] + closed
            if total > 0:
                metrics["issue_close_rate"] = round(closed / total * 100, 1)
        except GithubException:
            pass

        # 计算健康度评分和等级（与 RepoHealth 数据类逻辑一致）
        from .models import RepoHealth
        rh = RepoHealth(
            repo_name=full_name,
            commit_count_30d=metrics["commit_count_30d"],
            contributor_count=metrics["contributor_count"],
            release_count=metrics["release_count"],
            open_issues=metrics["open_issues"],
            closed_issues=metrics["closed_issues"],
            issue_close_rate=metrics["issue_close_rate"],
            last_commit_date=metrics["last_commit_date"],
            last_release_date=metrics["last_release_date"],
            top_contributors=metrics["top_contributors"],
            commit_activity_trend=metrics["commit_activity_trend"],
        )
        metrics["health_score"] = rh.health_score
        metrics["health_grade"] = rh.health_grade

        self._cache_set(cache_key, metrics)
        return metrics

    def _format_health_metrics(self, metrics: dict) -> str:
        """将健康度指标 dict 格式化为 Markdown 文本。"""
        if not metrics:
            return ""
        lines = [
            f"- 30天提交数: {metrics.get('commit_count_30d', 0)} 次（{metrics.get('commit_activity_trend', '未知')}）",
            f"- 贡献者: {metrics.get('contributor_count', 0)} 人",
            f"- Release 总数: {metrics.get('release_count', 0)} 个",
            f"- Issue 关闭率: {metrics.get('issue_close_rate', 0)}%（open: {metrics.get('open_issues', 0)} / closed: {metrics.get('closed_issues', 0)}）",
            f"- 最近提交: {metrics.get('last_commit_date') or '未知'}",
            f"- 最近发布: {metrics.get('last_release_date') or '未知'}",
        ]
        top = metrics.get("top_contributors") or []
        if top:
            top_str = "、".join(f"{c.get('name', '?')}({c.get('commits', 0)})" for c in top[:3])
            lines.append(f"- Top 贡献者: {top_str}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Mock 模式
    # ------------------------------------------------------------------
    def _mock_extract(self, repo) -> str:
        """Mock 模式下的深度提取。"""
        repo_name = repo.name.split("/")[-1]
        health = self._mock_health_metrics()
        self._last_health_metrics = health
        parts = [
            f"## 仓库结构\n```\n📁 src/\n  📄 main.py\n  📄 utils.py\n📁 tests/\n  📄 test_main.py\n📄 README.md\n📄 setup.py\n📄 requirements.txt\n```",
            f"### 关键文件: setup.py\n```\nfrom setuptools import setup\nsetup(name='{repo_name}', version='1.0.0')\n```",
            f"## 依赖清单\n{self._mock_parse_dependencies()}",
            f"## 最近发布\n### v1.0.0: Initial Release\n首次发布，包含核心功能。",
            f"## 语言分布\n- Python: 85.2%\n- JavaScript: 10.3%\n- Shell: 4.5%",
            f"## 开发动态\n{self._mock_commit_activity()}",
            f"## 健康度\n{self._format_health_metrics(health)}",
        ]
        # 记录 mock 证据（标注来源为 mock）
        self._last_evidence = []
        self._record_evidence("file_tree", "src/ tests/ README.md setup.py", "file_tree", "mock_data")
        self._record_evidence("source_code", "setup.py", "source_code", "mock_data")
        self._record_evidence("dependencies", "flask, requests, openai, pydantic", "dependency_file", "mock_data")
        self._record_evidence("releases", "v1.0.0: Initial Release", "release_notes", "mock_data")
        self._record_evidence("languages", "Python: 85.2%, JavaScript: 10.3%", "github_stats", "mock_data")
        self._record_evidence("commit_activity", "功能开发(15), Bug修复(8)", "commit_history", "mock_data")
        self._record_evidence("health_metrics", "commit_count_30d=27, issue_close_rate=80%", "github_stats", "mock_data")

        # 存储 mock 原始数据供 CodeAnalyzer 使用
        self._last_file_tree = ["src/", "src/main.py", "src/utils.py", "tests/", "tests/test_main.py", "README.md", "setup.py", "requirements.txt"]
        self._last_source_code = {
            "setup.py": f"from setuptools import setup\nsetup(name='{repo_name}', version='1.0.0')\n",
            "main.py": "def main():\n    print('Hello')\n\nif __name__ == '__main__':\n    main()\n",
        }

        return "\n\n".join(parts)

    def _mock_commit_activity(self) -> str:
        """Mock 提交活动叙述。"""
        return (
            "近30次提交主要方向：功能开发(15)、Bug修复(8)、文档(3)、重构(2)、测试(2)。\n"
            "核心贡献者：alice(12次)、bob(8次)、carol(5次)（共5位贡献者）。\n"
            "最近提交：2024-01-15"
        )

    def _mock_parse_dependencies(self) -> str:
        """Mock 依赖清单。"""
        return (
            "- Python: flask, requests, openai, pydantic (4个)\n"
            "- Dev: pytest, black, flake8 (3个)"
        )

    def _mock_health_metrics(self) -> dict:
        """Mock 健康度指标。"""
        metrics = {
            "commit_count_30d": 27,
            "contributor_count": 5,
            "release_count": 3,
            "open_issues": 12,
            "closed_issues": 48,
            "issue_close_rate": 80.0,
            "last_commit_date": "2024-01-15",
            "last_release_date": "2024-01-10",
            "top_contributors": [
                {"name": "alice", "commits": 12},
                {"name": "bob", "commits": 8},
                {"name": "carol", "commits": 5},
            ],
            "commit_activity_trend": "活跃",
        }
        from .models import RepoHealth
        rh = RepoHealth(repo_name="mock", **{k: v for k, v in metrics.items() if k in RepoHealth.__dataclass_fields__})
        metrics["health_score"] = rh.health_score
        metrics["health_grade"] = rh.health_grade
        return metrics
