"""LLM 结构化输出的 Pydantic 模型定义。

每个模型对应一个 LLM 模块的输出 schema，
instructor 使用这些模型自动校验 LLM 返回的 JSON 并重试。
替代各模块手写的 _extract_json / _parse_* 容错逻辑。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ════════════════════════════════════════
# ScriptCritic 评审结果
# ════════════════════════════════════════


class CriticResultLLM(BaseModel):
    """ScriptCritic 的 LLM 输出 schema。"""

    overall_score: float = Field(description="综合评分 (1-10 的整数)")
    dimensions: dict[str, float] = Field(
        description="五维评分: info_density, coherence, speaker_diversity, factual_grounding, engagement (各 1-10)"
    )
    feedback: str = Field(description="具体的改进建议（2-3句）")
    passed: bool = Field(description="是否通过评审 (>=7分为通过)")


# ════════════════════════════════════════
# ProjectAnalyzer 分析结果
# ════════════════════════════════════════


class KeyModuleLLM(BaseModel):
    """关键模块信息。"""

    name: str = Field(description="模块名称")
    description: str = Field(description="模块功能描述")
    responsibility: str = Field(default="", description="模块职责")


class ComparisonLLM(BaseModel):
    """项目对比分析。"""

    strengths: list[str] = Field(default_factory=list, description="项目优势")
    weaknesses: list[str] = Field(default_factory=list, description="项目劣势")
    alternatives: list[str] = Field(default_factory=list, description="替代方案")


class CodeInsightsLLM(BaseModel):
    """代码洞察。"""

    patterns: list[str] = Field(default_factory=list, description="设计模式")
    quality: str = Field(default="", description="代码质量评估")
    complexity: str = Field(default="", description="复杂度分析")


class AnalysisResultLLM(BaseModel):
    """ProjectAnalyzer 的 LLM 输出 schema。"""

    summary: str = Field(description="项目概述 (2-3句话)")
    tech_stack: list[str] = Field(description="技术栈列表")
    architecture: str = Field(description="架构描述")
    key_modules: list[KeyModuleLLM] = Field(default_factory=list, description="关键模块")
    quick_start: str = Field(default="", description="快速上手指南")
    highlights: list[str] = Field(default_factory=list, description="项目亮点")
    use_cases: list[str] = Field(default_factory=list, description="应用场景")
    comparison: ComparisonLLM = Field(default_factory=ComparisonLLM, description="对比分析")
    code_insights: CodeInsightsLLM = Field(default_factory=CodeInsightsLLM, description="代码洞察")
    mermaid_diagram: str = Field(default="", description="Mermaid 架构图源码")
    quality_score: float = Field(default=7.0, description="质量评分 (0-10)")


class ReviewResultLLM(BaseModel):
    """ProjectAnalyzer 评审回路的结果。"""

    score: float = Field(description="评审分数 (0-10)")
    issues: list[str] = Field(default_factory=list, description="发现的问题")
    suggestions: str = Field(default="", description="改进建议")


# ════════════════════════════════════════
# ShowNotesGenerator 结果
# ════════════════════════════════════════


class ShowNotesLLM(BaseModel):
    """ShowNotesGenerator 的 LLM 输出 schema。"""

    key_takeaways: list[str] = Field(description="关键要点 (3-5条)")
    social_quotes: list[str] = Field(default_factory=list, description="金句摘录")
    summary: str = Field(description="内容摘要 (100-200字)")


# ════════════════════════════════════════
# CrossProjectComparator 结果
# ════════════════════════════════════════


class TechOverlapLLM(BaseModel):
    """技术重叠项。"""

    projects: list[str] = Field(description="重叠的项目名称")
    technologies: list[str] = Field(description="共享的技术/工具")


class ProjectPositioningLLM(BaseModel):
    """项目定位。"""

    project: str = Field(description="项目名称")
    positioning: str = Field(description="项目定位描述")


class CompareResultLLM(BaseModel):
    """CrossProjectComparator 的 LLM 输出 schema。"""

    tech_overlap: list[TechOverlapLLM] = Field(default_factory=list, description="技术重叠分析")
    positioning: list[ProjectPositioningLLM] = Field(default_factory=list, description="各项目定位")
    verdict: str = Field(default="", description="综合评判")


# ════════════════════════════════════════
# LLMScript 脚本生成结果
# ════════════════════════════════════════


class HostLLM(BaseModel):
    """播客主持人。"""

    name: str = Field(description="主持人名称")
    persona: str = Field(default="", description="人设描述")
    voice_key: str = Field(default="host", description="语音标识 (host/guest)")


class SegmentLLM(BaseModel):
    """播客对话段落。"""

    speaker: str = Field(description="说话人名称")
    text: str = Field(description="对话内容")
    emotion: str = Field(default="neutral", description="情感标注")
    voice_key: str = Field(default="host", description="语音标识")


class ScriptLLM(BaseModel):
    """LLMScript 的 LLM 输出 schema。"""

    title: str = Field(description="节目标题")
    description: str = Field(default="", description="节目描述")
    hosts: list[HostLLM] = Field(description="主持人列表")
    segments: list[SegmentLLM] = Field(description="对话段落列表")


class OutlineSectionLLM(BaseModel):
    """大纲章节。"""

    title: str = Field(description="章节标题")
    key_points: list[str] = Field(description="关键讨论点")


class OutlineLLM(BaseModel):
    """LLMScript 大纲生成的输出 schema。"""

    title: str = Field(description="节目标题")
    sections: list[OutlineSectionLLM] = Field(description="章节列表")
