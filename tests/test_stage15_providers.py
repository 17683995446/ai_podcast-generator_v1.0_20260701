"""阶段 3 测试：Provider 抽象层 — ABC 接口 + 注册表模式。

测试覆盖：
  1. Base ABC 抽象类验证（不可直接实例化）
  2. Registry 注册/查找/列表/清空
  3. LLM Provider 适配器（OpenAICompatibleProvider）
  4. TTS Provider 适配器（SiliconFlow / DashScope / Edge / Mock）
  5. Discovery Provider 适配器（GitHubTrending / GitHubSearch / RepoURL / Mock）
  6. 自动注册（导入包后所有 provider 可用）
  7. 可扩展性（自定义 provider 通过装饰器注册）
  8. 端到端集成（mock 配置完整流程）
"""
import struct
import pytest
from typing import Any
from unittest.mock import patch, MagicMock

from src.providers import (
    BaseLLMProvider,
    BaseTTSProvider,
    BaseDiscoveryProvider,
    get_llm_provider,
    get_tts_provider,
    get_discovery_provider,
    list_llm_providers,
    list_tts_providers,
    list_discovery_providers,
    list_all_providers,
    register_llm_provider,
    register_tts_provider,
    register_discovery_provider,
    clear_registries,
)
from src.providers.discovery_providers import (
    GitHubTrendingDiscoveryProvider,
    GitHubSearchDiscoveryProvider,
    RepoURLDiscoveryProvider,
    MockDiscoveryProvider,
)
from src.providers.llm_openai import OpenAICompatibleProvider
from src.providers.tts_providers import (
    SiliconFlowTTSProvider,
    DashScopeTTSProvider,
    EdgeTTSProvider,
    MockTTSProvider,
)
from src.models import GitHubRepo


def _make_config(**overrides) -> dict[str, Any]:
    """构造测试配置。"""
    config: dict[str, Any] = {
        "api_keys": {
            "llm": "test-key",
            "tts": "test-key",
            "deepseek": "",
            "dashscope": "",
            "siliconflow": "test-key",
            "github": "test-token",
        },
        "llm": {
            "model": "test-model",
            "base_url": "https://test.api/v1",
            "temperature": 0.8,
            "max_tokens": 4000,
            "timeout": 120,
            "enable_thinking": False,
        },
        "tts": {
            "provider": "mock",
            "base_url": "https://test.api/v1",
            "model": "test-tts",
            "voice_mapping": {"host": "alex", "guest": "anna"},
            "sample_rate": 24000,
        },
        "discovery": {
            "max_projects": 3,
            "min_stars": 100,
            "rsshub_base_url": "https://rsshub.app",
            "trending_since": "daily",
            "language": "",
            "trending_api_url": "https://test.api/trending",
            "keywords": [],
            "exclude_keywords": [],
        },
        "project_root": "/tmp/test",
        "_mock_mode": False,
    }
    config.update(overrides)
    return config


# ════════════════════════════════════════
# 1. Base ABC 抽象类验证
# ════════════════════════════════════════
class TestBaseABC:
    """验证抽象基类不可直接实例化。"""

    def test_base_llm_provider_is_abstract(self):
        """BaseLLMProvider 不可实例化。"""
        with pytest.raises(TypeError):
            BaseLLMProvider()

    def test_base_tts_provider_is_abstract(self):
        """BaseTTSProvider 不可实例化。"""
        with pytest.raises(TypeError):
            BaseTTSProvider()

    def test_base_discovery_provider_is_abstract(self):
        """BaseDiscoveryProvider 不可实例化。"""
        with pytest.raises(TypeError):
            BaseDiscoveryProvider()

    def test_subclass_must_implement_all_methods(self):
        """子类必须实现所有抽象方法，否则不可实例化。"""

        class IncompleteLLM(BaseLLMProvider):
            def create_client(self, config):
                return None, {}

            # 缺少 create_raw_client 和 is_available

        with pytest.raises(TypeError):
            IncompleteLLM()


