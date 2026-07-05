"""Stage 1 单元测试：验证 instructor 重构后的 6 个 LLM 模块。

覆盖范围：
  1. llm_client.py   — 工厂函数（create_llm_client / build_kwargs / create_raw_client）
  2. llm_models.py   — Pydantic 模型校验
  3. script_critic.py — mock 模式评审
  4. show_notes_generator.py — mock 模式 + 规则提取
  5. cross_project_comparator.py — mock 模式 + 规则计算
  6. project_analyzer.py — mock 模式 + Pydantic 转换
  7. qa_engine.py — mock 模式问答
  8. llm_script.py — mock 模式脚本生成

运行：python -m pytest tests/test_stage1_llm.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm_client import create_llm_client, build_kwargs, create_raw_client
from src.llm_models import (
    CriticResultLLM,
    AnalysisResultLLM,
    ReviewResultLLM,
    ShowNotesLLM,
    CompareResultLLM,
    ScriptLLM,
    OutlineLLM,
    HostLLM,
    SegmentLLM,
    KeyModuleLLM,
    ComparisonLLM,
    CodeInsightsLLM,
    ProjectPositioningLLM,
    TechOverlapLLM,
    OutlineSectionLLM,
)
from src.models import (
    GitHubRepo,
    PodcastScript,
    PodcastHost,
    PodcastSegment,
    ProjectAnalysis,
    ProjectComparison,
    ShowNotes,
    Chapter,
    RepoHealth,
)
from src.script_critic import ScriptCritic
from src.show_notes_generator import ShowNotesGenerator
from src.cross_project_comparator import CrossProjectComparator
from src.project_analyzer import ProjectAnalyzer
from src.qa_engine import QAEngine
from src.llm_script import ScriptGenerator


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def make_config(api_key: str = "") -> dict:
    """构建测试用配置（无 API Key 时走 mock 模式）。"""
    return {
        "api_keys": {"llm": api_key, "deepseek": ""},
        "llm": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False,
            "temperature": 0.8,
            "max_tokens": 4000,
            "timeout": 120,
        },
        "podcast_style": "casual",
        "longform": False,
        "project_root": str(Path(__file__).resolve().parent.parent),
    }


def make_repo(name: str = "test/repo") -> GitHubRepo:
    """构建测试用 GitHubRepo。"""
    return GitHubRepo(
        name=name,
        url=f"https://github.com/{name}",
        description="A test repository for unit testing",
        stars=1000,
        language="Python",
        topics=["python", "testing"],
        readme_markdown="# Test Repo\n\nThis is a test README.",
    )


def make_script() -> PodcastScript:
    """构建测试用 PodcastScript。"""
    host = PodcastHost("Alice", "主持人", "host")
    guest = PodcastHost("Bob", "嘉宾", "guest")
    return PodcastScript(
        title="Test Podcast",
        description="A test podcast episode",
        hosts=[host, guest],
        segments=[
            PodcastSegment("Alice", "Hello everyone!", "excited", "host"),
            PodcastSegment("Bob", "Hi Alice, great to be here.", "neutral", "guest"),
            PodcastSegment("Alice", "Let's talk about the project.", "curious", "host"),
        ],
        repo_names=["test/repo"],
    )


def make_analysis(repo_name: str = "test/repo") -> ProjectAnalysis:
    """构建测试用 ProjectAnalysis。"""
    return ProjectAnalysis(
        repo_name=repo_name,
        summary="A test project for unit testing",
        tech_stack=["Python", "PyTorch"],
        architecture="Modular design with clear separation.",
        key_modules=[{"name": "Core", "description": "Main module"}],
        quick_start="1. Install\n2. Run",
        highlights=["Fast inference", "Clean API"],
        use_cases=["Testing", "Development"],
        comparison="优势：Fast. 劣势：Limited docs.",
        code_insights="设计模式：Factory. 代码质量：Good.",
    )


# ═══════════════════════════════════════════════════════════════
# 1. llm_client.py 工厂函数测试
# ═══════════════════════════════════════════════════════════════


class TestLLMClient:
    """测试 LLM 客户端工厂函数。"""

    def test_create_llm_client_no_api_key(self):
        """无 API Key 时返回 (None, meta)。"""
        config = make_config(api_key="")
        client, meta = create_llm_client(config)
        assert client is None
        assert meta["api_key"] == ""
        assert meta["model"] == "Qwen/Qwen3.5-9B"
        assert meta["enable_thinking"] is False

    def test_create_llm_client_with_api_key(self):
        """有 API Key 时返回 instructor 客户端。"""
        config = make_config(api_key="test-key-123")
        client, meta = create_llm_client(config)
        assert client is not None
        assert meta["api_key"] == "test-key-123"

    def test_create_llm_client_deepseek_fallback(self):
        """api_keys.llm 为空时回退到 api_keys.deepseek。"""
        config = make_config(api_key="")
        config["api_keys"]["deepseek"] = "deepseek-key"
        client, meta = create_llm_client(config)
        assert client is not None
        assert meta["api_key"] == "deepseek-key"

    def test_build_kwargs_basic(self):
        """build_kwargs 注入 model 参数。"""
        meta = {"model": "test-model", "enable_thinking": None}
        kwargs = build_kwargs(meta, messages=[{"role": "user", "content": "hi"}])
        assert kwargs["model"] == "test-model"
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
        assert "extra_body" not in kwargs

    def test_build_kwargs_enable_thinking_false(self):
        """enable_thinking=False 时注入 extra_body。"""
        meta = {"model": "test-model", "enable_thinking": False}
        kwargs = build_kwargs(meta)
        assert kwargs["extra_body"] == {"enable_thinking": False}

    def test_build_kwargs_enable_thinking_true(self):
        """enable_thinking=True 时不注入 extra_body。"""
        meta = {"model": "test-model", "enable_thinking": True}
        kwargs = build_kwargs(meta)
        assert "extra_body" not in kwargs

    def test_create_raw_client_no_api_key(self):
        """无 API Key 时 create_raw_client 返回 (None, meta)。"""
        config = make_config(api_key="")
        client, meta = create_raw_client(config)
        assert client is None
        assert meta["api_key"] == ""

    def test_create_raw_client_with_api_key(self):
        """有 API Key 时返回原始 OpenAI 客户端。"""
        config = make_config(api_key="test-key-123")
        client, meta = create_raw_client(config)
        assert client is not None
        # 原始客户端不应有 instructor 的 create 方法签名
        assert meta["api_key"] == "test-key-123"


# ═══════════════════════════════════════════════════════════════
# 2. llm_models.py Pydantic 模型测试
# ═══════════════════════════════════════════════════════════════


class TestLLMModels:
    """测试 Pydantic 模型校验。"""

    def test_critic_result_llm(self):
        """CriticResultLLM 正确解析评审结果。"""
        model = CriticResultLLM(
            overall_score=8.0,
            dimensions={
                "info_density": 8,
                "coherence": 9,
                "speaker_diversity": 7,
                "factual_grounding": 8,
                "engagement": 9,
            },
            feedback="Good script with minor improvements needed.",
            passed=True,
        )
        assert model.overall_score == 8.0
        assert model.dimensions["info_density"] == 8
        assert model.passed is True

    def test_analysis_result_llm(self):
        """AnalysisResultLLM 正确解析分析结果（含嵌套模型）。"""
        model = AnalysisResultLLM(
            summary="Test project summary",
            tech_stack=["Python", "FastAPI"],
            architecture="Layered architecture",
            key_modules=[
                KeyModuleLLM(name="API", description="REST API layer"),
                KeyModuleLLM(name="Core", description="Business logic"),
            ],
            quick_start="1. pip install\n2. python main.py",
            highlights=["Fast", "Clean"],
            use_cases=["Web API", "Microservice"],
            comparison=ComparisonLLM(
                strengths=["Fast"],
                weaknesses=["Limited docs"],
                alternatives=["Flask"],
            ),
            code_insights=CodeInsightsLLM(
                patterns=["Factory"],
                quality="Good",
                complexity="Low",
            ),
            mermaid_diagram="graph TD\n  A --> B",
            quality_score=8.5,
        )
        assert model.summary == "Test project summary"
        assert len(model.key_modules) == 2
        assert model.key_modules[0].name == "API"
        assert model.comparison.strengths == ["Fast"]
        assert model.code_insights.patterns == ["Factory"]

    def test_show_notes_llm(self):
        """ShowNotesLLM 正确解析。"""
        model = ShowNotesLLM(
            key_takeaways=["Point 1", "Point 2", "Point 3"],
            social_quotes=["Quote 1", "Quote 2"],
            summary="Episode summary text",
        )
        assert len(model.key_takeaways) == 3
        assert model.summary == "Episode summary text"

    def test_compare_result_llm(self):
        """CompareResultLLM 正确解析对比结果。"""
        model = CompareResultLLM(
            tech_overlap=[
                TechOverlapLLM(
                    projects=["repo1", "repo2"],
                    technologies=["Python"],
                )
            ],
            positioning=[
                ProjectPositioningLLM(
                    project="repo1",
                    positioning="Web framework",
                )
            ],
            verdict="Both are good choices",
        )
        assert len(model.tech_overlap) == 1
        assert model.positioning[0].project == "repo1"
        assert model.verdict == "Both are good choices"

    def test_script_llm(self):
        """ScriptLLM 正确解析脚本。"""
        model = ScriptLLM(
            title="Test Episode",
            description="Test description",
            hosts=[
                HostLLM(name="Alice", persona="Host", voice_key="host"),
                HostLLM(name="Bob", persona="Guest", voice_key="guest"),
            ],
            segments=[
                SegmentLLM(speaker="Alice", text="Hello!", emotion="excited"),
                SegmentLLM(speaker="Bob", text="Hi there!", emotion="neutral"),
            ],
        )
        assert model.title == "Test Episode"
        assert len(model.hosts) == 2
        assert model.hosts[0].voice_key == "host"
        assert len(model.segments) == 2
        assert model.segments[0].speaker == "Alice"

    def test_outline_llm(self):
        """OutlineLLM 正确解析大纲。"""
        model = OutlineLLM(
            title="Episode Outline",
            sections=[
                OutlineSectionLLM(
                    title="Introduction",
                    key_points=["Welcome", "Topic intro"],
                ),
                OutlineSectionLLM(
                    title="Deep Dive",
                    key_points=["Architecture", "Code review"],
                ),
            ],
        )
        assert model.title == "Episode Outline"
        assert len(model.sections) == 2
        assert model.sections[0].key_points == ["Welcome", "Topic intro"]

    def test_review_result_llm(self):
        """ReviewResultLLM 正确解析评审结果。"""
        model = ReviewResultLLM(
            score=8.0,
            issues=["Minor issue 1"],
            suggestions="Improve documentation",
        )
        assert model.score == 8.0
        assert len(model.issues) == 1


# ═══════════════════════════════════════════════════════════════
# 3. ScriptCritic 测试
# ═══════════════════════════════════════════════════════════════


class TestScriptCritic:
    """测试脚本评审模块（mock 模式）。"""

    def test_mock_mode_returns_pass(self):
        """无 API Key 时返回默认通过结果。"""
        config = make_config(api_key="")
        critic = ScriptCritic(config)
        script = make_script()
        repos = [make_repo()]

        result = critic.evaluate(script, repos)

        assert result["passed"] is True
        assert result["overall_score"] == 8.0
        assert "info_density" in result["dimensions"]
        assert result["dimensions"]["info_density"] == 8

    def test_mock_mode_has_all_dimensions(self):
        """mock 结果包含全部 5 个评估维度。"""
        config = make_config(api_key="")
        critic = ScriptCritic(config)
        script = make_script()
        repos = [make_repo()]

        result = critic.evaluate(script, repos)
        expected_dims = {
            "info_density",
            "coherence",
            "speaker_diversity",
            "factual_grounding",
            "engagement",
        }
        assert set(result["dimensions"].keys()) == expected_dims

    def test_build_eval_content(self):
        """_build_eval_content 正确构建评审输入。"""
        config = make_config(api_key="")
        critic = ScriptCritic(config)
        script = make_script()
        repos = [make_repo()]

        content = critic._build_eval_content(script, repos)
        assert "Test Podcast" in content
        assert "test/repo" in content
        assert "Hello everyone!" in content


# ═══════════════════════════════════════════════════════════════
# 4. ShowNotesGenerator 测试
# ═══════════════════════════════════════════════════════════════


class TestShowNotesGenerator:
    """测试 Show Notes 生成器（mock 模式 + 规则提取）。"""

    def test_mock_mode_generate(self):
        """无 API Key 时走 mock 模式生成。"""
        config = make_config(api_key="")
        gen = ShowNotesGenerator(config)
        script = make_script()
        repos = [make_repo()]
        analyses = [make_analysis()]
        chapters = [
            Chapter(title="Intro", start_time=0.0, description="Opening"),
            Chapter(title="Main", start_time=60.0, description="Main content"),
        ]

        notes = gen.generate(script, repos, analyses, chapters)

        assert notes.title == "Test Podcast"
        assert len(notes.project_links) == 1
        assert notes.project_links[0]["name"] == "test/repo"
        assert len(notes.timestamps) == 2
        assert notes.timestamps[0]["title"] == "Intro"
        assert "Python" in notes.mentioned_tech

    def test_extract_project_links(self):
        """规则提取项目链接。"""
        repos = [make_repo("a/b"), make_repo("c/d")]
        links = ShowNotesGenerator._extract_project_links(repos)
        assert len(links) == 2
        assert links[0]["name"] == "a/b"
        assert links[1]["name"] == "c/d"

    def test_chapters_to_timestamps_with_dict(self):
        """兼容 dict 格式的 chapters。"""
        chapters = [{"title": "Ch1", "start_time": 10.0, "description": "Desc"}]
        timestamps = ShowNotesGenerator._chapters_to_timestamps(chapters)
        assert len(timestamps) == 1
        assert timestamps[0]["time"] == 10.0
        assert timestamps[0]["title"] == "Ch1"

    def test_extract_mentioned_tech_dedup(self):
        """技术栈去重（大小写不敏感）。"""
        analyses = [
            {"tech_stack": ["Python", "PyTorch"]},
            {"tech_stack": ["python", "FastAPI"]},
        ]
        techs = ShowNotesGenerator._extract_mentioned_tech(analyses)
        assert "Python" in techs
        assert "python" not in techs  # 被去重
        assert "FastAPI" in techs
        assert len(techs) == 3  # Python, PyTorch, FastAPI


# ═══════════════════════════════════════════════════════════════


class TestCrossProjectComparator:
    """测试跨项目对比模块（mock 模式 + 规则计算）。"""

    def test_mock_mode_compare(self):
        """无 API Key 时走 mock 模式。"""
        config = make_config(api_key="")
        comp = CrossProjectComparator(config)
        repos = [make_repo("a/b"), make_repo("c/d")]
        analyses = [make_analysis("a/b"), make_analysis("c/d")]
        health_data = [
            RepoHealth(repo_name="a/b", commit_count_30d=100,
                       contributor_count=50),
            RepoHealth(repo_name="c/d", commit_count_30d=10,
                       contributor_count=3),
        ]

        result = comp.compare(repos, analyses, health_data)

        assert len(result.repos) == 2
        assert result.positioning_diff  # 非空
        assert result.verdict  # 非空
        assert "mock" in result.positioning_diff

    def test_compute_tech_overlap(self):
        """技术重叠计算正确。"""
        config = make_config(api_key="")
        comp = CrossProjectComparator(config)
        analyses = [
            make_analysis("a/b"),  # tech_stack=["Python", "PyTorch"]
            ProjectAnalysis(
                repo_name="c/d",
                summary="Another project",
                tech_stack=["Python", "FastAPI"],
                architecture="Layered",
            ),
        ]
        overlap = comp._compute_tech_overlap(analyses)
        # Python 出现在 2 个项目，应被标记为重叠
        python_entry = [o for o in overlap if o["technology"] == "Python"]
        assert len(python_entry) == 1
        assert python_entry[0]["count"] == 2

    def test_compute_activity_ranking(self):
        """活跃度排名正确排序。"""
        config = make_config(api_key="")
        comp = CrossProjectComparator(config)
        repos = [make_repo("a/b"), make_repo("c/d")]
        health_data = [
            {"repo_name": "a/b", "health_score": 80.0, "commit_count_30d": 50},
            {"repo_name": "c/d", "health_score": 60.0, "commit_count_30d": 30},
        ]
        ranking = comp._compute_activity_ranking(repos, health_data)
        assert ranking[0]["repo"] == "a/b"  # 健康度更高排第一
        assert ranking[0]["rank"] == 1
        assert ranking[1]["rank"] == 2


# ═══════════════════════════════════════════════════════════════
# 5. ProjectAnalyzer 测试
# ═══════════════════════════════════════════════════════════════


class TestProjectAnalyzer:
    """测试项目分析模块（mock 模式 + Pydantic 转换）。"""

    def test_mock_mode_analyze(self):
        """无 API Key 时返回 mock 分析。"""
        config = make_config(api_key="")
        analyzer = ProjectAnalyzer(config)
        repo = make_repo()

        analysis = analyzer.analyze_single(repo)

        assert analysis.repo_name == "test/repo"
        assert "mock" in analysis.summary or "mock" in analysis.architecture
        assert analysis.mermaid_diagram  # mock 也有 mermaid

    def test_llm_to_analysis_conversion(self):
        """Pydantic → dataclass 转换正确。"""
        config = make_config(api_key="")
        analyzer = ProjectAnalyzer(config)
        repo = make_repo()

        llm_result = AnalysisResultLLM(
            summary="Test summary",
            tech_stack=["Python", "FastAPI"],
            architecture="Layered design",
            key_modules=[
                KeyModuleLLM(name="API", description="API layer"),
                KeyModuleLLM(name="Core", description="Core logic"),
            ],
            quick_start="1. Install\n2. Run",
            highlights=["Fast", "Clean"],
            use_cases=["Web", "API"],
            comparison=ComparisonLLM(
                strengths=["Speed"],
                weaknesses=["Docs"],
                alternatives=["Flask"],
            ),
            code_insights=CodeInsightsLLM(
                patterns=["Factory"],
                quality="Good",
                complexity="Low",
            ),
        )

        analysis = analyzer._llm_to_analysis(llm_result, repo)
        assert analysis.repo_name == "test/repo"
        assert analysis.summary == "Test summary"
        assert analysis.tech_stack == ["Python", "FastAPI"]
        assert len(analysis.key_modules) == 2
        assert analysis.key_modules[0]["name"] == "API"
        assert "优势" in analysis.comparison
        assert "设计模式" in analysis.code_insights

    def test_strip_mermaid_fence(self):
        """_strip_mermaid_fence 正确去除代码块围栏。"""
        # 有围栏
        raw = "```mermaid\ngraph TD\n  A --> B\n```"
        result = ProjectAnalyzer._strip_mermaid_fence(raw)
        assert result == "graph TD\n  A --> B"

        # 无围栏
        raw = "graph TD\n  A --> B"
        result = ProjectAnalyzer._strip_mermaid_fence(raw)
        assert result == "graph TD\n  A --> B"


# ═══════════════════════════════════════════════════════════════
# 6. QAEngine 测试
# ═══════════════════════════════════════════════════════════════


class TestQAEngine:
    """测试问答引擎（mock 模式）。"""

    def test_mock_mode_ask(self):
        """无 API Key 时返回 mock 回答。"""
        config = make_config(api_key="")
        engine = QAEngine(config)
        analysis_data = {
            "repo_name": "test/repo",
            "summary": "A test project",
            "tech_stack": ["Python"],
        }
        answer = engine.ask("What is this project?", analysis_data)
        assert "mock" in answer.lower()
        assert "test/repo" in answer

    def test_build_context(self):
        """_build_context 正确构建上下文。"""
        config = make_config(api_key="")
        engine = QAEngine(config)
        analysis_data = {
            "repo_name": "test/repo",
            "summary": "Test summary",
            "tech_stack": ["Python", "FastAPI"],
            "architecture": "Layered",
            "key_modules": [{"name": "Core", "description": "Main module"}],
            "highlights": ["Fast"],
            "use_cases": ["Web"],
        }
        context = engine._build_context(analysis_data, "README excerpt")
        assert "test/repo" in context
        assert "Python, FastAPI" in context
        assert "Layered" in context
        assert "README 摘要" in context


# ═══════════════════════════════════════════════════════════════
# 7. ScriptGenerator 测试
# ═══════════════════════════════════════════════════════════════


class TestScriptGenerator:
    """测试脚本生成器（mock 模式）。"""

    def test_mock_mode_generate(self):
        """无 API Key 时返回 mock 脚本。"""
        config = make_config(api_key="")
        gen = ScriptGenerator(config)
        repos = [make_repo()]

        script = gen.generate(repos)

        assert script.title  # 非空标题
        assert len(script.hosts) >= 2  # 至少两个主持人
        assert len(script.segments) > 0  # 有对话片段
        assert "test/repo" in script.repo_names

    def test_mock_script_has_introduction(self):
        """mock 脚本包含开场白。"""
        config = make_config(api_key="")
        gen = ScriptGenerator(config)
        repos = [make_repo()]

        script = gen._mock_script(repos)
        first_text = script.segments[0].text
        assert "大家好" in first_text or "欢迎" in first_text

    def test_llm_to_script_conversion(self):
        """Pydantic ScriptLLM → PodcastScript dataclass 转换正确。"""
        config = make_config(api_key="")
        gen = ScriptGenerator(config)
        repos = [make_repo()]

        llm_result = ScriptLLM(
            title="Test Episode",
            description="Test description",
            hosts=[
                HostLLM(name="Alice", persona="Host", voice_key="host"),
                HostLLM(name="Bob", persona="Guest", voice_key="guest"),
            ],
            segments=[
                SegmentLLM(speaker="Alice", text="Hello!", emotion="excited"),
                SegmentLLM(speaker="Bob", text="Hi!", emotion="neutral"),
            ],
        )

        script = gen._llm_to_script(llm_result, repos)
        assert script.title == "Test Episode"
        assert len(script.hosts) == 2
        assert script.hosts[0].voice_key == "host"
        assert len(script.segments) == 2
        assert script.segments[0].speaker == "Alice"
        assert script.segments[0].voice_key == "host"

    def test_llm_to_script_empty_hosts(self):
        """空 hosts 列表时使用默认主持人。"""
        config = make_config(api_key="")
        gen = ScriptGenerator(config)
        repos = [make_repo()]

        llm_result = ScriptLLM(
            title="Test",
            description="Desc",
            hosts=[],
            segments=[
                SegmentLLM(speaker="Alice", text="Hi", emotion="neutral"),
            ],
        )

        script = gen._llm_to_script(llm_result, repos)
        assert len(script.hosts) == 2  # 默认主持人

    def test_style_addon(self):
        """风格预设返回正确的 prompt 指导。"""
        config = make_config(api_key="")
        gen = ScriptGenerator(config)
        gen.style = "casual"
        addon = gen._get_style_addon()
        assert "轻松闲聊" in addon

        gen.style = "technical"
        addon = gen._get_style_addon()
        assert "技术深度" in addon


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
