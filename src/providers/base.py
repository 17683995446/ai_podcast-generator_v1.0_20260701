"""Provider 抽象基类 — 定义 LLM/TTS/Discovery 的统一接口。

设计原则（第一性原理）：
  1. 依赖倒置：上层模块依赖抽象接口，而非具体实现
  2. 开闭原则：新增 provider 通过实现接口+注册，无需修改现有代码
  3. 单一职责：每个接口只定义该领域的核心操作
  4. 可测试性：接口允许轻松 Mock

使用方式：
    from src.providers.base import BaseLLMProvider
    from src.providers.registry import register_llm_provider

    @register_llm_provider("openai")
    class OpenAIProvider(BaseLLMProvider):
        def create_client(self, config):
            ...
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generator

from ..models import GitHubRepo, PodcastSegment


# ════════════════════════════════════════
# LLM Provider 抽象
# ════════════════════════════════════════

class BaseLLMProvider(ABC):
    """LLM 提供商抽象基类。

    所有 LLM 实现（OpenAI 兼容、Anthropic、本地模型等）均需实现此接口。
    """

    @abstractmethod
    def create_client(self, config: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
        """创建 LLM 客户端。

        Args:
            config: 全局配置字典

        Returns:
            (client, meta) 元组：
            - client: 结构化输出客户端（如 instructor），无 API Key 时为 None
            - meta: 包含 model / api_key / enable_thinking 等元信息
        """

    @abstractmethod
    def create_raw_client(self, config: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
        """创建原始文本客户端（无需结构化输出）。

        Args:
            config: 全局配置字典

        Returns:
            (client, meta) — 无 API Key 时 client 为 None
        """

    @abstractmethod
    def is_available(self, config: dict[str, Any]) -> bool:
        """检查此 provider 是否可用（如 API Key 是否配置）。"""


# ════════════════════════════════════════
# TTS Provider 抽象
# ════════════════════════════════════════

class BaseTTSProvider(ABC):
    """TTS 提供商抽象基类。

    所有 TTS 实现（SiliconFlow、DashScope、Edge-TTS、Mock 等）均需实现此接口。
    """

    @abstractmethod
    def synthesize_segment(
        self,
        text: str,
        voice: str,
        emotion: str = "neutral",
    ) -> bytes | None:
        """合成单段语音。

        Args:
            text: 要合成的文本
            voice: 语音标识（如 "host" / "guest"）
            emotion: 情感标注

        Returns:
            音频字节流（WAV 格式），失败返回 None
        """

    @abstractmethod
    def is_available(self, config: dict[str, Any]) -> bool:
        """检查此 provider 是否可用。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称标识。"""


# ════════════════════════════════════════
# Discovery Provider 抽象
# ════════════════════════════════════════

class BaseDiscoveryProvider(ABC):
    """数据源发现提供商抽象基类。

    所有发现实现（RSSHub、GitHub Trending、GitHub Search、Mock 等）均需实现此接口。
    """

    @abstractmethod
    def discover(self, config: dict[str, Any]) -> list[GitHubRepo]:
        """发现 GitHub 项目。

        Args:
            config: 全局配置字典

        Returns:
            GitHubRepo 列表
        """

    @abstractmethod
    def is_available(self, config: dict[str, Any]) -> bool:
        """检查此 provider 是否可用。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 名称标识。"""