# ════════════════════════════════════════
# 2. Registry 注册/查找/列表
# ════════════════════════════════════════
class TestRegistry:
    """注册表核心功能测试。"""

    def test_list_all_providers_returns_dict(self):
        """list_all_providers 返回包含三类的字典。"""
        all_providers = list_all_providers()
        assert isinstance(all_providers, dict)
        assert "llm" in all_providers
        assert "tts" in all_providers
        assert "discovery" in all_providers

    def test_list_llm_providers_includes_openai(self):
        """LLM 注册表包含 openai。"""
        providers = list_llm_providers()
        assert "openai" in providers

    def test_list_tts_providers_includes_all_four(self):
        """TTS 注册表包含四种 provider。"""
        providers = list_tts_providers()
        assert "siliconflow" in providers
        assert "dashscope" in providers
        assert "edge" in providers
        assert "mock" in providers

    def test_list_discovery_providers_includes_all_four(self):
        """Discovery 注册表包含四种 provider。"""
        providers = list_discovery_providers()
        assert "github_trending" in providers
        assert "github_search" in providers
        assert "repo_url" in providers
        assert "mock" in providers

    def test_get_llm_provider_returns_instance(self):
        """get_llm_provider 返回正确实例。"""
        provider = get_llm_provider("openai")
        assert provider is not None
        assert isinstance(provider, OpenAICompatibleProvider)
        assert isinstance(provider, BaseLLMProvider)

    def test_get_tts_provider_returns_instance(self):
        """get_tts_provider 返回正确实例。"""
        provider = get_tts_provider("mock")
        assert provider is not None
        assert isinstance(provider, MockTTSProvider)
        assert isinstance(provider, BaseTTSProvider)

    def test_get_discovery_provider_returns_instance(self):
        """get_discovery_provider 返回正确实例。"""
        provider = get_discovery_provider("mock")
        assert provider is not None
        assert isinstance(provider, MockDiscoveryProvider)
        assert isinstance(provider, BaseDiscoveryProvider)

    def test_get_unknown_provider_returns_none(self):
        """查找不存在的 provider 返回 None。"""
        assert get_llm_provider("nonexistent") is None
        assert get_tts_provider("nonexistent") is None
        assert get_discovery_provider("nonexistent") is None

    def test_register_custom_llm_provider(self):
        """自定义 LLM provider 可通过装饰器注册。"""

        @register_llm_provider("custom_test_llm")
        class CustomLLMProvider(BaseLLMProvider):
            def create_client(self, config):
                return None, {"model": "custom"}

            def create_raw_client(self, config):
                return None, {"model": "custom"}

            def is_available(self, config):
                return True

        assert "custom_test_llm" in list_llm_providers()
        provider = get_llm_provider("custom_test_llm")
        assert provider is not None
        assert isinstance(provider, CustomLLMProvider)

    def test_register_custom_tts_provider(self):
        """自定义 TTS provider 可通过装饰器注册。"""

        @register_tts_provider("custom_test_tts")
        class CustomTTSProvider(BaseTTSProvider):
            @property
            def name(self):
                return "custom_test_tts"

            def synthesize_segment(self, text, voice, emotion="neutral"):
                return b"custom_audio"

            def is_available(self, config):
                return True

        assert "custom_test_tts" in list_tts_providers()
        provider = get_tts_provider("custom_test_tts")
        assert provider is not None
        audio = provider.synthesize_segment("test", "host")
        assert audio == b"custom_audio"

    def test_register_custom_discovery_provider(self):
        """自定义 Discovery provider 可通过装饰器注册。"""

        @register_discovery_provider("custom_test_discovery")
        class CustomDiscoveryProvider(BaseDiscoveryProvider):
            @property
            def name(self):
                return "custom_test_discovery"

            def discover(self, config):
                return [GitHubRepo(name="custom/repo", url="https://github.com/custom/repo")]

            def is_available(self, config):
                return True

        assert "custom_test_discovery" in list_discovery_providers()
        provider = get_discovery_provider("custom_test_discovery")
        assert provider is not None
        repos = provider.discover({})
        assert len(repos) == 1
        assert repos[0].name == "custom/repo"

    def test_duplicate_registration_overwrites(self):
        """重复注册同名 provider 会覆盖（带警告日志）。"""

        @register_llm_provider("dup_test")
        class FirstProvider(BaseLLMProvider):
            def create_client(self, config):
                return None, {}

            def create_raw_client(self, config):
                return None, {}

            def is_available(self, config):
                return True

        @register_llm_provider("dup_test")
        class SecondProvider(BaseLLMProvider):
            def create_client(self, config):
                return None, {}

            def create_raw_client(self, config):
                return None, {}

            def is_available(self, config):
                return True

        provider = get_llm_provider("dup_test")
        assert isinstance(provider, SecondProvider)


