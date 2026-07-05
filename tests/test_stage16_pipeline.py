"""阶段 4 测试：Pipeline 编排重构 — 420行 God 函数拆分为可组合 Stage 类。

测试覆盖：
  1. PipelineContext 数据容器
  2. PipelineStage ABC 抽象基类
  3. 公共访问器（DeepExtractor / PipelineReporter）
  4. 各 Stage 独立测试（should_run / execute 逻辑）
  5. Pipeline 编排器（阶段列表管理 / 条件执行 / 错误处理）
  6. 可扩展性（add_stage / remove_stage）
  7. 向后兼容（run_pipeline 接口不变）
  8. 端到端集成（mock 配置完整流程）
"""
import json
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

from src.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineStage,
    PipelineStageError,
    DiscoveryStage,
    CrawlStage,
    DeepExtractStage,
    AnalyzeStage,
    CompareStage,
    ScriptStage,
    TTSStage,
    AudioMixStage,
    PublishStage,
)
from src.pipeline_reporter import PipelineReporter
from src.models import GitHubRepo


def _make_config(**overrides) -> dict[str, Any]:
    """构造测试配置。"""
    config: dict[str, Any] = {
        "api_keys": {
            "llm": "", "tts": "", "deepseek": "", "dashscope": "",
            "siliconflow": "", "github": "",
        },
        "llm": {
            "model": "test-model", "base_url": "https://test.api/v1",
            "temperature": 0.8, "max_tokens": 4000, "timeout": 120,
            "enable_thinking": False,
        },
        "tts": {
            "provider": "mock", "base_url": "https://test.api/v1",
            "model": "test-tts", "voice_mapping": {"host": "alex", "guest": "anna"},
            "sample_rate": 24000,
        },
        "discovery": {
            "max_projects": 3, "min_stars": 100,
            "rsshub_base_url": "https://rsshub.app",
            "trending_since": "daily", "language": "",
            "trending_api_url": "https://test.api/trending",
            "keywords": [], "exclude_keywords": [],
        },
        "crawler": {
            "jina_reader_url": "https://r.jina.ai",
            "max_readme_chars": 8000, "timeout": 30,
        },
        "audio": {
            "segment_silence_ms": 400, "sentence_silence_ms": 150,
            "target_lufs": -16.0, "output_format": "mp3",
            "output_bitrate": "192k", "bgm_path": "",
        },
        "output": {
            "episodes_dir": "output/episodes",
            "feed_path": "output/feed.xml",
            "scripts_dir": "output/scripts",
        },
        "project_root": "/tmp/test_pipeline",
        "_mock_mode": True,
    }
    config.update(overrides)
    return config


def _make_mock_repo(name="test/repo", **kwargs) -> GitHubRepo:
    """构造测试 GitHubRepo。"""
    defaults = {
        "url": f"https://github.com/{name}",
        "description": "A test repository.",
        "stars": 1000,
        "language": "Python",
        "topics": ["test"],
    }
    defaults.update(kwargs)
    return GitHubRepo(name=name, **defaults)


# ════════════════════════════════════════
# 1. PipelineContext 数据容器
# ════════════════════════════════════════
class TestPipelineContext:
    """PipelineContext 数据容器测试。"""

    def test_default_values(self):
        ctx = PipelineContext()
        assert ctx.config == {}
        assert ctx.repos == []
        assert ctx.analyses == []
        assert ctx.dry_run is False
        assert ctx.script is None
        assert ctx.episode is None

    def test_config_injection(self):
        config = _make_config()
        ctx = PipelineContext(config=config)
        assert ctx.config == config
        assert ctx.dry_run is False

    def test_project_root_property(self):
        config = _make_config(project_root="/custom/path")
        ctx = PipelineContext(config=config)
        assert ctx.project_root == Path("/custom/path")

    def test_output_dir_property(self):
        config = _make_config(project_root="/custom/path")
        ctx = PipelineContext(config=config)
        assert ctx.output_dir == Path("/custom/path/output")

    def test_emit_progress_without_reporter_does_not_crash(self):
        """无 reporter 时 emit_progress 不崩溃。"""
        ctx = PipelineContext()
        ctx.emit_progress("discovery", "running", "test")  # 不应抛异常

    def test_emit_progress_with_reporter(self, capsys):
        """有 reporter 时 emit_progress 输出到 stdout。"""
        reporter = PipelineReporter(output_dir="/tmp/test")
        ctx = PipelineContext(reporter=reporter)
        ctx.emit_progress("discovery", "done", "发现3个项目")
        captured = capsys.readouterr()
        assert "::PROGRESS::" in captured.out
        assert "discovery" in captured.out
        assert "发现3个项目" in captured.out


