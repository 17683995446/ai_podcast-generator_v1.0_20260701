"""Show Notes 生成器：从播客脚本和项目数据自动生成结构化节目笔记。

借鉴 Transcribr（自动摘要+时间戳+金句+SEO逐字稿）和 LumiClip（一次性生成
摘要/亮点/时间戳/金句/嘉宾简介/链接）的 show notes 生成方法。

复用 config["llm"] 的 API 配置（base_url / model / api_key / enable_thinking 等），
与 ProjectAnalyzer / ScriptGenerator 保持一致的初始化与错误处理模式：
  - 无 API Key → 返回 mock 节目笔记
  - API 调用失败 → 回退到规则提取（从片段文本生成简单要点）
  - JSON mode 不被支持 → 去掉 response_format 重试
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

import json
import re
from typing import Any

from openai import OpenAI

from .models import PodcastScript, GitHubRepo, ProjectAnalysis, ShowNotes, Chapter


_SHOW_NOTES_SYSTEM_PROMPT = (
    "你是一位播客制作人。请基于以下播客脚本，提取关键要点（3-5条）、"
    "可分享金句（3条）。输出JSON格式。"
)


class ShowNotesGenerator:
    """从播客脚本和项目数据生成结构化节目笔记。

    规则部分始终可用（项目链接 / 时间戳 / 技术栈），LLM 部分在配置了
    API Key 时启用，否则回退到 mock / 规则提取。
    """

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["llm"]
        self.project_root = config.get("project_root", ".")
        # 优先使用通用 LLM key（与 ProjectAnalyzer / ScriptGenerator 一致）
        self.api_key = (
            config["api_keys"].get("llm", "")
            or config["api_keys"].get("deepseek", "")
        )
        # 是否需要关闭 thinking 模式（SiliconFlow Qwen3.5 系列）
        self.enable_thinking = self.cfg.get("enable_thinking", None)

        if not self.api_key:
            print("[show_notes] 警告：未配置 LLM API Key，将使用 mock 模式")

        self.client = OpenAI(
            api_key=self.api_key or "mock-key",
            base_url=self.cfg["base_url"],
            timeout=self.cfg.get("timeout", 120),
        )

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
        输出 JSON：{"key_takeaways": [...], "social_quotes": [...], "summary": "..."}
        """
        segment_texts = " ".join(seg.text for seg in script.segments)
        user_content = (
            f"播客标题：{script.title}\n"
            f"播客描述：{script.description}\n"
            f"脚本内容（前3000字）：\n{segment_texts[:3000]}"
        )

        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _SHOW_NOTES_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"},
        }

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}
            print("[show_notes] 已关闭 thinking 模式（enable_thinking=false）")

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            data = json.loads(self._extract_json(raw))
            takeaways = self._as_str_list(data.get("key_takeaways"))
            quotes = self._as_str_list(data.get("social_quotes"))
            summary = str(data.get("summary", "")).strip() or script.description
            print(
                f"[show_notes] LLM 提取完成：{len(takeaways)} 要点 / "
                f"{len(quotes)} 金句"
            )
            return takeaways, quotes, summary
        except Exception as e:
            print(f"[show_notes] LLM 提取失败: {e}")
            # 某些模型不支持 JSON mode → 去掉 response_format 重试
            if "response_format" in str(e).lower() or "json" in str(e).lower():
                print("[show_notes] 尝试不带 JSON mode 重试...")
                kwargs.pop("response_format", None)
                if self.enable_thinking is False:
                    kwargs["extra_body"] = {"enable_thinking": False}
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    raw = response.choices[0].message.content or ""
                    data = json.loads(self._extract_json(raw))
                    takeaways = self._as_str_list(data.get("key_takeaways"))
                    quotes = self._as_str_list(data.get("social_quotes"))
                    summary = str(data.get("summary", "")).strip() or script.description
                    print(
                        f"[show_notes] 重试成功：{len(takeaways)} 要点 / "
                        f"{len(quotes)} 金句"
                    )
                    return takeaways, quotes, summary
                except Exception as e2:
                    print(f"[show_notes] 重试失败: {e2}")
            # 回退规则提取
            print("[show_notes] 回退到规则提取要点")
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

    @staticmethod
    def _extract_json(raw: str) -> str:
        """容错提取首个 JSON 对象文本（去除 markdown 代码块包裹）。"""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        if not raw.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
        return raw

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
