"""LLM 驱动的播客脚本生成器。

使用 instructor + Pydantic 实现结构化输出，替代手写 JSON 容错解析。
支持两步生成（大纲→完整脚本）、多风格预设、长内容模式、多智能体评审回路。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import ScriptLLM, OutlineLLM
from .models import GitHubRepo, PodcastHost, PodcastScript, PodcastSegment

from src.logger import get_logger

logger = get_logger(__name__)


class ScriptGenerator(LLMClientMixin):
    """播客脚本生成器（LLM 驱动）。"""

    def __init__(self, config: dict):
        self._init_llm(config)
        # 保存完整配置，供 ScriptCritic 等子智能体复用
        self._full_config = config
        self.cfg = config["llm"]
        self._system_prompt: str | None = None
        # 播客风格预设（借鉴 Podcastfy 的对话定制）
        self.style = config.get("podcast_style", "casual")
        self.longform = config.get("longform", False)

    @property
    def system_prompt(self) -> str:
        """加载系统提示词（缓存）。"""
        if self._system_prompt is None:
            prompt_path = self.project_root / "prompts" / "podcast_system.txt"
            if prompt_path.exists():
                self._system_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                self._system_prompt = _DEFAULT_SYSTEM_PROMPT
        return self._system_prompt

    @property
    def project_root(self) -> Path:
        return Path(self._full_config.get("project_root", "."))

    def _get_style_addon(self) -> str:
        """根据风格预设返回额外的 prompt 指导。"""
        styles = {
            "casual": """
## 风格：轻松闲聊
- 对话氛围轻松愉快，像朋友间聊天
- 多用口语化表达和日常比喻
- 主持人活泼，嘉宾幽默
- 适当加入"哈哈""对对对""哇"等自然语气词
""",
            "technical": """
## 风格：技术深度
- 对话专业严谨，深入技术细节
- 讨论架构设计、性能优化、代码质量
- 使用专业术语并给出解释
- 嘉宾角色设定为资深技术专家
- 适当引用具体代码片段和设计模式
""",
            "debate": """
## 风格：辩论对话
- 主持人和嘉宾就项目的技术选型、设计决策展开讨论
- 包含不同观点的碰撞和辩论
- 主持人扮演"质疑者"角色，提出挑战性问题
- 嘉宾需要论证和 defend 技术选择
- 最终达成共识或保留分歧
""",
            "interview": """
