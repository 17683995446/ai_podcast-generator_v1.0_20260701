"""流水线编排基础设施 — PipelineContext + PipelineStage ABC。

设计原则（第一性原理）：
  1. 单一职责：每个 Stage 只负责一个流水线阶段
  2. 开闭原则：新增阶段通过实现 PipelineStage 接口，无需修改现有代码
  3. 依赖倒置：Pipeline 依赖 Stage 抽象，不依赖具体实现
  4. 可测试性：每个 Stage 可独立测试，PipelineContext 提供隔离的测试上下文
  5. 显式数据流：所有阶段间共享数据通过 PipelineContext 传递，无隐式全局状态

PipelineContext 是所有阶段共享的数据容器，替代原来 run_pipeline 中的局部变量。
每个阶段从 context 读取输入、写入输出，形成显式的数据流管道。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.models import GitHubRepo, PodcastScript, Episode, ProjectAnalysis
from src.pipeline_reporter import PipelineReporter


@dataclass
class PipelineContext:
    """流水线上下文 — 阶段间共享的数据容器。

    替代 run_pipeline 中的局部变量，使数据流显式可追踪。
    每个阶段从 context 读取所需输入，将输出写入 context。
    """

    # ── 配置与模式 ──
    config: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    mock_data: bool = False
    quiet: bool = False
    style: str = "casual"
    longform: bool = False

    # ── 用户输入 ──
    repo_urls: list[str] | None = None
    topic: str | None = None

    # ── 阶段产出（按流水线顺序）──
    repos: list[GitHubRepo] = field(default_factory=list)
    evidence_map: dict[str, list[dict]] = field(default_factory=dict)
    health_data_list: list[dict] = field(default_factory=list)
    code_metrics_map: dict[str, dict] = field(default_factory=dict)
    analyses: list[ProjectAnalysis] = field(default_factory=list)
    validation_reports: dict = field(default_factory=dict)
    comparison_data: dict | None = None
    script: PodcastScript | None = None
    audio_files: list[Path] = field(default_factory=list)
    episode: Episode | None = None
    ep_num: int = 0

    # ── 基础设施 ──
    reporter: PipelineReporter | None = None
    extractor: Any = None  # DeepExtractor 实例（跨阶段复用）
    publisher: Any = None  # RSSPublisher 实例（跨阶段复用）

    @property
    def project_root(self) -> Path:
        """项目根目录的 Path 对象。"""
        return Path(self.config.get("project_root", "."))

    @property
    def output_dir(self) -> Path:
        """输出目录。"""
        return self.project_root / "output"

    def emit_progress(self, stage: str, status: str, summary: str = "",
                      details: dict | None = None) -> None:
        """向 stdout 输出结构化进度事件（供仪表盘实时解析）。

        封装了原来 main.py 中的 _emit_progress 函数，
        消除了对 reporter._events 的直接访问。
        """
        import json
        import sys

        if self.reporter is None:
            return
        label = self.reporter.get_stage_label(stage)
        data: dict[str, Any] = {
            "stage": stage,
            "status": status,
            "label": label,
            "summary": summary,
        }
        if details:
            data["details"] = details
        sys.stdout.write(f"::PROGRESS::{json.dumps(data, ensure_ascii=False)}\n")
        sys.stdout.flush()


class PipelineStageError(Exception):
    """阶段执行错误。"""


class PipelineStage(ABC):
    """流水线阶段抽象基类。

    每个具体阶段实现 execute() 方法，从 context 读取输入、写入输出。
    可选实现 should_run() 方法控制条件执行（如跨项目对比仅多项目时运行）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """阶段标识（如 "discovery" / "crawl" / "analyze"）。"""

    @property
    def label(self) -> str:
        """阶段中文标签（供报告器使用）。"""
        return self.name

    def should_run(self, ctx: PipelineContext) -> bool:
        """是否应该执行此阶段（默认 True）。

        子类可覆盖以实现条件执行，如跨项目对比仅在多项目时运行。
        """
        return True

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> None:
        """执行此阶段的核心逻辑。

        Args:
            ctx: 流水线上下文，包含输入数据和写入输出的容器

        Raises:
            PipelineStageError: 阶段执行失败时抛出
        """