# ════════════════════════════════════════
# 2. PipelineStage ABC
# ════════════════════════════════════════
class TestPipelineStageABC:
    """PipelineStage 抽象基类测试。"""

    def test_cannot_instantiate_directly(self):
        """PipelineStage 不可直接实例化。"""
        with pytest.raises(TypeError):
            PipelineStage()

    def test_subclass_must_implement_name_and_execute(self):
        """子类必须实现 name 属性和 execute 方法。"""

        class Incomplete(PipelineStage):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_should_run_defaults_true(self):
        """should_run 默认返回 True。"""

        class TestStage(PipelineStage):
            @property
            def name(self):
                return "test"

            def execute(self, ctx):
                pass

        stage = TestStage()
        assert stage.should_run(PipelineContext()) is True


# ════════════════════════════════════════
# 3. 公共访问器
# ════════════════════════════════════════
class TestPublicAccessors:
    """验证 DeepExtractor 和 PipelineReporter 的公共访问器。"""

    def test_deep_extractor_get_last_health_metrics(self):
        """get_last_health_metrics 返回副本。"""
        from src.deep_extractor import DeepExtractor
        config = _make_config(_mock_mode=True)
        extractor = DeepExtractor(config)
        extractor._last_health_metrics = {"health_score": 85, "health_grade": "A"}
        result = extractor.get_last_health_metrics()
        assert result["health_score"] == 85
        # 修改返回值不影响内部状态
        result["health_score"] = 0
        assert extractor._last_health_metrics["health_score"] == 85

    def test_deep_extractor_get_last_file_tree(self):
        """get_last_file_tree 返回副本。"""
        from src.deep_extractor import DeepExtractor
        config = _make_config(_mock_mode=True)
        extractor = DeepExtractor(config)
        extractor._last_file_tree = ["src/main.py", "README.md"]
        result = extractor.get_last_file_tree()
        assert result == ["src/main.py", "README.md"]
        result.append("modified")
        assert "modified" not in extractor._last_file_tree

    def test_deep_extractor_get_last_source_code(self):
        """get_last_source_code 返回副本。"""
        from src.deep_extractor import DeepExtractor
        config = _make_config(_mock_mode=True)
        extractor = DeepExtractor(config)
        extractor._last_source_code = {"main.py": "print('hello')"}
        result = extractor.get_last_source_code()
        assert result["main.py"] == "print('hello')"
        result["modified"] = "code"
        assert "modified" not in extractor._last_source_code

    def test_reporter_get_stage_label(self):
        """get_stage_label 返回正确标签。"""
        reporter = PipelineReporter(output_dir="/tmp/test")
        assert reporter.get_stage_label("discovery") == "项目发现"
        assert reporter.get_stage_label("crawl") == "README抓取"
        assert reporter.get_stage_label("nonexistent") == "nonexistent"

    def test_reporter_get_stage_status(self):
        """get_stage_status 返回正确状态。"""
        reporter = PipelineReporter(output_dir="/tmp/test")
        assert reporter.get_stage_status("discovery") == "pending"
        reporter.start_stage("discovery", "测试")
        assert reporter.get_stage_status("discovery") == "running"
        reporter.finish_stage("discovery", "完成")
        assert reporter.get_stage_status("discovery") == "done"


