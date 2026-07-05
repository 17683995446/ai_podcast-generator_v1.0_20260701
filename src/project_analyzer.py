"""项目深度分析模块：用 LLM 对每个 GitHub 项目生成结构化解读（类似 zread.ai）。

复用 config["llm"] 的 API 配置（base_url / model / api_key / enable_thinking 等），
通过 instructor + Pydantic 实现结构化输出，替代手写 JSON 容错解析：
  - 无 API Key → 返回 mock 分析
  - API 调用失败 → 回退 mock
  - SiliconFlow Qwen3.5 系列通过 enable_thinking=false 关闭思考模式
"""
from __future__ import annotations

from typing import Any

from .llm_helper import LLMClientMixin
from .llm_models import AnalysisResultLLM, ReviewResultLLM
from .models import GitHubRepo, ProjectAnalysis

from src.logger import get_logger

logger = get_logger(__name__)


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
{"score": 1到10的整数, "issues": ["发现的问题列表"], "suggestions": "改进建议"}
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


class ProjectAnalyzer(LLMClientMixin):
    """调用 LLM 对 GitHub 项目生成结构化深度分析（类似 zread.ai 解读页）。"""

    def __init__(self, config: dict[str, Any]):
        self._init_llm(config)
        self.cfg = config["llm"]
        self.project_root = config.get("project_root", ".")

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def analyze(self, repos: list[GitHubRepo], evidence_map: dict | None = None) -> list[ProjectAnalysis]:
        """对一批项目逐个生成结构化深度分析。

        Args:
            evidence_map: {repo_name: evidence_list} 深提取证据映射，用于证据链追踪
        """
        if evidence_map is None:
            evidence_map = {}
        results: list[ProjectAnalysis] = []
        for i, repo in enumerate(repos, 1):
            logger.info(f"({i}/{len(repos)}) 分析 {repo.name} ...")
            repo_evidence = evidence_map.get(repo.name, [])
            results.append(self.analyze_single(repo, repo_evidence))
        return results

    def analyze_single(self, repo: GitHubRepo, evidence_list: list[dict] | None = None) -> ProjectAnalysis:
        """分析单个项目，失败时回退到 mock。

        Args:
            evidence_list: 深提取证据列表，用于证据链追踪
        """
        if evidence_list is None:
            evidence_list = []
        if not self.api_key:
            return self._attach_evidence(self._mock_analysis(repo), evidence_list)

        user_content = self._build_user_content(repo)
        logger.info(
            f"调用 {self.cfg['model']} 分析 {repo.name}，"
            f"输入 {len(user_content)} 字符..."
        )

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            logger.info("已关闭 thinking 模式（enable_thinking=false）")

        try:
            result, completion = self.client.chat.completions.create_with_completion(
                response_model=AnalysisResultLLM,
                messages=[
                    {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.cfg.get("temperature", 0.4),
                max_tokens=self.cfg.get("max_tokens", 4000),
                **self.build_llm_kwargs(),
            )
            analysis = self._llm_to_analysis(result, repo)
            usage = completion.usage
            if usage:
                logger.info(
                    f"完成 {repo.name}：tokens 输入 "
                    f"{usage.prompt_tokens} / 输出 {usage.completion_tokens}"
                )
            # 增强：生成 Mermaid 架构图 + 多轮评审回路
            analysis = self._finalize(analysis, repo)
            # 附加证据链
            return self._attach_evidence(analysis, evidence_list)
        except Exception as e:
            logger.error(f"API 调用失败（{repo.name}）: {e}")
            logger.warning(f"回退到 mock 分析（{repo.name}）")
            return self._attach_evidence(self._mock_analysis(repo), evidence_list)

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

    def _llm_to_analysis(
        self, result: AnalysisResultLLM, repo: GitHubRepo
    ) -> ProjectAnalysis:
        """将 AnalysisResultLLM 转换为 ProjectAnalysis dataclass。

        处理嵌套结构：
        - key_modules：KeyModuleLLM -> {"name","description"}（仅保留 name/description，过滤空名）
        - comparison：ComparisonLLM -> 字符串
        - code_insights：CodeInsightsLLM -> 字符串
        mermaid_diagram 不在此设置，由 _finalize -> _generate_mermaid 单独生成。
        """
        # key_modules：KeyModuleLLM -> {"name","description"}
        key_modules = [
            {
                "name": m.name.strip(),
                "description": m.description.strip(),
            }
            for m in result.key_modules
            if m.name.strip()
        ]

        # comparison：ComparisonLLM -> 字符串
        comp = result.comparison
        comp_parts: list[str] = []
        if comp.strengths:
            comp_parts.append("优势：" + "；".join(comp.strengths))
        if comp.weaknesses:
            comp_parts.append("劣势：" + "；".join(comp.weaknesses))
        if comp.alternatives:
            comp_parts.append("替代方案：" + "；".join(comp.alternatives))
        comparison_str = "。".join(comp_parts)

        # code_insights：CodeInsightsLLM -> 字符串
        ci = result.code_insights
        ci_parts: list[str] = []
        if ci.patterns:
            ci_parts.append("设计模式：" + "；".join(ci.patterns))
        if ci.quality:
            ci_parts.append("代码质量：" + ci.quality)
        if ci.complexity:
            ci_parts.append("复杂度分析：" + ci.complexity)
        code_insights_str = "。".join(ci_parts)

        return ProjectAnalysis(
            repo_name=repo.name,
            summary=result.summary.strip(),
            tech_stack=list(result.tech_stack),
            architecture=result.architecture.strip(),
            key_modules=key_modules,
            quick_start=result.quick_start.strip(),
            highlights=list(result.highlights),
            use_cases=list(result.use_cases),
            comparison=comparison_str,
            code_insights=code_insights_str,
        )

    # ------------------------------------------------------------------
    # 增强：Mermaid 架构图 + 多轮评审回路
    # ------------------------------------------------------------------
    def _attach_evidence(self, analysis: ProjectAnalysis, evidence_list: list[dict]) -> ProjectAnalysis:
        """将深提取证据匹配到分析结果，生成证据链。

        如果 evidence_list 为空，analysis.evidence_sources 保持空列表（前端显示"无证据"）。
        """
        if not evidence_list:
            return analysis
        try:
            from src.evidence_tracker import match_evidence_to_analysis
            analysis.evidence_sources = match_evidence_to_analysis(analysis, evidence_list)
            verified = sum(1 for e in analysis.evidence_sources if e.get("confidence") == "verified")
            total = len(analysis.evidence_sources)
            logger.info(f"证据链：{verified}/{total} 项已验证")
        except Exception as e:
            logger.error(f"证据链匹配失败: {e}")
        return analysis

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

        Mermaid 输出为原始文本（非 JSON），故以 response_model=None 调用，
        instructor 将直接返回原始 ChatCompletion。
        """
        if not self.api_key:
            return ""
        user_content = self._build_mermaid_content(analysis, repo)
        logger.info(f"生成 Mermaid 架构图（{repo.name}）...")

        # SiliconFlow Qwen3.5 需关闭 thinking 模式
        if self.enable_thinking is False:
            logger.info("已关闭 thinking 模式（enable_thinking=false）")

        try:
            response = self.client.chat.completions.create(
                response_model=None,
                messages=[
                    {"role": "system", "content": _MERMAID_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.3,
                max_tokens=1000,
                **self.build_llm_kwargs(),
            )
            raw = response.choices[0].message.content or ""
            return self._strip_mermaid_fence(raw)
        except Exception as e:
            logger.error(f"Mermaid 生成失败（{repo.name}）: {e}")
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
        if not raw.startswith("```"):
            return raw
        lines = raw.splitlines()
        # 去除首行围栏（``` 或 ```mermaid）
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # 去除末行闭合围栏
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()

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
                logger.warning(f"评审失败（{repo.name}），保留当前分析")
                return current

            current.review_score = score
            if score >= 7:
                current.review_passed = True
                logger.info(f"评审通过（{repo.name}），分数 {score}")
                return current

            # score < 7
            if i < max_iterations - 1:
                logger.warning(
                    f"评审分数 {score} < 7（{repo.name}），"
                    "使用更严格 prompt 重新生成..."
                )
                regenerated = self._regenerate_with_strict_prompt(current, repo)
                if regenerated is not None:
                    # 保留已生成的 Mermaid 图
                    regenerated.mermaid_diagram = current.mermaid_diagram
                    current = regenerated
                else:
                    current.review_passed = False
                    logger.warning(f"重新生成失败（{repo.name}），保留原分析")
                    return current
            else:
                current.review_passed = False
                logger.warning(
                    f"评审未通过（{repo.name}），已达最大轮次，分数 {score}"
                )
                return current
        return current

    def _review_analysis(
        self, analysis: ProjectAnalysis, repo: GitHubRepo
    ) -> float | None:
        """调用 LLM 评审分析准确性，返回 1-10 分；失败返回 None。"""
        user_content = self._build_review_content(analysis, repo)
        try:
            result = self.client.chat.completions.create(
                response_model=ReviewResultLLM,
                messages=[
                    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=500,
                **self.build_llm_kwargs(),
            )
            # 将 ReviewResultLLM 转换为旧格式：评审回路仅需 score（1-10）
            score = float(result.score)
            return max(0.0, min(10.0, score))
        except Exception as e:
            logger.error(f"评审调用失败（{repo.name}）: {e}")
            return None

    def _build_review_content(self, analysis: ProjectAnalysis, repo: GitHubRepo) -> str:
        """构建评审用的用户消息：待评审分析 + README 证据。"""
        parts = ["请评审以下项目分析结果的准确性：\n"]
        parts.append(f"项目名称：{repo.name}")
        parts.append(f"概述：{analysis.summary}")
        parts.append(f"技术栈：{', '.join(analysis.tech_stack)}")
        parts.append(f"架构：{analysis.architecture}")
        if analysis.key_modules:
            modules_text = "; ".join(
                f"{m.get('name', '')}：{m.get('description', '')}"
                for m in analysis.key_modules
                if isinstance(m, dict)
            )
        else:
            modules_text = "（无）"
        parts.append(f"关键模块：{modules_text}")
        readme = repo.readme_markdown.strip()
        if readme:
            parts.append(f"\nREADME（用于核对证据，已截断）：\n{readme[:4000]}")
        else:
            parts.append("\nREADME：（未抓取到，请基于描述与标签评审）")
        parts.append(
            "\n请严格基于 README 核对，输出 JSON："
            '{"score": 1到10的整数, "issues": ["问题列表"], "suggestions": "改进建议"}。'
        )
        return "\n".join(parts)

    def _regenerate_with_strict_prompt(
        self, analysis: ProjectAnalysis, repo: GitHubRepo
    ) -> ProjectAnalysis | None:
        """用更严格的 system prompt 重新生成分析；失败返回 None。"""
        user_content = self._build_user_content(repo)
        try:
            result = self.client.chat.completions.create(
                response_model=AnalysisResultLLM,
                messages=[
                    {"role": "system", "content": _STRICT_ANALYSIS_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=self.cfg.get("temperature", 0.4),
                max_tokens=self.cfg.get("max_tokens", 4000),
                **self.build_llm_kwargs(),
            )
            return self._llm_to_analysis(result, repo)
        except Exception as e:
            logger.error(f"严格重新生成失败（{repo.name}）: {e}")
            return None

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
