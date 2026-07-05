"""分段式播客脚本生成器：按项目边界切分，独立审查，全局连贯。

核心设计（第一性原理）：
  1. 单一职责：每个 LLM 调用只负责一个项目段落，上下文聚焦，质量更高
  2. 独立审查：每个段落独立经过 ScriptCritic 评审，低分重写
  3. 全局连贯：合并后检查段落间过渡，补充衔接句
  4. 可组合：开场段 + N 个项目段 + 结尾段 + 过渡句 → 合并为完整脚本

与 ScriptGenerator 的关系：
  - ScriptGenerator 是单次 LLM 调用生成完整脚本（适合 ≤2 个项目）
  - SegmentedScriptGenerator 是多次 LLM 调用分段生成（适合 3+ 项目或长内容）
  - 两者输出相同的 PodcastScript 接口，下游无需感知差异
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import ScriptLLM
from .models import GitHubRepo, PodcastHost, PodcastScript, PodcastSegment

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ScriptSection:
    """脚本的独立段落（开场/项目讨论/结尾）。

    每个段落包含自己的对话片段列表和评审结果。
    """
    section_type: str = "project"  # intro / project / outro
    repo_name: str = ""            # 项目段对应的仓库名（intro/outro 为空）
    segments: list[PodcastSegment] = field(default_factory=list)
    review_score: float = 0.0
    review_feedback: str = ""
    rewrites: int = 0              # 重写次数
    transition_before: list[PodcastSegment] = field(default_factory=list)  # 该段之前的过渡句

    @property
    def char_count(self) -> int:
        """该段落总字符数。"""
        return sum(len(s.text) for s in self.segments)


# ════════════════════════════════════════
# 提示词模板
# ════════════════════════════════════════

_INTRO_PROMPT = """你是一位资深科技播客制作人。请根据以下项目信息，生成播客节目的开场段落。

要求：
- 开场 2-4 段对话，主持人介绍本期主题和将要讨论的项目
- 氛围热情、引人入胜
- 不要深入讨论具体项目细节，只做概要介绍
- 严格输出 JSON 格式：{{"title": "节目标题", "description": "节目描述", "hosts": [{{"name": "主持人名", "persona": "人设", "voice_key": "host"}}], "segments": [{{"speaker": "说话人", "text": "台词", "emotion": "情绪", "voice_key": "host"}}]}}

项目列表：
{project_list}
"""

_PROJECT_PROMPT = """你是一位资深科技播客制作人。请针对以下单个项目生成播客对话段落。

要求：
- 4-8 段对话，深入讨论该项目的核心特性、技术亮点和使用场景
- 主持人和嘉宾就该项目展开深入对话
- 包含具体技术细节，不要泛泛而谈
- {style_guidance}
- 严格输出 JSON 格式：{{"title": "", "description": "", "hosts": [{{"name": "主持人名", "persona": "人设", "voice_key": "host"}}], "segments": [{{"speaker": "说话人", "text": "台词", "emotion": "情绪", "voice_key": "host"}}]}}

项目信息：
{project_info}

这是本期第 {index}/{total} 个项目，请生成独立的讨论段落。
"""

_OUTRO_PROMPT = """你是一位资深科技播客制作人。请根据以下项目信息，生成播客节目的结尾段落。

要求：
- 结尾 2-3 段对话，总结本期讨论的项目要点
- 主持人感谢嘉宾，预告下期内容
- 氛围温暖、有号召力
- 严格输出 JSON 格式：{{"title": "", "description": "", "hosts": [{{"name": "主持人名", "persona": "人设", "voice_key": "host"}}], "segments": [{{"speaker": "说话人", "text": "台词", "emotion": "情绪", "voice_key": "host"}}]}}

项目列表：
{project_list}
"""

_TRANSITION_PROMPT = """你是播客过渡句生成器。请生成 1-2 段过渡对话，用于从「{from_topic}」自然过渡到「{to_topic}」。

