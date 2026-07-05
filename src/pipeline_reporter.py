"""流水线进度报告器：实时追踪生成过程，记录检查点，生成最终报告。

核心职责：
  1. 追踪 8 个阶段的实时进度（发现→抓取→深提取→分析→对比→脚本→TTS→混音）
  2. 记录每个阶段的中间产物摘要（发现了什么、提取了什么、生成了什么）
  3. 持久化检查点数据（支持断点续传时的状态恢复）
  4. 生成最终制作报告（评审分数、重写次数、覆盖率等）

设计原则（第一性原理）：
  - 报告器是被动观察者，不干预流水线执行
  - 所有方法线程安全（与 Huey 任务队列兼容）
  - 检查点数据可序列化为 JSON，独立于运行时内存
  - 前端可通过 API 轮询实时获取进度
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class StageEvent:
    """单个阶段事件。"""
    stage: str = ""           # 阶段标识：discovery / crawl / deep_extract / analyze / compare / script / tts / mix / publish
    stage_label: str = ""     # 中文标签：项目发现 / README抓取 / 深度提取 ...
    status: str = "pending"   # pending / running / done / failed / skipped
    started_at: float = 0.0   # 开始时间戳
    finished_at: float = 0.0  # 完成时间戳
    duration_ms: int = 0      # 耗时（毫秒）
    summary: str = ""         # 阶段摘要（如"发现 3 个项目"）
    details: dict = field(default_factory=dict)  # 详细数据（如项目列表、文件数等）
    error: str = ""           # 错误信息（失败时）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CheckpointData:
    """检查点数据——流水线中间状态的快照。"""
    episode_number: int = 0
    timestamp: float = 0.0
    stage: str = ""
    repos_found: list[str] = field(default_factory=list)
    readme_fetched: list[str] = field(default_factory=list)
    deep_extracted: list[str] = field(default_factory=list)
    analysis_completed: list[str] = field(default_factory=list)
    evidence_count: int = 0
    validation_scores: dict[str, float] = field(default_factory=dict)
    script_segments: int = 0
    script_review_score: float = 0.0
    script_rewrites: int = 0
    audio_segments: int = 0
    audio_duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class PipelineReporter:
    """流水线进度报告器。

    线程安全设计：所有公共方法都通过 _lock 保护。
    """

    # 阶段定义（有序）
    STAGES = [
        ("discovery", "项目发现"),
        ("crawl", "README抓取"),
        ("deep_extract", "深度提取"),
        ("analyze", "项目分析"),
        ("compare", "跨项目对比"),
        ("script", "脚本生成"),
        ("tts", "语音合成"),
        ("mix", "音频混音"),
        ("publish", "RSS发布"),
    ]

    def __init__(self, output_dir: str | Path = "."):
        self._lock = threading.RLock()
        self._output_dir = Path(output_dir)
        self._events: dict[str, StageEvent] = {}
        self._checkpoint = CheckpointData()
        self._report_path: Path | None = None
        self._started_at: float = 0.0
        self._finished_at: float = 0.0

        # 初始化所有阶段为 pending
        for stage_id, stage_label in self.STAGES:
            self._events[stage_id] = StageEvent(stage=stage_id, stage_label=stage_label)

    def start_pipeline(self, episode_number: int = 0) -> None:
        """标记流水线开始。"""
        with self._lock:
            self._started_at = time.time()
            self._checkpoint.episode_number = episode_number
            self._checkpoint.timestamp = self._started_at

    def start_stage(self, stage: str, summary: str = "") -> None:
        """标记某阶段开始。"""
        with self._lock:
            if stage in self._events:
                self._events[stage].status = "running"
                self._events[stage].started_at = time.time()
                self._events[stage].summary = summary

    def finish_stage(self, stage: str, summary: str = "", details: dict | None = None) -> None:
        """标记某阶段完成。"""
        with self._lock:
            if stage in self._events:
                ev = self._events[stage]
                ev.status = "done"
                ev.finished_at = time.time()
                ev.duration_ms = int((ev.finished_at - ev.started_at) * 1000) if ev.started_at else 0
                if summary:
                    ev.summary = summary
                if details:
                    ev.details = details

    def fail_stage(self, stage: str, error: str) -> None:
        """标记某阶段失败。"""
        with self._lock:
            if stage in self._events:
                ev = self._events[stage]
                ev.status = "failed"
                ev.finished_at = time.time()
                ev.duration_ms = int((ev.finished_at - ev.started_at) * 1000) if ev.started_at else 0
                ev.error = error

    def skip_stage(self, stage: str, reason: str = "") -> None:
        """标记某阶段跳过。"""
        with self._lock:
            if stage in self._events:
                self._events[stage].status = "skipped"
                self._events[stage].summary = reason

    def update_checkpoint(self, **kwargs) -> None:
        """更新检查点数据。"""
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self._checkpoint, key):
                    setattr(self._checkpoint, key, value)

    def save_checkpoint(self, filename: str = "checkpoint.json") -> Path:
        """持久化检查点到文件。"""
        with self._lock:
            path = self._output_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "checkpoint": self._checkpoint.to_dict(),
                "events": {k: v.to_dict() for k, v in self._events.items()},
                "started_at": self._started_at,
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._report_path = path
            return path

    def finish_pipeline(self) -> dict:
        """标记流水线完成并生成最终报告。"""
        with self._lock:
            self._finished_at = time.time()
            total_ms = int((self._finished_at - self._started_at) * 1000) if self._started_at else 0

            completed = sum(1 for e in self._events.values() if e.status == "done")
            failed = sum(1 for e in self._events.values() if e.status == "failed")
            skipped = sum(1 for e in self._events.values() if e.status == "skipped")

            report = {
                "episode_number": self._checkpoint.episode_number,
                "total_duration_ms": total_ms,
                "stages_completed": completed,
                "stages_failed": failed,
                "stages_skipped": skipped,
                "stages": {k: v.to_dict() for k, v in self._events.items()},
                "checkpoint": self._checkpoint.to_dict(),
                "started_at": self._started_at,
                "finished_at": self._finished_at,
            }
            return report

    def get_stage_label(self, stage: str) -> str:
        """获取阶段中文标签。

        替代外部直接访问 reporter._events[stage].stage_label。
        """
        with self._lock:
            ev = self._events.get(stage)
            return ev.stage_label if ev else stage

    def get_stage_status(self, stage: str) -> str:
        """获取阶段当前状态。

        替代外部直接访问 reporter._events[stage].status。
        """
        with self._lock:
            ev = self._events.get(stage)
            return ev.status if ev else "pending"

    def get_progress(self) -> dict:
        """获取当前进度快照（供 API 轮询）。"""
        with self._lock:
            completed = sum(1 for e in self._events.values() if e.status == "done")
            total = len(self._events)
            current_stage = next(
                (e.stage for e in self._events.values() if e.status == "running"),
                None
            )
            return {
                "total_stages": total,
                "completed_stages": completed,
                "progress_percent": round(completed / total * 100) if total > 0 else 0,
                "current_stage": current_stage,
                "stages": {k: {
                    "status": v.status,
                    "label": v.stage_label,
                    "summary": v.summary,
                    "duration_ms": v.duration_ms,
                } for k, v in self._events.items()},
                "checkpoint": self._checkpoint.to_dict(),
            }

    def generate_report(self) -> dict:
        """生成最终制作报告。"""
        with self._lock:
            total_ms = int((self._finished_at - self._started_at) * 1000) if self._started_at else 0
            cp = self._checkpoint

            return {
                "episode_number": cp.episode_number,
                "total_duration_ms": total_ms,
                "total_duration_human": _format_duration(total_ms),
                "repos_processed": len(cp.repos_found),
                "repos_found": cp.repos_found,
                "evidence_count": cp.evidence_count,
                "validation_scores": cp.validation_scores,
                "avg_validation_score": (
                    round(sum(cp.validation_scores.values()) / len(cp.validation_scores), 2)
                    if cp.validation_scores else 0.0
                ),
                "script_segments": cp.script_segments,
                "script_review_score": cp.script_review_score,
                "script_rewrites": cp.script_rewrites,
                "audio_segments": cp.audio_segments,
                "audio_duration_seconds": cp.audio_duration_seconds,
                "audio_duration_human": _format_duration(int(cp.audio_duration_seconds * 1000)),
                "stages": {k: v.to_dict() for k, v in self._events.items()},
            }


def _format_duration(ms: int) -> str:
    """将毫秒格式化为人类可读时长。"""
    if ms <= 0:
        return "0s"
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m{seconds}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h{minutes}m"
