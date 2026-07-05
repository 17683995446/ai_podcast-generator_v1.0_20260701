"""后台任务状态管理（基于 Huey 任务队列）。

使用 Huey 的 SqliteHuey 作为任务后端，通过共享 _progress 字典实时跟踪进度。
保持与旧版 TaskManager 相同的公开 API，确保路由层无需修改。

替换前（旧版）：
  - threading.Thread + subprocess.Popen 手写任务管理
  - in-memory dict + RLock 手写状态管理
  - 无任务持久化、无结果存储

替换后（Huey）：
  - SqliteHuey 提供任务队列与结果存储（SQLite 持久化）
  - 消费者线程自动出队执行
  - 标准 Huey API：enqueue / revoke / result
"""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

from .huey_app import (
    huey,
    run_pipeline_task,
    _progress,
    _progress_lock,
)

# 进度事件前缀（与 main.py 的 _emit_progress 保持一致）
_PROGRESS_PREFIX = "::PROGRESS::"

# 流水线总阶段数（与 PipelineReporter.STAGES 一致，通过常量引用避免硬编码）
try:
    from src.config_defaults import PIPELINE_TOTAL_STAGES as _TOTAL_STAGES
except ImportError:
    _TOTAL_STAGES = 9


def _parse_progress_from_log(log_lines: list[str]) -> dict | None:
    """从日志行中解析结构化进度事件。

    main.py 的 PipelineReporter 通过 stdout 输出 ::PROGRESS::{json} 行，
    这些行被 Huey 捕获到 _progress["log"]。本函数扫描日志，提取最新的
    每个阶段状态，构建 pipeline_progress 对象供前端渲染。

    Returns:
        包含 stages 和 current_stage 的字典，无进度事件时返回 None。
    """
    stages: dict[str, dict] = {}
    for line in log_lines:
        if not line.startswith(_PROGRESS_PREFIX):
            continue
        try:
            data = json.loads(line[len(_PROGRESS_PREFIX):])
            stage = data.get("stage", "")
            if stage:
                stages[stage] = {
                    "stage": stage,
                    "status": data.get("status", ""),
                    "label": data.get("label", ""),
                    "summary": data.get("summary", ""),
                }
        except (json.JSONDecodeError, KeyError):
            continue

    if not stages:
        return None

    # 找出当前正在运行的阶段
    current_stage = None
    for stage_info in stages.values():
        if stage_info["status"] == "running":
            current_stage = stage_info["stage"]
            break

    completed = sum(1 for s in stages.values() if s["status"] == "done")
    total_stages = _TOTAL_STAGES  # 与 PipelineReporter.STAGES 一致
    progress_percent = round(completed / total_stages * 100) if total_stages > 0 else 0

    return {
        "stages": stages,
        "current_stage": current_stage,
        "completed_stages": completed,
        "total_stages": total_stages,
        "progress_percent": progress_percent,
    }


class TaskManager:
    """基于 Huey 的任务管理器（模块级单例）。

    公开 API 与旧版完全一致：
      - lock: RLock 属性（路由层用于原子操作）
      - is_running() -> bool
      - start_task(task_type, cmd, cwd) -> None
      - cancel_task() -> bool
      - force_reset() -> None
      - get_status() -> dict
      - append_log(line) -> None
      - get_log_tail(n) -> list[str]
    """

    def __init__(self):
        self._lock = _progress_lock
        self._current_result = None  # Huey Result 包装器

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def is_running(self) -> bool:
        with self._lock:
            return _progress["running"]

    def start_task(self, task_type: str, cmd: list[str], cwd: str) -> None:
        """初始化任务状态并入队 Huey 任务（调用方需持有 lock）。

        Args:
            task_type: 任务类型描述（如 "单期生成"）
            cmd: 命令列表（如 [sys.executable, "main.py", "run"]）
            cwd: 工作目录
        """
        _progress.update({
            "running": True,
            "type": task_type,
            "progress": "",
            "log": [],
            "done": False,
            "_proc": None,
        })
        # 入队 Huey 任务
        # immediate 模式：同步执行（测试用）
        # 正常模式：入队后由消费者线程异步执行
        self._current_result = run_pipeline_task(cmd, cwd, task_type)

    def cancel_task(self) -> bool:
        """终止当前正在运行的任务（杀死子进程 + 撤销 Huey 任务）。

        Returns:
            True 表示已发送终止信号，False 表示没有正在运行的任务。
        """
        with self._lock:
            if not _progress["running"]:
                return False

            # 1. 终止子进程
            proc = _progress.get("_proc")
            if proc is not None and proc.poll() is None:
                try:
                    # 先尝试优雅终止，再强制杀死
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=3)
                    _progress["log"].append("[仪表盘] 任务已被用户取消")
                except Exception as e:
                    _progress["log"].append(f"[仪表盘] 取消任务时出错: {e}")
                    try:
                        proc.kill()
                    except Exception:
                        pass

            # 2. 撤销 Huey 任务（防止待执行的任务被消费者拾取）
            if self._current_result is not None:
                try:
                    huey.revoke_by_id(self._current_result.task.id)
                except Exception:
                    pass
                self._current_result = None

            # 3. 标记任务结束
            _progress["running"] = False
            _progress["done"] = True
            _progress["progress"] = "任务已取消"
            _progress["_proc"] = None
            return True

    def force_reset(self) -> None:
        """强制重置任务状态（用于子进程异常退出但状态未清理的情况）。"""
        with self._lock:
            # 如果有残留子进程，尝试杀死
            proc = _progress.get("_proc")
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            _progress["_proc"] = None
            _progress["running"] = False
            _progress["done"] = False
            _progress["progress"] = ""
            _progress["log"].append("[仪表盘] 任务状态已强制重置")

    def get_status(self) -> dict:
        """获取当前状态（读取后自动重置 done 标志）。"""
        with self._lock:
            running = _progress["running"]
            done = _progress["done"]
            log_lines = list(_progress["log"][-50:])
            response = {
                "running": running,
                "type": _progress["type"],
                "progress": _progress["progress"],
                "log": log_lines,
                "done": done,
                "pipeline_progress": _parse_progress_from_log(log_lines),
            }
            # 任务已完成且未运行时，通知前端后重置 done 标志
            if done and not running:
                _progress["done"] = False
        return response

    def append_log(self, line: str) -> None:
        """追加日志。"""
        with self._lock:
            _progress["log"].append(line)
            _progress["progress"] = line
            if len(_progress["log"]) > 500:
                _progress["log"] = _progress["log"][-500:]

    def get_log_tail(self, n: int = 50) -> list[str]:
        """获取最后 n 行日志。"""
        with self._lock:
            return list(_progress["log"][-n:]) if _progress["log"] else []


# 模块级单例
task_manager = TaskManager()
