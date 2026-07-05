"""阶段 2 测试：配置访问层统一 — ConfigAccessor + config_defaults。

测试覆盖：
  1. config_defaults 常量完整性
  2. ConfigAccessor 属性式访问
  3. ConfigAccessor 向后兼容（dict 式访问）
  4. ConfigAccessor 安全默认值
  5. config_loader 使用集中常量
  6. task_manager 使用 PIPELINE_TOTAL_STAGES
  7. main.py 使用集中常量
  8. 端到端：ConfigAccessor 在 mock 流水线中工作
"""
import pytest
from pathlib import Path

from src.config_defaults import (
    LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT,
    TTS_PROVIDER, TTS_SAMPLE_RATE,
    DISCOVERY_MAX_PROJECTS, DISCOVERY_MIN_STARS,
    CRAWLER_MAX_README_CHARS, CRAWLER_TIMEOUT,
    AUDIO_TARGET_LUFS, AUDIO_OUTPUT_FORMAT,
    PODCAST_TITLE, PODCAST_STYLE, PODCAST_STYLES,
    PIPELINE_TOTAL_STAGES, PIPELINE_SEGMENTED_THRESHOLD,
    CONSOLE_WIDTH, FREE_MODEL_KEYWORDS,
    OUTPUT_EPISODES_DIR, OUTPUT_FEED_PATH,
    ENV_LLM_API_KEY, ENV_GITHUB_TOKEN,
)
from src.config_accessor import ConfigAccessor


# ════════════════════════════════════════
# 1. config_defaults 常量完整性
# ════════════════════════════════════════
class TestConfigDefaults:
    """config_defaults 常量验证。"""

    def test_llm_defaults_exist(self):
        """LLM 默认值应存在且类型正确。"""
        assert isinstance(LLM_TEMPERATURE, float)
        assert isinstance(LLM_MAX_TOKENS, int)
        assert isinstance(LLM_TIMEOUT, int)
        assert LLM_TEMPERATURE > 0
        assert LLM_MAX_TOKENS > 0

    def test_tts_defaults_exist(self):
        """TTS 默认值应存在。"""
        assert isinstance(TTS_PROVIDER, str)
        assert isinstance(TTS_SAMPLE_RATE, int)
        assert TTS_SAMPLE_RATE > 0

    def test_discovery_defaults_exist(self):
        """Discovery 默认值应存在。"""
        assert isinstance(DISCOVERY_MAX_PROJECTS, int)
        assert isinstance(DISCOVERY_MIN_STARS, int)
        assert DISCOVERY_MAX_PROJECTS > 0

    def test_pipeline_defaults_exist(self):
        """Pipeline 默认值应存在。"""
        assert isinstance(PIPELINE_TOTAL_STAGES, int)
        assert isinstance(PIPELINE_SEGMENTED_THRESHOLD, int)
        assert PIPELINE_TOTAL_STAGES > 0
        assert PIPELINE_SEGMENTED_THRESHOLD > 0

    def test_console_width_exists(self):
        """Console 宽度常量应存在。"""
        assert isinstance(CONSOLE_WIDTH, int)
        assert CONSOLE_WIDTH > 0

    def test_free_model_keywords_exist(self):
        """免费模型关键词应存在且为列表。"""
        assert isinstance(FREE_MODEL_KEYWORDS, list)
        assert len(FREE_MODEL_KEYWORDS) > 0

    def test_podcast_styles_exist(self):
        """播客风格列表应存在。"""
        assert isinstance(PODCAST_STYLES, list)
        assert "casual" in PODCAST_STYLES
        assert len(PODCAST_STYLES) >= 4

    def test_output_paths_exist(self):
        """输出路径默认值应存在。"""
        assert isinstance(OUTPUT_EPISODES_DIR, str)
        assert isinstance(OUTPUT_FEED_PATH, str)
        assert "output" in OUTPUT_EPISODES_DIR

    def test_env_var_names_exist(self):
        """环境变量名常量应存在。"""
        assert isinstance(ENV_LLM_API_KEY, str)
        assert isinstance(ENV_GITHUB_TOKEN, str)
        assert ENV_LLM_API_KEY == "LLM_API_KEY"
        assert ENV_GITHUB_TOKEN == "GITHUB_TOKEN"


