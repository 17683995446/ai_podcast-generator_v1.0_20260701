"""Show Notes 生成器：从播客脚本和项目数据自动生成结构化节目笔记。

借鉴 Transcribr（自动摘要+时间戳+金句+SEO逐字稿）和 LumiClip（一次性生成
摘要/亮点/时间戳/金句/嘉宾简介/链接）的 show notes 生成方法。

复用 config["llm"] 的 API 配置（base_url / model / api_key / enable_thinking 等），
通过 instructor + ShowNotesLLM 实现结构化输出（替代手写 JSON 容错解析），
与 ProjectAnalyzer / ScriptGenerator 保持一致的初始化与错误处理模式：
  - 无 API Key → 返回 mock 节目笔记
  - API 调用失败 → 回退到规则提取（从片段文本生成简单要点）
  - SiliconFlow Qwen3.5 系列通过 enable_thinking=false 关闭思考模式

生成内容分两类：
  规则提取（无需 LLM）：
    - project_links: 从 repos 提取 name / url / stars / description
    - timestamps: 将 chapters 转为 [{"time","title","description"}]
    - mentioned_tech: 从 analyses 的 tech_stack 聚合去重
  LLM 提取（有 API Key 时）：
    - summary / key_takeaways（3-5 条）/ social_quotes（3 条）
"""
from __future__ import annotations

from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import ShowNotesLLM
from .models import PodcastScript, GitHubRepo, ProjectAnalysis, ShowNotes, Chapter

from src.logger import get_logger

logger = get_logger(__name__)


_SHOW_NOTES_SYSTEM_PROMPT = (
    "你是一位播客制作人。请基于以下播客脚本，提取关键要点（3-5条）、"
    "可分享金句（3条）。输出JSON格式。"
)


