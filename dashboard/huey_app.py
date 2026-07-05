"""Huey 任务队列集成。

使用 SqliteHuey 作为后端（无需外部 Redis），在 Flask 进程内启动消费者线程。
替代原有的手写线程+subprocess 任务管理器，获得以下优势：
  - 任务持久化（SQLite 存储，Flask 重启后可恢复）
  - 标准化任务生命周期（queued → executing → complete/failed）
  - 结果存储与查询（huey.result() / huey.all_results()）
  - 任务撤销（huey.revoke_by_id()）

任务流程：
  1. Flask 路由调用 TaskManager.start_task()
  2. TaskManager 通过 Huey 入队任务
  3. 消费者线程出队并执行任务（subprocess）
  4. 任务执行期间通过共享 _progress 字典实时更新进度
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import logging
from typing import Any

from huey import SqliteHuey

from .config import PROJECT_ROOT

# ═══════════════════════════════════════════════════════════════
# Huey 实例
# ═══════════════════════════════════════════════════════════════

HUEY_DB_PATH = str(PROJECT_ROOT / "output" / ".huey.sqlite")

huey = SqliteHuey(
    "github-podcast",
    filename=HUEY_DB_PATH,
    # immediate=True 时任务同步执行（用于测试环境）
    immediate=os.environ.get("HUEY_IMMEDIATE", "").lower() in ("1", "true", "yes"),
)

# ═══════════════════════════════════════════════════════════════
# 共享进度状态（线程安全）
# ═══════════════════════════════════════════════════════════════
# 注意：始终通过 _progress["key"] 修改，不要重新赋值 _progress 本身
# _proc 为内部字段，不包含在 get_status() 返回中

_progress: dict[str, Any] = {
    "running": False,
    "type": "",
    "progress": "",
    "log": [],
    "done": False,
    "_proc": None,  # subprocess.Popen 引用（内部使用）
}
_progress_lock = threading.RLock()


# ═══════════════════════════════════════════════════════════════
# Huey 任务定义
# ═══════════════════════════════════════════════════════════════

@huey.task()
def run_pipeline_task(cmd: list[str], cwd: str, task_type: str = "") -> int:
    """运行管线命令的 Huey 任务。

    在消费者线程中执行，通过共享 _progress 字典实时更新进度。
    调用方（TaskManager.start_task）负责初始化 _progress["running"] = True，
    本任务在结束时设置 _progress["running"] = False, _progress["done"] = True。

    包含子进程超时保护：默认 3600 秒（1 小时），超时后自动终止子进程。

    Args:
        cmd: 命令列表（如 [sys.executable, "main.py", "run"]）
        cwd: 工作目录
        task_type: 任务类型描述

    Returns:
        子进程退出码
    """
    # 子进程超时（秒）：单期生成最多 1 小时，批量生成可能更久
    # 通过环境变量可覆盖（如测试环境设为更短时间）
    _timeout = int(os.environ.get("PIPELINE_TIMEOUT", "3600"))

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    with _progress_lock:
        _progress["_proc"] = proc

    start_time = time.time()
    timed_out = False

    try:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                with _progress_lock:
                    _progress["log"].append(line)
                    _progress["progress"] = line
                    if len(_progress["log"]) > 500:
                        _progress["log"] = _progress["log"][-500:]

            # 超时检查：子进程运行过久则终止
            elapsed = time.time() - start_time
            if elapsed > _timeout:
                timed_out = True
                with _progress_lock:
                    _progress["log"].append(
                        f"[huey] 任务超时（{_timeout}s），正在终止子进程..."
                    )
                    _progress["progress"] = f"任务超时（{_timeout}s）"
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                break

        if not timed_out:
            proc.wait()
        return_code = proc.returncode

        with _progress_lock:
            if timed_out:
                _progress["progress"] = f"任务超时已终止（退出码 {return_code}）"
                _progress["log"].append(f"[huey] 任务超时已终止，退出码 {return_code}")
            else:
                _progress["progress"] = f"完成（退出码 {return_code}）"
        return return_code
    except Exception as e:
        with _progress_lock:
            _progress["log"].append(f"[huey] 任务异常: {type(e).__name__}: {e}")
            _progress["progress"] = f"任务异常: {e}"
        raise
    finally:
        # 清理子进程资源
        if proc.stdout:
            try:
                proc.stdout.close()
            except Exception as e:
                logging.warning("关闭子进程 stdout 失败: %s", e)
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception as e:
                logging.warning("终止子进程失败: %s", e)
        with _progress_lock:
            _progress["running"] = False
            _progress["done"] = True
            _progress["_proc"] = None


# ═══════════════════════════════════════════════════════════════
# 消费者线程
# ═══════════════════════════════════════════════════════════════

_consumer_thread: threading.Thread | None = None
_consumer_running = False


def start_consumer() -> threading.Thread:
    """启动 Huey 消费者守护线程。

    消费者线程在后台轮询任务队列，出队并执行任务。
    在 Flask 应用启动时调用一次即可。immediate 模式下不需要消费者。
    """
    global _consumer_thread, _consumer_running

    # immediate 模式下任务同步执行，不需要消费者线程
    if huey.immediate:
        print("[huey] immediate 模式，跳过消费者线程启动")
        return None

    if _consumer_thread is not None and _consumer_thread.is_alive():
        return _consumer_thread

    _consumer_running = True

    def _consumer_loop():
        """消费者主循环：出队 → 执行 → 轮询。"""
        while _consumer_running:
            try:
                task = huey.dequeue()
                if task is not None:
                    huey.execute(task)
                else:
                    time.sleep(0.5)
            except Exception as e:
                print(f"[huey] 消费者异常: {type(e).__name__}: {e}")
                time.sleep(1.0)

    _consumer_thread = threading.Thread(
        target=_consumer_loop, daemon=True, name="huey-consumer"
    )
    _consumer_thread.start()
    print("[huey] 消费者线程已启动")
    return _consumer_thread


def stop_consumer() -> None:
    """停止消费者线程（用于测试或优雅关闭）。"""
    global _consumer_running
    _consumer_running = False


def reset_progress() -> None:
    """重置共享进度状态（用于测试）。"""
    with _progress_lock:
        _progress["running"] = False
        _progress["type"] = ""
        _progress["progress"] = ""
        _progress["log"] = []
        _progress["done"] = False
        _progress["_proc"] = None
