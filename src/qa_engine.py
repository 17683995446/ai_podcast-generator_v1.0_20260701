"""交互式问答引擎（借鉴 NotebookLM 交互模式）。

用户可对已分析的项目提问，引擎基于项目分析数据 + README 生成回答。
无需向量数据库——直接将完整上下文喂给 LLM（项目分析数据通常 < 4K tokens）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI


_QA_SYSTEM_PROMPT = """你是一位技术博学的播客助手。用户会就某个 GitHub 项目提问，你需要基于提供的项目分析数据回答问题。

## 回答原则
1. **严格基于提供的数据**：只使用下方"项目分析数据"中的信息回答，不得编造项目中不存在的内容
2. **如果数据不足以回答**：坦诚告知"根据目前的分析数据，我无法回答这个问题"，并建议用户查看项目 README 或源码
3. **回答风格**：清晰、专业、有条理。用中文回答，适当使用列表和代码格式
4. **深度优先**：尽量给出有深度的技术回答，而不是泛泛而谈
5. **关联播客内容**：如果问题与播客讨论的内容相关，可以引用播客中的观点

## 输出格式
直接输出回答文本，不要输出 JSON。回答控制在 200-500 字。"""


class QAEngine:
    """交互式问答引擎。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["llm"]
        self.project_root = Path(config.get("project_root", "."))
        self.api_key = (
            config["api_keys"].get("llm", "")
            or config["api_keys"].get("deepseek", "")
        )
        self.enable_thinking = self.cfg.get("enable_thinking", None)

        if not self.api_key:
            print("[qa] 警告：未配置 LLM API Key，将使用 mock 模式")

        self.client = OpenAI(
            api_key=self.api_key or "mock-key",
            base_url=self.cfg["base_url"],
            timeout=self.cfg.get("timeout", 60),
        )

    def ask(self, question: str, analysis_data: dict, readme_excerpt: str = "") -> str:
        """回答用户关于项目的问题。
        
        Args:
            question: 用户问题
            analysis_data: 项目分析数据（ProjectAnalysis.to_dict() 格式）
            readme_excerpt: README 摘要（可选，提供更多上下文）
        
        Returns:
            回答文本
        """
        if not self.api_key:
            return self._mock_answer(question, analysis_data)

        # Build context
        context = self._build_context(analysis_data, readme_excerpt)
        user_content = f"## 项目分析数据\n{context}\n\n## 用户问题\n{question}"

        kwargs = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _QA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.4,
            "max_tokens": 800,
        }
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}

        try:
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"[qa] API 调用失败: {e}")
            return f"抱歉，回答生成失败：{e}"

    def ask_by_episode(self, question: str, episode_number: int, repo_name: str = "") -> str:
        """基于已保存的节目分析数据回答问题。
        
        Args:
            question: 用户问题
            episode_number: 节目编号
            repo_name: 指定项目名（空则用第一个项目）
        """
        analysis_data = self._load_episode_analysis(episode_number, repo_name)
        if not analysis_data:
            return f"未找到第 {episode_number} 期的分析数据。"
        return self.ask(question, analysis_data)

    def _build_context(self, analysis_data: dict, readme_excerpt: str = "") -> str:
        """构建 LLM 上下文：项目分析数据 + README 摘要。"""
        parts = []
        repo_name = analysis_data.get("repo_name", "未知项目")
        parts.append(f"项目：{repo_name}")
        if analysis_data.get("summary"):
            parts.append(f"概述：{analysis_data['summary']}")
        if analysis_data.get("tech_stack"):
            parts.append(f"技术栈：{', '.join(analysis_data['tech_stack'])}")
        if analysis_data.get("architecture"):
            parts.append(f"架构设计：{analysis_data['architecture']}")
        if analysis_data.get("key_modules"):
            modules = analysis_data["key_modules"]
            if isinstance(modules, list):
                for m in modules:
                    if isinstance(m, dict):
                        parts.append(f"  模块 {m.get('name', '')}：{m.get('description', '')}")
        if analysis_data.get("highlights"):
            parts.append(f"技术亮点：{'; '.join(analysis_data['highlights'])}")
        if analysis_data.get("use_cases"):
            parts.append(f"应用场景：{'; '.join(analysis_data['use_cases'])}")
        if analysis_data.get("code_insights"):
            parts.append(f"代码洞察：{analysis_data['code_insights']}")
        if analysis_data.get("comparison"):
            parts.append(f"同类对比：{analysis_data['comparison']}")
        if analysis_data.get("commit_narrative"):
            parts.append(f"提交动态：{analysis_data['commit_narrative']}")
        if analysis_data.get("health_data"):
            hd = analysis_data["health_data"]
            if isinstance(hd, dict):
                parts.append(f"健康度：{hd.get('health_grade', 'N/A')} ({hd.get('health_score', 0)}/100)")
        if readme_excerpt:
            parts.append(f"\nREADME 摘要：\n{readme_excerpt[:3000]}")
        return "\n".join(parts)

    def _load_episode_analysis(self, episode_number: int, repo_name: str = "") -> dict | None:
        """从 output/analyses/ 加载指定节目的分析数据。"""
        analyses_dir = self.project_root / "output" / "analyses"
        if not analyses_dir.exists():
            return None
        
        # Find the analysis file for this episode
        # Files are named: analysis_YYYYMMDD_HHMMSS.json or analysis_YYYYMMDD_HHMMSS_epNN.json
        candidates = sorted(analyses_dir.glob("analysis_*.json"), reverse=True)
        for f in candidates:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("episode_number") == episode_number:
                    analyses = data.get("analyses", [])
                    if not analyses:
                        continue
                    if repo_name:
                        for a in analyses:
                            if a.get("repo_name", "") == repo_name:
                                return a
                    # Return first if no specific repo
                    return analyses[0]
            except Exception:
                continue
        return None

    def _mock_answer(self, question: str, analysis_data: dict) -> str:
        """Mock answer when no API key."""
        repo = analysis_data.get("repo_name", "该项目")
        return (
            f"（mock 模式）关于「{repo}」的问题「{question}」：\n"
            f"请配置 LLM API Key 以获取真实回答。"
            f"目前可用的分析数据包括：{', '.join(analysis_data.keys())}"
        )
