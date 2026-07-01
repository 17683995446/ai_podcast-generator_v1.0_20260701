"""LLM 脚本生成模块：将项目 README 转为播客对话脚本。

支持任意 OpenAI 兼容 API（SiliconFlow / DeepSeek / 智谱 / OpenAI 等）。
SiliconFlow 免费 Qwen3.5-9B 需通过 enable_thinking=false 关闭思考模式。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from .models import GitHubRepo, PodcastHost, PodcastScript, PodcastSegment


# 播客脚本 JSON Schema（response_format 用）
PODCAST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "hosts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "persona": {"type": "string"},
                    "voice_key": {"type": "string"},
                },
                "required": ["name", "persona", "voice_key"],
            },
        },
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                    "emotion": {"type": "string"},
                    "voice_key": {"type": "string"},
                },
                "required": ["speaker", "text", "emotion", "voice_key"],
            },
        },
    },
    "required": ["title", "description", "hosts", "segments"],
}


class ScriptGenerator:
    """调用 LLM 生成播客脚本。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["llm"]
        self.project_root = Path(config["project_root"])
        # 保存完整配置，供 ScriptCritic 等子智能体复用
        self._full_config = config
        # 优先使用通用 LLM key
        self.api_key = config["api_keys"].get("llm", "") or config["api_keys"].get("deepseek", "")
        # 是否需要关闭 thinking 模式（SiliconFlow Qwen3.5 系列）
        self.enable_thinking = self.cfg.get("enable_thinking", None)
        self._system_prompt: str | None = None
        # 播客风格预设（借鉴 Podcastfy 的对话定制）
        self.style = config.get("podcast_style", "casual")
        self.longform = config.get("longform", False)

        if not self.api_key:
            print("[llm] 警告：未配置 LLM API Key，将使用 mock 模式")

        self.client = OpenAI(
            api_key=self.api_key or "mock-key",
            base_url=self.cfg["base_url"],
            timeout=self.cfg.get("timeout", 120),
        )

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
            print(f"[llm] 步骤2: 基于大纲生成完整脚本...")

        print(f"[llm] 调用 {self.cfg['model']}，输入 {len(user_content)} 字符...")

        # 根据风格和长内容模式调整 system prompt
        system_content = self.system_prompt
        style_addon = self._get_style_addon()
        if style_addon:
            system_content = system_content + "\n\n" + style_addon
        if self.longform:
            system_content += "\n\n## 长内容模式\n本期为长内容播客（目标 25-40 分钟），请生成 40-60 段对话，总字数 6000-10000 字。每个项目需要更深入的讨论，包括更多技术细节、实际代码示例解读、社区生态分析。"
        else:
            # 常规播客规格：由代码统一控制段数/字数，避免与系统提示词中的硬编码冲突
            system_content += "\n\n## 节目规格\n本期为常规播客（目标 5-8 分钟），请生成 15-30 段对话，总字数 1800-3000 字。"

        # longform 模式下增加 max_tokens
        max_tokens = self.cfg.get("max_tokens", 4000)
        if self.longform:
            max_tokens = min(max_tokens * 2, 8000)  # 长内容模式翻倍

        # 构建请求参数
        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.cfg.get("temperature", 0.8),
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}
            print("[llm] 已关闭 thinking 模式（enable_thinking=false）")

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            script = self._parse_script(raw, repos)
            # 回填生成时的元信息（供 RSS show notes / chapters 使用）
            script.outline = outline or {}
            script.repo_urls = [r.url for r in repos]
            script.style = self.style
            script.target_minutes = 30 if self.longform else 8
            usage = response.usage
            if usage:
                print(
                    f"[llm] 完成：tokens 输入 {usage.prompt_tokens} / "
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
                    print(f"[llm] 脚本评审通过（第{rev+1}轮），分数 {script.critic_score}/10")
                    break
                if rev < max_revisions - 1:
                    print(f"[llm] 脚本评审未通过（第{rev+1}轮），分数 {script.critic_score}/10，重写中...")
                    # 将评审反馈追加到用户内容并重新生成
                    feedback_text = result.get("feedback", "")
                    user_content_with_feedback = user_content + f"\n\n## 评审反馈（请据此改进）\n{feedback_text}\n\n请基于以上反馈重新生成更高质量的脚本。"
                    # 用带反馈的消息重建请求参数
                    kwargs["messages"] = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content_with_feedback},
                    ]
                    try:
                        response = self.client.chat.completions.create(**kwargs)
                        raw = response.choices[0].message.content or ""
                        script = self._parse_script(raw, repos)
                        script.outline = outline or {}
                        script.repo_urls = [r.url for r in repos]
                        script.style = self.style
                        script.target_minutes = 30 if self.longform else 8
                    except Exception as e:
                        print(f"[llm] 重写失败: {e}")
                        break
                else:
                    print(f"[llm] 脚本评审已达最大轮次，分数 {script.critic_score}/10")

            return script
        except Exception as e:
            print(f"[llm] API 调用失败: {e}")
            # 尝试不带 response_format 重试（某些模型不支持 JSON mode）
            if "response_format" in str(e).lower() or "json" in str(e).lower():
                print("[llm] 尝试不带 JSON mode 重试...")
                kwargs.pop("response_format", None)
                if self.enable_thinking is False:
                    kwargs["extra_body"] = {"enable_thinking": False}
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    raw = response.choices[0].message.content or ""
                    return self._parse_script(raw, repos)
                except Exception as e2:
                    print(f"[llm] 重试失败: {e2}")
            print("[llm] 回退到 mock 脚本")
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
        print(f"[llm] 步骤1: 生成节目大纲...")

        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": "你是一位资深播客制作人。请根据以下项目信息，生成一期播客的结构大纲。输出JSON格式，包含：title（标题）、sections（章节列表，每章含 title 和 key_points 数组）。"},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.6,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
            if not raw.startswith("{"):
                match = re.search(r"\{[\s\S]*\}", raw)
                if match:
                    raw = match.group(0)
            outline = json.loads(raw)
            print(f"[llm] 大纲完成: {outline.get('title', '')[:40]}, {len(outline.get('sections', []))} 章节")
            return outline
        except Exception as e:
            print(f"[llm] 大纲生成失败: {e}")
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

    def _parse_script(self, raw: str, repos: list[GitHubRepo]) -> PodcastScript:
        """解析 LLM 返回的 JSON 为 PodcastScript。"""
        raw = raw.strip()
        # 容错：提取 JSON 块
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # 尝试提取第一个 JSON 对象
        if not raw.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
        data = json.loads(raw)

        hosts = [
            PodcastHost(
                name=h["name"],
                persona=h.get("persona", ""),
                voice_key=h.get("voice_key", "host"),
            )
            for h in data.get("hosts", [])
        ]
        if not hosts:
            hosts = [
                PodcastHost("小前", "科技播客主持人", "host"),
                PodcastHost("阿开", "技术专家", "guest"),
            ]

        host_names = {h.name for h in hosts}
        segments: list[PodcastSegment] = []
        for seg in data.get("segments", []):
            speaker = seg.get("speaker", "")
            voice_key = seg.get("voice_key", "host")
            for h in hosts:
                if h.name == speaker:
                    voice_key = h.voice_key
                    break
            if speaker not in host_names:
                voice_key = "guest" if voice_key == "guest" else "host"
            segments.append(
                PodcastSegment(
                    speaker=speaker,
                    text=seg.get("text", "").strip(),
                    emotion=seg.get("emotion", "neutral"),
                    voice_key=voice_key,
                )
            )

        return PodcastScript(
            title=data.get("title", "GitHub 前沿观察"),
            description=data.get("description", ""),
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
