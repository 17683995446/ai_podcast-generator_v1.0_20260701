"""后台任务状态管理（线程安全）。"""
from __future__ import annotations

import os
import subprocess
import threading
from typing import Any


class TaskManager:
    """单例任务管理器，管理后台子进程任务。"""

    def __init__(self):
        self._state: dict[str, Any] = {
            "running": False,
            "type": "",
            "progress": "",
            "log": [],
            "done": False,
        }
        # 使用可重入锁，允许在已持锁上下文中调用 is_running() 等方法
        self._lock = threading.RLock()
        # 当前子进程引用（供 cancel_task 终止使用）
        self._proc: subprocess.Popen | None = None

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def is_running(self) -> bool:
        with self._lock:
            return self._state["running"]

    def start_task(self, task_type: str, cmd: list[str], cwd: str) -> None:
        """初始化任务状态并启动后台线程（调用方需持有 lock）。"""
        self._state.update({
            "running": True,
            "type": task_type,
            "progress": "",
            "log": [],
            "done": False,
        })

        thread = threading.Thread(target=self._worker, args=(cmd, cwd), daemon=True)
        thread.start()

    def cancel_task(self) -> bool:
        """终止当前正在运行的任务（杀死子进程）。

        Returns:
            True 表示已发送终止信号，False 表示没有正在运行的任务。
        """
        with self._lock:
            if not self._state["running"]:
                return False
            proc = self._proc
            if proc is not None and proc.poll() is None:
                try:
                    # 先尝试优雅终止，再强制杀死
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    self._state["log"].append("[仪表盘] 任务已被用户取消")
                except Exception as e:
                    self._state["log"].append(f"[仪表盘] 取消任务时出错: {e}")
                    try:
                        proc.kill()
                    except Exception:
                        pass
            # 标记任务结束
            self._state["running"] = False
            self._state["done"] = True
            self._state["progress"] = "任务已取消"
            self._proc = None
            return True

    def force_reset(self) -> None:
        """强制重置任务状态（用于子进程异常退出但状态未清理的情况）。"""
        with self._lock:
            # 如果有残留子进程，尝试杀死
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._state["running"] = False
            self._state["done"] = False
            self._state["progress"] = ""
            self._state["log"].append("[仪表盘] 任务状态已强制重置")

    def get_status(self) -> dict:
        """获取当前状态（读取后自动重置 done 标志）。"""
        with self._lock:
            running = self._state["running"]
            done = self._state["done"]
            response = {
                "running": running,
                "type": self._state["type"],
                "progress": self._state["progress"],
                "log": list(self._state["log"][-50:]),
                "done": done,
            }
            # 任务已完成且未运行时，通知前端后重置 done 标志，避免前端无限刷新
            if done and not running:
                self._state["done"] = False
        return response

    def _worker(self, cmd: list[str], cwd: str) -> None:
        """后台工作线程。"""
        proc = None
        try:
            # 设置 PYTHONUNBUFFERED 避免子进程缓冲导致日志延迟
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
            # 保存子进程引用，供 cancel_task 使用
            with self._lock:
                self._proc = proc
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    with self._lock:
                        self._state["log"].append(line)
                        self._state["progress"] = line
                        # 保留最近 500 行
                        if len(self._state["log"]) > 500:
                            self._state["log"] = self._state["log"][-500:]
            proc.wait()
            with self._lock:
                self._state["progress"] = f"完成（退出码 {proc.returncode}）"
        except Exception as e:
            with self._lock:
                self._state["log"].append(f"[仪表盘错误] {type(e).__name__}: {e}")
                self._state["progress"] = f"任务异常: {e}"
        finally:
            # 关闭 stdout 并清理可能残留的子进程
            if proc is not None:
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except Exception:
                        pass
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        pass
            # 确保无论成功或异常都重置运行状态并标记完成
            with self._lock:
                self._state["running"] = False
                self._state["done"] = True

    def append_log(self, line: str) -> None:
        """追加日志。"""
        with self._lock:
            self._state["log"].append(line)
            self._state["progress"] = line
            # 保留最近 500 行
            if len(self._state["log"]) > 500:
                self._state["log"] = self._state["log"][-500:]

    def get_log_tail(self, n: int = 50) -> list[str]:
        """获取最后 n 行日志。"""
        with self._lock:
            return list(self._state["log"][-n:]) if self._state["log"] else []


# 模块级单例
task_manager = TaskManager()
