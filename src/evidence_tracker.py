"""证据追踪器：将 LLM 分析结果与深提取证据关联。

核心职责：
  给 ProjectAnalysis 的每个字段值标注数据来源（source_type + source_detail），
  让用户能区分"这是项目真实数据"还是"AI 推测"。

匹配策略（第一性原理）：
  1. tech_stack 中的每项技术 → 在依赖清单证据中搜索匹配
  2. key_modules 中的每个模块 → 在文件树证据中搜索匹配目录/文件
  3. architecture 描述 → 标注为 LLM 推断（基于文件树+源码）
  4. dependencies → 直接来自依赖文件解析（verified）
  5. 其余字段 → 标注为 LLM 推断（inferred）
"""
from __future__ import annotations

from typing import Any


# 技术名到依赖名的模糊映射（处理大小写、别名）
_TECH_ALIASES: dict[str, set[str]] = {
    "python": {"python", "py", "cpython"},
    "pytorch": {"torch", "pytorch"},
    "tensorflow": {"tensorflow", "tf"},
    "fastapi": {"fastapi"},
    "flask": {"flask"},
    "django": {"django"},
    "react": {"react"},
    "vue": {"vue", "vuejs"},
    "rust": {"rust", "cargo"},
    "go": {"go", "golang"},
    "node.js": {"node", "nodejs", "npm"},
    "typescript": {"typescript", "ts"},
    "javascript": {"javascript", "js"},
    "docker": {"docker"},
    "kubernetes": {"kubernetes", "k8s"},
    "redis": {"redis"},
    "postgresql": {"postgresql", "psycopg2", "asyncpg"},
    "mysql": {"mysql", "pymysql"},
    "mongodb": {"mongodb", "pymongo"},
    "graphql": {"graphql", "strawberry", "ariadne"},
    "grpc": {"grpc", "grpcio"},
    "celery": {"celery"},
    "openai": {"openai"},
    "langchain": {"langchain"},
    "transformers": {"transformers"},
    "numpy": {"numpy"},
    "pandas": {"pandas"},
    "scikit-learn": {"scikit-learn", "sklearn"},
    "pytest": {"pytest"},
    "click": {"click"},
    "rich": {"rich"},
    "pydantic": {"pydantic"},
    "sqlalchemy": {"sqlalchemy"},
    "aiohttp": {"aiohttp"},
    "requests": {"requests"},
}


def _normalize_tech_name(tech: str) -> str:
    """标准化技术名用于匹配。"""
    return tech.lower().strip().replace(" ", "").replace("-", "").replace(".", "")


def _match_tech_to_dependency(tech: str, dep_evidence: list[dict]) -> dict | None:
    """尝试将一个技术名匹配到依赖证据。

    Returns:
        匹配到的证据 dict，或 None（未匹配到）。
    """
    normalized = _normalize_tech_name(tech)
    aliases = _TECH_ALIASES.get(tech.lower(), {tech.lower()})

    for ev in dep_evidence:
        source_detail = ev.get("source_detail", "")
        value = ev.get("value", "").lower()

        # 检查依赖文本中是否包含该技术名或其别名
        for alias in aliases:
            if alias in value or alias in source_detail.lower():
                return ev
        # 也检查标准化后的名称
        if normalized and normalized in value.replace(" ", "").replace("-", "").replace(".", ""):
            return ev

    return None


def _match_module_to_file_tree(module_name: str, file_tree_evidence: list[dict]) -> dict | None:
    """尝试将一个模块名匹配到文件树证据。

    Returns:
        匹配到的证据 dict，或 None。
    """
    module_lower = module_name.lower().strip()

    for ev in file_tree_evidence:
        value = ev.get("value", "").lower()
        # 检查文件树中是否有同名目录或文件
        if module_lower in value:
            return ev

    return None