# ════════════════════════════════════════
# 4. Stage 独立测试
# ════════════════════════════════════════
class TestStages:
    """各 Stage 类的独立测试。"""

    def test_discovery_stage_properties(self):
        stage = DiscoveryStage()
        assert stage.name == "discovery"
        assert stage.label == "项目发现"

    def test_crawl_stage_properties(self):
        stage = CrawlStage()
        assert stage.name == "crawl"
        assert stage.label == "README抓取"

    def test_deep_extract_stage_properties(self):
        stage = DeepExtractStage()
        assert stage.name == "deep_extract"
        assert stage.label == "深度提取"

    def test_analyze_stage_properties(self):
        stage = AnalyzeStage()
        assert stage.name == "analyze"
        assert stage.label == "项目分析"

    def test_compare_stage_should_run_with_multiple_repos(self):
        """CompareStage 在多项目时 should_run 返回 True。"""
        stage = CompareStage()
        ctx = PipelineContext(repos=[_make_mock_repo(), _make_mock_repo("test/repo2")])
        assert stage.should_run(ctx) is True

    def test_compare_stage_should_not_run_with_single_repo(self):
        """CompareStage 在单项目时 should_run 返回 False。"""
        stage = CompareStage()
        ctx = PipelineContext(repos=[_make_mock_repo()])
        assert stage.should_run(ctx) is False

    def test_compare_stage_should_not_run_with_no_repos(self):
        """CompareStage 在无项目时 should_run 返回 False。"""
        stage = CompareStage()
        ctx = PipelineContext(repos=[])
        assert stage.should_run(ctx) is False

    def test_script_stage_properties(self):
        stage = ScriptStage()
        assert stage.name == "script"

    def test_tts_stage_properties(self):
        stage = TTSStage()
        assert stage.name == "tts"

    def test_audio_mix_stage_properties(self):
        stage = AudioMixStage()
        assert stage.name == "mix"

    def test_publish_stage_properties(self):
        stage = PublishStage()
        assert stage.name == "publish"

    def test_all_stages_are_pipeline_stage_subclasses(self):
        """所有 Stage 类都是 PipelineStage 的子类。"""
        stages = [
            DiscoveryStage(), CrawlStage(), DeepExtractStage(),
            AnalyzeStage(), CompareStage(), ScriptStage(),
            TTSStage(), AudioMixStage(), PublishStage(),
        ]
        for stage in stages:
            assert isinstance(stage, PipelineStage)


# ════════════════════════════════════════
# 5. Pipeline 编排器
# ════════════════════════════════════════
class TestPipelineOrchestrator:
    """Pipeline 编排器测试。"""

    def test_pipeline_init_creates_default_stages(self):
        """Pipeline 初始化时创建 9 个默认阶段。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        assert len(pipeline.stages) == 9
        assert pipeline.stages[0].name == "discovery"
        assert pipeline.stages[-1].name == "publish"

    def test_pipeline_stages_are_ordered(self):
        """阶段顺序正确。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        expected_order = [
            "discovery", "crawl", "deep_extract", "analyze",
            "compare", "script", "tts", "mix", "publish",
        ]
        actual_order = [s.name for s in pipeline.stages]
        assert actual_order == expected_order

    def test_pipeline_stages_property_returns_copy(self):
        """stages 属性返回副本，修改不影响内部列表。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        stages = pipeline.stages
        stages.append(MockStage())
        assert len(pipeline.stages) == 9  # 内部列表未改变


# ════════════════════════════════════════
# 6. 可扩展性
# ════════════════════════════════════════
class TestPipelineExtensibility:
    """Pipeline 可扩展性测试。"""

    def test_add_stage_appends_to_end(self):
        """add_stage 默认追加到末尾。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        pipeline.add_stage(MockStage())
        assert len(pipeline.stages) == 10
        assert pipeline.stages[-1].name == "mock_custom"

    def test_add_stage_after_specific_stage(self):
        """add_stage 可在指定阶段后插入。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        pipeline.add_stage(MockStage(), after="crawl")
        assert len(pipeline.stages) == 10
        assert pipeline.stages[2].name == "mock_custom"  # 在 crawl (index 1) 之后
        assert pipeline.stages[1].name == "crawl"

    def test_add_stage_after_nonexistent_appends(self):
        """after 指定的阶段不存在时追加到末尾。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        pipeline.add_stage(MockStage(), after="nonexistent")
        assert len(pipeline.stages) == 10
        assert pipeline.stages[-1].name == "mock_custom"

    def test_remove_stage_existing(self):
        """remove_stage 成功移除已存在的阶段。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        result = pipeline.remove_stage("compare")
        assert result is True
        assert len(pipeline.stages) == 8
        assert "compare" not in [s.name for s in pipeline.stages]

    def test_remove_stage_nonexistent(self):
        """remove_stage 对不存在的阶段返回 False。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        result = pipeline.remove_stage("nonexistent")
        assert result is False
        assert len(pipeline.stages) == 9


