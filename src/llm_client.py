"""LLM 客户端工厂 — 统一创建 instructor 包装的 OpenAI 客户端。

所有 LLM 模块共用此工厂，消除重复的客户端初始化代码。
instructor 提供结构化输出（Pydantic 模型校验 + 自动重试），
替代各模块手写的 _extract_json / _parse_* 容错逻辑。
"""
from __future__ import annotations

from typing import Any

import instructor
from openai import OpenAI

from . import config_defaults as D


def create_llm_client(config: dict) -> tuple[instructor.Instructor | None, dict]:
    """创建 instructor 包装的 LLM 客户端。

    Args:
        config: 全局配置字典（含 api_keys / llm 子配置）

    Returns:
        (client, meta) 元组：
        - client: instructor 客户端，无 API Key 时为 None
        - meta: 包含 model / enable_thinking / timeout / api_key 等元信息
    """
    llm_cfg = config.get("llm", {})
    api_keys = config.get("api_keys", {})
    api_key = api_keys.get("llm", "") or api_keys.get("deepseek", "")
    enable_thinking = llm_cfg.get("enable_thinking", D.LLM_ENABLE_THINKING)
    timeout = llm_cfg.get("timeout", D.LLM_TIMEOUT)
    model = llm_cfg.get("model", D.LLM_MODEL)

    if not api_key:
        return None, {
            "api_key": "",
            "model": model,
            "enable_thinking": enable_thinking,
            "timeout": timeout,
        }

    raw_client = OpenAI(
        api_key=api_key,
        base_url=llm_cfg.get("base_url", D.LLM_BASE_URL),
        timeout=timeout,
    )

    # MD_JSON 模式：兼容所有模型（含不支持 response_format 的模型），
    # 通过系统指令引导 JSON 输出并自动提取，替代手写 _extract_json。
    client = instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)

    return client, {
        "api_key": api_key,
        "model": model,
        "enable_thinking": enable_thinking,
        "timeout": timeout,
    }


def build_kwargs(meta: dict, **extra: Any) -> dict[str, Any]:
    """构建 LLM 请求的公共参数。

    自动注入 model、enable_thinking 等公共参数，
    各模块只需传入 messages / temperature / max_tokens 等特定参数。

    Args:
        meta: create_llm_client 返回的元信息字典
        **extra: 模块特定参数（messages, temperature, max_tokens 等）

    Returns:
        完整的请求参数字典
    """
    kwargs: dict[str, Any] = {
        "model": meta["model"],
        **extra,
    }
    if meta.get("enable_thinking") is False:
        kwargs["extra_body"] = {"enable_thinking": False}
    return kwargs


def create_raw_client(config: dict) -> tuple[OpenAI | None, dict]:
    """创建原始 OpenAI 客户端（不包装 instructor）。

    用于返回纯文本的 LLM 调用（如 QA 引擎），
    无需 Pydantic 结构化输出。

    Returns:
        (client, meta) — 无 API Key 时 client 为 None
    """
    client, meta = create_llm_client(config)
    if client is None:
        return None, meta
    # instructor 包装的客户端底层持有原始 OpenAI 客户端
    raw = client.client if hasattr(client, "client") else client
    return raw, meta
