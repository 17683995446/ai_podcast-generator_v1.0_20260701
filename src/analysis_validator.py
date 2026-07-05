"""分析结果规则校验器：用硬规则交叉验证 LLM 分析结果。

核心职责：
  在 LLM 评审回路之外，增加一层基于规则的客观校验。
  LLM 评审可能同源幻觉（同一个模型既生成又评审），但规则校验是
  基于深提取的客观数据（依赖清单、文件树），不会幻觉。

校验规则：
  1. tech_stack 中的每项技术 → 必须在依赖清单或文件树中有证据
  2. key_modules 中的每个模块 → 优先在文件树中找匹配
  3. 不可验证的项 → 标记为 unverified，可选剔除

设计原则（第一性原理）：
  - 规则校验不修改原始分析结果，只生成校验报告
  - 校验报告可被 pipeline 用于决定是否触发重新生成
  - 规则可配置、可扩展
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationIssue:
    """单个校验问题。"""
    field: str = ""           # tech_stack / key_modules / architecture
    value: str = ""           # 被校验的值
    issue_type: str = ""      # unverified_tech / unverified_module / hallucination_risk
    severity: str = "warning" # warning / error
    message: str = ""         # 人类可读的问题描述
    suggestion: str = ""      # 建议操作

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationReport:
    """完整校验报告。"""
    repo_name: str = ""
    issues: list[ValidationIssue] = field(default_factory=list)
    tech_stack_verified: list[str] = field(default_factory=list)
    tech_stack_unverified: list[str] = field(default_factory=list)
    key_modules_verified: list[str] = field(default_factory=list)
    key_modules_unverified: list[str] = field(default_factory=list)
    passed: bool = True
    score: float = 1.0  # 0.0 ~ 1.0

    def to_dict(self) -> dict:
        return {
            "repo_name": self.repo_name,
            "issues": [i.to_dict() for i in self.issues],
            "tech_stack_verified": self.tech_stack_verified,
            "tech_stack_unverified": self.tech_stack_unverified,
            "key_modules_verified": self.key_modules_verified,
            "key_modules_unverified": self.key_modules_unverified,
            "passed": self.passed,
            "score": self.score,
        }


# ── 技术名到文件名模式的映射 ──
# 用于在文件树中检测技术存在性（如 Docker → Dockerfile）
_TECH_FILE_PATTERNS: dict[str, list[str]] = {
    "docker": ["dockerfile", "docker-compose", ".dockerignore"],
    "kubernetes": ["k8s", "kubernetes", "helm", "chart.yaml", "deployment.yaml"],
    "ci/cd": [".github/workflows", ".gitlab-ci", "jenkinsfile", ".circleci"],
    "make": ["makefile", "cmakelists"],
    "rust": ["cargo.toml"],
    "go": ["go.mod", "go.sum"],
    "node.js": ["package.json", "package-lock.json", "yarn.lock", "node_modules"],
    "typescript": ["tsconfig.json", ".ts"],
    "webpack": ["webpack.config"],
    "vite": ["vite.config"],
    "eslint": [".eslintrc", "eslint.config"],
    "prettier": [".prettierrc", "prettier.config"],
    "tailwind": ["tailwind.config"],
    "react": ["jsx", "tsx", "react"],
    "vue": ["vue"],
    "svelte": ["svelte"],
    "pytest": ["conftest", "pytest.ini", "tox.ini", "test_"],
    "jest": ["jest.config", "__tests__", ".test.", ".spec."],
    "mypy": ["mypy.ini", ".mypy"],
    "ruff": ["ruff.toml", ".ruff"],
    "black": [".black", "pyproject.toml"],
    "github actions": [".github/workflows"],
}


# ── 编程语言到依赖文件的映射 ──
# 编程语言不会作为依赖项出现在 requirements.txt 中，但其依赖文件的存在可证明语言使用
_LANGUAGE_FILE_PATTERNS: dict[str, list[str]] = {
    "python": ["requirements.txt", "setup.py", "pyproject.toml", "pipfile", "poetry.lock", "__pycache__", ".py"],
    "javascript": ["package.json", "node_modules", ".js"],
    "typescript": ["tsconfig.json", "package.json", ".ts", ".tsx"],
    "rust": ["cargo.toml", "cargo.lock", "src/main.rs", ".rs"],
    "go": ["go.mod", "go.sum", "cmd/", ".go"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts", "src/main/java"],
    "c++": ["cmakelists.txt", "makefile", ".cpp", ".hpp"],
    "c": ["makefile", ".c", ".h"],
    "c#": [".csproj", ".cs"],
    "ruby": ["gemfile", "gemfile.lock", ".rb"],
    "php": ["composer.json", "composer.lock", ".php"],
    "swift": ["package.swift", ".swift"],
    "kotlin": ["build.gradle.kts", ".kt"],
    "scala": ["build.sbt", ".scala"],
    "elixir": ["mix.exs", ".exs"],
    "haskell": ["cabal", "stack.yaml", ".hs"],
    "lua": ["rockspec", ".lua"],
    "dart": ["pubspec.yaml", ".dart"],
    "julia": ["project.toml", ".jl"],
}


def _check_tech_in_evidence(tech: str, evidence_list: list[dict]) -> bool:
    """检查某项技术是否在证据列表中有对应来源。"""
    tech_lower = tech.lower().strip()

    # 检查依赖文件证据
    for ev in evidence_list:
        if ev.get("source_type") == "dependency_file":
            value = ev.get("value", "").lower()
            detail = ev.get("source_detail", "").lower()
            if tech_lower in value or tech_lower in detail:
                return True
        # 检查文件树证据
        if ev.get("source_type") == "file_tree":
            value = ev.get("value", "").lower()
            # 检查技术名直接出现在文件树中
            if tech_lower in value:
                return True
            # 检查文件名模式
            patterns = _TECH_FILE_PATTERNS.get(tech_lower, [])
            for pattern in patterns:
                if pattern in value:
                    return True

    # 检查编程语言模式（如 Python → requirements.txt 存在）
    lang_patterns = _LANGUAGE_FILE_PATTERNS.get(tech_lower, [])
    if lang_patterns:
        for ev in evidence_list:
            value = ev.get("value", "").lower()
            detail = ev.get("source_detail", "").lower()
            combined = value + " " + detail
            for pattern in lang_patterns:
                if pattern in combined:
                    return True

    return False


def _check_module_in_evidence(module_name: str, evidence_list: list[dict]) -> bool:
    """检查某个模块名是否在文件树或源码证据中有对应。"""
    module_lower = module_name.lower().strip()

    for ev in evidence_list:
        if ev.get("source_type") in ("file_tree", "source_code"):
            value = ev.get("value", "").lower()
            if module_lower in value:
                return True

    return False


def validate_analysis(analysis, evidence_list: list[dict]) -> ValidationReport:
    """对单个项目分析结果执行规则校验。

    Args:
        analysis: ProjectAnalysis 对象
        evidence_list: 深提取证据列表

    Returns:
        ValidationReport 校验报告
    """
    report = ValidationReport(repo_name=analysis.repo_name)
    issues: list[ValidationIssue] = []

    # 1. 校验 tech_stack
    for tech in analysis.tech_stack:
        tech_str = str(tech).strip()
        if not tech_str:
            continue

        if _check_tech_in_evidence(tech_str, evidence_list):
            report.tech_stack_verified.append(tech_str)
        else:
            report.tech_stack_unverified.append(tech_str)
            issues.append(ValidationIssue(
                field="tech_stack",
                value=tech_str,
                issue_type="unverified_tech",
                severity="warning",
                message=f"技术栈项「{tech_str}」未在依赖清单或文件树中找到证据",
                suggestion="检查是否为 LLM 幻觉，或该项目确实使用了但未在依赖中声明",
            ))

    # 2. 校验 key_modules
    for mod in analysis.key_modules:
        mod_name = mod.get("name", "") if isinstance(mod, dict) else str(mod)
        mod_name = mod_name.strip()
        if not mod_name:
            continue

        if _check_module_in_evidence(mod_name, evidence_list):
            report.key_modules_verified.append(mod_name)
        else:
            report.key_modules_unverified.append(mod_name)
            issues.append(ValidationIssue(
                field="key_modules",
                value=mod_name,
                issue_type="unverified_module",
                severity="warning",
                message=f"关键模块「{mod_name}」未在文件树中找到对应目录或文件",
                suggestion="可能是 README 中描述的概念性模块，而非代码中的实际目录",
            ))

    # 3. 计算校验分数
    total_tech = len(report.tech_stack_verified) + len(report.tech_stack_unverified)
    total_modules = len(report.key_modules_verified) + len(report.key_modules_unverified)
    total_items = total_tech + total_modules

    if total_items > 0:
        verified_items = len(report.tech_stack_verified) + len(report.key_modules_verified)
        report.score = round(verified_items / total_items, 2)
    else:
        report.score = 1.0

    # 4. 判定是否通过
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    report.passed = error_count == 0 and report.score >= 0.5
    report.issues = issues

    return report


def filter_unverified_tech_stack(analysis, report: ValidationReport) -> list[str]:
    """从分析结果中过滤掉未验证的技术栈项。

    Returns:
        过滤后的技术栈列表（仅保留已验证的项）。
    """
    return list(report.tech_stack_verified)


def validate_batch(analyses: list, evidence_map: dict[str, list[dict]]) -> dict[str, ValidationReport]:
    """批量校验多个项目的分析结果。

    Args:
        analyses: ProjectAnalysis 列表
        evidence_map: {repo_name: evidence_list}

    Returns:
        {repo_name: ValidationReport}
    """
    reports: dict[str, ValidationReport] = {}
    for analysis in analyses:
        evidence = evidence_map.get(analysis.repo_name, [])
        reports[analysis.repo_name] = validate_analysis(analysis, evidence)
    return reports
