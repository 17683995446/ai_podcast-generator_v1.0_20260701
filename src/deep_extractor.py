"""深度内容提取器：超越 README，提取仓库的完整技术画像。

借鉴 GitPodcast 的 Direct repository access 和 Podcastfy 的多源内容提取。
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


class DeepExtractor:
    """深度提取 GitHub 仓库的技术画像。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config.get("crawler", {})
        self.github_token = config["api_keys"].get("github", "")
        self.allow_mock = bool(config.get("_mock_mode", False))
        self._session = requests.Session()
        if self.github_token:
            self._session.headers["Authorization"] = f"token {self.github_token}"
        self._session.headers["User-Agent"] = "github-podcast-tool/0.2"
        self._session.headers["Accept"] = "application/vnd.github+json"
        # 文件级 GitHub API 缓存（批量模式下避免重复请求同一仓库）
        self._cache_dir = Path(config["project_root"]) / "output" / ".api_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl = 3600  # 1 小时缓存
        # 最近一次 extract() 的健康度指标（供 main.py 复用，避免重复请求）
        self._last_health_metrics: dict = {}

    def extract(self, repo) -> str:
        """提取仓库的深度技术内容，拼装为 LLM 可读的 Markdown。

        Args:
            repo: GitHubRepo 对象（需有 name 和 url 属性）。

        Returns:
            格式化的 Markdown 文本，包含文件树、关键源码、Release Notes 等。
        """
        if self.allow_mock:
            return self._mock_extract(repo)

        parts = []
        
        # 1. 文件树结构
        tree = self._fetch_file_tree(repo.name)
        if tree:
            parts.append(f"## 仓库结构\n```\n{tree}\n```")

        # 2. 关键源码文件
        key_files = self._fetch_key_files(repo.name)
        for fname, content in key_files:
            if content:
                parts.append(f"### 关键文件: {fname}\n```\n{content[:2000]}\n```")

        # 3. 依赖清单（真实依赖解析）
        deps = self._parse_dependencies(repo.name)
        if deps:
            parts.append(f"## 依赖清单\n{deps}")

        # 4. Release Notes
        releases = self._fetch_releases(repo.name)
        if releases:
            parts.append(f"## 最近发布\n{releases}")

        # 5. 语言分布
        langs = self._fetch_languages(repo.name)
        if langs:
            parts.append(f"## 语言分布\n{langs}")

        # 6. 开发动态（提交历史 / 演进叙述）
        activity = self._fetch_commit_activity(repo.name)
        if activity:
            parts.append(f"## 开发动态\n{activity}")

        # 7. 健康度指标
        health = self._fetch_health_metrics(repo.name)
        self._last_health_metrics = health
        health_md = self._format_health_metrics(health)
        if health_md:
            parts.append(f"## 健康度\n{health_md}")

        return "\n\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # 文件级 GitHub API 缓存（批量模式下避免重复请求）
    # ------------------------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        """根据 cache key 生成稳定的缓存文件路径。"""
        # 使用 sha1 生成确定性的文件名（跨进程稳定，避免内置 hash 的随机化问题）
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
            print(f"[deep_extractor] 缓存写入失败: {e}")

    def _fetch_file_tree(self, full_name: str) -> str:
        """获取仓库文件树（仅目录级 + 关键文件）。"""
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/git/trees/main?recursive=1",
                timeout=30,
            )
            if resp.status_code != 200:
                # 尝试 master 分支
                resp = self._session.get(
                    f"https://api.github.com/repos/{full_name}/git/trees/master?recursive=1",
                    timeout=30,
                )
            if resp.status_code != 200:
                return ""
            
            tree = resp.json().get("tree", [])
            # 过滤：只保留目录和关键文件
            key_patterns = [
                r"\.py$", r"\.js$", r"\.ts$", r"\.go$", r"\.rs$",
                r"\.java$", r"\.c$", r"\.cpp$", r"\.h$",
                r"setup\.py$", r"pyproject\.toml$", r"package\.json$",
                r"Cargo\.toml$", r"go\.mod$", r"requirements\.txt$",
                r"Dockerfile$", r"Makefile$", r"\.yml$", r"\.yaml$",
                r"README", r"LICENSE", r"CONTRIBUTING",
            ]
            
            lines = []
            for item in tree[:200]:  # 限制数量
                path = item["path"]
                item_type = item["type"]
                # 只保留 2 层以内的路径
                depth = path.count("/")
                if depth > 2:
                    continue
                if item_type == "tree":
                    lines.append(f"📁 {path}/")
                elif any(re.search(p, path, re.IGNORECASE) for p in key_patterns):
                    lines.append(f"  📄 {path}")
            
            return "\n".join(lines[:80])  # 限制输出
        except Exception as e:
            print(f"[deep_extractor] 文件树获取失败: {e}")
            return ""

    def _fetch_key_files(self, full_name: str) -> list[tuple[str, str]]:
        """获取关键源码文件内容（入口文件、配置文件）。"""
        key_filenames = [
            "setup.py", "pyproject.toml", "package.json", "Cargo.toml",
            "go.mod", "requirements.txt", "Dockerfile", "Makefile",
            "main.py", "app.py", "index.js", "index.ts", "main.go",
            "src/lib.rs", "src/main.rs",
        ]
        results = []
        for fname in key_filenames:
            try:
                resp = self._session.get(
                    f"https://raw.githubusercontent.com/{full_name}/HEAD/{fname}",
                    timeout=15,
                )
                if resp.status_code == 200 and len(resp.text) > 10:
                    results.append((fname, resp.text[:3000]))
                    if len(results) >= 3:  # 最多3个关键文件
                        break
            except Exception:
                continue
        return results

    def _fetch_releases(self, full_name: str) -> str:
        """获取最近 3 个 Release Notes。"""
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/releases?per_page=3",
                timeout=30,
            )
            if resp.status_code != 200:
                return ""
            releases = resp.json()
            if not releases:
                return ""
            
            lines = []
            for rel in releases[:3]:
                tag = rel.get("tag_name", "")
                name = rel.get("name", tag)
                body = (rel.get("body") or "")[:500]
                lines.append(f"### {tag}: {name}\n{body}")
            return "\n".join(lines)
        except Exception as e:
            print(f"[deep_extractor] Release 获取失败: {e}")
            return ""

    def _fetch_languages(self, full_name: str) -> str:
        """获取语言分布。"""
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/languages",
                timeout=30,
            )
            if resp.status_code != 200:
                return ""
            langs = resp.json()
            if not langs:
                return ""
            total = sum(langs.values())
            lines = []
            for lang, bytes_count in sorted(langs.items(), key=lambda x: -x[1])[:5]:
                pct = bytes_count / total * 100 if total > 0 else 0
                lines.append(f"- {lang}: {pct:.1f}%")
            return "\n".join(lines)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # 开发动态：提交历史 / 演进叙述（借鉴 GitStory / GitNarrator）
    # ------------------------------------------------------------------
    def _fetch_commit_activity(self, full_name: str) -> str:
        """获取近 30 次提交并生成开发动态叙述。"""
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/commits?per_page=30",
                timeout=30,
            )
            if resp.status_code != 200:
                return ""
            commits = resp.json()
            if not commits:
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

            for c in commits:
                commit_obj = c.get("commit", {}) or {}
                # 贡献者：优先 login，回退到 commit.author.name
                author = (c.get("author") or {}).get("login") or (
                    commit_obj.get("author", {}) or {}
                ).get("name", "unknown")
                contributor_counts[author] = contributor_counts.get(author, 0) + 1
                # 提交主题：按 conventional commits 前缀归类
                msg = (commit_obj.get("message") or "").strip()
                first_line = msg.split("\n", 1)[0]
                m = re.match(r"^(\w+)(\([^)]+\))?!?:", first_line)
                label = theme_map.get(m.group(1).lower(), "其他") if m else "其他"
                themes[label] = themes.get(label, 0) + 1
                # 最近提交日期
                date_str = (commit_obj.get("author", {}) or {}).get("date", "")
                if date_str and date_str > last_commit_date:
                    last_commit_date = date_str

            # 贡献者总数：优先 stats/contributors，失败（202/404 等）则回退到 commits 去重数
            contributor_total = len(contributor_counts)
            try:
                stats_resp = self._session.get(
                    f"https://api.github.com/repos/{full_name}/stats/contributors",
                    timeout=30,
                )
                if stats_resp.status_code == 200:
                    stats_data = stats_resp.json()
                    if isinstance(stats_data, list) and stats_data:
                        contributor_total = len(stats_data)
            except Exception:
                pass

            theme_parts = [f"{label}({cnt})" for label, cnt in sorted(themes.items(), key=lambda x: -x[1])]
            top_contributors = sorted(contributor_counts.items(), key=lambda x: -x[1])[:3]
            contrib_parts = [f"{name}({cnt}次)" for name, cnt in top_contributors]
            last_date_short = last_commit_date[:10] if last_commit_date else "未知"

            lines = []
            if theme_parts:
                lines.append(f"近{len(commits)}次提交主要方向：{'、'.join(theme_parts)}。")
            lines.append(f"核心贡献者：{'、'.join(contrib_parts)}（共{contributor_total}位贡献者）。")
            lines.append(f"最近提交：{last_date_short}")
            return "\n".join(lines)
        except Exception as e:
            print(f"[deep_extractor] 提交活动获取失败: {e}")
            return ""

    # ------------------------------------------------------------------
    # 真实依赖解析（借鉴 readme-ai）
    # ------------------------------------------------------------------
    def _parse_dependencies(self, full_name: str) -> str:
        """解析依赖清单文件，提取真实依赖并格式化为 Markdown。"""
        file_parsers = [
            ("requirements.txt", self._parse_requirements),
            ("package.json", self._parse_package_json),
            ("pyproject.toml", self._parse_pyproject),
            ("Cargo.toml", self._parse_cargo),
            ("go.mod", self._parse_go_mod),
        ]

        deps: dict[str, list[str]] = {}
        for fname, parser in file_parsers:
            try:
                resp = self._session.get(
                    f"https://raw.githubusercontent.com/{full_name}/HEAD/{fname}",
                    timeout=15,
                )
                if resp.status_code != 200 or not resp.text:
                    continue
                parsed = parser(resp.text)
                for category, items in parsed.items():
                    if items:
                        deps.setdefault(category, []).extend(items)
            except Exception:
                continue

        if not deps:
            return ""

        lines = []
        for category, items in deps.items():
            unique_items = list(dict.fromkeys(items))  # 去重并保留顺序
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
            if " #" in line:  # 去掉行内注释
                line = line.split(" #", 1)[0].strip()
            m = re.match(r"^([A-Za-z0-9_.\-]+)", line)
            if m:
                pkgs.append(m.group(1))
        return {"Python": pkgs} if pkgs else {}

    def _parse_package_json(self, content: str) -> dict[str, list[str]]:
        """解析 package.json，提取 dependencies 与 devDependencies。"""
        try:
            data = json.loads(content)
        except Exception:
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
        # 回退：[tool.poetry.dependencies]
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
            # 块状 require 开始：require (
            if re.match(r"^require\s*\(\s*$", line):
                in_block = True
                continue
            # 单行 require：require github.com/foo/bar v1.2.3
            m = re.match(r"^require\s+(\S+)\s+v[0-9]", line)
            if m:
                pkgs.append(m.group(1).split("/")[-1])
        return {"Go": pkgs} if pkgs else {}

    # ------------------------------------------------------------------
    # 健康度指标（借鉴 GitHub Intelligence）
    # ------------------------------------------------------------------
    def _fetch_health_metrics(self, full_name: str) -> dict:
        """获取仓库健康度指标，返回 dict 供其他模块使用。"""
        if self.allow_mock:
            return self._mock_health_metrics()

        # 缓存命中则直接返回，避免批量模式下重复请求 GitHub API
        cache_key = f"health_{full_name}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

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

        # 仓库基本信息（open_issues_count）
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}",
                timeout=30,
            )
            if resp.status_code == 200:
                metrics["open_issues"] = resp.json().get("open_issues_count", 0) or 0
        except Exception as e:
            print(f"[deep_extractor] 仓库信息获取失败: {e}")

        # 贡献者列表（含匿名）
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/contributors?per_page=100&anon=true",
                timeout=30,
            )
            if resp.status_code == 200:
                contributors = resp.json() or []
                metrics["contributor_count"] = len(contributors)
                top = []
                for c in contributors[:5]:
                    name = c.get("login") or c.get("name") or "unknown"
                    top.append({"name": name, "commits": c.get("contributions", 0)})
                metrics["top_contributors"] = top
        except Exception:
            pass

        # Release 数量与最近发布日期
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/releases?per_page=100",
                timeout=30,
            )
            if resp.status_code == 200:
                releases = resp.json() or []
                metrics["release_count"] = len(releases)
                if releases:
                    metrics["last_release_date"] = (releases[0].get("published_at") or "")[:10]
        except Exception:
            pass

        # 近 30 天提交数与最近提交日期
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            resp = self._session.get(
                f"https://api.github.com/repos/{full_name}/commits?per_page=100&since={since}",
                timeout=30,
            )
            if resp.status_code == 200:
                commits = resp.json() or []
                metrics["commit_count_30d"] = len(commits)
                if commits:
                    metrics["last_commit_date"] = (
                        ((commits[0].get("commit", {}) or {}).get("author", {}) or {}).get("date", "")
                    )[:10]
                cnt = metrics["commit_count_30d"]
                if cnt >= 30:
                    metrics["commit_activity_trend"] = "活跃"
                elif cnt >= 10:
                    metrics["commit_activity_trend"] = "正常"
                elif cnt >= 1:
                    metrics["commit_activity_trend"] = "低活跃"
                else:
                    metrics["commit_activity_trend"] = "不活跃"
        except Exception:
            pass

        # 已关闭 Issue 数（search API），进而计算 Issue 关闭率 = closed / (open + closed)
        try:
            resp = self._session.get(
                f"https://api.github.com/search/issues?q=repo:{full_name}+is:issue+is:closed",
                timeout=30,
            )
            if resp.status_code == 200:
                closed = resp.json().get("total_count", 0) or 0
                metrics["closed_issues"] = closed
                total = metrics["open_issues"] + closed
                if total > 0:
                    metrics["issue_close_rate"] = round(closed / total * 100, 1)
        except Exception:
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
        # 同步暴露给 main.py 复用，保持与真实模式行为一致
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
        # 计算健康度评分
        from .models import RepoHealth
        rh = RepoHealth(repo_name="mock", **{k: v for k, v in metrics.items() if k in RepoHealth.__dataclass_fields__})
        metrics["health_score"] = rh.health_score
        metrics["health_grade"] = rh.health_grade
        return metrics
