"""LLM 客户端辅助工具 — 消除 7 个模块中重复的初始化和调用模式。

设计原则（第一性原理）：
  1. DRY：将 create_llm_client + 提取 api_key + 检查 + 警告 的重复模式提取为 Mixin
  2. 单一职责：Mixin 只负责 LLM 客户端初始化，不干预业务逻辑
  3. 向后兼容：Mixin 设置的属性与原代码完全一致

重复模式（在 7 个模块中出现）：
    self.client, self.meta = create_llm_client(config)
    self.api_key = self.meta["api_key"]
    self.enable_thinking = self.meta.get("enable_thinking", None)
    self.cfg = config["llm"]
    if not self.api_key:
        logger.warning("未配置 LLM API Key，将使用 mock 模式")

使用 Mixin 后：
    class ScriptGenerator(LLMClientMixin):
        def __init__(self, config):
            self._init_llm(config)
            ...
"""
from __future__ import annotations

from typing import Any

from .llm_client import create_llm_client, create_raw_client, build_kwargs
from .logger import get_logger

logger = get_logger(__name__)


class LLMClientMixin:
    """LLM 客户端初始化 Mixin。

    消除 7 个模块中重复的客户端初始化代码。
    子类在 __init__ 中调用 self._init_llm(config) 即可。
    """

    client: Any = None
    meta: dict[str, Any] = {}
    api_key: str = ""
    enable_thinking: bool | None = None
    llm_cfg: dict[str, Any] = {}

    def _init_llm(self, config: dict[str, Any], raw: bool = False) -> None:
        """初始化 LLM 客户端，设置公共属性。

        Args:
            config: 全局配置字典
            raw: True 使用 create_raw_client（纯文本输出），
                 False 使用 create_llm_client（instructor 结构化输出）
        """
        if raw:
            self.client, self.meta = create_raw_client(config)
        else:
            self.client, self.meta = create_llm_client(config)
        self.api_key = self.meta["api_key"]
        self.enable_thinking = self.meta.get("enable_thinking", None)
        self.llm_cfg = config.get("llm", {})

        if not self.api_key:
            logger.warning("未配置 LLM API Key，将使用 mock 模式")

    def build_llm_kwargs(self, **extra: Any) -> dict[str, Any]:
        """构建 LLM 请求参数（委托给 build_kwargs）。

        各模块只需传入 messages / temperature / max_tokens 等特定参数。
        """
        return build_kwargs(self.meta, **extra)
