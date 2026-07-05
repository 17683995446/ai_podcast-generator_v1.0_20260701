"""脚本评审智能体模块（借鉴 PodAgent Critic + PoDEval 评估框架）。

PodAgent 的 Host-Guest-Writer 系统中引入了 Critic 角色，用于对 Writer 生成的
脚本进行质量把关；低分时触发 Writer 重新生成。PoDEval 则提出了一套面向播客
对话的多维度评估框架。本模块将二者结合：

- 使用 instructor + Pydantic 实现结构化输出，替代手写 JSON 容错解析。
- 对脚本进行 5 维度评分：信息密度 / 连贯性 / 说话人多样性 / 事实性 / 吸引力。
- 评审失败时优雅降级，返回默认通过结果，避免阻塞主生成流程。
"""
from __future__ import annotations

from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import CriticResultLLM
from .models import GitHubRepo, PodcastScript

from src.logger import get_logger

logger = get_logger(__name__)


# 评审系统提示词（借鉴 PoDEval 多维度评估框架）
CRITIC_SYSTEM_PROMPT = """你是一位严格的播客脚本质量评审专家。请对以下播客脚本进行多维度评估，给出 1-10 的整数评分。

评估维度：
1. info_density（信息密度）：对话是否包含具体的技术细节、架构分析、设计动机？还是停留在泛泛的介绍？
2. coherence（连贯性）：对话是否自然流畅？话题过渡是否平滑？是否有逻辑断裂？
3. speaker_diversity（说话人多样性）：主持人和嘉宾是否有明显的角色差异？观点是否多元？还是两个人说的话可以互换？
4. factual_grounding（事实性）：脚本中的技术陈述是否可由提供的 README 推导？有无编造项目不存在的信息？
5. engagement（吸引力）：对话是否有趣、引人入胜？是否有让听众"学到东西"的时刻？

严格输出 JSON（不要输出 JSON 之外的文字）：
{"overall_score": 1到10的整数, "dimensions": {"info_density": 1到10, "coherence": 1到10, "speaker_diversity": 1到10, "factual_grounding": 1到10, "engagement": 1到10}, "feedback": "具体的改进建议（2-3句，指出最需要改进的维度和具体方向）", "passed": true或false}"""


# 评审通过的分数阈值（>= 该值视为通过）
PASS_THRESHOLD = 7.0


class ScriptCritic(LLMClientMixin):
    """播客脚本评审智能体（借鉴 PodAgent Critic + PoDEval 评估框架）。

    对生成的脚本进行多维度质量评估，低分触发 Writer 重新生成。
    """

    def __init__(self, config: dict):
        self._init_llm(config)

    def evaluate(self, script: PodcastScript, repos: list[GitHubRepo]) -> dict:
        """评估脚本质量，返回包含 overall_score/dimensions/feedback/passed 的字典。

        返回结构：
        - overall_score: float (1-10)
        - dimensions: {info_density, coherence, speaker_diversity, factual_grounding, engagement} 各 1-10
        - feedback: str（具体可执行的改进建议）
        - passed: bool（overall_score >= 7 视为通过）
        """
        # 无 API Key 时返回 mock 评审（默认通过，分数 8.0）
        if not self.api_key:
            return {
                "overall_score": 8.0,
                "dimensions": {
                    "info_density": 8,
                    "coherence": 8,
                    "speaker_diversity": 8,
                    "factual_grounding": 8,
                    "engagement": 8,
                },
                "feedback": "",
                "passed": True,
            }

        user_content = self._build_eval_content(script, repos)
        logger.info(f"调用 {self.meta['model']} 评审脚本，输入 {len(user_content)} 字符...")

        try:
            result = self.client.chat.completions.create(
                response_model=CriticResultLLM,
                messages=[
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=800,
                **self.build_llm_kwargs(),
            )
            # 转换 Pydantic 模型为 dict（保持与旧 API 兼容）
            dims = {k: int(v) for k, v in result.dimensions.items()}
            passed = result.passed
            if passed is None:
                passed = result.overall_score >= PASS_THRESHOLD
            logger.info(f"评审完成：总分 {result.overall_score}/10")
            return {
                "overall_score": result.overall_score,
                "dimensions": dims,
                "feedback": result.feedback,
                "passed": bool(passed),
            }
        except Exception as e:
            logger.error(f"评审失败: {e}")
            # 评审失败时返回默认通过结果（分数 0、空反馈），避免阻塞生成流程
            return {
                "overall_score": 0,
                "dimensions": {},
                "feedback": "",
                "passed": True,
            }

    def _build_eval_content(self, script: PodcastScript, repos: list[GitHubRepo]) -> str:
        """构建评审提示词：脚本片段 + 仓库信息（用于事实核查）。"""
        parts: list[str] = ["请对以下播客脚本进行多维度质量评估：\n"]

        # ── 脚本基本信息 ──
        parts.append(f"\n{'='*60}")
        parts.append("【脚本标题】")
        parts.append(script.title)
        parts.append("\n【脚本描述】")
        parts.append(script.description)
        parts.append("\n【主持人】")
        if script.hosts:
            for h in script.hosts:
                parts.append(f"- {h.name}（{h.persona}，音色：{h.voice_key}）")
        else:
            parts.append("- （未配置主持人）")

        # ── 对话脚本片段（序列化） ──
        parts.append(f"\n{'='*60}")
        parts.append("【对话脚本】")
        if script.segments:
            for i, seg in enumerate(script.segments, 1):
                parts.append(
                    f"{i}. [{seg.speaker}]（情绪：{seg.emotion}）：{seg.text}"
                )
        else:
            parts.append("（无对话片段）")

        # ── 参考仓库信息（用于事实性核查） ──
        parts.append(f"\n{'='*60}")
        parts.append("【参考仓库信息（用于事实性核查）】")
        if repos:
            for i, repo in enumerate(repos, 1):
                parts.append(f"\n仓库 {i}：{repo.name}")
                parts.append(f"地址：{repo.url}")
                parts.append(f"描述：{repo.description}")
                if repo.topics:
                    parts.append(f"标签：{', '.join(repo.topics[:10])}")
                # README 摘要（前 2000 字），用于事实性核查
                readme_excerpt = repo.readme_markdown[:2000] if repo.readme_markdown else ""
                if readme_excerpt:
                    parts.append(f"README 摘要：\n{readme_excerpt}")
        else:
            parts.append("（未提供参考仓库信息）")

        parts.append(f"\n{'='*60}")
        parts.append("请基于以上信息严格评估脚本质量，按维度给出 1-10 的整数评分，并给出具体改进建议。")
        parts.append("严格输出 JSON 格式，不要输出任何 JSON 之外的文字。")
        return "\n".join(parts)
