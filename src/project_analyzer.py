"""项目深度分析模块：用 LLM 对每个 GitHub 项目生成结构化解读（类似 zread.ai）。

复用 config["llm"] 的 API 配置（base_url / model / api_key / enable_thinking 等），
与 ScriptGenerator 保持一致的初始化与错误处理模式：
  - 无 API Key → 返回 mock 分析
  - API 调用失败 → 回退 mock
  - JSON mode 不被支持 → 去掉 response_format 重试
  - SiliconFlow Qwen3.5 系列通过 enable_thinking=false 关闭思考模式
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from .models import GitHubRepo, ProjectAnalysis


# 分析结果 JSON Schema（response_format 用）
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tech_stack": {
            "type": "array",
            "items": {"type": "string"},
        },
        "architecture": {"type": "string"},
        "key_modules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["name", "description"],
            },
        },
        "quick_start": {"type": "string"},
        "highlights": {
            "type": "array",
            "items": {"type": "string"},
        },
        "use_cases": {
            "type": "array",
            "items": {"type": "string"},
        },
        "comparison": {"type": "string"},
        "code_insights": {"type": "string"},
    },
    "required": [
        "summary",
        "tech_stack",
        "architecture",
        "key_modules",
        "quick_start",
        "highlights",
        "use_cases",
        "comparison",
        "code_insights",
    ],
}


_ANALYSIS_SYSTEM_PROMPT = """你是一位资深的开源项目架构师与技术分析师，擅长像 zread.ai 一样对 GitHub 项目进行结构化深度解读。你的读者是希望快速理解一个项目「值不值得用、怎么用、为什么这样设计」的开发者与工程决策者。

## 分析原则
1. **基于证据**：严格依据用户提供的 README / 描述 / 标签等材料进行分析，不得编造项目中不存在的技术细节、模块或数据。
2. **深入而非泛泛**：不要停留在「解决了什么问题」，必须深入到「怎么解决的、为什么这样设计、有什么取舍」。能从 README 推断架构与设计动机时才展开，推断不到就以通用工程经验补充并保持克制。
3. **架构视角优先**：关注分层设计、模块边界、依赖关系、扩展机制、数据流，而非简单罗列功能。
4. **代码质量与工程价值**：识别可观察的设计模式、性能策略、可扩展性设计，并给出可迁移的工程洞察。
5. **务实**：highlights 与 use_cases 要具体、可落地，避免营销式空话。

## 输出要求
严格输出一个 JSON 对象（不要输出任何 JSON 之外的文字、不要用 markdown 代码块包裹），包含以下字段：

- summary：一句话精准概述项目定位（做什么 + 面向谁 + 核心价值），不超过 50 字。
- tech_stack：技术栈列表，按重要性排序，如 ["Python", "PyTorch", "FastAPI"]。只列 README 中明确出现或可强推断的技术。
- architecture：架构设计描述，2-3 句话。说明核心分层 / 组件关系 / 数据流向 / 关键设计决策及其理由。
- key_modules：关键模块列表，每项为 {"name": "模块名", "description": "职责与设计说明（1-2 句）"}。提取 README 中体现的核心模块；若 README 未给出明确模块，列出可从功能推断的主要子系统。
- quick_start：快速上手指南，3-5 步，覆盖安装与基本用法，用编号步骤呈现（如 "1. ...\\n2. ..."）。
- highlights：技术亮点列表，3-5 条，每条聚焦一个具体技术点（设计模式 / 性能优化 / 扩展机制 / 工程实践）并简述其价值。
- use_cases：应用场景列表，3-5 条，具体到「谁、在什么场景、用它解决什么」。
- comparison：同类项目对比分析，2-3 句话。指出它相对于主流同类方案的差异化定位与取舍。若 README 无明确同类项目，基于领域常识给出对比。
- code_insights：代码层面的洞察，2-4 句话。如可观察的设计模式、性能优化技巧、依赖管理方式、可扩展点等；强调可被其他项目借鉴的工程经验。