# ════════════════════════════════════════
# 2. ConfigAccessor 属性式访问
# ════════════════════════════════════════
class TestConfigAccessorProperties:
    """ConfigAccessor 属性式访问验证。"""

    def test_llm_properties(self):
        """LLM 属性应返回配置值。"""
        config = {
            "llm": {
                "model": "test-model",
                "base_url": "https://test.api/v1",
                "temperature": 0.5,
                "max_tokens": 2000,
                "timeout": 60,
                "enable_thinking": True,
            }
        }
        cfg = ConfigAccessor(config)
        assert cfg.llm_model == "test-model"
        assert cfg.llm_base_url == "https://test.api/v1"
        assert cfg.llm_temperature == 0.5
        assert cfg.llm_max_tokens == 2000
        assert cfg.llm_timeout == 60
        assert cfg.llm_enable_thinking is True

    def test_llm_properties_use_defaults(self):
        """缺失配置时应使用默认值。"""
        cfg = ConfigAccessor({})
        assert cfg.llm_model == "Qwen/Qwen3.5-9B"
        assert cfg.llm_temperature == 0.8
        assert cfg.llm_max_tokens == 4000
        assert cfg.llm_timeout == 120

    def test_tts_properties(self):
        """TTS 属性应返回配置值。"""
        config = {
            "tts": {
                "provider": "dashscope",
                "model": "test-tts",
                "sample_rate": 48000,
            }
        }
        cfg = ConfigAccessor(config)
        assert cfg.tts_provider == "dashscope"
        assert cfg.tts_model == "test-tts"
        assert cfg.tts_sample_rate == 48000

    def test_tts_properties_use_defaults(self):
        """缺失 TTS 配置时应使用默认值。"""
        cfg = ConfigAccessor({})
        assert cfg.tts_provider == "siliconflow"
        assert cfg.tts_sample_rate == 24000

    def test_discovery_properties(self):
        """Discovery 属性应返回配置值。"""
        config = {
            "discovery": {
                "max_projects": 5,
                "min_stars": 200,
            }
        }
        cfg = ConfigAccessor(config)
        assert cfg.discovery_max_projects == 5
        assert cfg.discovery_min_stars == 200

    def test_api_key_access(self):
        """API Key 应通过 get_api_key 方法访问。"""
        config = {
            "api_keys": {
                "llm": "test-llm-key",
                "tts": "test-tts-key",
                "github": "test-github-token",
            }
        }
        cfg = ConfigAccessor(config)
        assert cfg.get_api_key("llm") == "test-llm-key"
        assert cfg.get_api_key("tts") == "test-tts-key"
        assert cfg.get_api_key("github") == "test-github-token"
        assert cfg.llm_api_key == "test-llm-key"
        assert cfg.tts_api_key == "test-tts-key"
        assert cfg.github_api_key == "test-github-token"

    def test_api_key_empty_when_missing(self):
        """缺失的 API Key 应返回空字符串。"""
        cfg = ConfigAccessor({})
        assert cfg.get_api_key("llm") == ""
        assert cfg.get_api_key("nonexistent") == ""

    def test_project_root(self):
        """project_root 应正确返回。"""
        cfg = ConfigAccessor({"project_root": "/test/path"})
        assert cfg.project_root == "/test/path"

    def test_project_root_default(self):
        """缺失 project_root 应返回 '.'。"""
        cfg = ConfigAccessor({})
        assert cfg.project_root == "."

    def test_is_free_model(self):
        """is_free_model 应正确判断免费模型。"""
        cfg_free = ConfigAccessor({"llm": {"model": "Qwen/Qwen3.5-9B"}})
        assert cfg_free.is_free_model is True

        cfg_paid = ConfigAccessor({"llm": {"model": "deepseek-ai/DeepSeek-V4"}})
        assert cfg_paid.is_free_model is False

    def test_mock_mode(self):
        """mock_mode 应正确返回。"""
        cfg = ConfigAccessor({"_mock_mode": True})
        assert cfg.mock_mode is True

        cfg2 = ConfigAccessor({})
        assert cfg2.mock_mode is False

    def test_longform(self):
        """longform 应正确返回。"""
        cfg = ConfigAccessor({"longform": True})
        assert cfg.longform is True

    def test_podcast_style(self):
        """podcast_style 应正确返回。"""
        cfg = ConfigAccessor({"podcast_style": "technical"})
        assert cfg.podcast_style == "technical"

    def test_podcast_style_default(self):
        """缺失 podcast_style 应返回默认值。"""
        cfg = ConfigAccessor({})
        assert cfg.podcast_style == "casual"