要求：
- 简短自然，1-2 段对话
- 主持人引出下一个话题
- 严格输出 JSON 格式：{{"segments": [{{"speaker": "{host_name}", "text": "过渡台词", "emotion": "neutral", "voice_key": "host"}}]}}
"""


class SegmentedScriptGenerator(LLMClientMixin):
    """分段式播客脚本生成器。

    将完整脚本拆分为：开场 + N 个项目段落 + 结尾，
    每段独立生成和审查，最后合并并检查全局连贯性。
    """

    def __init__(self, config: dict):
        self._init_llm(config)
        self._full_config = config
        self.cfg = config["llm"]
        self.style = config.get("podcast_style", "casual")
        self.longform = config.get("longform", False)

        # 统计指标（供 PipelineReporter 读取）
        self._total_rewrites: int = 0
        self._sections_generated: int = 0

    @property
    def project_root(self):
        from pathlib import Path
        return Path(self._full_config.get("project_root", "."))

    def generate_segmented(self, repos: list[GitHubRepo]) -> PodcastScript:
        """分段生成完整播客脚本。

        流程：
        1. 生成开场段
        2. 为每个项目生成独立段落（含审查回路）
        3. 生成结尾段
        4. 生成段落间过渡句
        5. 全局连贯性检查
        6. 合并为完整脚本
        """
        if not self.api_key:
            return self._mock_generate(repos)

        logger.info(f"分段生成模式：{len(repos)} 个项目")

        # 1. 生成开场段
        logger.info("生成开场段...")
        intro = self._generate_intro(repos)

        # 2. 逐个生成项目段落
        sections: list[ScriptSection] = [intro]
        for idx, repo in enumerate(repos, 1):
            logger.info(f"生成项目段 {idx}/{len(repos)}：{repo.name}...")
            section = self._generate_project_segment(repo, idx, len(repos))
            sections.append(section)

        # 3. 生成结尾段
        logger.info("生成结尾段...")
        outro = self._generate_outro(repos)
        sections.append(outro)

        # 4. 生成过渡句
        logger.info("生成段落过渡...")
        host_name = intro.segments[0].speaker if intro.segments else "主持人"
        for i in range(1, len(sections)):
            from_topic = sections[i - 1].repo_name or sections[i - 1].section_type
            to_topic = sections[i].repo_name or sections[i].section_type
            transitions = self._generate_transition(from_topic, to_topic, host_name)
            sections[i].transition_before = transitions

        # 5. 全局连贯性检查
        logger.info("全局连贯性检查...")
        coherence = self._check_coherence(sections, repos)
        logger.info(f"连贯性评分：{coherence['score']}/10")

        # 6. 合并为完整脚本
        script = self._merge_sections(sections, repos)
        script.critic_score = coherence["score"]
        script.critic_feedback = coherence.get("feedback", "")

        # 统计重写次数
        total_rewrites = sum(s.rewrites for s in sections)
        self._total_rewrites = total_rewrites
        self._sections_generated = len(sections)
        if total_rewrites > 0:
            logger.info(f"共重写 {total_rewrites} 个段落")

        return script

    # ════════════════════════════════════════
    # 段落生成
    # ════════════════════════════════════════

    def _generate_intro(self, repos: list[GitHubRepo]) -> ScriptSection:
        """生成开场段。"""
        project_list = "\n".join(
            f"- {r.name}：{r.description}" for r in repos
        )
        prompt = _INTRO_PROMPT.format(project_list=project_list)
        segments, hosts = self._call_llm_for_segments(prompt)
        return ScriptSection(
            section_type="intro",
            segments=segments,
        )

    def _generate_project_segment(
        self, repo: GitHubRepo, index: int, total: int
    ) -> ScriptSection:
        """生成单个项目段落（含独立审查回路）。"""
        style_guidance = self._get_style_guidance()
        project_info = self._build_project_info(repo)
        prompt = _PROJECT_PROMPT.format(
            project_info=project_info,
            index=index,
            total=total,
            style_guidance=style_guidance,
        )

        section = ScriptSection(
            section_type="project",
            repo_name=repo.name,
        )

        # 独立审查回路（最多 2 次重写）
        max_revisions = 2
        for rev in range(max_revisions):
            segments, hosts = self._call_llm_for_segments(prompt)
            section.segments = segments

            # 评审
            review = self._review_section(section, [repo])
            section.review_score = review.get("overall_score", 0)
            section.review_feedback = review.get("feedback", "")
            section.rewrites = rev

            if review.get("passed", True):
                logger.info(f"{repo.name} 评审通过（第{rev+1}轮），分数 {section.review_score}/10")
                break
            if rev < max_revisions - 1:
                logger.warning(f"{repo.name} 评审未通过（第{rev+1}轮），重写中...")
                prompt = prompt + f"\n\n## 评审反馈（请据此改进）\n{section.review_feedback}"
            else:
                logger.warning(f"{repo.name} 评审已达最大轮次，分数 {section.review_score}/10")

        return section

    def _generate_outro(self, repos: list[GitHubRepo]) -> ScriptSection:
        """生成结尾段。"""
        project_list = "\n".join(
            f"- {r.name}：{r.description}" for r in repos
        )
        prompt = _OUTRO_PROMPT.format(project_list=project_list)
        segments, hosts = self._call_llm_for_segments(prompt)
        return ScriptSection(
            section_type="outro",
            segments=segments,
        )

    def _generate_transition(
        self, from_topic: str, to_topic: str, host_name: str
    ) -> list[PodcastSegment]:
        """生成段落间过渡句。"""
        if not self.api_key:
            return []

        prompt = _TRANSITION_PROMPT.format(
            from_topic=from_topic,
            to_topic=to_topic,
            host_name=host_name,
        )
        try:
            result = self.client.chat.completions.create(
                response_model=_TransitionLLM,
                messages=[
                    {"role": "system", "content": "你是播客过渡句生成器。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=200,
                **self.build_llm_kwargs(),
            )
            return [
                PodcastSegment(
                    speaker=s.speaker or host_name,
                    text=s.text.strip(),
                    emotion=s.emotion,
                    voice_key=s.voice_key,
                )
                for s in result.segments
            ]
        except Exception as e:
            logger.error(f"过渡句生成失败: {e}")
            return []

    # ════════════════════════════════════════
    # 审查与连贯性
    # ════════════════════════════════════════

    def _review_section(
        self, section: ScriptSection, repos: list[GitHubRepo]
    ) -> dict:
        """对单个段落进行 ScriptCritic 评审。"""
        from .script_critic import ScriptCritic

        critic = ScriptCritic(self._full_config)
        # 构建临时 PodcastScript 供评审
        temp_script = PodcastScript(
            title=section.repo_name or section.section_type,
            description="",
            hosts=[],
            segments=section.segments,
            repo_names=[r.name for r in repos],
        )
        return critic.evaluate(temp_script, repos)

    def _check_coherence(
        self, sections: list[ScriptSection], repos: list[GitHubRepo]
    ) -> dict:
        """全局连贯性检查：检查段落间过渡是否自然。"""
        if not self.api_key:
            return {"score": 8.0, "feedback": "", "passed": True}

        # 构建完整脚本摘要供连贯性检查
        parts = ["请检查以下播客脚本的段落间连贯性：\n"]
        for i, section in enumerate(sections):
            label = section.section_type
            if section.repo_name:
                label = f"项目：{section.repo_name}"
            parts.append(f"\n--- 段落 {i+1}：{label} ---")
            for seg in section.segments[:3]:  # 每段取前3条
                parts.append(f"[{seg.speaker}] {seg.text[:80]}...")
            if len(section.segments) > 3:
                parts.append(f"（共 {len(section.segments)} 段）")

        parts.append("\n请评估整体连贯性（1-10分），指出是否有突兀的过渡或重复内容。")
        parts.append('严格输出 JSON：{"score": 数字, "feedback": "建议", "passed": true/false}')

        try:
            result = self.client.chat.completions.create(
                response_model=_CoherenceLLM,
                messages=[
                    {"role": "system", "content": "你是播客连贯性评审专家。"},
                    {"role": "user", "content": "\n".join(parts)},
                ],
                temperature=0.2,
                max_tokens=400,
                **self.build_llm_kwargs(),
            )
            return {
                "score": result.score,
                "feedback": result.feedback,
                "passed": result.passed if result.passed is not None else result.score >= 7,
            }
        except Exception as e:
            logger.error(f"连贯性检查失败: {e}")
            return {"score": 7.0, "feedback": "", "passed": True}

    # ════════════════════════════════════════
    # 合并与辅助
    # ════════════════════════════════════════

    def _merge_sections(
        self, sections: list[ScriptSection], repos: list[GitHubRepo]
    ) -> PodcastScript:
        """将所有段落合并为完整 PodcastScript。"""
        all_segments: list[PodcastSegment] = []
        hosts: list[PodcastHost] = []

        # 从开场段提取主持人信息
        for section in sections:
            for seg in section.segments:
                if seg.speaker and not any(h.name == seg.speaker for h in hosts):
                    hosts.append(PodcastHost(
                        name=seg.speaker,
                        persona="主持人" if seg.voice_key == "host" else "嘉宾",
                        voice_key=seg.voice_key,
                    ))

        if not hosts:
            hosts = [
                PodcastHost("小前", "科技播客主持人", "host"),
                PodcastHost("阿开", "技术专家", "guest"),
            ]

        # 合并段落（含过渡句）
        for section in sections:
            # 先添加过渡句
            for ts in section.transition_before:
                all_segments.append(ts)
            # 再添加段落内容
            all_segments.extend(section.segments)

        # 从开场段提取标题
        title = f"GitHub 前沿观察：{', '.join(r.short_name for r in repos)}"

        return PodcastScript(
            title=title,
            description=f"本期讨论 {len(repos)} 个 GitHub 前沿项目",
            hosts=hosts,
            segments=all_segments,
            repo_names=[r.name for r in repos],
            style=self.style,
            target_minutes=30 if self.longform else 10,
        )

    def _call_llm_for_segments(
        self, prompt: str
    ) -> tuple[list[PodcastSegment], list[PodcastHost]]:
        """调用 LLM 生成对话段落，返回 (segments, hosts)。"""
        system = "你是一位资深科技播客制作人，请根据提供的信息生成对话脚本。"
        if self.longform:
            system += " 本期为长内容模式，每个项目段落需要更深入的讨论。"

        max_tokens = self.cfg.get("max_tokens", 4000)
        if self.longform:
            max_tokens = min(max_tokens * 2, 8000)

        try:
            script_llm = self.client.chat.completions.create(
                response_model=ScriptLLM,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.cfg.get("temperature", 0.8),
                max_tokens=max_tokens,
                **self.build_llm_kwargs(),
            )
            hosts = [
                PodcastHost(name=h.name, persona=h.persona, voice_key=h.voice_key)
                for h in script_llm.hosts
            ]
            segments = [
                PodcastSegment(
                    speaker=seg.speaker,
                    text=seg.text.strip(),
                    emotion=seg.emotion,
                    voice_key=seg.voice_key,
                )
                for seg in script_llm.segments
            ]
            return segments, hosts
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return [], []

    def _build_project_info(self, repo: GitHubRepo) -> str:
        """构建单个项目的信息摘要。"""
        parts = [
            f"项目名称：{repo.name}",
            f"地址：{repo.url}",
            f"Star 数：{repo.stars}",
            f"语言：{repo.language or '未指定'}",
        ]
        if repo.topics:
            parts.append(f"标签：{', '.join(repo.topics[:10])}")
        parts.append(f"描述：{repo.description}")
        # README 内容（截断到 8000 字符）
        readme = repo.readme_markdown[:8000] if repo.readme_markdown else ""
        if readme:
            parts.append(f"README 内容：\n{readme}")
        return "\n".join(parts)

    def _get_style_guidance(self) -> str:
        """根据风格预设返回指导文本。"""
        guidance = {
            "casual": "对话轻松愉快，像朋友间聊天，多用口语化表达",
            "technical": "对话专业严谨，深入技术细节，使用专业术语并给出解释",
            "debate": "主持人和嘉宾就该项目的技术选型展开讨论和辩论",
            "interview": "主持人采访嘉宾，嘉宾分享项目内部视角和实战经验",
        }
        return guidance.get(self.style, guidance["casual"])

    # ════════════════════════════════════════
    # Mock 模式
    # ════════════════════════════════════════

    def _mock_generate(self, repos: list[GitHubRepo]) -> PodcastScript:
        """无 API Key 时的 mock 分段生成。"""
        host = PodcastHost("小前", "科技播客主持人", "host")
        guest = PodcastHost("阿开", "技术专家", "guest")
        segments: list[PodcastSegment] = []

        # 开场
        segments.append(PodcastSegment(
            host.name,
            f"大家好，欢迎收听「GitHub 前沿观察」。今天我们来聊 {len(repos)} 个值得关注的开源项目。",
            "excited", "host",
        ))

        # 每个项目段落
        for idx, repo in enumerate(repos, 1):
            # 过渡句
            if idx > 1:
                segments.append(PodcastSegment(
                    host.name,
                    f"接下来我们看第 {idx} 个项目。",
                    "neutral", "host",
                ))
            segments.append(PodcastSegment(
                host.name,
                f"第 {idx} 个项目是「{repo.name}」，Star 数 {repo.stars}，"
                f"它主要做的是：{repo.description[:80]}。",
                "curious", "host",
            ))
            segments.append(PodcastSegment(
                guest.name,
                f"这个项目挺有意思的。它解决了实际开发中的痛点，技术实现也很扎实。",
                "neutral", "guest",
            ))

        # 结尾
        segments.append(PodcastSegment(
            host.name,
            "好的，今天的节目就到这里，我们下期再见！",
            "happy", "host",
        ))

        return PodcastScript(
            title=f"GitHub 前沿观察：{', '.join(r.short_name for r in repos)}",
            description=f"本期讨论 {len(repos)} 个 GitHub 前沿项目（分段生成）",
            hosts=[host, guest],
            segments=segments,
            repo_names=[r.name for r in repos],
            style=self.style,
            target_minutes=30 if self.longform else 10,
            critic_score=8.0,
        )


# ════════════════════════════════════════
# 辅助 Pydantic 模型
# ════════════════════════════════════════

from pydantic import BaseModel, Field


class _TransitionSegmentLLM(BaseModel):
    """过渡句的 LLM 输出 schema。"""
    speaker: str = Field(description="说话人名称")
    text: str = Field(description="过渡台词")
    emotion: str = Field(default="neutral", description="情感标注")
    voice_key: str = Field(default="host", description="语音标识")


class _TransitionLLM(BaseModel):
    """过渡句生成的 LLM 输出 schema。"""
    segments: list[_TransitionSegmentLLM] = Field(description="过渡对话段落")


class _CoherenceLLM(BaseModel):
    """连贯性检查的 LLM 输出 schema。"""
    score: float = Field(description="连贯性评分 (1-10)")
    feedback: str = Field(default="", description="改进建议")
    passed: bool | None = Field(default=None, description="是否通过 (>=7)")
