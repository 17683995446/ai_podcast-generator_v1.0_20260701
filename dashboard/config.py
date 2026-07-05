"""路径常量与配置加载。

Stage 5: load_env() 改用 python-dotenv 替代手写解析器，提升鲁棒性。
PROJECT_ROOT 为 dashboard 包内的唯一定义点，其他模块统一从此导入。
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
EPISODES_DIR = OUTPUT_DIR / "episodes"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
ANALYSES_DIR = OUTPUT_DIR / "analyses"
HISTORY_PATH = OUTPUT_DIR / "episodes_history.json"
FEED_PATH = OUTPUT_DIR / "feed.xml"


def load_history() -> list[dict]:
    """加载节目历史。"""
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def load_config() -> dict:
    """加载 config.yaml。"""
    import yaml
    cfg_path = PROJECT_ROOT / "config.yaml"
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"error": "config.yaml 文件不存在"}
    except yaml.YAMLError as e:
        return {"error": f"config.yaml 格式错误: {e}"}
    except OSError as e:
        return {"error": f"读取 config.yaml 失败: {e}"}


def load_env() -> dict:
    """加载 .env 并脱敏。

    Stage 5: 使用 python-dotenv 的 dotenv_values() 替代手写解析器，
    正确处理引号、注释、export 前缀等边界情况。
    """
    from dotenv import dotenv_values

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return {}

    raw = dotenv_values(env_path)
    data = {}
    for k, v in raw.items():
        if v is None:
            v = ""
        if "KEY" in k or "TOKEN" in k:
            # 脱敏：统一掩码，不泄露任何片段
            v = "***已配置***" if v else "未设置"
        else:
            v = v if v else "未设置"
        data[k] = v
    return data