# ════════════════════════════════════════
# 3. LLM Provider 适配器
# ════════════════════════════════════════
class TestLLMProvider:
    """OpenAICompatibleProvider 适配器测试。"""

    def test_is_available_with_api_key(self):
        """有 API Key 时 is_available 返回 True。"""
        config = _make_config()
        provider = OpenAICompatibleProvider()
        assert provider.is_available(config) is True

    def test_is_available_without_api_key(self):
        """无 API Key 时 is_available 返回 False。"""
        config = _make_config()
        config["api_keys"]["llm"] = ""
        config["api_keys"]["deepseek"] = ""
        provider = OpenAICompatibleProvider()
        assert provider.is_available(config) is False

    def test_is_available_with_deepseek_fallback(self):
        """deepseek key 作为 fallback 可用。"""
        config = _make_config()
        config["api_keys"]["llm"] = ""
        config["api_keys"]["deepseek"] = "ds-key"
        provider = OpenAICompatibleProvider()
        assert provider.is_available(config) is True

    def test_create_client_returns_tuple(self):
        """create_client 返回 (client, meta) 元组。"""
        config = _make_config()
        provider = OpenAICompatibleProvider()
        with patch("src.llm_client.create_llm_client") as mock_create:
            mock_create.return_value = (MagicMock(), {"model": "test"})
            client, meta = provider.create_client(config)
            assert client is not None
            assert meta["model"] == "test"

    def test_create_raw_client_returns_tuple(self):
        """create_raw_client 返回 (client, meta) 元组。"""
        config = _make_config()
        provider = OpenAICompatibleProvider()
        with patch("src.llm_client.create_raw_client") as mock_create:
            mock_create.return_value = (MagicMock(), {"model": "test"})
            client, meta = provider.create_raw_client(config)
            assert client is not None
            assert meta["model"] == "test"

    def test_create_client_without_key_returns_none(self):
        """无 API Key 时 create_client 返回 (None, meta)。"""
        config = _make_config()
        config["api_keys"]["llm"] = ""
        config["api_keys"]["deepseek"] = ""
        provider = OpenAICompatibleProvider()
        client, meta = provider.create_client(config)
        assert client is None
        assert "model" in meta


