"""脚本评审智能体模块（借鉴 PodAgent Critic + PoDEval 评估框架）。

PodAgent 的 Host-Guest-Writer 系统中引入了 Critic 角色，用于对 Writer 生成的
脚本进行质量把关；低分时触发 Writer 重新生成。PoDEval 则提出了一套面向播客
对话的多维度评估框架。本模块将二者结合：

- 复用 ScriptGenerator 的 OpenAI 兼容客户端模式（SiliconFlow Qwen3.5）。
- 对脚本进行 5 维度评分：信息密度 / 连贯性 / 说话人多样性 / 事实性 / 吸引力。
- 评审失败时优雅降级，返回默认通过结果，避免阻塞主生成流程。
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .models import GitHubRepo, PodcastScript


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

# 评审维度键名
_DIMENSION_KEYS = (
    "info_density",
    "coherence",
    "speaker_diversity",
    "factual_grounding",
    "engagement",
)


class ScriptCritic:
    """播客脚本评审智能体（借鉴 PodAgent Critic + PoDEval 评估框架）。

    对生成的脚本进行多维度质量评估，低分触发 Writer 重新生成。
    """

    def __init__(self, config: dict):
        # 与 ScriptGenerator 相同的 OpenAI 客户端初始化模式
        self.cfg = config["llm"]
        # 优先使用通用 LLM key（与 ScriptGenerator 一致）
        self.api_key = config["api_keys"].get("llm", "") or config["api_keys"].get("deepseek", "")
        # 是否需要关闭 thinking 模式（SiliconFlow Qwen3.5 系列）
        self.enable_thinking = self.cfg.get("enable_thinking", None)

        if not self.api_key:
            print("[critic] 警告：未配置 LLM API Key，将使用 mock 评审")

        self.client = OpenAI(
            api_key=self.api_key or "mock-key",
            base_url=self.cfg["base_url"],
            timeout=self.cfg.get("timeout", 120),
        )

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

        # 构建请求参数：JSON 模式、低温（评审需稳定）、token 上限 800
        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        }

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}
            print("[critic] 已关闭 thinking 模式（enable_thinking=false）")

        print(f"[critic] 调用 {self.cfg['model']} 评审脚本，输入 {len(user_content)} 字符...")

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            result = self._parse_eval_result(raw)
            print(f"[critic] 评审完成：总分 {result.get('overall_score', 0)}/10")
            return result
        except Exception as e:
            print(f"[critic] 评审 API 调用失败: {e}")
            # 尝试不带 response_format 重试（某些模型不支持 JSON mode）
            if "response_format" in str(e).lower() or "json" in str(e).lower():
                print("[critic] 尝试不带 JSON mode 重试...")
                kwargs.pop("response_format", None)
                if self.enable_thinking is False:
                    kwargs["extra_body"] = {"enable_thinking": False}
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    raw = response.choices[0].message.content or ""
                    return self._parse_eval_result(raw)
                except Exception as e2:
                    print(f"[critic] 重试失败: {e2}")
            # 评审失败时返回默认通过结果（分数 0、空反馈），避免阻塞生成流程
            print("[critic] 评审失败，返回默认通过结果")
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

    def _parse_eval_result(self, raw: str) -> dict:
        """解析 LLM 返回的评审 JSON（容错处理）。"""
        raw = raw.strip()
        # 容错：去除 ```json 代码块包裹
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # 尝试提取第一个 JSON 对象
        if not raw.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
        data = json.loads(raw)

        # 解析总分（兼容整数/浮点/字符串）
        overall_score = data.get("overall_score", 0)
        try:
            overall_score = float(overall_score)
        except (TypeError, ValueError):
            overall_score = 0.0

        # 解析各维度评分
        dimensions = data.get("dimensions", {}) or {}
        parsed_dims: dict[str, int] = {}
        for key in _DIMENSION_KEYS:
            val = dimensions.get(key, 0)
            try:
                parsed_dims[key] = int(float(val))
            except (TypeError, ValueError):
                parsed_dims[key] = 0

        # 解析反馈
        feedback = data.get("feedback", "") or ""

        # 解析是否通过：若模型未给出，则按总分 >= 阈值判定
        passed = data.get("passed", None)
        if passed is None:
            passed = overall_score >= PASS_THRESHOLD
        elif isinstance(passed, str):
            passed = passed.strip().lower() in ("true", "1", "yes", "是")

        return {
            "overall_score": overall_score,
            "dimensions": parsed_dims,
            "feedback": feedback,
            "passed": bool(passed),
        }