# ════════════════════════════════════════
# 3. ConfigAccessor 向后兼容
# ════════════════════════════════════════
class TestConfigAccessorCompat:
    """ConfigAccessor 向后兼容验证。"""

    def test_getitem_access(self):
        """应支持 config["key"] 式访问。"""
        config = {"llm": {"model": "test"}}
        cfg = ConfigAccessor(config)
        assert cfg["llm"]["model"] == "test"

    def test_get_method(self):
        """应支持 config.get("key", default) 式访问。"""
        cfg = ConfigAccessor({"a": 1})
        assert cfg.get("a") == 1
        assert cfg.get("b", "default") == "default"

    def test_contains(self):
        """应支持 'key' in config。"""
        cfg = ConfigAccessor({"a": 1})
        assert "a" in cfg
        assert "b" not in cfg

    def test_to_dict(self):
        """to_dict 应返回原始 dict。"""
        original = {"llm": {"model": "test"}, "api_keys": {"llm": "key"}}
        cfg = ConfigAccessor(original)
        assert cfg.to_dict() == original

    def test_raw_property(self):
        """raw 属性应返回原始 dict 引用。"""
        original = {"test": True}
        cfg = ConfigAccessor(original)
        assert cfg.raw is original

    def test_section_returns_empty_dict_for_missing(self):
        """section() 对缺失段应返回空 dict 而非 KeyError。"""
        cfg = ConfigAccessor({})
        assert cfg.section("nonexistent") == {}

    def test_section_returns_empty_dict_for_none(self):
        """section() 对 None 值应返回空 dict。"""
        cfg = ConfigAccessor({"llm": None})
        assert cfg.section("llm") == {}


# ════════════════════════════════════════
# 4. 安全默认值
# ════════════════════════════════════════
class TestConfigAccessorSafety:
    """ConfigAccessor 安全性验证。"""

    def test_no_keyerror_on_any_property(self):
        """空配置下访问任何属性都不应抛 KeyError。"""
        cfg = ConfigAccessor({})
        # 逐个访问所有属性，不应抛异常
        _ = cfg.llm_model
        _ = cfg.llm_base_url
        _ = cfg.llm_temperature
        _ = cfg.llm_max_tokens
        _ = cfg.llm_timeout
        _ = cfg.llm_enable_thinking
        _ = cfg.llm_api_key
        _ = cfg.tts_provider
        _ = cfg.tts_base_url
        _ = cfg.tts_model
        _ = cfg.tts_sample_rate
        _ = cfg.tts_api_key
        _ = cfg.discovery_max_projects
        _ = cfg.discovery_min_stars
        _ = cfg.github_api_key
        _ = cfg.crawler_max_readme_chars
        _ = cfg.crawler_timeout
        _ = cfg.audio_target_lufs
        _ = cfg.audio_output_format
        _ = cfg.project_root
        _ = cfg.podcast_title
        _ = cfg.podcast_style
        _ = cfg.longform
        _ = cfg.mock_mode

    def test_none_config(self):
        """传入 None 应安全处理。"""
        cfg = ConfigAccessor(None)
        assert cfg.llm_model == "Qwen/Qwen3.5-9B"
        assert cfg.project_root == "."

    def test_empty_config(self):
        """空 dict 应安全处理。"""
        cfg = ConfigAccessor({})
        assert cfg.llm_model != ""
        assert cfg.tts_provider != ""


# ════════════════════════════════════════
# 5. config_loader 使用集中常量
# ════════════════════════════════════════
class TestConfigLoaderUsesDefaults:
    """验证 config_loader.py 使用 config_defaults 常量。"""

    def test_config_loader_imports_defaults(self):
        """config_loader 应导入 config_defaults。"""
        content = Path(__file__).parent.parent.joinpath("src/config_loader.py").read_text("utf-8")
        assert "config_defaults" in content

    def test_config_loader_uses_env_constants(self):
        """config_loader 应使用环境变量名常量而非字面量。"""
        content = Path(__file__).parent.parent.joinpath("src/config_loader.py").read_text("utf-8")
        # 不应直接使用字面量环境变量名
        assert 'os.getenv("SILICONFLOW_API_KEY"' not in content
        assert 'os.getenv("LLM_API_KEY"' not in content
        # 应使用常量
        assert "D.ENV_SILICONFLOW_API_KEY" in content
        assert "D.ENV_LLM_API_KEY" in content

    def test_config_loader_uses_podcast_title_default(self):
        """config_loader 应使用 PODCAST_TITLE 常量。"""
        content = Path(__file__).parent.parent.joinpath("src/config_loader.py").read_text("utf-8")
        assert "D.PODCAST_TITLE" in content


# ════════════════════════════════════════
# 6. task_manager 使用 PIPELINE_TOTAL_STAGES
# ════════════════════════════════════════
class TestTaskManagerUsesConstants:
    """验证 task_manager.py 使用集中常量。"""

    def test_task_manager_imports_total_stages(self):
        """task_manager 应导入 PIPELINE_TOTAL_STAGES。"""
        content = Path(__file__).parent.parent.joinpath("dashboard/task_manager.py").read_text("utf-8")
        assert "PIPELINE_TOTAL_STAGES" in content

    def test_task_manager_no_hardcoded_9(self):
        """task_manager 不应硬编码 total_stages = 9。"""
        content = Path(__file__).parent.parent.joinpath("dashboard/task_manager.py").read_text("utf-8")
        # 不应有硬编码的 9（排除注释和字符串中的 9）
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # 不应直接写 total_stages = 9
            if "total_stages = 9" in stripped and "_TOTAL_STAGES" not in stripped:
                pytest.fail(f"task_manager.py:{i} 硬编码 total_stages = 9: {stripped}")


