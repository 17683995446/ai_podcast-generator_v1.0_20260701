"""repo2pod · 人体工学命令行工具。

无需 Web 仪表盘即可独立使用的 GitHub 播客生成 CLI，借鉴 zread.ai 的命令行体验。
所有子命令均可在终端直接调用，输出以中文为主。

用法示例：
    python cli.py analyze https://github.com/owner/repo
    python cli.py script https://github.com/owner/repo --style technical
    python cli.py render https://github.com/owner/repo --mock-data
    python cli.py ask https://github.com/owner/repo "这个项目的核心架构是什么？"
    python cli.py serve --port 5000
    python cli.py batch --count 5 --mock-data
    python cli.py list --limit 10
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(width=120)

PROG = "repo2pod"
VERSION = "0.1.0"


# =====================================================================
# 主命令组
# =====================================================================
@click.group(
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="repo2pod · GitHub 项目播客生成命令行工具（无需 Web 仪表盘）。",
)
@click.version_option(message=f"{PROG} %(version)s", version=VERSION)
@click.pass_context
def cli(ctx: click.Context):
    """repo2pod · GitHub 项目播客生成命令行工具。"""
    if ctx.invoked_subcommand is None:
        _print_banner()


def _print_banner() -> None:
    """无子命令时打印横幅与可用命令一览。"""
    console.print(
        Panel.fit(
            f"[bold]{PROG}[/bold] · GitHub 项目播客生成命令行工具  [dim]v{VERSION}[/dim]\n"
            "无需 Web 仪表盘，直接在终端分析项目、生成脚本、渲染播客。",
            border_style="cyan",
        )
    )
    table = Table(title="可用命令", show_header=True, header_style="bold green")
    table.add_column("命令", style="cyan", no_wrap=True)
    table.add_column("说明")
    table.add_row("analyze", "分析 GitHub 项目（技术栈/架构/健康度/Mermaid 图），不生成音频")
    table.add_row("script", "生成播客脚本（含评审回路），不调用 TTS")
    table.add_row("render", "完整流水线：分析 → 脚本 → TTS → 音频 → RSS")
    table.add_row("ask", "就某个项目交互式问答，--speak 可朗读答案")
    table.add_row("serve", "启动 Web 仪表盘")
    table.add_row("batch", "批量生成多期播客")
    table.add_row("list", "列出已发布的节目")
    console.print(table)
    console.print(f"\n[dim]使用 {PROG} <命令> --help 查看各命令详细用法。[/dim]")


# =====================================================================
# 公共分析逻辑（analyze / script / ask 复用）
# =====================================================================
def _run_analysis(repo_url: str, config_path: str, mock_data: bool = False):
    """执行：发现 → 抓取 README → 深度提取（含健康度）→ 项目分析。

    返回 (config, repos, analyses, health_data_list)。
    """
    from src.config_loader import load_config
    from src.crawler import ReadmeCrawler, enrich_repo_topics
    from src.deep_extractor import DeepExtractor
    from src.discovery import RepoDiscovery
    from src.project_analyzer import ProjectAnalyzer

    config = load_config(config_path)
    if mock_data:
        config["_mock_mode"] = True

    # ── 发现 ──
    discovery = RepoDiscovery(config)
    repos = discovery.discover_by_repo_urls([repo_url])
    if not repos:
        raise click.ClickException(
            f"未找到项目：{repo_url}（请检查 URL 是否正确，或网络 / GITHUB_TOKEN 是否可用）"
        )

    # ── 抓取 README ──
    crawler = ReadmeCrawler(config)
    crawler.fetch_all(repos)
    if not mock_data:
        for repo in repos:
            try:
                enrich_repo_topics(repo, config["api_keys"].get("github", ""))
            except Exception as e:
                console.print(f"[yellow]补充 topics 失败（{repo.name}）：{e}[/yellow]")

    # ── 深度提取 + 健康度 ──
    extractor = DeepExtractor(config)
    health_data_list: list[dict] = []
    for repo in repos:
        deep = extractor.extract(repo)
        if deep:
            repo.readme_markdown += f"\n\n{deep}"
        health = dict(getattr(extractor, "_last_health_metrics", {}) or {})
        health["repo_name"] = repo.name
        health["stars"] = repo.stars
        health_data_list.append(health)

    # ── 项目分析 ──
    analyzer = ProjectAnalyzer(config)
    analyses = analyzer.analyze(repos)

    # 将分析结果注入 readme，供脚本生成 / 问答上下文使用
    analysis_map = {a.repo_name: a for a in analyses}
    for repo in repos:
        a = analysis_map.get(repo.name)
        if a:
            repo.readme_markdown += f"\n\n## 项目深度分析\n{a.to_dict()}"

    return config, repos, analyses, health_data_list


# =====================================================================
# analyze
# =====================================================================
@cli.command()
@click.argument("repo_url")
@click.option("--output", "-o", type=click.Choice(["json", "text"]), default="text", help="输出格式：json 或 text")
@click.option("--mock-data", is_flag=True, help="使用 mock 项目数据（不请求 GitHub）")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def analyze(repo_url: str, output: str, mock_data: bool, config_path: str):
    """分析 GitHub 项目（不生成音频）。

    抓取 README、运行深度提取与项目分析，输出技术栈、架构、健康度与 Mermaid 架构图。
    不生成脚本，也不调用 TTS。
    """
    console.print(f"[bold green]▸ 分析项目：[/bold green]{repo_url}")
    try:
        _config, _repos, analyses, health_data_list = _run_analysis(
            repo_url, config_path, mock_data
        )
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"分析失败：{e}")

    if not analyses:
        click.echo("未生成任何分析结果。", err=True)
        sys.exit(1)

    health_map = {h.get("repo_name", ""): h for h in health_data_list}

    for a in analyses:
        if output == "json":
            payload = a.to_dict()
            payload["health_data"] = health_map.get(a.repo_name, {})
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_analysis_text(a, health_map.get(a.repo_name, {}))


def _print_analysis_text(a, health: dict) -> None:
    """以富文本格式打印单个项目分析。"""
    console.print()
    console.print(f"[bold cyan]📦 {a.repo_name}[/bold cyan]")
    console.print(f"   [bold]概述：[/bold]{a.summary or '-'}")
    console.print(
        f"   [bold]技术栈：[/bold]{', '.join(a.tech_stack) if a.tech_stack else '-'}"
    )
    console.print(f"   [bold]架构：[/bold]{a.architecture or '-'}")

    if a.key_modules:
        console.print("   [bold]关键模块：[/bold]")
        for m in a.key_modules:
            name = m.get("name", "") if isinstance(m, dict) else str(m)
            desc = m.get("description", "") if isinstance(m, dict) else ""
            console.print(f"     • {name}：{desc}")

    if a.highlights:
        console.print("   [bold]技术亮点：[/bold]")
        for h in a.highlights:
            console.print(f"     • {h}")

    if a.use_cases:
        console.print("   [bold]应用场景：[/bold]")
        for u in a.use_cases:
            console.print(f"     • {u}")

    if a.comparison:
        console.print(f"   [bold]同类对比：[/bold]{a.comparison}")

    if a.code_insights:
        console.print(f"   [bold]代码洞察：[/bold]{a.code_insights}")

    if health:
        console.print(
            f"   [bold]健康度：[/bold]{health.get('health_grade', 'N/A')} "
            f"({health.get('health_score', 0)}/100) · "
            f"近30天提交 {health.get('commit_count_30d', 0)} · "
            f"贡献者 {health.get('contributor_count', 0)} · "
            f"Issue 关闭率 {health.get('issue_close_rate', 0):.0%}"
        )

    console.print(
        f"   [bold]评审分数：[/bold]{a.review_score}/10 "
        f"{'✅ 通过' if a.review_passed else '⚠️ 未通过'}"
    )

    if a.quick_start:
        console.print("   [bold]快速上手：[/bold]")
        for line in a.quick_start.splitlines():
            if line.strip():
                console.print(f"     {line}")

    if a.mermaid_diagram:
        console.print("\n   [bold]架构图（Mermaid）：[/bold]")
        for line in a.mermaid_diagram.splitlines():
            console.print(f"   {line}")


# =====================================================================
# script
# =====================================================================
@cli.command()
@click.argument("repo_url")
@click.option("--style", type=click.Choice(["casual", "technical", "debate", "interview"]), default="casual", help="播客风格预设")
@click.option("--longform", is_flag=True, help="长内容模式（25-40 分钟）")
@click.option("--output", "-o", "output_file", type=click.Path(), default=None, help="输出到文件（默认输出到 stdout）")
@click.option("--mock-data", is_flag=True, help="使用 mock 项目数据")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def script(repo_url: str, style: str, longform: bool, output_file: str, mock_data: bool, config_path: str):
    """生成播客脚本（含评审回路，不调用 TTS）。

    先运行完整项目分析，再生成双人对话脚本，输出为 JSON。
    不会调用 TTS，也不会产出音频。
    """
    console.print(
        f"[bold green]▸ 生成脚本：[/bold green]{repo_url}（风格={style}，长内容={longform}）"
    )
    try:
        config, repos, _analyses, _health = _run_analysis(
            repo_url, config_path, mock_data
        )
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"分析失败：{e}")

    config["podcast_style"] = style
    config["longform"] = longform

    from src.llm_script import ScriptGenerator

    generator = ScriptGenerator(config)
    script = generator.generate(repos)

    data = _script_to_dict(script)
    text = json.dumps(data, ensure_ascii=False, indent=2)

    if output_file:
        Path(output_file).write_text(text, encoding="utf-8")
        console.print(f"[green]✅ 脚本已保存：[/green]{output_file}")
        console.print(f"   标题：{script.title}")
        console.print(
            f"   段数：{len(script.segments)}，总字数：{script.total_chars()}，"
            f"预计 {script.estimate_minutes()} 分钟"
        )
    else:
        click.echo(text)


def _script_to_dict(script) -> dict:
    """将 PodcastScript 序列化为可存储的 dict（与 main._save_script 对齐）。"""
    return {
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
        "repo_urls": getattr(script, "repo_urls", []),
        "style": getattr(script, "style", "casual"),
        "target_minutes": getattr(script, "target_minutes", 8),
        "estimate_minutes": script.estimate_minutes(),
        "total_chars": script.total_chars(),
        "created_at": script.created_at,
    }


# =====================================================================
# render
# =====================================================================
@cli.command()
@click.argument("repo_url")
@click.option("--style", type=click.Choice(["casual", "technical", "debate", "interview"]), default="casual", help="播客风格预设")
@click.option("--longform", is_flag=True, help="长内容模式（25-40 分钟）")
@click.option("--mock-data", is_flag=True, help="项目数据用 mock，LLM/TTS 用真实 API")
@click.option("--dry-run", is_flag=True, help="干跑模式（不调用任何付费 API）")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def render(repo_url: str, style: str, longform: bool, mock_data: bool, dry_run: bool, config_path: str):
    """完整流水线：分析 → 脚本 → TTS → 音频 → RSS。

    直接调用 main.run_pipeline()，生成一期完整播客并发布 RSS。
    """
    console.print(f"[bold green]▸ 渲染播客：[/bold green]{repo_url}")
    try:
        from main import run_pipeline
    except Exception as e:
        raise click.ClickException(f"无法加载流水线（main.run_pipeline）：{e}")

    episode = run_pipeline(
        repo_urls=[repo_url],
        style=style,
        longform=longform,
        mock_data=mock_data,
        dry_run=dry_run,
        config_path=config_path,
    )
    if episode is None:
        sys.exit(1)


# =====================================================================
# ask
# =====================================================================
@cli.command()
@click.argument("repo_url")
@click.argument("question")
@click.option("--speak", is_flag=True, help="同时生成答案的 TTS 语音")
@click.option("--mock-data", is_flag=True, help="使用 mock 项目数据")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def ask(repo_url: str, question: str, speak: bool, mock_data: bool, config_path: str):
    """就某个 GitHub 项目进行交互式问答。

    先分析项目（或加载缓存分析），再基于分析上下文回答你的问题。
    问题需用引号包裹，例如：ask <url> "这个项目的核心架构是什么？"
    """
    console.print(f"[bold green]▸ 问答：[/bold green]{repo_url}")
    console.print(f"[dim]问题：{question}[/dim]")

    try:
        config, repos, analyses = _get_or_load_analysis(
            repo_url, config_path, mock_data
        )
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"获取项目分析失败：{e}")

    answer = _answer_question(config, repos, analyses, question)
    console.print()
    console.print(Panel(answer, title="回答", border_style="green"))

    if speak:
        _speak_answer(config, answer)


def _cache_path(config: dict, repo_url: str) -> Path:
    """返回单个项目的分析缓存文件路径。"""
    cache_dir = Path(config["project_root"]) / "output" / "cli_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = (
        repo_url.replace("https://github.com/", "")
        .replace("http://github.com/", "")
        .replace("/", "_")
        .replace(":", "_")
    )
    return cache_dir / f"{safe}.json"


def _get_or_load_analysis(repo_url: str, config_path: str, mock_data: bool):
    """获取项目分析结果，优先使用缓存。返回 (config, repos, analyses)。"""
    from src.config_loader import load_config
    from src.models import GitHubRepo, ProjectAnalysis

    config = load_config(config_path)
    cache = _cache_path(config, repo_url)

    # 尝试加载缓存（mock 模式下强制重新分析，以保证数据一致）
    if cache.exists() and not mock_data:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            repos = [GitHubRepo(**r) for r in data.get("repos", [])]
            analyses = [ProjectAnalysis.from_dict(a) for a in data.get("analyses", [])]
            if repos and analyses:
                console.print(f"[dim]（已加载缓存分析：{cache.name}）[/dim]")
                return config, repos, analyses
        except Exception as e:
            console.print(f"[yellow]缓存加载失败，重新分析：{e}[/yellow]")

    # 运行完整分析
    config, repos, analyses, _health = _run_analysis(repo_url, config_path, mock_data)

    # 写入缓存
    try:
        cache_data = {
            "repo_url": repo_url,
            "cached_at": datetime.now().isoformat(),
            "repos": [
                {
                    "name": r.name,
                    "url": r.url,
                    "description": r.description,
                    "stars": r.stars,
                    "language": r.language,
                    "topics": r.topics,
                    "readme_markdown": r.readme_markdown,
                    "trending_rank": r.trending_rank,
                }
                for r in repos
            ],
            "analyses": [a.to_dict() for a in analyses],
        }
        cache.write_text(
            json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        console.print(f"[dim]（分析已缓存：{cache.name}）[/dim]")
    except Exception as e:
        console.print(f"[yellow]缓存写入失败：{e}[/yellow]")

    return config, repos, analyses


def _answer_question(config: dict, repos, analyses, question: str) -> str:
    """基于项目分析上下文回答问题。

    优先使用 src.qa_engine.QAEngine；若尚未就绪或调用失败，回退到内置 LLM 问答，
    保证命令始终可用。ask 命令针对单个项目，因此取首个 repo / analysis。
    """
    if not analyses or not repos:
        return "（未生成项目分析，无法回答。请确认项目 URL 正确且可访问后重试。）"

    analysis_data = analyses[0].to_dict()
    readme_excerpt = repos[0].readme_markdown or ""

    # QAEngine 契约：ask(question, analysis_data: dict, readme_excerpt: str) -> str
    try:
        from src.qa_engine import QAEngine

        engine = QAEngine(config)
        return engine.ask(question, analysis_data, readme_excerpt)
    except ImportError:
        console.print(
            "[dim]（src/qa_engine.py 尚未就绪，使用内置 LLM 问答回退）[/dim]"
        )
    except Exception as e:
        console.print(f"[yellow]QAEngine 调用失败，回退到内置问答：{e}[/yellow]")

    return _fallback_llm_ask(config, repos, analyses, question)


def _fallback_llm_ask(config: dict, repos, analyses, question: str) -> str:
    """QAEngine 未就绪时的内置 LLM 问答回退。"""
    from openai import OpenAI

    cfg = config["llm"]
    api_key = config["api_keys"].get("llm", "") or config["api_keys"].get(
        "deepseek", ""
    )
    if not api_key:
        return (
            "（未配置 LLM API Key，无法回答。请在 .env 中配置 LLM_API_KEY / "
            "SILICONFLOW_API_KEY，或等待 src/qa_engine.py 就绪后重试。）"
        )

    context = _build_qa_context(repos, analyses)
    system = (
        "你是一位资深开源项目分析师。请基于以下 GitHub 项目的 README 与深度分析结果，"
        "用中文准确、简洁地回答用户的问题。如果提供的信息不足以回答，请如实说明，"
        "不要编造项目中不存在的技术细节。"
    )
    kwargs = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"## 项目上下文\n{context}\n\n## 问题\n{question}",
            },
        ],
        "temperature": 0.4,
        "max_tokens": cfg.get("max_tokens", 4000),
    }
    # SiliconFlow Qwen3.5 系列需关闭 thinking 模式
    if cfg.get("enable_thinking") is False:
        kwargs["extra_body"] = {"enable_thinking": False}

    client = OpenAI(
        api_key=api_key, base_url=cfg["base_url"], timeout=cfg.get("timeout", 120)
    )
    try:
        resp = client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip() or "（模型未返回内容）"
    except Exception as e:
        return f"（LLM 问答失败：{e}）"


def _build_qa_context(repos, analyses) -> str:
    """汇总项目信息为问答上下文文本。"""
    analysis_map = {a.repo_name: a for a in analyses}
    parts: list[str] = []
    for repo in repos:
        a = analysis_map.get(repo.name)
        parts.append(
            f"### {repo.name}\n- 地址：{repo.url}\n- Star：{repo.stars}\n"
            f"- 语言：{repo.language or '未指定'}\n- 描述：{repo.description}"
        )
        if a:
            parts.append(f"- 概述：{a.summary}")
            parts.append(f"- 技术栈：{', '.join(a.tech_stack)}")
            parts.append(f"- 架构：{a.architecture}")
            if a.highlights:
                parts.append(f"- 亮点：{'; '.join(a.highlights)}")
            if a.use_cases:
                parts.append(f"- 应用场景：{'; '.join(a.use_cases)}")
        if repo.readme_markdown:
            parts.append(f"- README 摘要：{repo.readme_markdown[:3000]}")
    return "\n".join(parts)


def _speak_answer(config: dict, answer: str) -> None:
    """将答案合成为 TTS 语音文件。"""
    import shutil

    from src.models import PodcastHost, PodcastScript, PodcastSegment
    from src.tts_synth import TTSSynthesizer

    synth = TTSSynthesizer(config)
    segment = PodcastSegment(
        speaker="助手", text=answer, emotion="neutral", voice_key="host"
    )
    script = PodcastScript(
        title="Q&A 回答",
        description="repo2pod ask 生成的回答语音",
        hosts=[PodcastHost("助手", "项目分析师", "host")],
        segments=[segment],
    )

    tmp_dir = Path(config["project_root"]) / "output" / "qa_tmp"
    try:
        audio_files = synth.synthesize_script(script, tmp_dir)
        if audio_files and Path(audio_files[0]).exists():
            out_dir = Path(config["project_root"]) / "output" / "qa_audio"
            out_dir.mkdir(parents=True, exist_ok=True)
            ext = config["tts"].get("response_format", "wav")
            final = out_dir / f"qa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
            shutil.move(audio_files[0], final)
            console.print(f"[green]🔊 答案语音已生成：[/green]{final}")
        else:
            console.print(
                "[yellow]语音合成未产出文件（可能未配置 TTS API Key）[/yellow]"
            )
    except Exception as e:
        console.print(f"[yellow]语音合成失败：{e}[/yellow]")
    finally:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =====================================================================
# serve
# =====================================================================
@cli.command()
@click.option("--port", default=5000, type=int, help="监听端口")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--debug", is_flag=True, help="开启 Flask 调试模式")
def serve(port: int, host: str, debug: bool):
    """启动 Web 仪表盘。"""
    try:
        from dashboard import create_app
    except Exception as e:
        raise click.ClickException(
            f"无法加载仪表盘：{e}（请确认已安装 flask 且 dashboard 包完整）"
        )

    app = create_app()

    # 确保输出目录存在（与 dashboard.py 启动逻辑保持一致）
    try:
        import os

        from dashboard.config import EPISODES_DIR, SCRIPTS_DIR

        os.makedirs(str(EPISODES_DIR), exist_ok=True)
        os.makedirs(str(SCRIPTS_DIR), exist_ok=True)
    except Exception:
        pass

    console.print(f"[bold cyan]▸ 启动 Web 仪表盘：[/bold cyan]http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


# =====================================================================
# batch
# =====================================================================
@cli.command()
@click.option("--count", default=5, type=int, help="批量生成的期数")
@click.option("--projects-per-episode", default=3, type=int, help="每期包含的项目数")
@click.option("--mock-data", is_flag=True, help="项目数据用 mock，LLM/TTS 用真实 API")
@click.option("--dry-run", is_flag=True, help="干跑模式（不调用任何 API）")
@click.option("--resume", is_flag=True, help="断点续传（跳过已生成的期数）")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def batch(count: int, projects_per_episode: int, mock_data: bool, dry_run: bool, resume: bool, config_path: str):
    """批量串行生成多期播客。

    委托给 main.run_batch() 执行，支持断点续传与 dry-run。
    """
    try:
        from main import run_batch
    except Exception as e:
        raise click.ClickException(f"无法加载批量逻辑（main.run_batch）：{e}")

    run_batch(
        count=count,
        projects_per_episode=projects_per_episode,
        mock_data=mock_data,
        dry_run=dry_run,
        resume=resume,
        config_path=config_path,
    )


# =====================================================================
# list
# =====================================================================
@cli.command(name="list")
@click.option("--limit", default=10, type=int, help="最多显示条数（0 表示全部）")
@click.option("--config", "config_path", default="config.yaml", help="配置文件路径")
def list_episodes(limit: int, config_path: str):
    """列出已发布的节目历史。"""
    from src.config_loader import load_config
    from src.rss_publisher import RSSPublisher

    cfg = load_config(config_path)
    publisher = RSSPublisher(cfg)
    history = publisher._load_history()
    if not history:
        console.print("[yellow]暂无已发布节目[/yellow]")
        return

    if limit and limit > 0:
        recent = history[-limit:]
    else:
        recent = history
    recent = list(reversed(recent))  # 最新的排在最前

    table = Table(title=f"已发布节目（最近 {len(recent)} 期）")
    table.add_column("#", justify="right", style="dim")
    table.add_column("标题", style="cyan")
    table.add_column("时长", justify="right")
    table.add_column("发布时间")
    for ep in recent:
        mins = ep.get("duration_seconds", 0) / 60
        table.add_row(
            str(ep.get("episode_number", "")),
            ep.get("title", ""),
            f"{mins:.1f} min",
            ep.get("published_at", "")[:16],
        )
    console.print(table)


if __name__ == "__main__":
    cli()
