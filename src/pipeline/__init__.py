"""流水线编排包 — 公共 API。

导入此包即可使用 Pipeline 编排器和所有阶段类。

使用方式：
    from src.pipeline import Pipeline, PipelineContext

    pipeline = Pipeline(config, dry_run=True)
    episode = pipeline.run(repo_urls=["https://github.com/..."])

设计原则（第一性原理）：
  1. 编排与执行分离：Pipeline 调度，Stage 执行
  2. 数据流显式：所有共享数据通过 PipelineContext 传递
  3. 可扩展：新增阶段通过实现 PipelineStage 接口 + add_stage()
"""
from __future__ import annotations

from .base import PipelineContext, PipelineStage, PipelineStageError
from .stages import (
    DiscoveryStage,
    CrawlStage,
    DeepExtractStage,
    AnalyzeStage,
    CompareStage,
    ScriptStage,
    TTSStage,
    AudioMixStage,
    PublishStage,
)
from .orchestrator import Pipeline

__all__ = [
    # Core
    "Pipeline",
    "PipelineContext",
    "PipelineStage",
    "PipelineStageError",
    # Stages
    "DiscoveryStage",
    "CrawlStage",
    "DeepExtractStage",
    "AnalyzeStage",
    "CompareStage",
    "ScriptStage",
    "TTSStage",
    "AudioMixStage",
    "PublishStage",
]
