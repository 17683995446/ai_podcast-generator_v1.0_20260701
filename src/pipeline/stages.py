"""流水线阶段实现 — 9 个可组合的 Stage 类。

将原来 420 行的 run_pipeline God 函数拆分为独立的阶段类，
每个阶段封装一个流水线步骤的核心逻辑。

阶段顺序：
  1. DiscoveryStage     — 项目发现（自动/URL/主题/预选）
  2. CrawlStage         — README 抓取 + topics 补充
  3. DeepExtractStage   — 深度内容提取 + 证据收集 + 代码级分析
  4. AnalyzeStage       — 项目深度分析 + 规则校验
  5. CompareStage       — 跨项目对比（条件执行：仅多项目时运行）
  6. ScriptStage        — LLM 脚本生成 + 保存
  7. TTSStage           — TTS 语音合成
  8. AudioMixStage      — 音频拼接 + Show Notes + 章节生成
  9. PublishStage       — RSS 发布 + 清理

设计原则（第一性原理）：
  - 每个阶段是自包含的，通过 PipelineContext 传递数据
  - 阶段间无直接依赖，仅通过 context 间接耦合
  - 每个阶段可独立测试、替换、跳过
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from src.config_defaults import CONSOLE_WIDTH, PIPELINE_SEGMENTED_THRESHOLD
from src.logger import get_logger
from src.models import Episode, ProjectAnalysis

from .base import PipelineContext, PipelineStage, PipelineStageError

logger = get_logger(__name__)
console = Console(width=CONSOLE_WIDTH)


# ════════════════════════════════════════
# 阶段 1：项目发现
# ════════════════════════════════════════
class DiscoveryStage(PipelineStage):
    """项目发现阶段 — 自动发现 / URL 指定 / 主题搜索 / 预选项目。"""

    @property
    def name(self) -> str:
        return "discovery"

    @property
    def label(self) -> str:
        return "项目发现"

    def execute(self, ctx: PipelineContext) -> None:
        from src.discovery import RepoDiscovery

        if ctx.reporter:
            ctx.reporter.start_pipeline()
            ctx.emit_progress(self.name, "running", "正在发现项目...")

        if not ctx.repos:
            # 需要发现项目
            discovery = RepoDiscovery(ctx.config)

            if ctx.repo_urls:
                if not ctx.quiet:
                    console.print(f"[bold green][1/6] 获取指定项目（{len(ctx.repo_urls)} 个）[/bold green]")
                ctx.repos = discovery.discover_by_repo_urls(ctx.repo_urls)
            elif ctx.topic:
                if not ctx.quiet:
                    console.print(f"[bold green][1/6] 按主题搜索：{ctx.topic}[/bold green]")
                ctx.repos = discovery.discover_by_topic(ctx.topic, ctx.config["discovery"]["max_projects"])
            else:
                if not ctx.quiet:
                    console.print("[bold green][1/6] 发现 GitHub 前沿项目[/bold green]")
                ctx.repos = discovery.discover()

            if not ctx.repos:
                console.print("[red]未发现任何项目，退出[/red]")
                raise PipelineStageError("未发现任何项目")
        else:
            if not ctx.quiet:
                console.print(f"[bold green][1/6] 使用预选项目（{len(ctx.repos)} 个）[/bold green]")

        # 报告
        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"发现 {len(ctx.repos)} 个项目",
                                      {"repos": [r.name for r in ctx.repos]})
            ctx.reporter.update_checkpoint(repos_found=[r.name for r in ctx.repos])
            ctx.emit_progress(self.name, "done", f"发现 {len(ctx.repos)} 个项目")


# ════════════════════════════════════════
# 阶段 2：README 抓取
# ════════════════════════════════════════
class CrawlStage(PipelineStage):
    """README 抓取阶段 — 获取 README 内容 + 补充 topics。"""

    @property
    def name(self) -> str:
        return "crawl"

    @property
    def label(self) -> str:
        return "README抓取"

    def execute(self, ctx: PipelineContext) -> None:
        from src.crawler import ReadmeCrawler, enrich_repo_topics

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "抓取 README 内容...")

        console.print("\n[bold green][2/6] 抓取 README 内容[/bold green]")
        crawler = ReadmeCrawler(ctx.config)
        crawler.fetch_all(ctx.repos)

        # 补充 topics
        if not ctx.dry_run and not ctx.mock_data:
            for repo in ctx.repos:
                enrich_repo_topics(repo, ctx.config["api_keys"].get("github", ""))

        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"已抓取 {len(ctx.repos)} 个 README")
            ctx.reporter.update_checkpoint(readme_fetched=[r.name for r in ctx.repos])
            ctx.emit_progress(self.name, "done", f"已抓取 {len(ctx.repos)} 个 README")


# ════════════════════════════════════════
# 阶段 3：深度内容提取
# ════════════════════════════════════════
class DeepExtractStage(PipelineStage):
    """深度内容提取阶段 — 文件树/源码/Release/Commit/依赖/健康度 + 代码级分析。"""

    @property
    def name(self) -> str:
        return "deep_extract"

    @property
    def label(self) -> str:
        return "深度提取"

    def execute(self, ctx: PipelineContext) -> None:
        from src.deep_extractor import DeepExtractor
        from src.code_analyzer import CodeAnalyzer

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "深度内容提取（文件树/源码/Release/Commit/依赖/健康度）...")

        if not ctx.quiet:
            console.print("[bold green][2.1/6] 深度内容提取（文件树/源码/Release/Commit/依赖/健康度）[/bold green]")

        extractor = DeepExtractor(ctx.config)
        ctx.extractor = extractor  # 保存供后续阶段复用

        for repo in ctx.repos:
            deep_content, repo_evidence = extractor.extract_with_evidence(repo)
            if deep_content:
                repo.readme_markdown += f"\n\n{deep_content}"
                if not ctx.quiet:
                    console.print(f"  📂 {repo.name}: 深度内容已提取")
            # 保存证据
            ctx.evidence_map[repo.name] = repo_evidence
            # 收集健康度数据 — 使用公共访问器替代私有属性访问
            health = extractor.get_last_health_metrics()
            health["repo_name"] = repo.name
            health["stars"] = repo.stars
            ctx.health_data_list.append(health)
            if not ctx.quiet:
                console.print(f"  💚 {repo.name}: 健康度 {health.get('health_grade', 'N/A')} ({health.get('health_score', 0)}/100)")

        # 代码级分析 — 使用公共访问器替代私有属性访问
        code_analyzer = CodeAnalyzer()
        for repo in ctx.repos:
            metrics = code_analyzer.analyze(
                file_tree=extractor.get_last_file_tree(),
                source_code=extractor.get_last_source_code(),
            )
            ctx.code_metrics_map[repo.name] = metrics.to_dict()
            if not ctx.quiet:
                console.print(f"  🔍 {repo.name}: {metrics.architecture_pattern} | "
                             f"LOC {metrics.total_loc} | 复杂度 {metrics.complexity_score}/10 | "
                             f"质量 {metrics.quality_score}/100")

        if ctx.reporter:
            total_evidence = sum(len(v) for v in ctx.evidence_map.values())
            ctx.reporter.finish_stage(self.name, f"已提取 {len(ctx.repos)} 个项目，{total_evidence} 条证据")
            ctx.reporter.update_checkpoint(
                deep_extracted=[r.name for r in ctx.repos], evidence_count=total_evidence,
            )
            ctx.emit_progress(self.name, "done",
                              f"已提取 {len(ctx.repos)} 个项目，{total_evidence} 条证据")


# ════════════════════════════════════════
# 阶段 4：项目深度分析
# ════════════════════════════════════════
class AnalyzeStage(PipelineStage):
    """项目深度分析阶段 — LLM 分析 + 规则校验 + 分析结果注入。"""

    @property
    def name(self) -> str:
        return "analyze"

    @property
    def label(self) -> str:
        return "项目分析"

    def execute(self, ctx: PipelineContext) -> None:
        from src.project_analyzer import ProjectAnalyzer
        from src.analysis_validator import validate_batch

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "项目深度分析...")

        analyses: list[ProjectAnalysis] = []
        if not ctx.dry_run:
            console.print("\n[bold green][2.5/6] 项目深度分析[/bold green]")
            analyzer = ProjectAnalyzer(ctx.config)
            analyses = analyzer.analyze(ctx.repos, evidence_map=ctx.evidence_map)
            for a in analyses:
                console.print(f"  📊 {a.repo_name}: {a.summary[:50]}...")
        else:
            for repo in ctx.repos:
                analyses.append(ProjectAnalysis(
                    repo_name=repo.name, summary=repo.description[:80],
                    mermaid_diagram="graph TD\n    A[核心模块] --> B[数据层]\n    A --> C[接口层]\n    B --> D[(存储)]",
                    commit_narrative="（mock）近期活跃开发，主要方向为功能完善",
                ))

        ctx.analyses = analyses

        # 规则校验
        ctx.validation_reports = validate_batch(analyses, ctx.evidence_map)

        # 将代码级分析指标附加到每个 ProjectAnalysis
        for analysis in analyses:
            if analysis.repo_name in ctx.code_metrics_map:
                analysis.code_metrics = ctx.code_metrics_map[analysis.repo_name]

        # 将分析结果注入 repo 供脚本生成使用
        analysis_map = {a.repo_name: a for a in analyses}
        for repo in ctx.repos:
            a = analysis_map.get(repo.name)
            if a:
                repo.readme_markdown += f"\n\n## 项目深度分析\n{a.to_dict()}"

        # 打印校验结果
        for repo_name, vr in ctx.validation_reports.items():
            status = "✓ 通过" if vr.passed else f"⚠ 未通过（score={vr.score}）"
            console.print(f"  🔍 校验 {repo_name}: {status} "
                         f"(tech: {len(vr.tech_stack_verified)}/{len(vr.tech_stack_verified)+len(vr.tech_stack_unverified)}, "
                         f"modules: {len(vr.key_modules_verified)}/{len(vr.key_modules_verified)+len(vr.key_modules_unverified)})")

        if ctx.reporter:
            val_scores = {name: vr.score for name, vr in ctx.validation_reports.items()}
            ctx.reporter.finish_stage(self.name, f"已分析 {len(analyses)} 个项目",
                                      {"validation_scores": val_scores})
            ctx.reporter.update_checkpoint(
                analysis_completed=[a.repo_name for a in analyses],
                validation_scores=val_scores,
            )
            ctx.emit_progress(self.name, "done", f"已分析 {len(analyses)} 个项目")


# ════════════════════════════════════════
# 阶段 5：跨项目对比（条件执行）
# ════════════════════════════════════════
class CompareStage(PipelineStage):
    """跨项目对比阶段 — 仅在多项目时运行。"""

    @property
    def name(self) -> str:
        return "compare"

    @property
    def label(self) -> str:
        return "跨项目对比"

    def should_run(self, ctx: PipelineContext) -> bool:
        """仅多项目时运行。"""
        return len(ctx.repos) > 1

    def execute(self, ctx: PipelineContext) -> None:
        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "跨项目横向对比...")

        ctx.comparison_data = None

        if not ctx.dry_run:
            console.print("\n[bold green][2.6/6] 跨项目横向对比[/bold green]")
            from src.cross_project_comparator import CrossProjectComparator
            comparator = CrossProjectComparator(ctx.config)
            comparison = comparator.compare(ctx.repos, ctx.analyses, ctx.health_data_list)
            ctx.comparison_data = comparison.to_dict()
            if not ctx.quiet:
                console.print(f"  ⚔️ 对比完成：{len(comparison.tech_overlap)} 项技术重叠")
                if comparison.verdict:
                    console.print(f"  📝 {comparison.verdict[:80]}...")
        else:
            # dry-run 模式下生成 mock 对比
            from src.models import ProjectComparison
            ranked = sorted(ctx.health_data_list, key=lambda h: h.get("health_score", 0), reverse=True)
            activity_ranking = [
                {"repo": h.get("repo_name", ""), "rank": i+1, "health_score": h.get("health_score", 0)}
                for i, h in enumerate(ranked)
            ]
            comparison = ProjectComparison(
                repos=[r.name for r in ctx.repos],
                tech_overlap=[{"technology": "Python", "projects": [r.name for r in ctx.repos], "count": len(ctx.repos)}],
                positioning_diff="（mock 模式）各项目定位各有侧重",
                activity_ranking=activity_ranking,
                verdict="（mock 模式）配置 LLM API Key 后可生成真实对比分析",
            )
            ctx.comparison_data = comparison.to_dict()

        if ctx.reporter:
            if ctx.comparison_data:
                ctx.reporter.finish_stage(self.name, f"对比完成：{len(ctx.comparison_data.get('tech_overlap', []))} 项技术重叠")
                ctx.emit_progress(self.name, "done", "跨项目对比完成")
            else:
                ctx.reporter.skip_stage(self.name, "单项目，无需对比")
                ctx.emit_progress(self.name, "skipped", "单项目，无需对比")


# ════════════════════════════════════════
# 阶段 6：脚本生成
# ════════════════════════════════════════
class ScriptStage(PipelineStage):
    """LLM 脚本生成阶段 — 生成播客脚本 + 保存脚本和分析文件。"""

    @property
    def name(self) -> str:
        return "script"

    @property
    def label(self) -> str:
        return "脚本生成"

    def execute(self, ctx: PipelineContext) -> None:
        from src.llm_script import ScriptGenerator
        from src.rss_publisher import RSSPublisher
        from src.evidence_tracker import summarize_evidence

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "生成播客脚本...")

        console.print("\n[bold green][3/6] 生成播客脚本[/bold green]")

        # 提前计算 episode_number
        publisher = RSSPublisher(ctx.config)
        ctx.publisher = publisher
        ctx.ep_num = publisher.get_next_episode_number()
        if ctx.reporter:
            ctx.reporter.update_checkpoint(episode_number=ctx.ep_num)

        # 分段生成模式
        if ctx.config.get("longform", False) or len(ctx.repos) >= PIPELINE_SEGMENTED_THRESHOLD:
            from src.segmented_generator import SegmentedScriptGenerator
            generator = SegmentedScriptGenerator(ctx.config)
            ctx.script = generator.generate_segmented(ctx.repos)
            console.print(f"  [dim]（分段生成模式：{len(ctx.repos)} 个项目独立生成 + 全局连贯性检查）[/dim]")
        else:
            generator = ScriptGenerator(ctx.config)
            ctx.script = generator.generate(ctx.repos)

        script = ctx.script
        console.print(f"  节目标题：[cyan]{script.title}[/cyan]")
        console.print(f"  主持人：{', '.join(h.name for h in script.hosts)}")
        console.print(f"  台词段数：{len(script.segments)}，总字数：{script.total_chars()}")
        console.print(f"  预计时长：{script.estimate_minutes()} 分钟")
        if script.critic_score > 0:
            grade_color = "green" if script.critic_score >= 7 else "yellow"
            console.print(f"  脚本评审：[{grade_color}]{script.critic_score}/10[/{grade_color}]" + (f"（{script.critic_feedback[:60]}...）" if script.critic_feedback else ""))

        # 保存脚本
        scripts_dir = ctx.project_root / ctx.config["output"]["scripts_dir"]
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_file = scripts_dir / f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        if not ctx.dry_run:
            _save_script(script, script_file, ctx.ep_num)
            console.print(f"  脚本已保存：{script_file}")
        else:
            console.print(f"  脚本已生成（dry-run 模式，未写入文件）：{script_file}")

        # 保存项目分析
        if ctx.analyses:
            analyses_dir = ctx.output_dir / "analyses"
            analyses_dir.mkdir(parents=True, exist_ok=True)
            analysis_file = analyses_dir / f"analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            health_map = {h.get("repo_name", ""): h for h in ctx.health_data_list}
            analyses_dicts = []
            for a in ctx.analyses:
                a_dict = a.to_dict()
                h = health_map.get(a.repo_name, {})
                if h:
                    a_dict["health_data"] = h
                analyses_dicts.append(a_dict)
            analysis_data = {
                "episode_number": ctx.ep_num,
                "title": script.title,
                "analyses": analyses_dicts,
                "evidence_summary": {
                    a.repo_name: summarize_evidence(a.evidence_sources) for a in ctx.analyses
                } if ctx.analyses else {},
                "validation_reports": {
                    name: vr.to_dict() for name, vr in ctx.validation_reports.items()
                } if ctx.validation_reports else {},
                "health_data": ctx.health_data_list,
                "comparison": ctx.comparison_data,
            }
            analysis_file.write_text(json.dumps(analysis_data, ensure_ascii=False, indent=2), encoding="utf-8")
            console.print(f"  分析已保存：{analysis_file}")

        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"脚本 {len(script.segments)} 段，{script.total_chars()} 字",
                                      {"segments": len(script.segments), "review_score": script.critic_score})
            ctx.reporter.update_checkpoint(
                script_segments=len(script.segments),
                script_review_score=script.critic_score,
            )
            ctx.emit_progress(self.name, "done",
                              f"脚本 {len(script.segments)} 段，{script.total_chars()} 字")


# ════════════════════════════════════════
# 阶段 7：TTS 语音合成
# ════════════════════════════════════════
class TTSStage(PipelineStage):
    """TTS 语音合成阶段。"""

    @property
    def name(self) -> str:
        return "tts"

    @property
    def label(self) -> str:
        return "语音合成"

    def execute(self, ctx: PipelineContext) -> None:
        from src.tts_synth import TTSSynthesizer

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "TTS 语音合成...")

        console.print("\n[bold green][4/6] TTS 语音合成[/bold green]")
        synthesizer = TTSSynthesizer(ctx.config)
        segments_dir = ctx.output_dir / "segments_tmp"
        ctx.audio_files = synthesizer.synthesize_script(ctx.script, segments_dir)

        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"已合成 {len(ctx.audio_files)} 段语音")
            ctx.reporter.update_checkpoint(audio_segments=len(ctx.audio_files))
            ctx.emit_progress(self.name, "done", f"已合成 {len(ctx.audio_files)} 段语音")


# ════════════════════════════════════════
# 阶段 8：音频混音 + Show Notes
# ════════════════════════════════════════
class AudioMixStage(PipelineStage):
    """音频拼接 + 响度归一化 + Show Notes + 章节生成。"""

    @property
    def name(self) -> str:
        return "mix"

    @property
    def label(self) -> str:
        return "音频混音"

    def execute(self, ctx: PipelineContext) -> None:
        from src.audio_mixer import AudioMixer

        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "音频拼接与响度归一化...")

        console.print("\n[bold green][5/6] 音频拼接与响度归一化[/bold green]")
        mixer = AudioMixer(ctx.config)
        episodes_dir = ctx.project_root / ctx.config["output"]["episodes_dir"]
        audio_path = episodes_dir / f"episode_{ctx.ep_num:03d}.{ctx.config['audio']['output_format']}"
        ctx.episode = mixer.mix(ctx.audio_files, ctx.script, audio_path, ctx.ep_num)

        # Show Notes + 章节 + 字幕
        console.print("\n[bold green][5.5/6] 生成 Show Notes / 章节 / 字幕[/bold green]")
        try:
            timings = mixer.get_segment_timings()
            chapters = mixer.generate_chapters_from_timings(ctx.script, timings, ctx.script.repo_names)
            ctx.episode.chapters = chapters
            if not ctx.quiet:
                console.print(f"  📑 生成 {len(chapters)} 个章节")

            from src.show_notes_generator import ShowNotesGenerator
            sng = ShowNotesGenerator(ctx.config)
            show_notes = sng.generate(ctx.script, ctx.repos, ctx.analyses, chapters)
            ctx.episode.show_notes = show_notes
            if not ctx.quiet:
                console.print(f"  📝 Show Notes: {len(show_notes.key_takeaways)} 要点, {len(show_notes.social_quotes)} 金句")

            transcript_path = ctx.publisher.generate_transcript_srt(ctx.script, timings)
            if transcript_path:
                ctx.episode.transcript_path = transcript_path
                if not ctx.quiet:
                    console.print(f"  🎬 字幕文件：{Path(transcript_path).name}")

            chapters_json_path = ctx.publisher.generate_chapters_json(ctx.episode)
            if chapters_json_path and not ctx.quiet:
                console.print(f"  📋 章节JSON：{Path(chapters_json_path).name}")
        except Exception as e:
            logger.error("Show Notes/章节生成失败: %s", e)

        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"音频 {ctx.episode.duration_seconds:.0f}s，{len(ctx.episode.chapters or [])} 章节")
            ctx.reporter.update_checkpoint(audio_duration_seconds=ctx.episode.duration_seconds)
            ctx.emit_progress(self.name, "done", f"音频 {ctx.episode.duration_seconds:.0f}s")


# ════════════════════════════════════════
# 阶段 9：RSS 发布 + 清理
# ════════════════════════════════════════
class PublishStage(PipelineStage):
    """RSS 发布阶段 + 临时文件清理。"""

    @property
    def name(self) -> str:
        return "publish"

    @property
    def label(self) -> str:
        return "RSS发布"

    def execute(self, ctx: PipelineContext) -> None:
        if ctx.reporter:
            ctx.reporter.start_stage(self.name, self.label)
            ctx.emit_progress(self.name, "running", "发布 RSS Feed...")

        console.print("\n[bold green][6/6] 发布 RSS Feed[/bold green]")

        if not ctx.dry_run:
            ctx.publisher.publish(ctx.episode)
            # 标记项目黑名单
            if not ctx.mock_data:
                try:
                    from src.discovery import RepoDiscovery
                    RepoDiscovery(ctx.config).mark_as_covered([r.name for r in ctx.repos])
                except Exception as e:
                    logger.error("标记项目黑名单失败: %s", e)

        if ctx.reporter:
            ctx.reporter.finish_stage(self.name, f"EP{ctx.ep_num:03d} 已发布")
            ctx.emit_progress(self.name, "done", f"EP{ctx.ep_num:03d} 已发布")

        # 清理临时文件
        segments_dir = ctx.output_dir / "segments_tmp"
        _cleanup_segments(segments_dir)

        # 保存检查点和报告
        if ctx.reporter:
            ctx.reporter.save_checkpoint(f"checkpoint_ep{ctx.ep_num:03d}.json")
            final_report = ctx.reporter.finish_pipeline()
            ctx.emit_progress(self.name, "done",
                              f"流水线完成：{final_report['stages_completed']}/{final_report['stages_completed']+final_report['stages_failed']} 阶段成功")
            report_dir = ctx.output_dir / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            report_file = report_dir / f"report_ep{ctx.ep_num:03d}.json"
            report_file.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")


# ════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════
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
    try:
        shutil.rmtree(segments_dir)
    except OSError:
        pass
