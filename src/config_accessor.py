"""配置访问器 — 统一配置访问模式，消除 ad-hoc dict 访问。

设计原则（第一性原理）：
  1. 一致性：所有配置通过同一个对象访问，使用统一的方法签名
  2. 安全性：所有访问提供默认值，永不抛 KeyError
  3. 类型安全：属性返回的类型明确，IDE 可推断
  4. 向后兼容：支持 __getitem__ 和 get()，兼容现有 dict 式代码
  5. 单一职责：仅负责配置读取，不负责加载（加载仍由 config_loader 完成）

使用方式：
    from src.config_accessor import ConfigAccessor
    cfg = ConfigAccessor(config_dict)
    llm_model = cfg.llm_model        # 属性式访问
    api_key = cfg.get_api_key("llm") # 方法式访问
    raw = cfg["llm"]["model"]        # dict 式访问（向后兼容）
"""
from __future__ import annotations

from typing import Any

from . import config_defaults as D


class ConfigAccessor:
    """配置访问器：包装原始 dict，提供类型安全的属性式访问。

    所有属性均返回配置值或默认值，永不抛 KeyError。
    同时支持 dict 式访问（__getitem__ / get / __contains__）以保持向后兼容。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config: dict[str, Any] = config or {}

    # ── 向后兼容：dict 式访问 ──

    def __getitem__(self, key: str) -> Any:
        return self._config[key]

    def __contains__(self, key: str) -> bool:
        return key in self._config

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """返回原始 dict（用于需要传给旧代码的场景）。"""
        return self._config

    @property
    def raw(self) -> dict[str, Any]:
        """返回原始 dict 的引用。"""
        return self._config

    # ════════════════════════════════════════
    # 通用访问方法
    # ════════════════════════════════════════

    def section(self, name: str) -> dict[str, Any]:
        """获取配置段（如 'llm'、'tts'），返回空 dict 而非 KeyError。"""
        return self._config.get(name, {}) or {}

    def get_api_key(self, name: str) -> str:
        """获取 API Key，支持 fallback 链。

        Args:
            name: 'llm' / 'tts' / 'github' / 'deepseek' / 'dashscope' / 'siliconflow'

        Returns:
            API Key 字符串，未配置则返回空字符串。
        """
        api_keys = self._config.get("api_keys", {}) or {}
        return api_keys.get(name, "")

    # ════════════════════════════════════════
    # LLM 配置属性
    # ════════════════════════════════════════

    @property
    def llm_section(self) -> dict[str, Any]:
        return self.section("llm")

    @property
    def llm_base_url(self) -> str:
        return self.llm_section.get("base_url", D.LLM_BASE_URL)

    @property
    def llm_model(self) -> str:
        return self.llm_section.get("model", D.LLM_MODEL)

    @property
    def llm_enable_thinking(self) -> bool:
        return self.llm_section.get("enable_thinking", D.LLM_ENABLE_THINKING)

    @property
    def llm_temperature(self) -> float:
        return self.llm_section.get("temperature", D.LLM_TEMPERATURE)

    @property
    def llm_max_tokens(self) -> int:
        return self.llm_section.get("max_tokens", D.LLM_MAX_TOKENS)

    @property
    def llm_timeout(self) -> int:
        return self.llm_section.get("timeout", D.LLM_TIMEOUT)

    @property
    def llm_api_key(self) -> str:
        return self.get_api_key("llm")

    @property
    def is_free_model(self) -> bool:
        """当前模型是否为免费模型。"""
        model = self.llm_model.lower()
        return any(kw.lower() in model for kw in D.FREE_MODEL_KEYWORDS)

    # ════════════════════════════════════════
    # TTS 配置属性
    # ════════════════════════════════════════

    @property
    def tts_section(self) -> dict[str, Any]:
        return self.section("tts")

    @property
    def tts_provider(self) -> str:
        return self.tts_section.get("provider", D.TTS_PROVIDER)

    @property
    def tts_base_url(self) -> str:
        return self.tts_section.get("base_url", D.TTS_BASE_URL)

    @property
    def tts_model(self) -> str:
        return self.tts_section.get("model", D.TTS_MODEL)

    @property
    def tts_response_format(self) -> str:
        return self.tts_section.get("response_format", D.TTS_RESPONSE_FORMAT)

    @property
    def tts_sample_rate(self) -> int:
        return self.tts_section.get("sample_rate", D.TTS_SAMPLE_RATE)

    @property
    def tts_voice_mapping(self) -> dict[str, str]:
        return self.tts_section.get("voice_mapping", D.TTS_VOICE_MAPPING)

    @property
    def tts_api_key(self) -> str:
        return self.get_api_key("tts")

    # ════════════════════════════════════════
    # Discovery 配置属性
    # ════════════════════════════════════════

    @property
    def discovery_section(self) -> dict[str, Any]:
        return self.section("discovery")

    @property
    def discovery_max_projects(self) -> int:
        return self.discovery_section.get("max_projects", D.DISCOVERY_MAX_PROJECTS)

    @property
    def discovery_min_stars(self) -> int:
        return self.discovery_section.get("min_stars", D.DISCOVERY_MIN_STARS)

    @property
    def discovery_rsshub_url(self) -> str:
        return self.discovery_section.get("rsshub_base_url", D.DISCOVERY_RSSHUB_BASE_URL)

    @property
    def github_api_key(self) -> str:
        return self.get_api_key("github")

    # ════════════════════════════════════════
    # Crawler 配置属性
    # ════════════════════════════════════════

    @property
    def crawler_section(self) -> dict[str, Any]:
        return self.section("crawler")

    @property
    def crawler_max_readme_chars(self) -> int:
        return self.crawler_section.get("max_readme_chars", D.CRAWLER_MAX_README_CHARS)

    @property
    def crawler_timeout(self) -> int:
        return self.crawler_section.get("timeout", D.CRAWLER_TIMEOUT)

    # ════════════════════════════════════════
    # Audio 配置属性
    # ════════════════════════════════════════

    @property
    def audio_section(self) -> dict[str, Any]:
        return self.section("audio")

    @property
    def audio_target_lufs(self) -> float:
        return self.audio_section.get("target_lufs", D.AUDIO_TARGET_LUFS)

    @property
    def audio_output_format(self) -> str:
        return self.audio_section.get("output_format", D.AUDIO_OUTPUT_FORMAT)

    # ════════════════════════════════════════
    # Publish 配置属性
    # ════════════════════════════════════════

    @property
    def publish_section(self) -> dict[str, Any]:
        return self.section("publish")

    # ════════════════════════════════════════
    # Output 配置属性
    # ════════════════════════════════════════

    @property
    def output_section(self) -> dict[str, Any]:
        return self.section("output")

    @property
    def project_root(self) -> str:
        return self._config.get("project_root", ".")

    @property
    def episodes_dir(self) -> str:
        return self.output_section.get("episodes_dir", D.OUTPUT_EPISODES_DIR)

    @property
    def feed_path(self) -> str:
        return self.output_section.get("feed_path", D.OUTPUT_FEED_PATH)

    @property
    def scripts_dir(self) -> str:
        return self.output_section.get("scripts_dir", D.OUTPUT_SCRIPTS_DIR)

    # ════════════════════════════════════════
    # Podcast 元信息属性
    # ════════════════════════════════════════

    @property
    def podcast_meta(self) -> dict[str, Any]:
        return self._config.get("podcast_meta", {})

    @property
    def podcast_title(self) -> str:
        return self.podcast_meta.get("title", D.PODCAST_TITLE)

    @property
    def podcast_style(self) -> str:
        return self._config.get("podcast_style", D.PODCAST_STYLE)

    @property
    def longform(self) -> bool:
        return self._config.get("longform", False)

    @property
    def mock_mode(self) -> bool:
        return self._config.get("_mock_mode", False)