## 风格：访谈风格
- 主持人作为采访者，嘉宾作为项目贡献者或领域专家
- 采用问答式对话结构
- 主持人提问精准，引导深入讨论
- 嘉宾分享"内部视角"和"实战经验"
- 适当加入"你是怎么想到的""能详细说说吗"等访谈话术
""",
        }
        return styles.get(self.style, "")

    def generate(self, repos: list[GitHubRepo]) -> PodcastScript:
        """根据仓库列表生成播客脚本。"""
        if not self.api_key:
            return self._mock_script(repos)

        user_content = self._build_user_content(repos)

        # 第一步：生成大纲（两步生成策略）
        outline = self.generate_outline(repos)

        # 第二步：基于大纲生成完整脚本
        if outline:
            outline_text = json.dumps(outline, ensure_ascii=False, indent=2)
            user_content += f"\n\n## 节目大纲（请基于此大纲展开详细对话）\n{outline_text}"
            logger.info(f"步骤2: 基于大纲生成完整脚本...")

        logger.info(f"调用 {self.meta['model']}，输入 {len(user_content)} 字符...")

        # 根据风格和长内容模式调整 system prompt
        system_content = self.system_prompt
        style_addon = self._get_style_addon()
        if style_addon:
            system_content = system_content + "\n\n" + style_addon
        if self.longform:
            system_content += "\n\n## 长内容模式\n本期为长内容播客（目标 25-40 分钟），请生成 40-60 段对话，总字数 6000-10000 字。每个项目需要更深入的讨论，包括更多技术细节、实际代码示例解读、社区生态分析。"
        else:
            system_content += "\n\n## 节目规格\n本期为常规播客（目标 5-8 分钟），请生成 15-30 段对话，总字数 1800-3000 字。"

        # longform 模式下增加 max_tokens
        max_tokens = self.cfg.get("max_tokens", 4000)
        if self.longform:
            max_tokens = min(max_tokens * 2, 8000)  # 长内容模式翻倍

        if self.enable_thinking is False:
            logger.info("已关闭 thinking 模式（enable_thinking=false）")

        try:
            script_llm, completion = self.client.chat.completions.create_with_completion(
                response_model=ScriptLLM,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.cfg.get("temperature", 0.8),
                max_tokens=max_tokens,
                **self.build_llm_kwargs(),
            )
            script = self._llm_to_script(script_llm, repos)
            script.outline = outline or {}
            script.repo_urls = [r.url for r in repos]
            script.style = self.style
            script.target_minutes = 30 if self.longform else 8

            usage = completion.usage
            if usage:
                logger.info(
                    f"完成：tokens 输入 {usage.prompt_tokens} / "
                    f"输出 {usage.completion_tokens}"
                )

            # ── 多智能体评审回路（借鉴 PodAgent Critic + PoDEval） ──
            from .script_critic import ScriptCritic
            critic = ScriptCritic(self._full_config)
            max_revisions = 2  # 最多重写 2 次
            for rev in range(max_revisions):
                result = critic.evaluate(script, repos)
                script.critic_score = result.get("overall_score", 0)
                script.critic_feedback = result.get("feedback", "")
                if result.get("passed", True):
                    logger.info(f"脚本评审通过（第{rev+1}轮），分数 {script.critic_score}/10")
                    break
                if rev < max_revisions - 1:
                    logger.warning(f"脚本评审未通过（第{rev+1}轮），分数 {script.critic_score}/10，重写中...")
                    # 将评审反馈追加到用户内容并重新生成
                    feedback_text = result.get("feedback", "")
                    user_content_with_feedback = user_content + f"\n\n## 评审反馈（请据此改进）\n{feedback_text}\n\n请基于以上反馈重新生成更高质量的脚本。"
                    try:
                        script_llm, _ = self.client.chat.completions.create_with_completion(
                            response_model=ScriptLLM,
                            messages=[
                                {"role": "system", "content": system_content},
                                {"role": "user", "content": user_content_with_feedback},
                            ],
                            temperature=self.cfg.get("temperature", 0.8),
                            max_tokens=max_tokens,
                            **self.build_llm_kwargs(),
                        )
                        script = self._llm_to_script(script_llm, repos)
                        script.outline = outline or {}
                        script.repo_urls = [r.url for r in repos]
                        script.style = self.style
                        script.target_minutes = 30 if self.longform else 8
                    except Exception as e:
                        logger.error(f"重写失败: {e}")
                        break
                else:
                    logger.warning(f"脚本评审已达最大轮次，分数 {script.critic_score}/10")

            return script
        except Exception as e:
            logger.error(f"API 调用失败: {e}")
            logger.warning("回退到 mock 脚本")
            return self._mock_script(repos)

    def _build_user_content(self, repos: list[GitHubRepo]) -> str:
        """构建用户消息：汇总所有项目信息。"""
        parts = ["以下是本期播客要讨论的 GitHub 前沿项目，请基于这些信息生成对话脚本：\n"]
        for i, repo in enumerate(repos, 1):
            parts.append(f"\n{'='*60}")
            parts.append(f"项目 {i}：{repo.name}")
            parts.append(f"地址：{repo.url}")
            parts.append(f"Star 数：{repo.stars}")
            parts.append(f"语言：{repo.language or '未指定'}")
            if repo.topics:
                parts.append(f"标签：{', '.join(repo.topics[:10])}")
            parts.append(f"描述：{repo.description}")
            # 深度提取内容（文件树/依赖/健康度/Commit叙事/项目分析）会被追加到
            # readme_markdown 末尾（见 main.py），此处提高截断上限以避免深度内容被切掉。
            # LLM 可处理 12K 字符输入。
            parts.append(f"\nREADME 内容：\n{repo.readme_markdown[:12000]}")
        parts.append(f"\n{'='*60}")
        parts.append("请根据以上项目信息，生成一期完整的中文播客对话脚本。")
        parts.append("严格输出 JSON 格式，不要输出任何 JSON 之外的文字。")
        return "\n".join(parts)

    def generate_outline(self, repos: list[GitHubRepo]) -> dict:
        """第一步：生成节目大纲（结构 + 关键讨论点）。

        借鉴 NotebookLM 的两步生成路径：先规划结构，再展开内容。
        """
        if not self.api_key:
            return {}

        user_content = self._build_outline_content(repos)
        logger.info(f"步骤1: 生成节目大纲...")

        try:
            outline_llm = self.client.chat.completions.create(
                response_model=OutlineLLM,
                messages=[
                    {"role": "system", "content": "你是一位资深播客制作人。请根据以下项目信息，生成一期播客的结构大纲。输出JSON格式，包含：title（标题）、sections（章节列表，每章含 title 和 key_points 数组）。"},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.6,
                max_tokens=2000,
                **self.build_llm_kwargs(),
            )
            outline = {
                "title": outline_llm.title,
                "sections": [
                    {"title": s.title, "key_points": s.key_points}
                    for s in outline_llm.sections
                ],
            }
            logger.info(f"大纲完成: {outline.get('title', '')[:40]}, {len(outline.get('sections', []))} 章节")
            return outline
        except Exception as e:
            logger.error(f"大纲生成失败: {e}")
            return {}

    def _build_outline_content(self, repos: list[GitHubRepo]) -> str:
        """构建大纲生成的输入内容。"""
        parts = ["请为以下 GitHub 项目生成一期播客的大纲：\n"]
        for i, repo in enumerate(repos, 1):
            parts.append(f"\n项目 {i}：{repo.name}")
            parts.append(f"描述：{repo.description}")
            if repo.topics:
                parts.append(f"标签：{', '.join(repo.topics[:5])}")
            parts.append(f"Star：{repo.stars}")
            # 大纲阶段只用 README 摘要（前4000字，含深度提取内容）
            readme_summary = repo.readme_markdown[:4000] if repo.readme_markdown else ""
            if readme_summary:
                parts.append(f"README摘要：{readme_summary}")
        parts.append("\n请生成包含开场、每项目讨论（2-3个关键讨论点）、总结收尾的大纲。")
        return "\n".join(parts)

    def _llm_to_script(self, llm: ScriptLLM, repos: list[GitHubRepo]) -> PodcastScript:
        """将 instructor 返回的 Pydantic 模型转换为 PodcastScript dataclass。"""
        hosts = [
            PodcastHost(
                name=h.name,
                persona=h.persona,
                voice_key=h.voice_key,
            )
            for h in llm.hosts
        ]
        if not hosts:
            hosts = [
                PodcastHost("小前", "科技播客主持人", "host"),
                PodcastHost("阿开", "技术专家", "guest"),
            ]

        host_names = {h.name for h in hosts}
        segments: list[PodcastSegment] = []
        for seg in llm.segments:
            speaker = seg.speaker
            voice_key = seg.voice_key
            for h in hosts:
                if h.name == speaker:
                    voice_key = h.voice_key
                    break
            if speaker not in host_names:
                voice_key = "guest" if voice_key == "guest" else "host"
            segments.append(
                PodcastSegment(
                    speaker=speaker,
                    text=seg.text.strip(),
                    emotion=seg.emotion,
                    voice_key=voice_key,
                )
            )

        return PodcastScript(
            title=llm.title,
            description=llm.description,
            hosts=hosts,
            segments=segments,
            repo_names=[r.name for r in repos],
        )

    def _mock_script(self, repos: list[GitHubRepo]) -> PodcastScript:
        """无 API Key 时的占位脚本。"""
        host = PodcastHost("小前", "科技播客主持人", "host")
        guest = PodcastHost("阿开", "技术专家", "guest")
        segments = [
            PodcastSegment(
                host.name,
                f"大家好，欢迎收听「GitHub 前沿观察」。今天我们来聊几个热门的开源项目。",
                "excited",
                "host",
            ),
            PodcastSegment(
                guest.name,
                f"没错，今天有 {len(repos)} 个值得关注的项目。",
                "neutral",
                "guest",
            ),
        ]
        for repo in repos:
            segments.append(
                PodcastSegment(
                    host.name,
                    f"先来看第一个项目「{repo.name}」，Star 数 {repo.stars}，"
                    f"它主要做的是：{repo.description[:80]}。",
                    "curious",
                    "host",
                )
            )
            segments.append(
                PodcastSegment(
                    guest.name,
                    f"这个项目挺有意思的。它解决了实际开发中的痛点，值得关注。",
                    "neutral",
                    "guest",
                )
            )
        segments.append(
            PodcastSegment(
                host.name,
                "好的，今天的节目就到这里，我们下期再见！",
                "happy",
                "host",
            )
        )
        return PodcastScript(
            title=f"GitHub 前沿观察：{', '.join(r.short_name for r in repos)}",
            description="本期讨论 GitHub 上的热门开源项目。",
            hosts=[host, guest],
            segments=segments,
            repo_names=[r.name for r in repos],
        )


_DEFAULT_SYSTEM_PROMPT = """你是一位资深科技播客制作人，请根据提供的 GitHub 项目信息，生成一期双人中文对话播客脚本。输出 JSON 格式，包含 title、description、hosts、segments 字段。"""
