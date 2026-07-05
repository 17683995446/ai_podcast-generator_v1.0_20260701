"""OpenAI 兼容 LLM Provider — 适配现有 llm_client 到 Provider 接口。

这是现有 LLM 客户端逻辑的 Provider 适配器，不改变底层实现，
仅将其包装为符合 BaseLLMProvider 接口的形式。
"""
from __future__ import annotations

from typing import Any

from .base import BaseLLMProvider
from .registry import register_llm_provider
from ..logger import get_logger

logger = get_logger(__name__)


@register_llm_provider("openai")
class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI 兼容 API Provider（支持 SiliconFlow / DeepSeek 等）。"""

    def create_client(self, config: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
        """创建 instructor 包装的 LLM 客户端。"""
        from ..llm_client import create_llm_client
        return create_llm_client(config)

    def create_raw_client(self, config: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
        """创建原始 OpenAI 客户端（不包装 instructor）。"""
        from ..llm_client import create_raw_client
        return create_raw_client(config)

    def is_available(self, config: dict[str, Any]) -> bool:
        """检查 API Key 是否已配置。"""
        api_keys = config.get("api_keys", {})
        return bool(api_keys.get("llm", "") or api_keys.get("deepseek", ""))