# ════════════════════════════════════════
# 7. main.py 使用集中常量
# ════════════════════════════════════════
class TestMainUsesConstants:
    """验证 main.py 使用集中常量。"""

    def test_main_imports_config_defaults(self):
        """main.py 应导入 config_defaults。"""
        content = Path(__file__).parent.parent.joinpath("main.py").read_text("utf-8")
        assert "config_defaults" in content

    def test_main_uses_console_width(self):
        """main.py 应使用 CONSOLE_WIDTH 常量。"""
        content = Path(__file__).parent.parent.joinpath("main.py").read_text("utf-8")
        assert "CONSOLE_WIDTH" in content
        assert 'Console(width=200)' not in content

    def test_main_uses_free_model_keywords(self):
        """main.py 应使用 FREE_MODEL_KEYWORDS 常量。"""
        content = Path(__file__).parent.parent.joinpath("main.py").read_text("utf-8")
        assert "FREE_MODEL_KEYWORDS" in content
        # 不应硬编码关键词列表
        assert '"9B", "4B", "7B"' not in content

    def test_main_uses_podcast_styles(self):
        """main.py 应使用 PODCAST_STYLES 常量。"""
        content = Path(__file__).parent.parent.joinpath("main.py").read_text("utf-8")
        assert "PODCAST_STYLES" in content
        assert '"casual", "technical", "debate", "interview"' not in content

    def test_main_uses_segmented_threshold(self):
        """流水线应使用 PIPELINE_SEGMENTED_THRESHOLD 常量（现位于 pipeline/stages.py）。"""
        # Stage 4 重构后，阈值逻辑从 main.py 移至 src/pipeline/stages.py
        stages_content = Path(__file__).parent.parent.joinpath("src/pipeline/stages.py").read_text("utf-8")
        assert "PIPELINE_SEGMENTED_THRESHOLD" in stages_content
        # main.py 不应硬编码阈值 3
        main_content = Path(__file__).parent.parent.joinpath("main.py").read_text("utf-8")
        assert "len(repos) >= 3" not in main_content


# ════════════════════════════════════════
# 8. llm_client 使用集中常量
# ════════════════════════════════════════
class TestLLMClientUsesDefaults:
    """验证 llm_client.py 使用 config_defaults 常量。"""

    def test_llm_client_imports_defaults(self):
        """llm_client 应导入 config_defaults。"""
        content = Path(__file__).parent.parent.joinpath("src/llm_client.py").read_text("utf-8")
        assert "config_defaults" in content

    def test_llm_client_uses_timeout_default(self):
        """llm_client 应使用 LLM_TIMEOUT 常量。"""
        content = Path(__file__).parent.parent.joinpath("src/llm_client.py").read_text("utf-8")
        assert "D.LLM_TIMEOUT" in content

    def test_llm_client_uses_model_default(self):
        """llm_client 应使用 LLM_MODEL 常量。"""
        content = Path(__file__).parent.parent.joinpath("src/llm_client.py").read_text("utf-8")
        assert "D.LLM_MODEL" in content


# ════════════════════════════════════════
# 9. 端到端：ConfigAccessor 在 mock 流水线中工作
# ════════════════════════════════════════
class TestEndToEndConfigAccessor:
    """端到端 ConfigAccessor 集成验证。"""

    def test_config_accessor_with_loaded_config(self):
        """ConfigAccessor 应能包装 load_config 的输出。"""
        from src.config_loader import load_config
        from tests.conftest import make_config

        raw_config = make_config(mock_mode=True)
        cfg = ConfigAccessor(raw_config)

        # 应能访问所有属性
        assert cfg.llm_model != ""
        assert cfg.tts_provider != ""
        assert cfg.project_root != ""
        assert cfg.mock_mode is True

    def test_config_accessor_backward_compat_with_modules(self):
        """ConfigAccessor 应能传给现有模块而不报错。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        raw_config = make_config(mock_mode=True)
        cfg = ConfigAccessor(raw_config)

        # DeepExtractor 接收 dict，ConfigAccessor 的 to_dict() 应能转换
        extractor = DeepExtractor(cfg.to_dict())
        repo = make_repo("test/config-accessor")
        result = extractor.extract(repo)
        assert result != ""
