"""跨项目对比模块：生成多项目横向对比矩阵。

借鉴 zread.ai 的多仓库对比功能和 RepoTale 的知识图谱关联分析。

复用 config["llm"] 的 API 配置（base_url / model / api_key / enable_thinking 等），
通过 instructor + CompareResultLLM 实现结构化输出（替代手写 JSON 容错解析），
与 ProjectAnalyzer / ScriptGenerator 保持一致的初始化与错误处理模式：
  - 无 API Key → 返回 mock 对比（规则计算结果仍保留）
  - API 调用失败 → 回退 mock 叙述
  - SiliconFlow Qwen3.5 系列通过 enable_thinking=false 关闭思考模式
"""
from __future__ import annotations

from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import CompareResultLLM
from .models import GitHubRepo, ProjectAnalysis, ProjectComparison, RepoHealth

from src.logger import get_logger

logger = get_logger(__name__)


_COMPARE_SYSTEM_PROMPT = "你是一位技术选型顾问，请基于以下多项目分析数据，生成横向对比分析。"


class CrossProjectComparator(LLMClientMixin):
    """生成多项目横向对比矩阵（规则计算 + LLM 叙述）。

    规则部分（无需 LLM）：
      - tech_overlap：多项目共同技术栈（出现在 >=2 个项目中的技术 + 使用它的项目列表）
      - activity_ranking：按健康度评分、Star 数、提交数排序的活跃度排名
    LLM 部分：
      - positioning_diff：定位差异分析
      - verdict：综合评判与选型建议
    """

    def __init__(self, config: dict[str, Any]):
        self._init_llm(config)
        # 保留 llm 子配置以读取模块特定参数（如 max_tokens）
        self.cfg = config["llm"]

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def compare(
        self,
        repos: list[GitHubRepo],
        analyses: list[ProjectAnalysis],
        health_data: list,
    ) -> ProjectComparison:
        """生成跨项目对比矩阵。

        先做规则计算（技术重叠 / 活跃度排名），再调用 LLM 生成定位差异与综合评判。
        无 API Key 时回退 mock（规则计算结果仍保留）。

        Args:
            repos: GitHubRepo 列表
            analyses: ProjectAnalysis 列表（与 repos 一一对应或按 repo_name 匹配）
            health_data: 健康度数据列表（RepoHealth 对象或其 to_dict() 字典）
        """
        # 1. 规则计算（无需 LLM）
        tech_overlap = self._compute_tech_overlap(analyses)
        activity_ranking = self._compute_activity_ranking(repos, health_data)
        repo_names = [r.name for r in repos]

        # 2. 无 API Key -> mock 叙述（规则结果仍保留）
        if not self.api_key:
            logger.info("未配置 LLM API Key，使用 mock 模式")
            return self._mock_compare(repos, analyses, health_data)

        # 3. LLM 叙述（定位差异 + 综合评判）
        positioning_diff, verdict = self._llm_narrative(repos, analyses, health_data)

        if positioning_diff == "" and verdict == "":
            # LLM 调用失败：回退 mock 叙述，但保留规则计算结果
            logger.warning("LLM 对比失败，回退 mock 叙述（保留规则计算结果）")
            mock = self._mock_compare(repos, analyses, health_data)
            return ProjectComparison(
                repos=repo_names,
                tech_overlap=tech_overlap,
                positioning_diff=mock.positioning_diff,
                activity_ranking=activity_ranking,
                verdict=mock.verdict,
            )

        return ProjectComparison(
            repos=repo_names,
            tech_overlap=tech_overlap,
            positioning_diff=positioning_diff,
            activity_ranking=activity_ranking,
            verdict=verdict,
        )

    # ------------------------------------------------------------------
    # 规则计算（无需 LLM）
    # ------------------------------------------------------------------
    def _compute_tech_overlap(self, analyses: list[ProjectAnalysis]) -> list[dict]:
        """计算多项目共同技术栈（出现在 >=2 个项目中的技术）。

        借鉴 RepoTale 知识图谱关联分析：每条记录技术名 + 使用该技术的项目列表，
        以便构建「技术 - 项目」关联视图。出现在所有项目中的技术会自然拥有最高 count。
        """
        tech_projects: dict[str, set[str]] = {}
        for analysis in analyses:
            # 项目内技术去重
            for tech in set(analysis.tech_stack):
                norm = tech.strip()
                if not norm:
                    continue
                tech_projects.setdefault(norm, set()).add(analysis.repo_name)

        overlap = [
            {
                "technology": tech,
                "projects": sorted(projs),
                "count": len(projs),
            }
            for tech, projs in tech_projects.items()
            if len(projs) >= 2
        ]
        # 按出现项目数降序、技术名升序
        overlap.sort(key=lambda x: (-x["count"], x["technology"]))
        return overlap

    def _compute_activity_ranking(
        self,
        repos: list[GitHubRepo],
        health_data: list,
    ) -> list[dict]:
        """按健康度评分、Star 数、提交数排序生成活跃度排名。"""
        health_by_repo: dict[str, dict] = {}
        for h in health_data:
            hd = self._health_to_dict(h)
            name = hd.get("repo_name")
            if name:
                health_by_repo[name] = hd

        rows: list[dict] = []
        for repo in repos:
            hd = health_by_repo.get(repo.name, {})
            rows.append(
                {
                    "repo": repo.name,
                    "health_score": hd.get("health_score", 0.0),
                    "stars": repo.stars,
                    "commit_count_30d": hd.get("commit_count_30d", 0),
                }
            )

        # 排序：健康度 -> Star -> 提交数（均降序）
        rows.sort(
            key=lambda r: (r["health_score"], r["stars"], r["commit_count_30d"]),
            reverse=True,
        )
        for i, row in enumerate(rows, 1):
            row["rank"] = i
        return rows

    # ------------------------------------------------------------------
    # LLM 叙述
    # ------------------------------------------------------------------
    def _llm_narrative(
        self,
        repos: list[GitHubRepo],
        analyses: list[ProjectAnalysis],
        health_data: list,
    ) -> tuple[str, str]:
        """调用 LLM 生成定位差异与综合评判。失败返回 ("", "")。

        通过 instructor + CompareResultLLM 实现结构化输出，无需手写 JSON 解析。
        """
        user_content = self._build_compare_content(repos, analyses, health_data)
        logger.info(
            f"调用 {self.meta['model']} 生成横向对比叙述，"
            f"输入 {len(user_content)} 字符..."
        )

        try:
            result, completion = self.client.chat.completions.create_with_completion(
                response_model=CompareResultLLM,
                messages=[
                    {"role": "system", "content": _COMPARE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.5,
                max_tokens=self.cfg.get("max_tokens", 4000),
                **self.build_llm_kwargs(),
            )
            usage = completion.usage
            if usage:
                logger.info(
                    f"完成：tokens 输入 {usage.prompt_tokens} / "
                    f"输出 {usage.completion_tokens}"
                )
            # CompareResultLLM.positioning（各项目定位列表）→ positioning_diff 字符串
            positioning_diff = "\n".join(
                f"{p.project}：{p.positioning}" for p in result.positioning
            ).strip()
            verdict = str(result.verdict).strip()
            return positioning_diff, verdict
        except Exception as e:
            logger.error(f"LLM 对比调用失败: {e}")
            return "", ""

    def _build_compare_content(
        self,
        repos: list[GitHubRepo],
        analyses: list[ProjectAnalysis],
        health_data: list,
    ) -> str:
        """构建横向对比的用户消息：每个项目的名称 / 概述 / 技术栈 / 亮点 / Star / 健康度。"""
        analysis_by_repo = {a.repo_name: a for a in analyses}
        health_by_repo: dict[str, dict] = {}
        for h in health_data:
            hd = self._health_to_dict(h)
            name = hd.get("repo_name")
            if name:
                health_by_repo[name] = hd

        parts = ["请基于以下多个项目的分析数据，生成横向对比分析。\n"]
        for i, repo in enumerate(repos, 1):
            a = analysis_by_repo.get(repo.name)
            hd = health_by_repo.get(repo.name, {})
            parts.append(f"--- 项目 {i} ---")
            parts.append(f"名称：{repo.name}")
            parts.append(f"概述：{a.summary if a else (repo.description or '未提供')}")
            parts.append(f"技术栈：{', '.join(a.tech_stack) if a else ''}")
            parts.append(f"技术亮点：{' | '.join(a.highlights) if a else ''}")
            parts.append(f"Star 数：{repo.stars}")
            parts.append(f"健康度评分：{hd.get('health_score', 0.0)}")
            parts.append("")
        parts.append("请输出 JSON 对象，包含：")
        parts.append("- positioning_diff：各项目定位差异分析（2-4 句，指出各自核心定位与差异化）")
        parts.append("- verdict：综合评判与选型建议（2-4 句，给出适用场景与推荐倾向）")
        parts.append("只输出 JSON，不要输出其他文字。")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _health_to_dict(h: Any) -> dict:
        """将健康度数据统一转为 dict（兼容 RepoHealth 对象与 dict）。"""
        if isinstance(h, dict):
            return h
        if isinstance(h, RepoHealth):
            return h.to_dict()
        if hasattr(h, "to_dict"):
            return h.to_dict()
        return {}

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_compare(
        self,
        repos: list[GitHubRepo],
        analyses: list[ProjectAnalysis],
        health_data: list,
    ) -> ProjectComparison:
        """无 API Key 或调用失败时的占位对比（规则结果仍真实计算）。"""
        tech_overlap = self._compute_tech_overlap(analyses)
        activity_ranking = self._compute_activity_ranking(repos, health_data)
        names = [r.short_name for r in repos]
        name_label = ", ".join(names) if names else "各项目"
        return ProjectComparison(
            repos=[r.name for r in repos],
            tech_overlap=tech_overlap,
            positioning_diff=(
                f"（mock 模式）{name_label} 在不同细分领域各有定位，"
                "技术栈存在重叠也有差异。请配置 LLM API Key 获取真实定位差异分析。"
            ),
            activity_ranking=activity_ranking,
            verdict=(
                "（mock 模式）综合活跃度与社区规模，各项目各有侧重。"
                "请配置 LLM API Key 获取真实综合评判与选型建议。"
            ),
        )