## 约束
- 所有列表字段都使用 JSON 数组。
- key_modules 数组中每个元素必须同时包含 name 与 description。
- 不要在 JSON 之外输出任何解释性文字。
"""


# 评审回路系统提示词（借鉴 DeepRepo 5-pass + repo2readme 评分）
_REVIEW_SYSTEM_PROMPT = """你是一位严格的技术分析评审。请对提交的项目分析结果进行准确性评审，给出 1-10 的整数评分。评审维度：
1. tech_stack 中的每一项是否都在 README 中真实出现或可强推断？有无杜撰？
2. key_modules 是否真实存在？是真实模块还是模型幻觉？
3. architecture 描述是否有证据支撑、是否脚踏实地？

严格输出一个 JSON 对象（不要输出 JSON 之外的文字）：
{"score": 1到10的整数, "reason": "简短理由（1-2 句）"}
"""


# 严格模式系统提示词：评审未通过时用于重新生成（在原 prompt 基础上加强证据约束）
_STRICT_ANALYSIS_PROMPT = _ANALYSIS_SYSTEM_PROMPT + """

## 严格模式（重新生成）
上一版分析在评审中被判定为存在准确性问题（技术栈 / 模块可能为幻觉、架构描述缺乏证据）。请更加严格地依据 README 证据重新生成：
- 不得编造项目中不存在的技术、模块或数据。
- 无法从 README 推断的内容，请留空或显式标注「README 未明确」。
- tech_stack 仅保留 README 中明确出现或可强推断的技术。
- key_modules 仅保留 README 体现的真实模块；无法确认时不臆造。
"""


# Mermaid 架构图生成系统提示词（借鉴 OpenDeepWiki / DeepRepo）
_MERMAID_SYSTEM_PROMPT = (
    "你是一位技术架构师。请基于项目分析结果，生成一个 Mermaid 架构图。"
    "使用 graph TD 语法，展示核心模块之间的依赖关系和数据流向。"
    "只输出 Mermaid 代码，不要其他文字。"
)


class ProjectAnalyzer:
    """调用 LLM 对 GitHub 项目生成结构化深度分析（类似 zread.ai 解读页）。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["llm"]
        self.project_root = config.get("project_root", ".")
        # 优先使用通用 LLM key（与 ScriptGenerator 一致）
        self.api_key = (
            config["api_keys"].get("llm", "")
            or config["api_keys"].get("deepseek", "")
        )
        # 是否需要关闭 thinking 模式（SiliconFlow Qwen3.5 系列）
        self.enable_thinking = self.cfg.get("enable_thinking", None)

        if not self.api_key:
            print("[analyzer] 警告：未配置 LLM API Key，将使用 mock 模式")

        self.client = OpenAI(
            api_key=self.api_key or "mock-key",
            base_url=self.cfg["base_url"],
            timeout=self.cfg.get("timeout", 120),
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def analyze(self, repos: list[GitHubRepo]) -> list[ProjectAnalysis]:
        """对一批项目逐个生成结构化深度分析。"""
        results: list[ProjectAnalysis] = []
        for i, repo in enumerate(repos, 1):
            print(f"[analyzer] ({i}/{len(repos)}) 分析 {repo.name} ...")
            results.append(self.analyze_single(repo))
        return results

    def analyze_single(self, repo: GitHubRepo) -> ProjectAnalysis:
        """分析单个项目，失败时回退到 mock。"""
        if not self.api_key:
            return self._mock_analysis(repo)

        user_content = self._build_user_content(repo)
        print(
            f"[analyzer] 调用 {self.cfg['model']} 分析 {repo.name}，"
            f"输入 {len(user_content)} 字符..."
        )

        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.cfg.get("temperature", 0.4),
            "max_tokens": self.cfg.get("max_tokens", 4000),
            "response_format": {"type": "json_object"},
        }

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}
            print("[analyzer] 已关闭 thinking 模式（enable_thinking=false）")

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            analysis = self._parse_analysis(raw, repo)
            usage = response.usage
            if usage:
                print(
                    f"[analyzer] 完成 {repo.name}：tokens 输入 "
                    f"{usage.prompt_tokens} / 输出 {usage.completion_tokens}"
                )
            # 增强：生成 Mermaid 架构图 + 多轮评审回路
            return self._finalize(analysis, repo)
        except Exception as e:
            print(f"[analyzer] API 调用失败（{repo.name}）: {e}")
            # 尝试不带 response_format 重试（某些模型不支持 JSON mode）
            if "response_format" in str(e).lower() or "json" in str(e).lower():
                print("[analyzer] 尝试不带 JSON mode 重试...")
                kwargs.pop("response_format", None)
                if self.enable_thinking is False:
                    kwargs["extra_body"] = {"enable_thinking": False}
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    raw = response.choices[0].message.content or ""
                    # 增强：生成 Mermaid 架构图 + 多轮评审回路
                    return self._finalize(self._parse_analysis(raw, repo), repo)
                except Exception as e2:
                    print(f"[analyzer] 重试失败（{repo.name}）: {e2}")
            print(f"[analyzer] 回退到 mock 分析（{repo.name}）")
            return self._mock_analysis(repo)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _build_user_content(self, repo: GitHubRepo) -> str:
        """构建分析用的用户消息：单项目信息汇总。"""
        parts = ["请基于以下 GitHub 项目信息进行结构化深度分析：\n"]
        parts.append(f"项目名称：{repo.name}")
        parts.append(f"仓库地址：{repo.url}")
        parts.append(f"Star 数：{repo.stars}")
        parts.append(f"主要语言：{repo.language or '未指定'}")
        if repo.topics:
            parts.append(f"标签：{', '.join(repo.topics[:15])}")
        parts.append(f"项目描述：{repo.description}")
        readme = repo.readme_markdown.strip()
        if readme:
            parts.append(
                f"\nREADME 内容（原始 Markdown，已截断）：\n{readme[:6000]}"
            )
        else:
            parts.append("\nREADME 内容：（未抓取到，请主要依据上述描述与标签分析）")
        parts.append("\n请严格输出 JSON 对象，不要输出 JSON 之外的文字。")
        return "\n".join(parts)

    def _parse_analysis(self, raw: str, repo: GitHubRepo) -> ProjectAnalysis:
        """解析 LLM 返回的 JSON 为 ProjectAnalysis。"""
        raw = raw.strip()
        # 容错：去除 markdown 代码块包裹
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        # 容错：提取首个 JSON 对象
        if not raw.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
        data = json.loads(raw)

        def _as_str_list(key: str) -> list[str]:
            val = data.get(key, [])
            if isinstance(val, list):
                return [str(x) for x in val if x is not None]
            if isinstance(val, str) and val:
                return [val]
            return []

        def _as_module_list(key: str) -> list[dict]:
            val = data.get(key, [])
            modules: list[dict] = []
            if not isinstance(val, list):
                return modules
            for item in val:
                if isinstance(item, dict):
                    modules.append(
                        {
                            "name": str(item.get("name", "")).strip(),
                            "description": str(item.get("description", "")).strip(),
                        }
                    )
                elif isinstance(item, str) and item.strip():
                    modules.append({"name": item.strip(), "description": ""})
            return [m for m in modules if m["name"]]

        return ProjectAnalysis(
            repo_name=repo.name,
            summary=str(data.get("summary", "")).strip(),
            tech_stack=_as_str_list("tech_stack"),
            architecture=str(data.get("architecture", "")).strip(),
            key_modules=_as_module_list("key_modules"),
            quick_start=str(data.get("quick_start", "")).strip(),
            highlights=_as_str_list("highlights"),
            use_cases=_as_str_list("use_cases"),
            comparison=str(data.get("comparison", "")).strip(),
            code_insights=str(data.get("code_insights", "")).strip(),
        )

    # ------------------------------------------------------------------
    # 增强：Mermaid 架构图 + 多轮评审回路
    # ------------------------------------------------------------------
    def _finalize(self, analysis: ProjectAnalysis, repo: GitHubRepo) -> ProjectAnalysis:
        """解析出分析后的增强入口：生成 Mermaid 图，再执行评审回路。

        对应 analyze_single 的集成步骤：
        1. 调用 _generate_mermaid() 并设置 analysis.mermaid_diagram
        2. 调用 _review_and_refine() 做质量检查
        3. 返回增强后的分析
        """
        analysis.mermaid_diagram = self._generate_mermaid(analysis, repo)
        analysis = self._review_and_refine(analysis, repo)
        return analysis

    def _generate_mermaid(self, analysis: ProjectAnalysis, repo: GitHubRepo) -> str:
        """调用 LLM 生成 Mermaid 架构图代码；失败返回空字符串。

        借鉴 OpenDeepWiki / DeepRepo 的架构图生成：以 key_modules 与 architecture 为输入，
        使用 graph TD 语法展示核心模块依赖与数据流向。
        """
        if not self.api_key:
            return ""
        user_content = self._build_mermaid_content(analysis, repo)
        print(f"[analyzer] 生成 Mermaid 架构图（{repo.name}）...")

        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _MERMAID_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        }
        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}
            print("[analyzer] 已关闭 thinking 模式（enable_thinking=false）")

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            return self._strip_mermaid_fence(raw)
        except Exception as e:
            print(f"[analyzer] Mermaid 生成失败（{repo.name}）: {e}")
            return ""

    def _build_mermaid_content(self, analysis: ProjectAnalysis, repo: GitHubRepo) -> str:
        """构建 Mermaid 生成用的用户消息：架构描述 + 关键模块。"""
        parts = ["请基于以下项目分析生成 Mermaid 架构图（graph TD 语法）：\n"]
        parts.append(f"项目名称：{repo.name}")
        parts.append(f"架构描述：{analysis.architecture}")
        parts.append("关键模块：")
        for m in analysis.key_modules:
            if isinstance(m, dict):
                name = str(m.get("name", "")).strip()
                desc = str(m.get("description", "")).strip()
            else:
                name = str(m).strip()
                desc = ""
            parts.append(f"  - {name}：{desc}")
        parts.append("\n只输出 Mermaid 代码，使用 graph TD 语法，展示核心模块间依赖关系与数据流向。")
        return "\n".join(parts)

    @staticmethod
    def _strip_mermaid_fence(raw: str) -> str:
        """去除 ```mermaid ... ``` 代码块包裹，返回纯 Mermaid 代码。"""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:mermaid)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        return raw.strip()

    def _review_and_refine(
        self, analysis: ProjectAnalysis, repo: GitHubRepo
    ) -> ProjectAnalysis:
        """多轮评审回路：评审分析准确性，低分则用更严格 prompt 重新生成。

        借鉴 DeepRepo 5-pass + repo2readme 评分：
          - 调用 LLM 对分析打分（1-10），依据 README 核对技术栈 / 模块 / 架构是否有证据。
          - 分数 < 7 则用更严格 prompt 重新生成。
          - 最多 2 轮（原始 + 1 次重试）。
          - 评审 API 失败时保留原分析并标记 review_passed=True（优雅降级）。
        """
        max_iterations = 2  # 原始 + 1 次重试
        current = analysis
        for i in range(max_iterations):
            score = self._review_analysis(current, repo)
            if score is None:
                # 评审失败 -> 保留当前分析，默认通过（优雅降级）
                current.review_passed = True
                print(f"[analyzer] 评审失败（{repo.name}），保留当前分析")
                return current

            current.review_score = score
            if score >= 7:
                current.review_passed = True
                print(f"[analyzer] 评审通过（{repo.name}），分数 {score}")
                return current

            # score < 7
            if i < max_iterations - 1:
                print(
                    f"[analyzer] 评审分数 {score} < 7（{repo.name}），"
                    "使用更严格 prompt 重新生成..."
                )
                regenerated = self._regenerate_with_strict_prompt(current, repo)
                if regenerated is not None:
                    # 保留已生成的 Mermaid 图
                    regenerated.mermaid_diagram = current.mermaid_diagram
                    current = regenerated
                else:
                    current.review_passed = False
                    print(f"[analyzer] 重新生成失败（{repo.name}），保留原分析")
                    return current
            else:
                current.review_passed = False
                print(
                    f"[analyzer] 评审未通过（{repo.name}），已达最大轮次，分数 {score}"
                )
                return current
        return current

    def _review_analysis(
        self, analysis: ProjectAnalysis, repo: GitHubRepo
    ) -> float | None:
        """调用 LLM 评审分析准确性，返回 1-10 分；失败返回 None。"""
        user_content = self._build_review_content(analysis, repo)
        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        }
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            data = json.loads(self._extract_json(raw))
            score = float(data.get("score", 0))
            return max(0.0, min(10.0, score))
        except Exception as e:
            print(f"[analyzer] 评审调用失败（{repo.name}）: {e}")
            return None

    def _build_review_content(self, analysis: ProjectAnalysis, repo: GitHubRepo) -> str:
        """构建评审用的用户消息：待评审分析 + README 证据。"""
        parts = ["请评审以下项目分析结果的准确性：\n"]
        parts.append(f"项目名称：{repo.name}")
        parts.append(f"概述：{analysis.summary}")
        parts.append(f"技术栈：{', '.join(analysis.tech_stack)}")
        parts.append(f"架构：{analysis.architecture}")
        parts.append(f"关键模块：{json.dumps(analysis.key_modules, ensure_ascii=False)}")
        readme = repo.readme_markdown.strip()
        if readme:
            parts.append(f"\nREADME（用于核对证据，已截断）：\n{readme[:4000]}")
        else:
            parts.append("\nREADME：（未抓取到，请基于描述与标签评审）")
        parts.append(
            "\n请严格基于 README 核对，输出 JSON："
            '{"score": 1到10的整数, "reason": "简短理由"}。'
        )
        return "\n".join(parts)

    def _regenerate_with_strict_prompt(
        self, analysis: ProjectAnalysis, repo: GitHubRepo
    ) -> ProjectAnalysis | None:
        """用更严格的 system prompt 重新生成分析；失败返回 None。"""
        user_content = self._build_user_content(repo)
        kwargs: dict[str, Any] = {
            "model": self.cfg["model"],
            "messages": [
                {"role": "system", "content": _STRICT_ANALYSIS_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.cfg.get("temperature", 0.4),
            "max_tokens": self.cfg.get("max_tokens", 4000),
            "response_format": {"type": "json_object"},
        }
        if self.enable_thinking is False:
            kwargs["extra_body"] = {"enable_thinking": False}

        try:
            response = self.client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content or ""
            return self._parse_analysis(raw, repo)
        except Exception as e:
            print(f"[analyzer] 严格重新生成失败（{repo.name}）: {e}")
            return None

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

    def _mock_analysis(self, repo: GitHubRepo) -> ProjectAnalysis:
        """无 API Key 或调用失败时的占位分析。"""
        desc = repo.description or "一个值得关注的开源项目"
        lang = repo.language or "通用"
        return ProjectAnalysis(
            repo_name=repo.name,
            summary=f"{repo.short_name}：{desc[:40]}",
            tech_stack=[lang] if lang and lang != "通用" else [],
            architecture=(
                f"基于 README 推断，{repo.short_name} 采用模块化设计，"
                "核心组件职责清晰、可独立扩展。"
                "（mock 模式：请配置 LLM API Key 获取真实深度分析）"
            ),
            key_modules=[
                {
                    "name": "核心模块",
                    "description": "（mock）项目的主体功能模块，待 LLM 解读。",
                }
            ],
            quick_start=(
                "1. 克隆仓库：git clone " + repo.url + "\n"
                "2. 安装依赖（参考 README）\n"
                "3. 运行示例（参考 README）\n"
                "（mock 模式：请配置 LLM API Key 获取真实指南）"
            ),
            highlights=[
                "（mock）技术亮点一：待 LLM 解读",
                "（mock）技术亮点二：待 LLM 解读",
                "（mock）技术亮点三：待 LLM 解读",
            ],
            use_cases=[
                "（mock）应用场景一：待 LLM 解读",
                "（mock）应用场景二：待 LLM 解读",
                "（mock）应用场景三：待 LLM 解读",
            ],
            comparison=(
                f"（mock 模式）{repo.short_name} 与同类项目相比，"
                "在易用性与生态上各有取舍。请配置 LLM API Key 获取真实对比分析。"
            ),
            code_insights=(
                "（mock 模式）待 LLM 基于 README 给出设计模式、性能优化与可扩展点等代码洞察。"
            ),
            mermaid_diagram=(
                "graph TD\n"
                "    A[核心模块] --> B[子模块1]\n"
                "    A --> C[子模块2]\n"
                "    B --> D[输出]\n"
                "    C --> D\n"
                "    %% mock 模式：请配置 LLM API Key 获取真实架构图"
            ),
            commit_narrative="（mock 模式）Commit 演进叙事待 LLM 生成。",
        )
