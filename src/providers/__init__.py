"""Provider 抽象层公共 API。

导入此包即自动注册所有内置 provider，使用方只需通过 registry 查找即可。

使用方式：
    from src.providers import get_llm_provider, get_tts_provider, get_discovery_provider

    llm = get_llm_provider("openai")
    client, meta = llm.create_client(config)

    tts = get_tts_provider("siliconflow")
    audio = tts.synthesize_segment("hello", "host")

    discovery = get_discovery_provider("github_trending")
    repos = discovery.discover(config)

设计原则（第一性原理）：
  1. 自动注册：导入 __init__ 即触发所有 provider 的 @register 装饰器
  2. 延迟导入：provider 模块在 __init__ 中导入，避免循环依赖
  3. 公开接口：仅暴露 registry 的查找函数和 base 的抽象类
"""
from __future__ import annotations

# ── 自动导入所有 provider 模块以触发注册 ──
# 顺序很重要：base → registry → 具体 providers
from . import base  # noqa: F401
from . import registry  # noqa: F401

# 导入具体实现模块，触发 @register_* 装饰器
from . import llm_openai  # noqa: F401
from . import tts_providers  # noqa: F401
from . import discovery_providers  # noqa: F401

# ── 公开 API ──
from .registry import (
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

from .base import (
    BaseLLMProvider,
    BaseTTSProvider,
    BaseDiscoveryProvider,
)

__all__ = [
    # Base classes
    "BaseLLMProvider",
    "BaseTTSProvider",
    "BaseDiscoveryProvider",
    # Registry — lookup
    "get_llm_provider",
    "get_tts_provider",
    "get_discovery_provider",
    # Registry — listing
    "list_llm_providers",
    "list_tts_providers",
    "list_discovery_providers",
    "list_all_providers",
    # Registry — registration
    "register_llm_provider",
    "register_tts_provider",
    "register_discovery_provider",
    "clear_registries",
]