def match_evidence_to_analysis(
    analysis,
    evidence_list: list[dict],
) -> list[dict]:
    """将证据列表匹配到分析结果的各个字段。

    Args:
        analysis: ProjectAnalysis 对象
        evidence_list: 深提取返回的证据列表

    Returns:
        匹配后的证据列表（已附加到 analysis.evidence_sources 的内容）
    """
    if not evidence_list:
        return []

    # 按来源类型分组证据
    dep_evidence = [e for e in evidence_list if e.get("source_type") == "dependency_file"]
    file_tree_evidence = [e for e in evidence_list if e.get("source_type") == "file_tree"]
    source_code_evidence = [e for e in evidence_list if e.get("source_type") == "source_code"]

    matched: list[dict] = []

    # 1. 匹配 tech_stack → 依赖清单
    for tech in analysis.tech_stack:
        dep_match = _match_tech_to_dependency(tech, dep_evidence)
        if dep_match:
            matched.append({
                "field": "tech_stack",
                "value": tech,
                "source_type": "dependency_file",
                "source_detail": dep_match.get("source_detail", "依赖文件"),
                "confidence": "verified",
            })
        else:
            # 检查是否在文件树中出现（如 Dockerfile → Docker）
            tree_match = _match_tech_to_dependency(tech, file_tree_evidence)
            if tree_match:
                matched.append({
                    "field": "tech_stack",
                    "value": tech,
                    "source_type": "file_tree",
                    "source_detail": tree_match.get("source_detail", "文件树"),
                    "confidence": "verified",
                })
            else:
                matched.append({
                    "field": "tech_stack",
                    "value": tech,
                    "source_type": "llm_inference",
                    "source_detail": "README 推断",
                    "confidence": "inferred",
                })

    # 2. 匹配 key_modules → 文件树
    for mod in analysis.key_modules:
        mod_name = mod.get("name", "") if isinstance(mod, dict) else str(mod)
        tree_match = _match_module_to_file_tree(mod_name, file_tree_evidence)
        if tree_match:
            matched.append({
                "field": "key_modules",
                "value": mod_name,
                "source_type": "file_tree",
                "source_detail": tree_match.get("source_detail", "文件树"),
                "confidence": "verified",
            })
        else:
            # 检查源码文件
            code_match = _match_module_to_file_tree(mod_name, source_code_evidence)
            if code_match:
                matched.append({
                    "field": "key_modules",
                    "value": mod_name,
                    "source_type": "source_code",
                    "source_detail": code_match.get("source_detail", "源码文件"),
                    "confidence": "verified",
                })
            else:
                matched.append({
                    "field": "key_modules",
                    "value": mod_name,
                    "source_type": "llm_inference",
                    "source_detail": "README 推断",
                    "confidence": "inferred",
                })

    # 3. architecture → 标注为 LLM 推断（基于综合证据）
    if analysis.architecture:
        matched.append({
            "field": "architecture",
            "value": analysis.architecture[:100],
            "source_type": "llm_inference",
            "source_detail": "基于 README + 文件树 + 源码综合推断",
            "confidence": "inferred",
        })

    # 4. 直接传递深提取的原始证据（dependencies / health / releases 等）
    for ev in evidence_list:
        if ev.get("source_type") in ("dependency_file", "github_stats", "release_notes", "commit_history"):
            matched.append(ev)

    return matched


def summarize_evidence(evidence_list: list[dict]) -> dict:
    """生成证据摘要统计。

    Returns:
        {
            "total": 总证据数,
            "verified": 已验证数,
            "inferred": 推断数,
            "unverified": 未验证数,
            "by_source": {source_type: count},
            "coverage": 覆盖率（verified / total）
        }
    """
    total = len(evidence_list)
    if total == 0:
        return {"total": 0, "verified": 0, "inferred": 0, "unverified": 0, "by_source": {}, "coverage": 0.0}

    verified = sum(1 for e in evidence_list if e.get("confidence") == "verified")
    inferred = sum(1 for e in evidence_list if e.get("confidence") == "inferred")
    unverified = sum(1 for e in evidence_list if e.get("confidence") == "unverified")

    by_source: dict[str, int] = {}
    for e in evidence_list:
        st = e.get("source_type", "unknown")
        by_source[st] = by_source.get(st, 0) + 1

    coverage = round(verified / total, 2) if total > 0 else 0.0

    return {
        "total": total,
        "verified": verified,
        "inferred": inferred,
        "unverified": unverified,
        "by_source": by_source,
        "coverage": coverage,
    }
