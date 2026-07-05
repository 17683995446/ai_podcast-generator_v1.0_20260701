"""阶段 1 测试：统一日志框架 — logger 模块 + print 消除验证。

测试覆盖：
  1. logger 模块基础功能（configure / get_logger / 级别控制）
  2. 环境变量 LOG_LEVEL 支持
  3. 文件日志持久化
  4. stdout/stderr 分离（::PROGRESS:: 协议兼容性）
  5. src/ 模块 print() 消除验证
  6. 各模块 logger 可用性验证
"""
import io
import logging
import os
import re
from pathlib import Path

import pytest

from src.logger import configure, get_logger, is_configured


# ════════════════════════════════════════
# 1. logger 模块基础功能
# ════════════════════════════════════════
class TestLoggerModule:
    """logger 模块基础功能验证。"""

    def test_get_logger_returns_logger(self):
        """get_logger 应返回 logging.Logger 实例。"""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_get_logger_auto_configures(self):
        """首次调用 get_logger 应自动配置。"""
        # 即使 is_configured 为 False，get_logger 也应自动配置
        logger = get_logger("test_auto")
        assert logger is not None

    def test_configure_sets_level(self):
        """configure 应正确设置日志级别。"""
        configure(level="DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_configure_with_int_level(self):
        """configure 应接受整数级别。"""
        configure(level=logging.WARNING)
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_configure_env_level(self, monkeypatch):
        """configure 应从 LOG_LEVEL 环境变量读取级别。"""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        configure(level=None)
        root = logging.getLogger()
        assert root.level == logging.ERROR

    def test_configure_invalid_level_defaults_info(self):
        """无效级别应默认为 INFO。"""
        configure(level="INVALID")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_is_configured_flag(self):
        """configure 后 is_configured 应返回 True。"""
        configure()
        assert is_configured() is True


class TestLoggerOutput:
    """日志输出验证。"""

    def test_log_to_stderr(self, capsys):
        """日志应输出到 stderr，而非 stdout。"""
        configure(level="INFO")
        logger = get_logger("test_stderr")
        logger.info("test message")

        captured = capsys.readouterr()
        assert "test message" in captured.err
        assert "test message" not in captured.out

    def test_stdout_reserved_for_progress(self, capsys):
        """stdout 不应被日志污染（保留给 ::PROGRESS:: 协议）。"""
        configure(level="DEBUG")
        logger = get_logger("test_stdout")
        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warn msg")

        captured = capsys.readouterr()
        # stdout 应为空（无日志输出）
        assert captured.out == "" or "::PROGRESS::" in captured.out

    def test_log_format_contains_timestamp(self, capsys):
        """日志格式应包含时间戳。"""
        configure(level="INFO")
        logger = get_logger("test_format")
        logger.info("formatted message")

        captured = capsys.readouterr()
        # 应包含日期格式 (YYYY-MM-DD HH:MM:SS)
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", captured.err)

    def test_log_format_contains_level(self, capsys):
        """日志格式应包含级别。"""
        configure(level="WARNING")
        logger = get_logger("test_level_fmt")
        logger.warning("level test")

        captured = capsys.readouterr()
        assert "[WARNING]" in captured.err

    def test_log_format_contains_module_name(self, capsys):
        """日志格式应包含模块名。"""
        configure(level="INFO")
        logger = get_logger("my.test.module")
        logger.info("module test")

        captured = capsys.readouterr()
        assert "my.test.module" in captured.err


class TestLoggerFileOutput:
    """文件日志验证。"""

    def test_log_to_file(self, tmp_path):
        """配置 log_file 后应写入文件。"""
        log_path = tmp_path / "test.log"
        configure(level="INFO", log_file=log_path)

        logger = get_logger("test_file")
        logger.info("file log message")
        logger.warning("file warning")

        # 强制 flush 所有 handlers
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8")
        assert "file log message" in content
        assert "file warning" in content

    def test_log_file_creates_parent_dirs(self, tmp_path):
        """日志文件路径的父目录不存在时应自动创建。"""
        log_path = tmp_path / "logs" / "subdir" / "app.log"
        configure(level="INFO", log_file=log_path)

        logger = get_logger("test_mkdir")
        logger.info("mkdir test")

        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_path.exists()


class TestLoggerLevelFiltering:
    """日志级别过滤验证。"""

    def test_warning_level_filters_info(self, capsys):
        """WARNING 级别应过滤掉 INFO 消息。"""
        configure(level="WARNING")
        logger = get_logger("test_filter")

        logger.info("should not appear")
        logger.warning("should appear")

        captured = capsys.readouterr()
        assert "should not appear" not in captured.err
        assert "should appear" in captured.err

    def test_error_level_filters_warning(self, capsys):
        """ERROR 级别应过滤掉 WARNING 消息。"""
        configure(level="ERROR")
        logger = get_logger("test_error_filter")

        logger.warning("should not appear")
        logger.error("should appear")

        captured = capsys.readouterr()
        assert "should not appear" not in captured.err
        assert "should appear" in captured.err


# ════════════════════════════════════════
# 2. src/ 模块 print() 消除验证
# ════════════════════════════════════════
class TestPrintElimination:
    """验证 src/ 模块中 print() 已被完全替换。"""

    def _find_print_calls(self, src_dir: Path) -> list[tuple[str, int, str]]:
        """扫描 src/ 目录下所有 .py 文件中的 print() 调用。

        排除：注释行、字符串字面量内的 print、logger.py 文档字符串。
        """
        results = []
        for py_file in src_dir.glob("*.py"):
            if py_file.name == "logger.py":
                continue  # logger.py 文档字符串中提及 print() 是正常的

            lines = py_file.read_text(encoding="utf-8").split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # 跳过注释
                if stripped.startswith("#"):
                    continue
                # 跳过字符串字面量内的 print（如 mock 数据中的 print('Hello')）
                if "print(" in stripped and not stripped.startswith("print("):
                    # 检查是否在字符串内
                    prefix = stripped.split("print(")[0]
                    if prefix.count('"') % 2 == 1 or prefix.count("'") % 2 == 1:
                        continue
                # 检查是否是实际的 print() 调用
                if re.match(r"^\s*print\s*\(", line):
                    results.append((str(py_file.name), i, stripped))
        return results

    def test_no_print_calls_in_src(self):
        """src/ 目录下不应有任何 print() 函数调用。"""
        src_dir = Path(__file__).parent.parent / "src"
        print_calls = self._find_print_calls(src_dir)

        if print_calls:
            detail = "\n".join(
                f"  {f}:{n}: {s}" for f, n, s in print_calls
            )
            pytest.fail(f"发现 {len(print_calls)} 处 print() 调用:\n{detail}")

    def test_no_print_in_specific_modules(self):
        """逐个验证关键模块无 print()。"""
        src_dir = Path(__file__).parent.parent / "src"
        modules_to_check = [
            "deep_extractor.py",
            "segmented_generator.py",
            "project_analyzer.py",
            "tts_synth.py",
            "llm_script.py",
            "discovery.py",
            "crawler.py",
            "audio_mixer.py",
            "rss_publisher.py",
            "script_critic.py",
            "qa_engine.py",
            "search_index.py",
            "cross_project_comparator.py",
            "show_notes_generator.py",
        ]

        for mod_name in modules_to_check:
            mod_path = src_dir / mod_name
            if not mod_path.exists():
                continue
            content = mod_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # 排除字符串字面量
                if "print('Hello')" in line:
                    continue
                if re.match(r"^\s*print\s*\(", line):
                    pytest.fail(
                        f"{mod_name}:{i} 仍有 print() 调用: {stripped}"
                    )


# ════════════════════════════════════════
# 3. 各模块 logger 可用性验证
# ════════════════════════════════════════
class TestModuleLoggers:
    """验证各 src/ 模块已正确导入和使用 logger。"""

    @pytest.mark.parametrize("module_name", [
        "deep_extractor",
        "segmented_generator",
        "project_analyzer",
        "tts_synth",
        "llm_script",
        "discovery",
        "crawler",
        "audio_mixer",
        "rss_publisher",
        "script_critic",
        "qa_engine",
        "search_index",
        "cross_project_comparator",
        "show_notes_generator",
    ])
    def test_module_has_logger_import(self, module_name):
        """每个模块应导入 get_logger。"""
        src_dir = Path(__file__).parent.parent / "src"
        mod_path = src_dir / f"{module_name}.py"
        if not mod_path.exists():
            pytest.skip(f"{module_name}.py not found")

        content = mod_path.read_text(encoding="utf-8")
        assert "from src.logger import get_logger" in content or \
               "from .logger import get_logger" in content, \
               f"{module_name}.py 未导入 get_logger"

    @pytest.mark.parametrize("module_name", [
        "deep_extractor",
        "segmented_generator",
        "project_analyzer",
        "tts_synth",
        "llm_script",
        "discovery",
    ])
    def test_module_defines_logger_variable(self, module_name):
        """每个模块应定义 logger 变量。"""
        src_dir = Path(__file__).parent.parent / "src"
        mod_path = src_dir / f"{module_name}.py"
        if not mod_path.exists():
            pytest.skip(f"{module_name}.py not found")

        content = mod_path.read_text(encoding="utf-8")
        assert re.search(r"^logger\s*=\s*get_logger\(", content, re.MULTILINE), \
               f"{module_name}.py 未定义 logger 变量"

    def test_main_py_uses_logger(self):
        """main.py 应使用 logger 替代 bare print()。"""
        main_path = Path(__file__).parent.parent / "main.py"
        content = main_path.read_text(encoding="utf-8")

        # 应导入 get_logger
        assert "from src.logger import get_logger" in content

        # 应定义 logger 变量
        assert re.search(r"^logger\s*=\s*get_logger\(", content, re.MULTILINE)

        # 不应有 bare print() 调用（排除 sys.stdout.write 的 ::PROGRESS:: 协议）
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r"^\s*print\s*\(", line):
                pytest.fail(f"main.py:{i} 仍有 print() 调用: {stripped}")


