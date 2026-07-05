"""Stage 7 单元测试：验证 Huey 任务队列集成。

覆盖范围：
  1. TaskManager API 兼容性（与旧版接口一致）
  2. Huey immediate 模式同步执行
  3. get_status 返回格式正确
  4. is_running 状态追踪
  5. cancel_task 终止子进程
  6. force_reset 强制重置
  7. append_log / get_log_tail 日志管理
  8. run_pipeline_task 任务函数执行
  9. 进度跟踪（日志更新、进度字符串）
  10. 消费者线程启动/停止
  11. 错误处理（子进程失败）
  12. 日志截断（最大 500 行）

运行：python -m pytest tests/test_stage7_huey.py -v
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 在导入 dashboard 模块前设置 immediate 模式
os.environ["HUEY_IMMEDIATE"] = "1"

from dashboard.huey_app import (
    huey,
    run_pipeline_task,
    _progress,
    _progress_lock,
    start_consumer,
    stop_consumer,
    reset_progress,
)
from dashboard.task_manager import TaskManager, task_manager


# ═══════════════════════════════════════════════════════════════
# 测试夹具
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_state():
    """每个测试前重置进度状态。"""
    reset_progress()
    # 确保 immediate 模式
    huey.immediate = True
    yield
    reset_progress()


@pytest.fixture
def fresh_task_manager():
    """创建全新的 TaskManager 实例（避免单例状态污染）。"""
    return TaskManager()


# ═══════════════════════════════════════════════════════════════
# 1. API 兼容性测试
# ═══════════════════════════════════════════════════════════════


class TestAPICompatibility:
    """TaskManager 公开 API 与旧版兼容。"""

    def test_has_lock_property(self, fresh_task_manager):
        """应有 lock 属性。"""
        assert hasattr(fresh_task_manager, "lock")
        assert fresh_task_manager.lock is not None

    def test_has_is_running_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "is_running", None))

    def test_has_start_task_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "start_task", None))

    def test_has_cancel_task_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "cancel_task", None))

    def test_has_force_reset_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "force_reset", None))

    def test_has_get_status_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "get_status", None))

    def test_has_append_log_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "append_log", None))

    def test_has_get_log_tail_method(self, fresh_task_manager):
        assert callable(getattr(fresh_task_manager, "get_log_tail", None))

    def test_module_singleton_exists(self):
        """模块级单例 task_manager 应存在。"""
        assert task_manager is not None
        assert isinstance(task_manager, TaskManager)


# ═══════════════════════════════════════════════════════════════
# 2. 基础状态测试
# ═══════════════════════════════════════════════════════════════


class TestInitialState:
    """初始状态测试。"""

    def test_initial_not_running(self, fresh_task_manager):
        """初始状态不应有任务运行。"""
        assert fresh_task_manager.is_running() is False

    def test_initial_status_format(self, fresh_task_manager):
        """get_status 应返回正确的字典格式。"""
        status = fresh_task_manager.get_status()
        assert "running" in status
        assert "type" in status
        assert "progress" in status
        assert "log" in status
        assert "done" in status
        assert isinstance(status["log"], list)

    def test_initial_log_empty(self, fresh_task_manager):
        """初始日志应为空。"""
        assert fresh_task_manager.get_log_tail() == []

    def test_status_does_not_include_proc(self, fresh_task_manager):
        """get_status 不应包含内部 _proc 字段。"""
        status = fresh_task_manager.get_status()
        assert "_proc" not in status


# ═══════════════════════════════════════════════════════════════
# 3. 任务执行测试（immediate 模式）
# ═══════════════════════════════════════════════════════════════


class TestTaskExecution:
    """任务执行测试（使用 immediate 模式同步执行）。"""

    def test_simple_echo_command(self, fresh_task_manager, tmp_path):
        """执行简单 echo 命令应成功。"""
        cmd = ["echo", "hello-world"]
        fresh_task_manager.start_task("测试任务", cmd, str(tmp_path))

        # immediate 模式下任务同步完成
        status = fresh_task_manager.get_status()
        assert "hello-world" in status["log"]
        assert "完成" in status["progress"]

    def test_python_print_command(self, fresh_task_manager, tmp_path):
        """执行 Python print 命令应成功。"""
        cmd = [sys.executable, "-c", "print('test-output-line')"]
        fresh_task_manager.start_task("Python测试", cmd, str(tmp_path))

        status = fresh_task_manager.get_status()
        assert "test-output-line" in status["log"]

    def test_progress_updates_during_execution(self, fresh_task_manager, tmp_path):
        """任务执行期间应更新进度字符串。"""
        cmd = [sys.executable, "-c", "print('line1'); print('line2'); print('line3')"]
        fresh_task_manager.start_task("多行输出", cmd, str(tmp_path))

        status = fresh_task_manager.get_status()
        assert "line3" in status["log"]
        assert status["progress"]  # 进度不应为空

    def test_task_completes_sets_done(self, fresh_task_manager, tmp_path):
        """任务完成后 done 标志应被设置。"""
        cmd = ["echo", "done-test"]
        fresh_task_manager.start_task("完成测试", cmd, str(tmp_path))

        # 第一次 get_status 应显示 done=True
        status = fresh_task_manager.get_status()
        assert status["done"] is True
        assert status["running"] is False

    def test_done_flag_resets_after_read(self, fresh_task_manager, tmp_path):
        """done 标志读取后应自动重置。"""
        cmd = ["echo", "reset-test"]
        fresh_task_manager.start_task("重置测试", cmd, str(tmp_path))

        status1 = fresh_task_manager.get_status()
        assert status1["done"] is True

        status2 = fresh_task_manager.get_status()
        assert status2["done"] is False

    def test_failed_command_exit_code(self, fresh_task_manager, tmp_path):
        """命令失败时应记录退出码。"""
        cmd = [sys.executable, "-c", "import sys; sys.exit(1)"]
        fresh_task_manager.start_task("失败测试", cmd, str(tmp_path))

        status = fresh_task_manager.get_status()
        assert "完成" in status["progress"]
        assert "1" in status["progress"]


# ═══════════════════════════════════════════════════════════════
# 4. 取消任务测试
# ═══════════════════════════════════════════════════════════════


class TestCancelTask:
    """cancel_task 测试。"""

    def test_cancel_when_not_running_returns_false(self, fresh_task_manager):
        """无任务运行时取消应返回 False。"""
        assert fresh_task_manager.cancel_task() is False

    def test_cancel_running_task(self, fresh_task_manager, tmp_path):
        """取消正在运行的任务应返回 True。"""
        # 手动设置运行状态（模拟任务正在运行）
        with _progress_lock:
            _progress["running"] = True
            _progress["_proc"] = None  # 无实际子进程

        result = fresh_task_manager.cancel_task()
        assert result is True
        assert fresh_task_manager.is_running() is False

    def test_cancel_sets_progress_message(self, fresh_task_manager, tmp_path):
        """取消后进度应显示取消消息。"""
        with _progress_lock:
            _progress["running"] = True

        fresh_task_manager.cancel_task()
        status = fresh_task_manager.get_status()
        assert "取消" in status["progress"]


# ═══════════════════════════════════════════════════════════════
# 5. force_reset 测试
# ═══════════════════════════════════════════════════════════════


class TestForceReset:
    """force_reset 测试。"""

    def test_reset_clears_running_state(self, fresh_task_manager):
        """重置后 running 应为 False。"""
        with _progress_lock:
            _progress["running"] = True
            _progress["done"] = True

        fresh_task_manager.force_reset()
        assert fresh_task_manager.is_running() is False

    def test_reset_adds_log_message(self, fresh_task_manager):
        """重置应添加日志消息。"""
        fresh_task_manager.force_reset()
        logs = fresh_task_manager.get_log_tail()
        assert any("重置" in line for line in logs)

    def test_reset_clears_progress(self, fresh_task_manager):
        """重置后 progress 应为空。"""
        with _progress_lock:
            _progress["progress"] = "some progress"

        fresh_task_manager.force_reset()
        status = fresh_task_manager.get_status()
        assert status["progress"] == ""


# ═══════════════════════════════════════════════════════════════
# 6. 日志管理测试
# ═══════════════════════════════════════════════════════════════


class TestLogManagement:
    """append_log / get_log_tail 测试。"""

    def test_append_single_log(self, fresh_task_manager):
        """追加单条日志。"""
        fresh_task_manager.append_log("测试日志1")
        logs = fresh_task_manager.get_log_tail()
        assert "测试日志1" in logs

    def test_append_multiple_logs(self, fresh_task_manager):
        """追加多条日志。"""
        for i in range(10):
            fresh_task_manager.append_log(f"日志_{i}")
        logs = fresh_task_manager.get_log_tail(5)
        assert len(logs) == 5
        assert "日志_9" in logs[-1]

    def test_get_log_tail_n(self, fresh_task_manager):
        """get_log_tail(n) 返回最后 n 条。"""
        for i in range(20):
            fresh_task_manager.append_log(f"line_{i}")
        logs = fresh_task_manager.get_log_tail(3)
        assert len(logs) == 3
        assert "line_19" in logs[-1]

    def test_log_truncation_at_500(self, fresh_task_manager):
        """日志超过 500 行应自动截断。"""
        for i in range(550):
            fresh_task_manager.append_log(f"line_{i}")
        logs = fresh_task_manager.get_log_tail(600)
        assert len(logs) <= 500
        # 最早的日志应被删除
        assert "line_0" not in logs
        # 最新的日志应保留
        assert "line_549" in logs[-1]


# ═══════════════════════════════════════════════════════════════
# 7. Huey 集成测试
# ═══════════════════════════════════════════════════════════════


class TestHueyIntegration:
    """Huey 任务队列集成测试。"""

    def test_huey_instance_is_sqlite(self):
        """Huey 实例应为 SqliteHuey。"""
        from huey import SqliteHuey
        assert isinstance(huey, SqliteHuey)

    def test_immediate_mode_enabled(self):
        """测试环境应启用 immediate 模式。"""
        assert huey.immediate is True

    def test_run_pipeline_task_is_registered(self):
        """run_pipeline_task 应被 Huey 注册为任务。"""
        assert hasattr(run_pipeline_task, "huey")
        assert run_pipeline_task.huey is huey

    def test_task_returns_exit_code(self, tmp_path):
        """任务应返回子进程退出码。"""
        cmd = [sys.executable, "-c", "import sys; sys.exit(42)"]
        result = run_pipeline_task(cmd, str(tmp_path), "退出码测试")
        assert result.get() == 42

    def test_task_stdout_captured_in_progress(self, tmp_path):
        """任务 stdout 应被捕获到 _progress["log"]。"""
        cmd = [sys.executable, "-c", "print('captured-output')"]
        run_pipeline_task(cmd, str(tmp_path), "捕获测试")

        with _progress_lock:
            assert any("captured-output" in line for line in _progress["log"])


# ═══════════════════════════════════════════════════════════════
# 8. 消费者线程测试
# ═══════════════════════════════════════════════════════════════


class TestConsumerThread:
    """消费者线程测试。"""

    def test_start_consumer_in_immediate_mode_returns_none(self):
        """immediate 模式下 start_consumer 应返回 None。"""
        result = start_consumer()
        assert result is None

    def test_stop_consumer_does_not_crash(self):
        """stop_consumer 应正常执行。"""
        stop_consumer()  # 不应抛出异常


# ═══════════════════════════════════════════════════════════════
# 9. 并发安全测试
# ═══════════════════════════════════════════════════════════════


class TestThreadSafety:
    """线程安全测试。"""

    def test_concurrent_append_log(self, fresh_task_manager):
        """并发追加日志不应丢失数据。"""
        import threading

        def append_batch(start, count):
            for i in range(start, start + count):
                fresh_task_manager.append_log(f"thread_{i}")

        threads = [
            threading.Thread(target=append_batch, args=(i * 100, 100))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        logs = fresh_task_manager.get_log_tail(1000)
        assert len(logs) == 500  # 5 threads × 100 logs each

    def test_lock_is_reentrant(self, fresh_task_manager):
        """RLock 应允许同线程重入。"""
        with fresh_task_manager.lock:
            # 在持锁状态下调用需要锁的方法
            fresh_task_manager.append_log("reentrant-test")
            logs = fresh_task_manager.get_log_tail()
            assert "reentrant-test" in logs


# ═══════════════════════════════════════════════════════════════
# 10. 路由集成测试（验证 API 不变）
# ═══════════════════════════════════════════════════════════════


class TestRouteIntegration:
    """验证路由层 API 不变。"""

    def test_task_status_route_format(self, fresh_task_manager):
        """get_status 返回格式与路由期望一致。"""
        fresh_task_manager.append_log("route-test")
        status = fresh_task_manager.get_status()

        # 路由直接 jsonify(status)，前端期望这些字段
        required_keys = {"running", "type", "progress", "log", "done"}
        assert required_keys.issubset(set(status.keys()))

    def test_start_task_lock_pattern(self, fresh_task_manager, tmp_path):
        """验证路由层的 lock 使用模式。"""
        cmd = ["echo", "lock-pattern-test"]

        # 模拟路由代码
        with fresh_task_manager.lock:
            if fresh_task_manager.is_running():
                pass  # would return 409
            else:
                fresh_task_manager.start_task("锁模式测试", cmd, str(tmp_path))

        status = fresh_task_manager.get_status()
        assert "lock-pattern-test" in status["log"]
