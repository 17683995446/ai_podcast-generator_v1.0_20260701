"""集中式日志配置 — 统一替代散落的 print() 调用。

设计原则（第一性原理）：
  1. 单一配置入口：所有模块通过 get_logger(__name__) 获取 logger
  2. stdout 保留给 ::PROGRESS:: 协议；日志输出到 stderr
  3. 支持日志级别控制（LOG_LEVEL 环境变量）
  4. 支持文件持久化（可选）
  5. 向后兼容：未调用 configure() 时使用默认配置

使用方式：
    from src.logger import get_logger
    logger = get_logger(__name__)
    logger.info("消息")
    logger.warning("警告")
    logger.error("错误")
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ── 格式定义 ──
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 模块级标志：避免重复配置
_configured = False


def configure(
    level: str | int | None = None,
    log_file: str | Path | None = None,
    fmt: str | None = None,
) -> None:
    """配置全局日志。

    Args:
        level: 日志级别（"DEBUG"/"INFO"/"WARNING"/"ERROR" 或 logging 常量）。
               默认从 LOG_LEVEL 环境变量读取，再默认 INFO。
        log_file: 可选日志文件路径。设置后同时输出到 stderr 和文件。
        fmt: 自定义格式字符串。默认使用 _DEFAULT_FORMAT。
    """
    global _configured

    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    fmt = fmt or _DEFAULT_FORMAT
    formatter = logging.Formatter(fmt, datefmt=_DATE_FORMAT)

    # 配置 root logger
    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有 handlers（避免重复添加）
    root.handlers.clear()

    # stderr handler（日志输出到 stderr，stdout 保留给 ::PROGRESS:: 协议）
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # 可选文件 handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger。

    首次调用时自动应用默认配置（如果尚未配置）。

    Args:
        name: 模块名，通常传 __name__。

    Returns:
        logging.Logger 实例。
    """
    if not _configured:
        configure()
    return logging.getLogger(name)


def is_configured() -> bool:
    """检查日志是否已配置。"""
    return _configured