# ════════════════════════════════════════
# 4. TTS Provider 适配器
# ════════════════════════════════════════
class TestTTSProviders:
    """TTS Provider 测试。"""

    def test_siliconflow_name(self):
        provider = SiliconFlowTTSProvider()
        assert provider.name == "siliconflow"

    def test_siliconflow_is_available_with_key(self):
        config = _make_config()
        provider = SiliconFlowTTSProvider()
        assert provider.is_available(config) is True

    def test_siliconflow_is_available_without_key(self):
        config = _make_config()
        config["api_keys"]["tts"] = ""
        config["api_keys"]["siliconflow"] = ""
        provider = SiliconFlowTTSProvider()
        assert provider.is_available(config) is False

    def test_siliconflow_synthesize_delegates(self):
        """SiliconFlow synthesize 委托给 TTSSynthesizer。"""
        provider = SiliconFlowTTSProvider()
        provider.configure(_make_config())
        with patch("src.tts_synth.TTSSynthesizer._call_siliconflow", return_value=b"audio"):
            result = provider.synthesize_segment("hello", "host")
            assert result == b"audio"

    def test_dashscope_name(self):
        provider = DashScopeTTSProvider()
        assert provider.name == "dashscope"

    def test_dashscope_is_available_with_key(self):
        config = _make_config()
        config["api_keys"]["dashscope"] = "ds-key"
        provider = DashScopeTTSProvider()
        assert provider.is_available(config) is True

    def test_dashscope_is_available_without_key(self):
        config = _make_config()
        config["api_keys"]["dashscope"] = ""
        provider = DashScopeTTSProvider()
        assert provider.is_available(config) is False

    def test_edge_name(self):
        provider = EdgeTTSProvider()
        assert provider.name == "edge"

    def test_edge_is_always_available(self):
        """Edge-TTS 无需 API Key，始终可用。"""
        config = _make_config()
        provider = EdgeTTSProvider()
        assert provider.is_available(config) is True

    def test_edge_synthesize_delegates(self):
        """Edge-TTS synthesize 委托给 TTSSynthesizer。"""
        provider = EdgeTTSProvider()
        provider.configure(_make_config())
        with patch("src.tts_synth.TTSSynthesizer._call_edge_tts", return_value=b"audio"):
            result = provider.synthesize_segment("hello", "host")
            assert result == b"audio"

    def test_mock_name(self):
        provider = MockTTSProvider()
        assert provider.name == "mock"

    def test_mock_is_always_available(self):
        config = _make_config()
        provider = MockTTSProvider()
        assert provider.is_available(config) is True

    def test_mock_synthesize_returns_valid_wav(self):
        """Mock TTS 返回有效的 WAV 字节流。"""
        provider = MockTTSProvider()
        audio = provider.synthesize_segment("hello world", "host")
        assert audio is not None
        assert len(audio) > 44  # WAV header 至少 44 字节
        # 验证 WAV 头
        assert audio[:4] == b"RIFF"
        assert audio[8:12] == b"WAVE"
        assert audio[12:16] == b"fmt "

    def test_mock_synthesize_scales_with_text_length(self):
        """Mock TTS 音频时长与文本长度成正比。"""
        provider = MockTTSProvider()
        short_audio = provider.synthesize_segment("hi", "host")
        long_audio = provider.synthesize_segment("a" * 1000, "host")
        assert len(long_audio) > len(short_audio)