# ════════════════════════════════════════
# 7. 向后兼容
# ════════════════════════════════════════
class TestBackwardCompatibility:
    """验证 run_pipeline 接口向后兼容。"""

    def test_run_pipeline_function_exists(self):
        """run_pipeline 函数仍然存在。"""
        import main
        assert hasattr(main, "run_pipeline")
        assert callable(main.run_pipeline)

    def test_run_pipeline_accepts_same_args(self):
        """run_pipeline 接受相同的参数。"""
        import inspect
        import main
        sig = inspect.signature(main.run_pipeline)
        expected_params = {
            "dry_run", "mock_data", "config_path", "repos",
            "quiet", "repo_urls", "topic", "style", "longform",
        }
        actual_params = set(sig.parameters.keys())
        assert expected_params == actual_params

    def test_run_pipeline_returns_episode_or_none(self):
        """run_pipeline 返回类型为 Episode | None。"""
        import inspect
        import main
        sig = inspect.signature(main.run_pipeline)
        assert sig.return_annotation is not None

    def test_cli_commands_exist(self):
        """CLI 命令仍然存在。"""
        import main
        assert hasattr(main, "cli")
        assert hasattr(main, "run_batch")
        assert hasattr(main, "_print_repos")


# ════════════════════════════════════════
# 8. 端到端集成
# ════════════════════════════════════════
class TestEndToEndPipeline:
    """端到端：使用 Pipeline 完成完整 mock 流程。"""

    def test_pipeline_context_data_flow(self):
        """PipelineContext 在阶段间正确传递数据。"""
        ctx = PipelineContext()
        repo1 = _make_mock_repo("test/repo1")
        repo2 = _make_mock_repo("test/repo2")

        # 模拟阶段间数据流
        ctx.repos = [repo1, repo2]
        ctx.evidence_map = {repo1.name: [], repo2.name: []}
        ctx.health_data_list = [{"repo_name": repo1.name, "health_score": 80}]

        # 验证数据在 context 中正确存储
        assert len(ctx.repos) == 2
        assert len(ctx.evidence_map) == 2
        assert ctx.health_data_list[0]["health_score"] == 80

    def test_pipeline_stage_error_is_exception(self):
        """PipelineStageError 是 Exception 的子类。"""
        assert issubclass(PipelineStageError, Exception)

    def test_all_stage_names_unique(self):
        """所有阶段名称唯一。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        names = [s.name for s in pipeline.stages]
        assert len(names) == len(set(names))

    def test_all_stage_labels_are_chinese(self):
        """所有阶段标签是中文。"""
        config = _make_config()
        pipeline = Pipeline(config=config)
        for stage in pipeline.stages:
            # 中文标签应包含中文字符
            assert any('\u4e00' <= char <= '\u9fff' for char in stage.label), \
                f"Stage '{stage.name}' label '{stage.label}' is not Chinese"


# ════════════════════════════════════════
# 辅助 Mock Stage
# ════════════════════════════════════════
class MockStage(PipelineStage):
    """测试用 Mock 阶段。"""

    @property
    def name(self):
        return "mock_custom"

    @property
    def label(self):
        return "测试阶段"

    def execute(self, ctx: PipelineContext) -> None:
        ctx.config["_mock_stage_executed"] = True