class ShowNotesGenerator(LLMClientMixin):
    """从播客脚本和项目数据生成结构化节目笔记。

    规则部分始终可用（项目链接 / 时间戳 / 技术栈），LLM 部分在配置了
    API Key 时启用，否则回退到 mock / 规则提取。
    """

    def __init__(self, config: dict[str, Any]):
        self._init_llm(config)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def generate(
        self,
        script: PodcastScript,
        repos: list[GitHubRepo],
        analyses: list,
        chapters: list,
    ) -> ShowNotes:
        """生成完整节目笔记。

        Args:
            script: 播客脚本。
            repos: 本期讨论的 GitHub 仓库列表。
            analyses: 各项目的深度分析结果（ProjectAnalysis 或 dict）。
            chapters: 章节列表（Chapter 对象或 dict）。

        Returns:
            ShowNotes 对象，包含项目链接、时间戳、技术栈、关键要点、金句、摘要。
        """
        # 1. 规则提取（无需 LLM）
        project_links = self._extract_project_links(repos)
        timestamps = self._chapters_to_timestamps(chapters)
        mentioned_tech = self._extract_mentioned_tech(analyses)

        # 2. LLM 提取关键要点 / 金句 / 摘要（无 API Key 时走 mock）
        if not self.api_key:
            return self._mock_generate(script, repos, analyses, chapters)

        key_takeaways, social_quotes, summary = self._llm_extract(script)

        return ShowNotes(
            title=script.title,
            summary=summary,
            key_takeaways=key_takeaways,
            social_quotes=social_quotes,
            timestamps=timestamps,
            project_links=project_links,
            mentioned_tech=mentioned_tech,
        )

    # ------------------------------------------------------------------
    # 规则提取（无需 LLM）
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_project_links(repos: list[GitHubRepo]) -> list[dict]:
        """从 repos 提取项目链接信息：name / url / stars / description。"""
        links: list[dict] = []
        for repo in repos:
            links.append(
                {
                    "name": repo.name,
                    "url": repo.url,
                    "stars": repo.stars,
                    "description": repo.description,
                }
            )
        return links

    @staticmethod
    def _chapters_to_timestamps(chapters: list) -> list[dict]:
        """将 Chapter 列表转为时间戳格式 [{"time","title","description"}]。

        兼容 Chapter 对象与 dict 两种输入。
        """
        timestamps: list[dict] = []
        for ch in chapters:
            if isinstance(ch, dict):
                title = ch.get("title", "")
                start = ch.get("start_time", ch.get("time", 0.0))
                desc = ch.get("description", "")
            else:
                title = getattr(ch, "title", "")
                start = getattr(ch, "start_time", getattr(ch, "time", 0.0))
                desc = getattr(ch, "description", "")
            timestamps.append(
                {
                    "time": float(start),
                    "title": str(title),
                    "description": str(desc),
                }
            )
        return timestamps

    @staticmethod
    def _extract_mentioned_tech(analyses: list) -> list[str]:
        """从各项目分析的 tech_stack 提取并去重技术栈。

        兼容 ProjectAnalysis 对象与 dict 两种输入；去重时大小写不敏感，
        保留首次出现的大小写形式。
        """
        seen_lower: set[str] = set()
        techs: list[str] = []
        for analysis in analyses:
            if isinstance(analysis, dict):
                stack = analysis.get("tech_stack", [])
            else:
                stack = getattr(analysis, "tech_stack", [])
            if not isinstance(stack, list):
                continue
            for tech in stack:
                key = str(tech).strip()
                if not key:
                    continue
                if key.lower() in seen_lower:
                    continue
                seen_lower.add(key.lower())
                techs.append(key)
        return techs

    # ------------------------------------------------------------------
    # LLM 提取（关键要点 / 金句 / 摘要）
    # ------------------------------------------------------------------
    def _llm_extract(
        self, script: PodcastScript
    ) -> tuple[list[str], list[str], str]:
        """调用 LLM 提取关键要点、金句、摘要；失败回退到规则提取。

        输入：脚本标题、描述、前 3000 字片段文本。
        通过 instructor + ShowNotesLLM 实现结构化输出，无需手写 JSON 解析。
        """
        segment_texts = " ".join(seg.text for seg in script.segments)
        user_content = (
            f"播客标题：{script.title}\n"
            f"播客描述：{script.description}\n"
            f"脚本内容（前3000字）：\n{segment_texts[:3000]}"
        )

        try:
            result = self.client.chat.completions.create(
                response_model=ShowNotesLLM,
                messages=[
                    {"role": "system", "content": _SHOW_NOTES_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=1000,
                **self.build_llm_kwargs(),
            )
            takeaways = self._as_str_list(result.key_takeaways)
            quotes = self._as_str_list(result.social_quotes)
            summary = str(result.summary).strip() or script.description
            logger.info(
                f"LLM 提取完成：{len(takeaways)} 要点 / "
                f"{len(quotes)} 金句"
            )
            return takeaways, quotes, summary
        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            # 回退规则提取
            logger.warning("回退到规则提取要点")
            return self._fallback_takeaways(script), [], script.description

    @staticmethod
    def _fallback_takeaways(script: PodcastScript) -> list[str]:
        """无 API Key 或 LLM 失败时，从片段文本简单生成要点。"""
        takeaways: list[str] = []
        for seg in script.segments[:5]:
            text = seg.text.strip()
            if not text:
                continue
            # 取每段前 60 字作为要点
            takeaways.append(text[:60] + ("..." if len(text) > 60 else ""))
        if not takeaways:
            takeaways.append(
                script.description or "本期节目精彩内容回顾。"
            )
        return takeaways

    @staticmethod
    def _as_str_list(val: Any) -> list[str]:
        """将 LLM 返回的字段规整为干净的字符串列表。"""
        if isinstance(val, list):
            return [
                str(x).strip()
                for x in val
                if x is not None and str(x).strip()
            ]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_generate(
        self,
        script: PodcastScript,
        repos: list[GitHubRepo],
        analyses: list,
        chapters: list,
    ) -> ShowNotes:
        """无 API Key 时的占位节目笔记（规则字段仍真实提取）。"""
        project_links = self._extract_project_links(repos)
        timestamps = self._chapters_to_timestamps(chapters)
        mentioned_tech = self._extract_mentioned_tech(analyses)
        takeaways = self._fallback_takeaways(script)

        if script.description:
            mock_summary = script.description
        else:
            mock_summary = (
                f"本期节目讨论了 {len(repos)} 个 GitHub 热门项目。"
                "（mock 模式：请配置 LLM API Key 获取真实摘要）"
            )

        return ShowNotes(
            title=script.title,
            summary=mock_summary,
            key_takeaways=takeaways,
            social_quotes=[
                "（mock）可分享金句一：待 LLM 提取",
                "（mock）可分享金句二：待 LLM 提取",
                "（mock）可分享金句三：待 LLM 提取",
            ],
            timestamps=timestamps,
            project_links=project_links,
            mentioned_tech=mentioned_tech,
        )
