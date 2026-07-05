"""Provider 注册表 — 装饰器模式注册和查找 provider。

设计原则（第一性原理）：
  1. 注册与发现分离：provider 通过装饰器自注册，使用方通过名称查找
  2. 延迟加载：provider 类注册时不实例化，首次查找时才创建
  3. 可扩展：新增 provider 只需实现接口 + 加 @register 装饰器
  4. 可发现：list_available_providers() 提供运行时自省

使用方式：
    @register_llm_provider("openai")
    class OpenAIProvider(BaseLLMProvider):
        ...

    # 查找
    provider = get_llm_provider("openai")
    client, meta = provider.create_client(config)
"""
from __future__ import annotations

from typing import Any, Type

from .base import BaseLLMProvider, BaseTTSProvider, BaseDiscoveryProvider
from ..logger import get_logger

logger = get_logger(__name__)


# ════════════════════════════════════════
# 注册表存储
# ════════════════════════════════════════

_LLM_REGISTRY: dict[str, Type[BaseLLMProvider]] = {}
_TTS_REGISTRY: dict[str, Type[BaseTTSProvider]] = {}
_DISCOVERY_REGISTRY: dict[str, Type[BaseDiscoveryProvider]] = {}


# ════════════════════════════════════════
# LLM Provider 注册/查找
# ════════════════════════════════════════

def register_llm_provider(name: str) -> callable:
    """LLM Provider 注册装饰器。

    Args:
        name: provider 唯一标识（如 "openai" / "anthropic"）

    Returns:
        类装饰器

    Example:
        @register_llm_provider("openai")
        class OpenAIProvider(BaseLLMProvider):
            ...
    """
    def decorator(cls: Type[BaseLLMProvider]) -> Type[BaseLLMProvider]:
        if name in _LLM_REGISTRY:
            logger.warning("LLM provider '%s' 已存在，将被覆盖", name)
        _LLM_REGISTRY[name] = cls
        logger.debug("注册 LLM provider: %s -> %s", name, cls.__name__)
        return cls
    return decorator


def get_llm_provider(name: str) -> BaseLLMProvider | None:
    """通过名称获取 LLM provider 实例。

    Args:
        name: provider 标识

    Returns:
        provider 实例，未注册则返回 None
    """
    cls = _LLM_REGISTRY.get(name)
    if cls is None:
        logger.error("未找到 LLM provider: %s", name)
        return None
    return cls()


def list_llm_providers() -> list[str]:
    """列出所有已注册的 LLM provider 名称。"""
    return list(_LLM_REGISTRY.keys())


# ════════════════════════════════════════
# TTS Provider 注册/查找
# ════════════════════════════════════════

def register_tts_provider(name: str) -> callable:
    """TTS Provider 注册装饰器。"""
    def decorator(cls: Type[BaseTTSProvider]) -> Type[BaseTTSProvider]:
        if name in _TTS_REGISTRY:
            logger.warning("TTS provider '%s' 已存在，将被覆盖", name)
        _TTS_REGISTRY[name] = cls
        logger.debug("注册 TTS provider: %s -> %s", name, cls.__name__)
        return cls
    return decorator


def get_tts_provider(name: str) -> BaseTTSProvider | None:
    """通过名称获取 TTS provider 实例。"""
    cls = _TTS_REGISTRY.get(name)
    if cls is None:
        logger.error("未找到 TTS provider: %s", name)
        return None
    return cls()


def list_tts_providers() -> list[str]:
    """列出所有已注册的 TTS provider 名称。"""
    return list(_TTS_REGISTRY.keys())


# ════════════════════════════════════════
# Discovery Provider 注册/查找
# ════════════════════════════════════════

def register_discovery_provider(name: str) -> callable:
    """Discovery Provider 注册装饰器。"""
    def decorator(cls: Type[BaseDiscoveryProvider]) -> Type[BaseDiscoveryProvider]:
        if name in _DISCOVERY_REGISTRY:
            logger.warning("Discovery provider '%s' 已存在，将被覆盖", name)
        _DISCOVERY_REGISTRY[name] = cls
        logger.debug("注册 Discovery provider: %s -> %s", name, cls.__name__)
        return cls
    return decorator


def get_discovery_provider(name: str) -> BaseDiscoveryProvider | None:
    """通过名称获取 Discovery provider 实例。"""
    cls = _DISCOVERY_REGISTRY.get(name)
    if cls is None:
        logger.error("未找到 Discovery provider: %s", name)
        return None
    return cls()


def list_discovery_providers() -> list[str]:
    """列出所有已注册的 Discovery provider 名称。"""
    return list(_DISCOVERY_REGISTRY.keys())


# ════════════════════════════════════════
# 全局自省
# ════════════════════════════════════════

def list_all_providers() -> dict[str, list[str]]:
    """列出所有已注册的 provider，按类型分组。"""
    return {
        "llm": list_llm_providers(),
        "tts": list_tts_providers(),
        "discovery": list_discovery_providers(),
    }


def clear_registries() -> None:
    """清空所有注册表（仅供测试使用）。"""
    _LLM_REGISTRY.clear()
    _TTS_REGISTRY.clear()
    _DISCOVERY_REGISTRY.clear()
