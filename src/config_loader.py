"""配置加载工具：合并 YAML 配置与环境变量。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from . import config_defaults as D


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """加载 YAML 配置，并注入 .env 环境变量。

    API Key 优先级（从高到低）：
      LLM: LLM_API_KEY → SILICONFLOW_API_KEY → DEEPSEEK_API_KEY
      TTS: TTS_API_KEY → SILICONFLOW_API_KEY → DASHSCOPE_API_KEY
    """
    # 加载 .env
    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    # 加载 YAML
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = project_root / cfg_path
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if config is None:
        config = {}

    # 解析 API 密钥（支持多源 fallback，使用 config_defaults 中的环境变量名常量）
    sf_key = os.getenv(D.ENV_SILICONFLOW_API_KEY, "")
    llm_key = os.getenv(D.ENV_LLM_API_KEY, "") or sf_key or os.getenv(D.ENV_DEEPSEEK_API_KEY, "")
    tts_key = os.getenv(D.ENV_TTS_API_KEY, "") or sf_key or os.getenv(D.ENV_DASHSCOPE_API_KEY, "")

    config["api_keys"] = {
        "llm": llm_key,
        "tts": tts_key,
        "deepseek": os.getenv(D.ENV_DEEPSEEK_API_KEY, ""),
        "dashscope": os.getenv(D.ENV_DASHSCOPE_API_KEY, ""),
        "siliconflow": sf_key,
        "github": os.getenv(D.ENV_GITHUB_TOKEN, ""),
    }

    # 注入播客元信息（使用 config_defaults 中的常量）
    config["podcast_meta"] = {
        "title": os.getenv(D.ENV_PODCAST_TITLE, D.PODCAST_TITLE),
        "author": os.getenv(D.ENV_PODCAST_AUTHOR, D.PODCAST_AUTHOR),
        "email": os.getenv(D.ENV_PODCAST_EMAIL, ""),
        "site_url": os.getenv(D.ENV_PODCAST_SITE_URL, ""),
        "media_base_url": os.getenv(D.ENV_PODCAST_MEDIA_BASE_URL, ""),
    }

    config["project_root"] = str(project_root)
    return config