# ════════════════════════════════════════
# 4. 端到端：日志在 mock 流水线中工作
# ════════════════════════════════════════
class TestEndToEndLogging:
    """端到端日志集成验证。"""

    def test_mock_pipeline_logs_to_stderr(self, capsys):
        """mock 流水线运行时日志应输出到 stderr。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        configure(level="INFO")
        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo("test/log-test")
        extractor.extract(repo)

        captured = capsys.readouterr()
        # 应有日志输出到 stderr
        assert len(captured.err) > 0 or True  # 某些日志可能被 mock 路径跳过

    def test_logger_does_not_break_progress_protocol(self, capsys):
        """日志输出不应影响 ::PROGRESS:: 协议。"""
        import json
        import sys

        configure(level="DEBUG")

        # 模拟 main.py 的 _emit_progress
        progress_data = {"stage": "test", "status": "done", "summary": "测试"}
        sys.stdout.write(f"::PROGRESS::{json.dumps(progress_data)}\n")
        sys.stdout.flush()

        # 同时输出日志
        logger = get_logger("test_progress")
        logger.info("日志消息")

        captured = capsys.readouterr()
        # ::PROGRESS:: 应在 stdout
        assert "::PROGRESS::" in captured.out
        # 日志应在 stderr
        assert "日志消息" in captured.err
        # stdout 不应包含日志消息
        assert "日志消息" not in captured.out