# ════════════════════════════════════════
# 5. Discovery Provider 适配器
# ════════════════════════════════════════
class TestDiscoveryProviders:
    """Discovery Provider 测试。"""

    def test_github_trending_name(self):
        provider = GitHubTrendingDiscoveryProvider()
        assert provider.name == "github_trending"

    def test_github_trending_is_always_available(self):
        """Trending 始终可用（有 mock fallback）。"""
        provider = GitHubTrendingDiscoveryProvider()
        assert provider.is_available({}) is True

    def test_github_trending_discover_delegates(self):
        """Trending discover 委托给 RepoDiscovery。"""
        provider = GitHubTrendingDiscoveryProvider()
        mock_repos = [GitHubRepo(name="test/repo", url="https://github.com/test/repo")]
        with patch("src.discovery.RepoDiscovery") as MockDiscovery:
            instance = MockDiscovery.return_value
            instance.discover.return_value = mock_repos
            repos = provider.discover(_make_config())
            assert repos == mock_repos

    def test_github_search_name(self):
        provider = GitHubSearchDiscoveryProvider()
        assert provider.name == "github_search"

    def test_github_search_is_available_with_token(self):
        config = _make_config()
        provider = GitHubSearchDiscoveryProvider()
        assert provider.is_available(config) is True

    def test_github_search_is_available_without_token(self):
        config = _make_config()
        config["api_keys"]["github"] = ""
        provider = GitHubSearchDiscoveryProvider()
        assert provider.is_available(config) is False

    def test_github_search_discover_without_topic_returns_empty(self):
        """无搜索关键词时返回空列表。"""
        provider = GitHubSearchDiscoveryProvider()
        repos = provider.discover(_make_config())
        assert repos == []

    def test_github_search_discover_with_topic_delegates(self):
        """有搜索关键词时委托给 RepoDiscovery。"""
        provider = GitHubSearchDiscoveryProvider()
        config = _make_config()
        config["_search_topic"] = "machine-learning"
        mock_repos = [GitHubRepo(name="test/repo", url="https://github.com/test/repo")]
        with patch("src.discovery.RepoDiscovery") as MockDiscovery:
            instance = MockDiscovery.return_value
            instance.discover_by_topic.return_value = mock_repos
            repos = provider.discover(config)
            assert repos == mock_repos

    def test_repo_url_name(self):
        provider = RepoURLDiscoveryProvider()
        assert provider.name == "repo_url"

    def test_repo_url_is_always_available(self):
        provider = RepoURLDiscoveryProvider()
        assert provider.is_available({}) is True

    def test_repo_url_discover_without_urls_returns_empty(self):
        """无 URL 列表时返回空列表。"""
        provider = RepoURLDiscoveryProvider()
        repos = provider.discover(_make_config())
        assert repos == []

    def test_repo_url_discover_with_urls_delegates(self):
        """有 URL 列表时委托给 RepoDiscovery。"""
        provider = RepoURLDiscoveryProvider()
        config = _make_config()
        config["_repo_urls"] = ["https://github.com/test/repo"]
        mock_repos = [GitHubRepo(name="test/repo", url="https://github.com/test/repo")]
        with patch("src.discovery.RepoDiscovery") as MockDiscovery:
            instance = MockDiscovery.return_value
            instance.discover_by_repo_urls.return_value = mock_repos
            repos = provider.discover(config)
            assert repos == mock_repos

    def test_mock_discovery_name(self):
        provider = MockDiscoveryProvider()
        assert provider.name == "mock"

    def test_mock_discovery_is_always_available(self):
        provider = MockDiscoveryProvider()
        assert provider.is_available({}) is True

    def test_mock_discovery_returns_repos(self):
        """Mock discovery 返回内置样例项目。"""
        provider = MockDiscoveryProvider()
        config = _make_config()
        repos = provider.discover(config)
        assert len(repos) > 0
        assert all(isinstance(r, GitHubRepo) for r in repos)

    def test_mock_discovery_respects_max_projects(self):
        """Mock discovery 尊重 max_projects 配置。"""
        provider = MockDiscoveryProvider()
        config = _make_config()
        config["discovery"]["max_projects"] = 1
        repos = provider.discover(config)
        assert len(repos) == 1

    def test_mock_discovery_assigns_ranking(self):
        """Mock discovery 为每个项目分配排名。"""
        provider = MockDiscoveryProvider()
        config = _make_config()
        config["discovery"]["max_projects"] = 3
        repos = provider.discover(config)
        for i, repo in enumerate(repos, 1):
            assert repo.trending_rank == i

    def test_mock_discovery_returns_copies(self):
        """Mock discovery 返回的是副本，不修改内置数据。"""
        provider = MockDiscoveryProvider()
        config = _make_config()
        repos1 = provider.discover(config)
        repos1[0].name = "modified"
        repos2 = provider.discover(config)
        assert repos2[0].name != "modified"


# ════════════════════════════════════════
# 6. 自动注册验证
# ════════════════════════════════════════
class TestAutoRegistration:
    """导入包后自动注册所有 provider。"""

    def test_all_llm_providers_registered(self):
        """导入后 openai 已注册。"""
        assert "openai" in list_llm_providers()

    def test_all_tts_providers_registered(self):
        """导入后四种 TTS provider 已注册。"""
        tts = list_tts_providers()
        assert "siliconflow" in tts
        assert "dashscope" in tts
        assert "edge" in tts
        assert "mock" in tts

    def test_all_discovery_providers_registered(self):
        """导入后四种 discovery provider 已注册。"""
        disc = list_discovery_providers()
        assert "github_trending" in disc
        assert "github_search" in disc
        assert "repo_url" in disc
        assert "mock" in disc

    def test_list_all_providers_count(self):
        """list_all_providers 返回正确数量的 provider。"""
        all_p = list_all_providers()
        assert len(all_p["llm"]) >= 1
        assert len(all_p["tts"]) >= 4
        assert len(all_p["discovery"]) >= 4


