"""代码级分析器：复杂度指标、架构模式检测、代码质量量化。

核心设计（第一性原理）：
  1. 基于已提取的文件树和源码，不额外请求 API
  2. 启发式规则检测架构模式，不依赖 LLM
  3. 量化指标可验证、可复现
  4. 与证据链系统联动：每个指标标注数据来源

分析维度：
  - 代码规模：LOC、文件数、平均文件大小
  - 架构模式：MVC / 微服务 / 单体 / 插件式 / 库 / CLI / 框架
  - 复杂度：圈复杂度估算、嵌套深度、分支密度
  - 质量量化：文档比例、测试覆盖估计、可维护性指数
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodeMetrics:
    """代码级分析指标。"""
    total_loc: int = 0                          # 总代码行数
    loc_by_language: dict[str, int] = field(default_factory=dict)  # 按语言统计
    file_count: int = 0                         # 源码文件数
    avg_file_loc: float = 0.0                   # 平均文件行数
    max_file_loc: int = 0                       # 最大文件行数
    architecture_pattern: str = "unknown"       # 检测到的架构模式
    architecture_confidence: float = 0.0        # 检测置信度 (0-1)
    architecture_signals: list[str] = field(default_factory=list)  # 检测信号
    complexity_score: float = 0.0               # 复杂度评分 (1-10)
    complexity_factors: dict[str, Any] = field(default_factory=dict)  # 复杂度因子
    quality_score: float = 0.0                  # 质量评分 (0-100)
    quality_factors: dict[str, Any] = field(default_factory=dict)  # 质量因子
    test_coverage_level: str = "unknown"        # 测试覆盖级别
    documentation_ratio: float = 0.0            # 文档/代码比
    maintainability_index: float = 0.0          # 可维护性指数 (0-100)
    code_smells: list[str] = field(default_factory=list)  # 代码异味
    largest_files: list[dict] = field(default_factory=list)  # [{"path","loc"}]

    def to_dict(self) -> dict:
        return {
            "total_loc": self.total_loc,
            "loc_by_language": self.loc_by_language,
            "file_count": self.file_count,
            "avg_file_loc": round(self.avg_file_loc, 1),
            "max_file_loc": self.max_file_loc,
            "architecture_pattern": self.architecture_pattern,
            "architecture_confidence": round(self.architecture_confidence, 2),
            "architecture_signals": self.architecture_signals,
            "complexity_score": round(self.complexity_score, 1),
            "complexity_factors": self.complexity_factors,
            "quality_score": round(self.quality_score, 1),
            "quality_factors": self.quality_factors,
            "test_coverage_level": self.test_coverage_level,
            "documentation_ratio": round(self.documentation_ratio, 2),
            "maintainability_index": round(self.maintainability_index, 1),
            "code_smells": self.code_smells,
            "largest_files": self.largest_files,
        }


# ════════════════════════════════════════
# 语言文件扩展名映射
# ════════════════════════════════════════
_LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript", ".tsx": "TypeScript",
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".c": "C", ".cpp": "C++",
    ".h": "C", ".hpp": "C++", ".cs": "C#", ".swift": "Swift",
    ".scala": "Scala", ".sh": "Shell", ".lua": "Lua",
    ".dart": "Dart", ".elixir": "Elixir", ".ex": "Elixir",
    ".clj": "Clojure", ".hs": "Haskell", ".ml": "OCaml",
    ".vue": "Vue", ".svelte": "Svelte",
}

# 代码文件扩展名集合（用于统计文件数）
_CODE_EXTENSIONS = set(_LANGUAGE_EXTENSIONS.keys())

# 测试文件模式
_TEST_PATTERNS = [
    re.compile(r"test_.*\.py$"), re.compile(r".*_test\.py$"),
    re.compile(r".*\.test\.js$"), re.compile(r".*\.test\.ts$"),
    re.compile(r".*\.spec\.js$"), re.compile(r".*\.spec\.ts$"),
    re.compile(r"test/.*\.go$"), re.compile(r".*_test\.go$"),
    re.compile(r"src/test/.*\.java$"), re.compile(r".*Test\.java$"),
    re.compile(r"tests?/.*\.(rs|rb|php|cs)$"),
]

# 文档文件
_DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

# CI/CD 配置文件
_CI_PATTERNS = [
    re.compile(r"^\.github/workflows/.*\.ya?ml$"),
    re.compile(r"^\.gitlab-ci\.yml$"),
    re.compile(r"^\.circleci/.*$"),
    re.compile(r"^Jenkinsfile$"),
    re.compile(r"^azure-pipelines\.yml$"),
]

# Lint/Format 配置
_LINT_CONFIGS = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
    ".prettierrc", ".prettierrc.js", ".prettierrc.json",
    ".flake8", "setup.cfg", "pyproject.toml", ".pylintrc",
    ".rustfmt.toml", "rustfmt.toml",
    ".golangci.yml", ".golangci.yaml",
}


class CodeAnalyzer:
    """代码级分析器：基于文件树和源码进行静态分析。"""

    def __init__(self):
        pass

    def analyze(
        self,
        file_tree: list[str] | str,
        source_code: dict[str, str] | None = None,
        languages: dict[str, float] | None = None,
    ) -> CodeMetrics:
        """执行代码级分析。

        Args:
            file_tree: 文件树路径列表（或换行分隔的字符串）
            source_code: {文件路径: 文件内容} 字典
            languages: GitHub API 返回的语言分布

        Returns:
            CodeMetrics 对象
        """
        # 归一化 file_tree
        if isinstance(file_tree, str):
            paths = [p.strip() for p in file_tree.split("\n") if p.strip()]
        else:
            paths = list(file_tree)

        source_code = source_code or {}
        languages = languages or {}

        metrics = CodeMetrics()

        # 1. 代码规模分析
        self._analyze_scale(metrics, paths, source_code)

        # 2. 架构模式检测
        self._detect_architecture(metrics, paths)

        # 3. 复杂度估算
        self._estimate_complexity(metrics, paths, source_code)

        # 4. 质量评估
        self._assess_quality(metrics, paths, source_code)

        # 5. 可维护性指数
        self._compute_maintainability(metrics)

        return metrics

    # ════════════════════════════════════════
    # 1. 代码规模分析
    # ════════════════════════════════════════

    def _analyze_scale(
        self,
        metrics: CodeMetrics,
        paths: list[str],
        source_code: dict[str, str],
    ) -> None:
        """分析代码规模：LOC、文件数、语言分布。"""
        file_locs: list[tuple[str, int, str]] = []  # (path, loc, language)

        for path in paths:
            ext = self._get_extension(path)
            if ext not in _CODE_EXTENSIONS:
                continue

            lang = _LANGUAGE_EXTENSIONS[ext]
            content = source_code.get(path, "")
            loc = self._count_loc(content) if content else 0

            # 如果没有源码内容，用文件存在性估算（1 行占位）
            if loc == 0 and content == "":
                loc = 1  # 至少标记文件存在

            file_locs.append((path, loc, lang))
            metrics.total_loc += loc
            metrics.loc_by_language[lang] = metrics.loc_by_language.get(lang, 0) + loc

        metrics.file_count = len(file_locs)
        if file_locs:
            metrics.avg_file_loc = metrics.total_loc / metrics.file_count
            metrics.max_file_loc = max(loc for _, loc, _ in file_locs)

            # 记录最大的 5 个文件
            file_locs.sort(key=lambda x: x[1], reverse=True)
            metrics.largest_files = [
                {"path": p, "loc": loc} for p, loc, _ in file_locs[:5]
            ]

    def _count_loc(self, content: str) -> int:
        """计算有效代码行数（排除空行和纯注释行）。"""
        if not content:
            return 0
        lines = content.split("\n")
        loc = 0
        in_block_comment = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # 块注释处理
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("/*"):
                if "*/" not in stripped[2:]:
                    in_block_comment = True
                continue
            # 单行注释
            if stripped.startswith("//") or stripped.startswith("#"):
                continue
            loc += 1
        return loc

    # ════════════════════════════════════════
    # 2. 架构模式检测
    # ════════════════════════════════════════

    def _detect_architecture(
        self, metrics: CodeMetrics, paths: list[str]
    ) -> None:
        """基于文件树启发式检测架构模式。"""
        path_set = {p.lower() for p in paths}
        signals: list[str] = []
        candidates: list[tuple[str, float, list[str]]] = []

        # MVC 模式
        mvc_dirs = {"models", "views", "controllers"}
        mvc_found = sum(1 for d in mvc_dirs if any(f"/{d}/" in p or p.startswith(f"{d}/") for p in path_set))
        if mvc_found >= 2:
            conf = mvc_found / 3.0
            candidates.append(("MVC", conf, [f"包含 {mvc_found}/3 个 MVC 目录"]))

        # 微服务模式
        dockerfiles = [p for p in paths if p.lower().endswith("dockerfile") or "docker-compose" in p.lower()]
        services_dirs = [p for p in path_set if "/services/" in p or p.startswith("services/")]
        if len(dockerfiles) >= 2 or (len(services_dirs) >= 2 and len(dockerfiles) >= 1):
            conf = min(1.0, len(dockerfiles) / 3.0)
            candidates.append(("微服务", conf, [f"{len(dockerfiles)} 个 Dockerfile", f"{len(services_dirs)} 个服务目录"]))

        # 插件式架构
        plugin_dirs = [p for p in path_set if "/plugins/" in p or "/extensions/" in p or p.startswith("plugins/") or p.startswith("extensions/")]
        if plugin_dirs:
            conf = min(1.0, len(plugin_dirs) / 5.0)
            candidates.append(("插件式", conf, [f"{len(plugin_dirs)} 个插件相关路径"]))

        # 库/SDK
        has_lib = any("/lib/" in p or p.startswith("lib/") for p in path_set)
        has_setup = any(p in {"setup.py", "setup.cfg", "pyproject.toml"} for p in paths)
        has_exports = any("index.js" in p or "index.ts" in p or "__init__.py" in p for p in paths)
        if has_lib or (has_setup and has_exports):
            sigs = []
            if has_lib: sigs.append("lib/ 目录")
            if has_setup: sigs.append("包管理配置")
            if has_exports: sigs.append("入口导出文件")
            candidates.append(("库/SDK", 0.7, sigs))

        # CLI 工具
        has_cli = any("cli.py" in p or "cli.ts" in p or "cli.js" in p for p in paths)
        has_argparse = any("argparse" in (paths_lower := path_set) for _ in [None])  # 简化检查
        has_bin = any(p.startswith("bin/") or "/bin/" in p for p in paths)
        if has_cli or has_bin:
            sigs = []
            if has_cli: sigs.append("CLI 入口文件")
            if has_bin: sigs.append("bin/ 目录")
            candidates.append(("CLI 工具", 0.8, sigs))

        # 框架
        has_core = any("/core/" in p or p.startswith("core/") for p in paths)
        has_abstractions = any("/abstractions/" in p or "/interfaces/" in p for p in paths)
        if has_core and has_abstractions:
            candidates.append(("框架", 0.75, ["core/ 目录", "抽象层目录"]))

        # 单体应用（默认）
        if not candidates:
            candidates.append(("单体应用", 0.5, ["未检测到特定架构模式信号"]))

        # 选择置信度最高的
        candidates.sort(key=lambda x: x[1], reverse=True)
        pattern, conf, sigs = candidates[0]
        metrics.architecture_pattern = pattern
        metrics.architecture_confidence = conf
        metrics.architecture_signals = sigs

    # ════════════════════════════════════════
    # 3. 复杂度估算
    # ════════════════════════════════════════

    def _estimate_complexity(
        self,
        metrics: CodeMetrics,
        paths: list[str],
        source_code: dict[str, str],
    ) -> None:
        """估算代码复杂度。"""
        factors: dict[str, Any] = {}
        total_branches = 0
        max_nesting = 0
        total_functions = 0

        for path, content in source_code.items():
            ext = self._get_extension(path)
            if ext not in _CODE_EXTENSIONS:
                continue

            # 统计分支语句
            branches = self._count_branches(content, ext)
            total_branches += branches

            # 统计函数/方法
            functions = self._count_functions(content, ext)
            total_functions += functions

            # 最大嵌套深度
            nesting = self._max_nesting_depth(content, ext)
            max_nesting = max(max_nesting, nesting)

        factors["total_branches"] = total_branches
        factors["total_functions"] = total_functions
        factors["max_nesting_depth"] = max_nesting
        factors["avg_file_loc"] = metrics.avg_file_loc

        # 复杂度评分 (1-10)
        score = 1.0
        # 文件规模
        if metrics.avg_file_loc > 300:
            score += 2.0
        elif metrics.avg_file_loc > 150:
            score += 1.0
        # 嵌套深度
        if max_nesting > 6:
            score += 2.0
        elif max_nesting > 4:
            score += 1.0
        # 分支密度
        if metrics.file_count > 0:
            branch_density = total_branches / max(metrics.file_count, 1)
            if branch_density > 20:
                score += 2.0
            elif branch_density > 10:
                score += 1.0
        # 文件数
        if metrics.file_count > 100:
            score += 1.5
        elif metrics.file_count > 50:
            score += 0.5

        score = min(10.0, score)
        metrics.complexity_score = score
        metrics.complexity_factors = factors

        # 代码异味检测
        smells: list[str] = []
        if metrics.avg_file_loc > 300:
            smells.append("平均文件过大（>300行）")
        if max_nesting > 6:
            smells.append(f"嵌套过深（{max_nesting}层）")
        if metrics.max_file_loc > 1000:
            smells.append("存在超大文件（>1000行）")
        if total_branches > 0 and metrics.file_count > 0:
            if total_branches / max(metrics.file_count, 1) > 30:
                smells.append("分支密度过高")
        metrics.code_smells = smells

    def _count_branches(self, content: str, ext: str) -> int:
        """统计分支语句数量。"""
        if ext in (".py",):
            # Python: if/elif/for/while/try/except/with (用 \b 词边界，兼容 try: 无空格)
            return len(re.findall(r"^\s*(if|elif|for|while|try|except|with)\b", content, re.MULTILINE))
        elif ext in (".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cs", ".go", ".rs"):
            # C-like: if/for/while/switch/case/catch
            return len(re.findall(r"\b(if|for|while|switch|case|catch)\s*\(", content))
        return 0

    def _count_functions(self, content: str, ext: str) -> int:
        """统计函数/方法数量。"""
        if ext == ".py":
            return len(re.findall(r"^\s*def\s+", content, re.MULTILINE))
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            return len(re.findall(r"\b(function\s|=>\s|const\s+\w+\s*=\s*\()", content))
        elif ext in (".java", ".c", ".cpp", ".cs"):
            return len(re.findall(r"\b(void|int|float|double|char|bool|String|public|private|protected)\s+\w+\s*\(", content))
        elif ext == ".go":
            return len(re.findall(r"^\s*func\s+", content, re.MULTILINE))
        elif ext == ".rs":
            return len(re.findall(r"^\s*fn\s+", content, re.MULTILINE))
        return 0

    def _max_nesting_depth(self, content: str, ext: str) -> int:
        """估算最大嵌套深度。"""
        if ext == ".py":
            # Python: 按缩进统计
            max_depth = 0
            for line in content.split("\n"):
                if line.strip() and not line.strip().startswith("#"):
                    indent = len(line) - len(line.lstrip())
                    depth = indent // 4
                    max_depth = max(max_depth, depth)
            return max_depth
        else:
            # C-like: 按 { } 统计
            depth = 0
            max_depth = 0
            for char in content:
                if char == "{":
                    depth += 1
                    max_depth = max(max_depth, depth)
                elif char == "}":
                    depth = max(0, depth - 1)
            return max_depth

    # ════════════════════════════════════════
    # 4. 质量评估
    # ════════════════════════════════════════

    def _assess_quality(
        self,
        metrics: CodeMetrics,
        paths: list[str],
        source_code: dict[str, str],
    ) -> None:
        """评估代码质量。"""
        factors: dict[str, Any] = {}

        # 测试覆盖估计
        test_files = [p for p in paths if self._is_test_file(p)]
        test_ratio = len(test_files) / max(metrics.file_count, 1) if metrics.file_count > 0 else 0
        if test_ratio >= 0.3:
            test_level = "高"
        elif test_ratio >= 0.15:
            test_level = "中"
        elif test_ratio > 0:
            test_level = "低"
        else:
            test_level = "无"
        metrics.test_coverage_level = test_level
        factors["test_file_count"] = len(test_files)
        factors["test_to_code_ratio"] = round(test_ratio, 2)

        # 文档比例
        doc_files = [p for p in paths if self._get_extension(p) in _DOC_EXTENSIONS]
        doc_count = len(doc_files)
        if metrics.file_count > 0:
            doc_ratio = doc_count / max(metrics.file_count, 1)
        else:
            doc_ratio = 0.0
        metrics.documentation_ratio = doc_ratio
        factors["doc_file_count"] = doc_count

        # 代码内文档（注释比例）
        comment_lines = 0
        code_lines = 0
        for content in source_code.values():
            for line in content.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
                    comment_lines += 1
                else:
                    code_lines += 1
        inline_doc_ratio = comment_lines / max(code_lines, 1) if code_lines > 0 else 0
        factors["inline_comment_ratio"] = round(inline_doc_ratio, 2)

        # CI/CD 配置
        ci_files = [p for p in paths if any(pat.match(p) for pat in _CI_PATTERNS)]
        factors["has_ci"] = len(ci_files) > 0
        factors["ci_files"] = ci_files

        # Lint/Format 配置
        lint_files = [p for p in paths if p in _LINT_CONFIGS or any(p.endswith(ext) for ext in [".eslintrc", ".prettierrc"])]
        factors["has_lint_config"] = len(lint_files) > 0

        # 质量评分 (0-100)
        score = 0.0
        # 测试覆盖 (35分)
        if test_level == "高": score += 35
        elif test_level == "中": score += 25
        elif test_level == "低": score += 10
        # 文档 (20分)
        if doc_ratio >= 0.1: score += 15
        elif doc_ratio >= 0.05: score += 10
        elif doc_ratio > 0: score += 5
        if inline_doc_ratio >= 0.15: score += 5
        # CI/CD (15分)
        if factors["has_ci"]: score += 15
        # Lint (10分)
        if factors["has_lint_config"]: score += 10
        # 代码组织 (10分) - 目录结构清晰度
        dir_count = len(set(p.rsplit("/", 1)[0] for p in paths if "/" in p))
        if dir_count >= 5: score += 10
        elif dir_count >= 3: score += 5
        # 代码异味扣分 (10分)
        if not metrics.code_smells: score += 10
        else: score -= min(10, len(metrics.code_smells) * 3)

        score = max(0, min(100, score))
        metrics.quality_score = score
        metrics.quality_factors = factors

    # ════════════════════════════════════════
    # 5. 可维护性指数
    # ════════════════════════════════════════

    def _compute_maintainability(self, metrics: CodeMetrics) -> None:
        """计算可维护性指数 (0-100)。

        基于 Halstead 指标简化版：
        MI = max(0, 100 - complexity_penalty - size_penalty + quality_bonus)
        """
        # 复杂度惩罚（复杂度 1-10 映射到 0-40 惩罚）
        complexity_penalty = (metrics.complexity_score - 1) / 9.0 * 40

        # 规模惩罚（平均文件 LOC > 200 开始惩罚）
        size_penalty = 0
        if metrics.avg_file_loc > 200:
            size_penalty = min(20, (metrics.avg_file_loc - 200) / 20)

        # 质量加分（质量分 0-100 映射到 0-20 加分）
        quality_bonus = metrics.quality_score / 100.0 * 20

        mi = 100 - complexity_penalty - size_penalty + quality_bonus
        mi = max(0, min(100, mi))
        metrics.maintainability_index = mi

    # ════════════════════════════════════════
    # 辅助方法
    # ════════════════════════════════════════

    def _get_extension(self, path: str) -> str:
        """获取文件扩展名（小写）。"""
        parts = path.rsplit(".", 1)
        if len(parts) == 2:
            return f".{parts[1].lower()}"
        return ""

    def _is_test_file(self, path: str) -> bool:
        """判断是否为测试文件。"""
        return any(pat.search(path) for pat in _TEST_PATTERNS)
