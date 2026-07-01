"""路径常量与配置加载。"""
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
    """加载 .env 并脱敏。"""
    env_path = PROJECT_ROOT / ".env"
    data = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                # 去除首尾空白与成对引号
                v = v.strip().strip('"').strip("'").strip()
                if "KEY" in k or "TOKEN" in k:
                    # 脱敏：统一掩码，不泄露任何片段
                    v = "***已配置***" if v else "未设置"
                else:
                    v = v if v else "未设置"
                data[k] = v
    return data