# ════════════════════════════════════════
# 7. 可扩展性验证
# ════════════════════════════════════════
class TestExtensibility:
    """验证新增 provider 无需修改现有代码（开闭原则）。"""

    def test_new_llm_provider_does_not_break_existing(self):
        """新增 LLM provider 不影响已有 provider。"""
        original_count = len(list_llm_providers())

        @register_llm_provider("ext_test_llm")
        class ExtLLMProvider(BaseLLMProvider):
            def create_client(self, config):
                return None, {}

            def create_raw_client(self, config):
                return None, {}

            def is_available(self, config):
                return True

        assert len(list_llm_providers()) == original_count + 1
        # 原有 provider 仍然可用
        assert "openai" in list_llm_providers()

    def test_new_tts_provider_does_not_break_existing(self):
        """新增 TTS provider 不影响已有 provider。"""
        original_count = len(list_tts_providers())

        @register_tts_provider("ext_test_tts")
        class ExtTTSProvider(BaseTTSProvider):
            @property
            def name(self):
                return "ext_test_tts"

            def synthesize_segment(self, text, voice, emotion="neutral"):
                return b""

            def is_available(self, config):
                return True

        assert len(list_tts_providers()) == original_count + 1
        assert "mock" in list_tts_providers()

    def test_new_discovery_provider_does_not_break_existing(self):
        """新增 Discovery provider 不影响已有 provider。"""
        original_count = len(list_discovery_providers())

        @register_discovery_provider("ext_test_disc")
        class ExtDiscoveryProvider(BaseDiscoveryProvider):
            @property
            def name(self):
                return "ext_test_disc"

            def discover(self, config):
                return []

            def is_available(self, config):
                return True

        assert len(list_discovery_providers()) == original_count + 1
        assert "mock" in list_discovery_providers()

    def test_provider_instances_are_independent(self):
        """每次 get 返回新实例（无共享状态）。"""
        p1 = get_tts_provider("mock")
        p2 = get_tts_provider("mock")
        assert p1 is not p2
        assert p1.name == p2.name


# ════════════════════════════════════════
# 8. 端到端集成测试
# ════════════════════════════════════════
class TestEndToEndIntegration:
    """端到端：使用 provider 抽象层完成完整 mock 流程。"""

    def test_mock_discovery_to_mock_tts_pipeline(self):
        """从 mock discovery 到 mock TTS 的完整流程。"""
        config = _make_config()
        config["_mock_mode"] = True

        # 1. 通过 provider 发现项目
        discovery = get_discovery_provider("mock")
        assert discovery is not None
        repos = discovery.discover(config)
        assert len(repos) > 0

        # 2. 通过 provider 合成语音
        tts = get_tts_provider("mock")
        assert tts is not None
        for repo in repos:
            audio = tts.synthesize_segment(repo.description, "host")
            assert audio is not None
            assert audio[:4] == b"RIFF"

    def test_llm_provider_is_available_check(self):
        """LLM provider 可用性检查在完整配置中工作。"""
        config = _make_config()
        llm = get_llm_provider("openai")
        assert llm is not None
        assert llm.is_available(config) is True

    def test_all_providers_accessible_via_registry(self):
        """所有 provider 均可通过注册表访问。"""
        all_p = list_all_providers()
        for name in all_p["llm"]:
            assert get_llm_provider(name) is not None
        for name in all_p["tts"]:
            assert get_tts_provider(name) is not None
        for name in all_p["discovery"]:
            assert get_discovery_provider(name) is not None

    def test_provider_isinstance_base(self):
        """所有通过注册表获取的 provider 都是对应基类的实例。"""
        llm = get_llm_provider("openai")
        assert isinstance(llm, BaseLLMProvider)

        tts = get_tts_provider("mock")
        assert isinstance(tts, BaseTTSProvider)

        disc = get_discovery_provider("mock")
        assert isinstance(disc, BaseDiscoveryProvider)
