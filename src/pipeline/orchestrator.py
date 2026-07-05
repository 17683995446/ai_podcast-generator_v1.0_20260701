"""流水线编排器 — Pipeline 类，协调各阶段执行。

设计原则（第一性原理）：
  1. 编排与执行分离：Pipeline 只负责调度，不包含业务逻辑
  2. 可组合：阶段列表可动态配置，支持增删改
  3. 错误隔离：单个阶段失败不影响其他阶段的清理
  4. 可观测：通过 reporter 提供实时进度

Pipeline 持有有序的阶段列表，按序执行每个阶段。
每个阶段通过 PipelineContext 共享数据，Pipeline 本身不持有业务状态。
"""
from __future__ import annotations

from typing import Any

from rich.console import Console

from src.config_defaults import CONSOLE_WIDTH
from src.logger import get_logger
from src.models import Episode
from src.pipeline_reporter import PipelineReporter

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

logger = get_logger(__name__)
console = Console(width=CONSOLE_WIDTH)


class Pipeline:
    """播客生成流水线编排器。

    持有有序的阶段列表，按序执行，通过 PipelineContext 传递数据。

    使用方式：
        pipeline = Pipeline(config, dry_run=True)
        episode = pipeline.run(repo_urls=["https://github.com/..."])
    """

    def __init__(
        self,
        config: dict[str, Any],
        dry_run: bool = False,
        mock_data: bool = False,
        quiet: bool = False,
        style: str = "casual",
        longform: bool = False,
    ):
        self._config = config
        self._dry_run = dry_run
        self._mock_data = mock_data
        self._quiet = quiet
        self._style = style
        self._longform = longform
        self._stages: list[PipelineStage] = self._build_default_stages()

    def _build_default_stages(self) -> list[PipelineStage]:
        """构建默认阶段列表。"""
        return [
            DiscoveryStage(),
            CrawlStage(),
            DeepExtractStage(),
            AnalyzeStage(),
            CompareStage(),
            ScriptStage(),
            TTSStage(),
            AudioMixStage(),
            PublishStage(),
        ]

    @property
    def stages(self) -> list[PipelineStage]:
        """当前阶段列表（只读）。"""
        return list(self._stages)

    def add_stage(self, stage: PipelineStage, after: str | None = None) -> None:
        """在指定阶段后插入新阶段（可扩展性入口）。

        Args:
            stage: 要插入的阶段实例
            after: 插入到哪个阶段之后（按 name 匹配），None 表示追加到末尾
        """
        if after is None:
            self._stages.append(stage)
        else:
            for i, s in enumerate(self._stages):
                if s.name == after:
                    self._stages.insert(i + 1, stage)
                    return
            self._stages.append(stage)

    def remove_stage(self, name: str) -> bool:
        """移除指定名称的阶段。

        Returns:
            True 如果成功移除，False 如果阶段不存在
        """
        for i, s in enumerate(self._stages):
            if s.name == name:
                self._stages.pop(i)
                return True
        return False

    def run(
        self,
        repos: list | None = None,
        repo_urls: list[str] | None = None,
        topic: str | None = None,
    ) -> Episode | None:
        """执行完整流水线。

        Args:
            repos: 预先指定的项目列表（批量模式）
            repo_urls: 用户指定的仓库 URL 列表
            topic: 按主题搜索

        Returns:
            生成的 Episode，失败返回 None
        """
        if not self._quiet:
            console.print("\n[bold cyan]═══ GitHub 前沿观察 · 播客生成流水线 ═══[/bold cyan]\n")

        # 构建上下文
        ctx = PipelineContext(
            config=self._config,
            dry_run=self._dry_run,
            mock_data=self._mock_data,
            quiet=self._quiet,
            style=self._style,
            longform=self._longform,
            repo_urls=repo_urls,
            topic=topic,
            repos=repos if repos else [],
            reporter=PipelineReporter(output_dir=self._config.get("project_root", ".") + "/output")
            if isinstance(self._config.get("project_root", ""), str)
            else PipelineReporter(),
        )

        # 修正 reporter output_dir
        from pathlib import Path
        ctx.reporter = PipelineReporter(
            output_dir=Path(self._config.get("project_root", ".")) / "output"
        )

        # 按序执行阶段
        for stage in self._stages:
            if not stage.should_run(ctx):
                if ctx.reporter:
                    ctx.reporter.skip_stage(stage.name, "条件不满足，跳过")
                    ctx.emit_progress(stage.name, "skipped", f"{stage.label} 跳过")
                continue

            try:
                stage.execute(ctx)
            except PipelineStageError as e:
                logger.error("阶段 %s 失败: %s", stage.name, e)
                if ctx.reporter:
                    ctx.reporter.fail_stage(stage.name, str(e))
                return None
            except Exception as e:
                logger.error("阶段 %s 异常: %s", stage.name, e, exc_info=True)
                if ctx.reporter:
                    ctx.reporter.fail_stage(stage.name, str(e))
                return None

        # 成本估算
        if ctx.script:
            _print_cost_estimate(ctx.script, ctx.config)

        if ctx.episode:
            console.print("\n[bold green]✅ 播客生成完成！[/bold green]")
            console.print(f"   音频文件：{ctx.episode.audio_path}")
            console.print(f"   时长：{ctx.episode.duration_seconds:.1f}s")
            if ctx.publisher:
                console.print(f"   RSS Feed：{ctx.publisher.feed_path}\n")

        return ctx.episode


def _print_cost_estimate(script, config) -> None:
    """打印本次生成的成本估算。"""
    from src.config_defaults import FREE_MODEL_KEYWORDS

    chars = script.total_chars()
    llm_model = config["llm"]["model"]
    tts_model = config["tts"]["model"]
    tts_provider = config["tts"].get("provider", "siliconflow")

    free_llm = any(k in llm_model for k in FREE_MODEL_KEYWORDS)
    if tts_provider == "siliconflow":
        tts_bytes = chars * 3
        tts_cost = tts_bytes / 10000 * 0.5
        if tts_bytes < 14000:
            tts_cost = 0
    else:
        tts_rate = 1.0 if "flash" in tts_model else 2.0
        tts_cost = chars / 10000 * tts_rate

    llm_cost = 0 if free_llm else 0.04
    console.print("\n[dim]── 成本估算 ──[/dim]")
    if free_llm:
        console.print(f"[dim]  LLM 模型：{llm_model}（[green]免费[/green]）[/dim]")
    else:
        console.print(f"[dim]  LLM 模型：{llm_model}（约 ¥{llm_cost:.2f}/期）[/dim]")
    if tts_cost == 0:
        console.print(f"[dim]  TTS 模型：{tts_model}，{chars} 字符（[green]免费额度内[/green]）[/dim]")
    else:
        console.print(f"[dim]  TTS 模型：{tts_model}，{chars} 字符 ≈ ¥{tts_cost:.2f}[/dim]")
    console.print(f"[dim]  合计 ≈ ¥{llm_cost + tts_cost:.2f}[/dim]")
