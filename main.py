"""主入口：编排 GitHub 项目发现 → README 抓取 → 脚本生成 → TTS → 音频后期 → RSS 发布。

用法：
    python main.py run                 # 完整生成一期播客
    python main.py run --dry-run       # 仅测试流程（mock 模式，无 API 调用）
    python main.py batch --count 50    # 批量串行生成 50 期
    python main.py discover            # 仅发现并打印项目列表
    python main.py list                # 列出已发布的节目历史
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from src.config_loader import load_config
from src.discovery import RepoDiscovery
from src.logger import get_logger, configure as configure_logging
from src.models import Episode
from src.pipeline import Pipeline

from src.config_defaults import (
    CONSOLE_WIDTH,
    FREE_MODEL_KEYWORDS,
    PODCAST_STYLES,
)

console = Console(width=CONSOLE_WIDTH)
logger = get_logger("main")


def run_pipeline(
    dry_run: bool = False,
    mock_data: bool = False,
    config_path: str = "config.yaml",
    repos: list | None = None,
    quiet: bool = False,
    repo_urls: list[str] | None = None,
    topic: str | None = None,
    style: str = "casual",
    longform: bool = False,
) -> Episode | None:
    """执行完整播客生成流水线。

    委托给 Pipeline 编排器，将 420 行 God 函数拆分为 9 个可组合 Stage 类。
    保持接口向后兼容，CLI 和 batch 模式无需修改。

    Args:
        dry_run: 干跑模式（使用 mock，不调用付费 API）。
        mock_data: 仅 mock 项目发现/抓取，但使用真实 LLM/TTS API。
        config_path: 配置文件路径。
        repos: 预先指定的项目列表（批量模式传入，跳过发现阶段）。
        quiet: 安静模式（批量生成时减少输出）。
        repo_urls: 用户指定的 GitHub 仓库 URL 列表（跳过自动发现）。
        topic: 按主题关键词搜索项目（跳过自动发现）。
        style: 播客风格预设（casual/technical/debate/interview）。
        longform: 长内容模式（25-40 分钟）。

    Returns:
        生成的 Episode，失败返回 None。
    """
    config = load_config(config_path)

    # 配置日志（支持 LOG_LEVEL 环境变量）
    log_file = Path(config.get("project_root", ".")) / "output" / "podcast.log"
    configure_logging(log_file=log_file if not dry_run else None)

    # 注入风格和长内容配置
    config["podcast_style"] = style
    config["longform"] = longform

    # 若 dry_run，清空 API keys 强制走 mock
    if dry_run:
        config["api_keys"] = {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""}
        config["_mock_mode"] = True
        if not quiet:
            console.print("[yellow]DRY-RUN 模式：使用 mock 数据，不调用付费 API[/yellow]\n")
    elif mock_data:
        config["_mock_mode"] = True
        if not quiet:
            console.print("[yellow]MOCK-DATA 模式：项目数据使用 mock，LLM/TTS 使用真实 API[/yellow]\n")

    # 委托给 Pipeline 编排器
    pipeline = Pipeline(
        config=config,
        dry_run=dry_run,
        mock_data=mock_data,
        quiet=quiet,
        style=style,
        longform=longform,
    )
    return pipeline.run(repos=repos, repo_urls=repo_urls, topic=topic)


def _print_repos(repos) -> None:
    """用 rich 表格打印项目列表。"""
    table = Table(title="发现的项目", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("项目", style="cyan")
    table.add_column("⭐", justify="right")
    table.add_column("语言", style="green")
    table.add_column("描述")
    for repo in repos:
        table.add_row(
            str(repo.trending_rank),
            repo.name,
            str(repo.stars),
            repo.language or "-",
            (repo.description[:50] + "...") if len(repo.description) > 50 else repo.description,
        )
    console.print(table)


# =====================================================================
# CLI 命令
# =====================================================================
@click.group()
def cli():
    """GitHub 前沿研究项目播客生成工具。"""
    pass


@cli.command()
@click.option("--dry-run", is_flag=True, help="干跑模式（mock，不调用付费 API）")
@click.option("--mock-data", is_flag=True, help="项目数据用 mock，LLM/TTS 用真实 API")
@click.option("--config", default="config.yaml", help="配置文件路径")
@click.option("--repo-urls", multiple=True, help="指定 GitHub 仓库 URL（可多个）")
@click.option("--topic", default="", help="按主题关键词搜索项目")
@click.option("--style", type=click.Choice(PODCAST_STYLES), default="casual", help="播客风格")
@click.option("--longform", is_flag=True, help="长内容模式（25-40 分钟）")
def run(dry_run, mock_data, config, repo_urls, topic, style, longform):
    """完整生成一期播客节目。"""
    episode = run_pipeline(
        dry_run=dry_run, mock_data=mock_data, config_path=config,
        repo_urls=list(repo_urls) if repo_urls else None,
        topic=topic or None,
        style=style, longform=longform,
    )
    if episode is None:
        sys.exit(1)


@cli.command()
@click.option("--count", default=10, help="批量生成的期数")
@click.option("--projects-per-episode", default=3, help="每期包含的项目数")
@click.option("--mock-data", is_flag=True, help="项目数据用 mock，LLM/TTS 用真实 API")
@click.option("--dry-run", is_flag=True, help="干跑模式（不调用任何 API）")
@click.option("--resume", is_flag=True, help="断点续传（跳过已生成的期数）")
@click.option("--config", default="config.yaml", help="配置文件路径")
def batch(
    count: int,
    projects_per_episode: int,
    mock_data: bool,
    dry_run: bool,
    resume: bool,
    config: str,
):
    """批量串行生成多期播客。

    \b
    示例：
      python main.py batch --count 50                    # 生成 50 期
      python main.py batch --count 100 --mock-data       # mock 项目 + 真实 API
      python main.py batch --count 50 --resume           # 断点续传
      python main.py batch --count 10 --dry-run          # 纯测试
    """
    run_batch(
        count=count,
        projects_per_episode=projects_per_episode,
        mock_data=mock_data,
        dry_run=dry_run,
        resume=resume,
        config_path=config,
    )


def run_batch(
    count: int,
    projects_per_episode: int,
    mock_data: bool,
    dry_run: bool,
    resume: bool,
    config_path: str,
) -> None:
    """批量串行生成核心逻辑。"""
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

    console.print(f"\n[bold cyan]═══ 批量播客生成 · 共 {count} 期 ═══[/bold cyan]\n")
    config = load_config(config_path)

    if dry_run:
        config["api_keys"] = {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""}
        config["_mock_mode"] = True
    elif mock_data:
        config["_mock_mode"] = True

    # 断点续传：检查已生成期数
    from src.rss_publisher import RSSPublisher
    publisher = RSSPublisher(config)
    start_from = 0
    if resume:
        history = publisher._load_history()
        start_from = len(history)
        if start_from >= count:
            console.print(f"[yellow]已完成 {start_from} 期，无需继续[/yellow]")
            return
        if start_from > 0:
            console.print(f"[yellow]断点续传：从第 {start_from + 1} 期开始（已完成 {start_from} 期）[/yellow]")
        remaining = count - start_from
    else:
        remaining = count

    # 批量获取项目
    total_projects = remaining * projects_per_episode
    console.print(f"[bold green]批量获取 {total_projects} 个项目（{remaining} 期 × {projects_per_episode} 个/期）[/bold green]")
    discovery = RepoDiscovery(config)
    all_repos = discovery.discover_batch(total_projects)

    if len(all_repos) < total_projects:
        console.print(
            f"[yellow]仅获取到 {len(all_repos)} 个项目，"
            f"将生成 {len(all_repos) // projects_per_episode} 期[/yellow]"
        )

    # 分组：每组 projects_per_episode 个项目
    groups = []
    for i in range(0, len(all_repos), projects_per_episode):
        group = all_repos[i : i + projects_per_episode]
        if group:
            groups.append(group)

    actual_count = len(groups)
    console.print(f"[green]分为 {actual_count} 组，开始串行生成...[/green]\n")

    # 串行生成
    success_count = 0
    fail_count = 0
    failed_details: list[str] = []
    start_time = time.time()

    for idx, group in enumerate(groups):
        ep_num = start_from + idx + 1
        console.rule(f"[bold]第 {ep_num}/{count} 期（批次 {idx + 1}/{actual_count}）")
        console.print(f"项目：{', '.join(r.name for r in group)}")

        try:
            episode = run_pipeline(
                dry_run=dry_run,
                mock_data=mock_data,
                config_path=config_path,
                repos=group,
                quiet=True,
            )
            if episode:
                success_count += 1
                console.print(
                    f"[green]✅ 第 {episode.episode_number} 期完成：{episode.script.title} "
                    f"({episode.duration_seconds:.0f}s)[/green]"
                )
            else:
                fail_count += 1
                failed_details.append(f"第 {ep_num} 期：流水线返回 None")
                console.print(f"[red]❌ 第 {ep_num} 期失败：流水线返回 None[/red]")
        except Exception as e:
            fail_count += 1
            failed_details.append(f"第 {ep_num} 期：{e}")
            console.print(f"[red]❌ 第 {ep_num} 期异常：{e}[/red]")

        # 进度
        elapsed = time.time() - start_time
        done = idx + 1
        avg = elapsed / done
        remaining_time = avg * (actual_count - done)
        console.print(
            f"[dim]进度 {done}/{actual_count} · "
            f"已用 {elapsed/60:.1f}min · 预计剩余 {remaining_time/60:.1f}min · "
            f"成功 {success_count} / 失败 {fail_count}[/dim]\n"
        )

    # 总结
    total_time = time.time() - start_time
    console.print("\n[bold cyan]═══ 批量生成完成 ═══[/bold cyan]")
    console.print(f"  总期数：{count}")
    console.print(f"  [green]成功：{success_count}[/green]")
    console.print(f"  [red]失败：{fail_count}[/red]")
    console.print(f"  总耗时：{total_time/60:.1f} 分钟")
    console.print(f"  平均每期：{total_time/max(success_count,1):.0f} 秒")
    if failed_details:
        console.print("\n[red]失败详情：[/red]")
        for d in failed_details:
            console.print(f"  - {d}")
    console.print(f"\n  RSS Feed：{publisher.feed_path}")
    console.print(f"  音频目录：{config['output']['episodes_dir']}\n")


@cli.command()
@click.option("--config", default="config.yaml")
def discover(config: str):
    """仅发现并打印 GitHub 前沿项目。"""
    cfg = load_config(config)
    repos = RepoDiscovery(cfg).discover()
    _print_repos(repos)


@cli.command(name="list")
@click.option("--config", default="config.yaml")
def list_episodes(config: str):
    """列出已发布的节目历史。"""
    cfg = load_config(config)
    from src.rss_publisher import RSSPublisher
    publisher = RSSPublisher(cfg)
    history = publisher._load_history()
    if not history:
        console.print("[yellow]暂无已发布节目[/yellow]")
        return
    table = Table(title="已发布节目")
    table.add_column("#", justify="right")
    table.add_column("标题", style="cyan")
    table.add_column("时长", justify="right")
    table.add_column("发布时间")
    for ep in history:
        mins = ep.get("duration_seconds", 0) / 60
        table.add_row(
            str(ep["episode_number"]),
            ep["title"],
            f"{mins:.1f} min",
            ep.get("published_at", "")[:16],
        )
    console.print(table)


if __name__ == "__main__":
    cli()
