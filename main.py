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

from src.audio_mixer import AudioMixer
from src.config_loader import load_config
from src.crawler import ReadmeCrawler, enrich_repo_topics
from src.discovery import RepoDiscovery
from src.llm_script import ScriptGenerator
from src.models import Episode, ProjectAnalysis
from src.project_analyzer import ProjectAnalyzer
from src.rss_publisher import RSSPublisher
from src.tts_synth import TTSSynthesizer

console = Console(width=200)


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
    if not quiet:
        console.print("\n[bold cyan]═══ GitHub 前沿观察 · 播客生成流水线 ═══[/bold cyan]\n")
    config = load_config(config_path)

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

    # ── 阶段 1：项目发现 ──
    if repos is None:
        if repo_urls:
            # 用户指定了仓库 URL
            if not quiet:
                console.print(f"[bold green][1/6] 获取指定项目（{len(repo_urls)} 个）[/bold green]")
            discovery = RepoDiscovery(config)
            repos = discovery.discover_by_repo_urls(repo_urls)
        elif topic:
            # 用户指定了主题
            if not quiet:
                console.print(f"[bold green][1/6] 按主题搜索：{topic}[/bold green]")
            discovery = RepoDiscovery(config)
            repos = discovery.discover_by_topic(topic, config["discovery"]["max_projects"])
        else:
            # 自动发现
            if not quiet:
                console.print("[bold green][1/6] 发现 GitHub 前沿项目[/bold green]")
            discovery = RepoDiscovery(config)
            repos = discovery.discover()
        if not repos:
            console.print("[red]未发现任何项目，退出[/red]")
            return None
        if not quiet:
            _print_repos(repos)
    else:
        if not quiet:
            console.print(f"[bold green][1/6] 使用预选项目（{len(repos)} 个）[/bold green]")

    # ── 阶段 2：README 抓取 ──
    console.print("\n[bold green][2/6] 抓取 README 内容[/bold green]")
    crawler = ReadmeCrawler(config)
    crawler.fetch_all(repos)
    # 补充 topics
    if not dry_run and not mock_data:
        for repo in repos:
            enrich_repo_topics(repo, config["api_keys"].get("github", ""))

    # ── 阶段 2.1：深度内容提取（含 Commit 历史/依赖解析/健康度） ──
    if not quiet:
        console.print("[bold green][2.1/6] 深度内容提取（文件树/源码/Release/Commit/依赖/健康度）[/bold green]")
    from src.deep_extractor import DeepExtractor
    extractor = DeepExtractor(config)
    health_data_list: list[dict] = []
    for repo in repos:
        deep_content = extractor.extract(repo)
        if deep_content:
            repo.readme_markdown += f"\n\n{deep_content}"
            if not quiet:
                console.print(f"  📂 {repo.name}: 深度内容已提取")
        # 收集健康度数据（供跨项目对比使用）
        # 复用 extract() 内部已获取的指标，避免重复请求 GitHub API（双取问题修复）
        health = extractor._last_health_metrics
        health["repo_name"] = repo.name
        health["stars"] = repo.stars
        health_data_list.append(health)
        if not quiet:
            console.print(f"  💚 {repo.name}: 健康度 {health.get('health_grade', 'N/A')} ({health.get('health_score', 0)}/100)")

    # ── 阶段 2.5：项目深度分析（类似 zread.ai） ──
    analyses: list[ProjectAnalysis] = []
    if not dry_run:
        console.print("\n[bold green][2.5/6] 项目深度分析[/bold green]")
        analyzer = ProjectAnalyzer(config)
        analyses = analyzer.analyze(repos)
        for a in analyses:
            console.print(f"  📊 {a.repo_name}: {a.summary[:50]}...")
    else:
        # dry-run 模式下生成 mock 分析（健康度数据已在阶段2.1收集）
        from src.models import ProjectAnalysis
        for repo in repos:
            analyses.append(ProjectAnalysis(
                repo_name=repo.name, summary=repo.description[:80],
                mermaid_diagram="graph TD\n    A[核心模块] --> B[数据层]\n    A --> C[接口层]\n    B --> D[(存储)]",
                commit_narrative="（mock）近期活跃开发，主要方向为功能完善",
            ))

    # 将分析结果注入 repo 供脚本生成使用
    analysis_map = {a.repo_name: a for a in analyses}
    for repo in repos:
        a = analysis_map.get(repo.name)
        if a:
            repo.readme_markdown += f"\n\n## 项目深度分析\n{a.to_dict()}"

    # ── 阶段 2.6：跨项目对比（借鉴 zread.ai 多仓库对比） ──
    comparison_data = None
    if len(repos) > 1 and not dry_run:
        console.print("\n[bold green][2.6/6] 跨项目横向对比[/bold green]")
        from src.cross_project_comparator import CrossProjectComparator
        comparator = CrossProjectComparator(config)
        comparison = comparator.compare(repos, analyses, health_data_list)
        comparison_data = comparison.to_dict()
        if not quiet:
            console.print(f"  ⚔️ 对比完成：{len(comparison.tech_overlap)} 项技术重叠")
            if comparison.verdict:
                console.print(f"  📝 {comparison.verdict[:80]}...")
    elif len(repos) > 1 and dry_run:
        # dry-run 模式下生成 mock 对比（使用真实健康度数据）
        from src.models import ProjectComparison
        # 按健康度排序
        ranked = sorted(health_data_list, key=lambda h: h.get("health_score", 0), reverse=True)
        activity_ranking = [
            {"repo": h.get("repo_name", ""), "rank": i+1, "health_score": h.get("health_score", 0)}
            for i, h in enumerate(ranked)
        ]
        comparison = ProjectComparison(
            repos=[r.name for r in repos],
            tech_overlap=[{"technology": "Python", "projects": [r.name for r in repos], "count": len(repos)}],
            positioning_diff="（mock 模式）各项目定位各有侧重",
            activity_ranking=activity_ranking,
            verdict="（mock 模式）配置 LLM API Key 后可生成真实对比分析",
        )
        comparison_data = comparison.to_dict()

    # 提前计算 episode_number（脚本保存与分析文件保存均需要）
    publisher = RSSPublisher(config)
    ep_num = publisher.get_next_episode_number()

    # ── 阶段 3：LLM 脚本生成 ──
    console.print("\n[bold green][3/6] 生成播客脚本[/bold green]")
    generator = ScriptGenerator(config)
    script = generator.generate(repos)
    console.print(f"  节目标题：[cyan]{script.title}[/cyan]")
    console.print(f"  主持人：{', '.join(h.name for h in script.hosts)}")
    console.print(f"  台词段数：{len(script.segments)}，总字数：{script.total_chars()}")
    console.print(f"  预计时长：{script.estimate_minutes()} 分钟")
    if script.critic_score > 0:
        grade_color = "green" if script.critic_score >= 7 else "yellow"
        console.print(f"  脚本评审：[{grade_color}]{script.critic_score}/10[/{grade_color}]" + (f"（{script.critic_feedback[:60]}...）" if script.critic_feedback else ""))

    # 保存脚本
    scripts_dir = Path(config["project_root"]) / config["output"]["scripts_dir"]
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_file = scripts_dir / f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    if not dry_run:
        _save_script(script, script_file, ep_num)
        console.print(f"  脚本已保存：{script_file}")
    else:
        console.print(f"  脚本已生成（dry-run 模式，未写入文件）：{script_file}")

    # 保存项目分析（含健康度、Mermaid图、跨项目对比）
    if analyses:
        analyses_dir = Path(config["project_root"]) / "output" / "analyses"
        analyses_dir.mkdir(parents=True, exist_ok=True)
        analysis_file = analyses_dir / f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        # 将健康度数据合并到每个项目分析中
        health_map = {h.get("repo_name", ""): h for h in health_data_list}
        analyses_dicts = []
        for a in analyses:
            a_dict = a.to_dict()
            h = health_map.get(a.repo_name, {})
            if h:
                a_dict["health_data"] = h
            analyses_dicts.append(a_dict)
        analysis_data = {
            "episode_number": ep_num,
            "title": script.title,
            "analyses": analyses_dicts,
            "health_data": health_data_list,
            "comparison": comparison_data,
        }
        analysis_file.write_text(json.dumps(analysis_data, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"  分析已保存：{analysis_file}")

    # ── 阶段 4：TTS 合成 ──
    console.print("\n[bold green][4/6] TTS 语音合成[/bold green]")
    synthesizer = TTSSynthesizer(config)
    segments_dir = Path(config["project_root"]) / "output" / "segments_tmp"
    try:
        audio_files = synthesizer.synthesize_script(script, segments_dir)

        # ── 阶段 5：音频后期 ──
        console.print("\n[bold green][5/6] 音频拼接与响度归一化[/bold green]")
        mixer = AudioMixer(config)
        episodes_dir = Path(config["project_root"]) / config["output"]["episodes_dir"]
        audio_path = episodes_dir / f"episode_{ep_num:03d}.{config['audio']['output_format']}"
        episode = mixer.mix(audio_files, script, audio_path, ep_num)

        # ── 阶段 5.5：Show Notes + 章节时间戳 + 字幕生成 ──
        console.print("\n[bold green][5.5/6] 生成 Show Notes / 章节 / 字幕[/bold green]")
        try:
            # 从音频拼接中获取段落时间戳
            timings = mixer.get_segment_timings()
            
            # 生成章节（按项目边界自动切分）
            chapters = mixer.generate_chapters_from_timings(script, timings, script.repo_names)
            episode.chapters = chapters
            if not quiet:
                console.print(f"  📑 生成 {len(chapters)} 个章节")
            
            # 生成 Show Notes（借鉴 Transcribr/LumiClip）
            from src.show_notes_generator import ShowNotesGenerator
            sng = ShowNotesGenerator(config)
            show_notes = sng.generate(script, repos, analyses, chapters)
            episode.show_notes = show_notes
            if not quiet:
                console.print(f"  📝 Show Notes: {len(show_notes.key_takeaways)} 要点, {len(show_notes.social_quotes)} 金句")
            
            # 生成 SRT 字幕文件
            transcript_path = publisher.generate_transcript_srt(script, timings)
            if transcript_path:
                episode.transcript_path = transcript_path
                if not quiet:
                    console.print(f"  🎬 字幕文件：{Path(transcript_path).name}")
            
            # 生成 Podcasting 2.0 chapters JSON
            chapters_json_path = publisher.generate_chapters_json(episode)
            if chapters_json_path and not quiet:
                console.print(f"  📋 章节JSON：{Path(chapters_json_path).name}")
        except Exception as e:
            print(f"[main] Show Notes/章节生成失败: {e}")

        # ── 阶段 6：RSS 发布 ──
        console.print("\n[bold green][6/6] 发布 RSS Feed[/bold green]")
        if not dry_run:
            publisher.publish(episode)
            # 将本期项目加入 30 天去重黑名单，防止近期重复覆盖
            # 仅在真实数据模式下标记，避免 mock 数据污染黑名单
            if not mock_data:
                try:
                    RepoDiscovery(config).mark_as_covered([r.name for r in repos])
                except Exception as e:
                    print(f"[main] 标记项目黑名单失败: {e}")
    finally:
        # 清理临时段落文件
        _cleanup_segments(segments_dir)

    # 成本估算
    _print_cost_estimate(script, config)

    console.print("\n[bold green]✅ 播客生成完成！[/bold green]")
    console.print(f"   音频文件：{episode.audio_path}")
    console.print(f"   时长：{episode.duration_seconds:.1f}s")
    console.print(f"   RSS Feed：{publisher.feed_path}\n")
    return episode


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


def _save_script(script, path: Path, episode_number: int = 0) -> None:
    """保存脚本为 JSON。"""
    data = {
        "title": script.title,
        "description": script.description,
        "hosts": [
            {"name": h.name, "persona": h.persona, "voice_key": h.voice_key}
            for h in script.hosts
        ],
        "segments": [
            {
                "speaker": s.speaker,
                "text": s.text,
                "emotion": s.emotion,
                "voice_key": s.voice_key,
            }
            for s in script.segments
        ],
        "repo_names": script.repo_names,
        "episode_number": episode_number,
        "created_at": script.created_at,
        "critic_score": script.critic_score,
        "critic_feedback": script.critic_feedback,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cleanup_segments(segments_dir: Path) -> None:
    """清理临时段落音频文件。"""
    if not segments_dir.exists():
        return
    import shutil
    try:
        shutil.rmtree(segments_dir)
    except OSError:
        pass


def _print_cost_estimate(script, config) -> None:
    """打印本次生成的成本估算。"""
    chars = script.total_chars()
    llm_model = config["llm"]["model"]
    tts_model = config["tts"]["model"]
    tts_provider = config["tts"].get("provider", "siliconflow")

    # SiliconFlow 免费模型
    free_llm = any(k in llm_model for k in ["9B", "4B", "7B", "Flash", "flash"])
    # SiliconFlow TTS 按 UTF-8 字节计费（中文 3 字节/字）
    if tts_provider == "siliconflow":
        tts_bytes = chars * 3  # 中文 UTF-8 约 3 字节
        tts_cost = tts_bytes / 10000 * 0.5  # 约 ¥0.5/万字节（估算）
        if tts_bytes < 14000:  # ¥14 免费额度内
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
@click.option("--style", type=click.Choice(["casual", "technical", "debate", "interview"]), default="casual", help="播客风格")
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
