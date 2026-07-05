"""共享测试 fixture —— 供所有 test_stage*.py 使用。

设计原则（第一性原理）：
  1. 单一数据源：工厂函数集中定义，消除跨文件重复
  2. 可组合：基础 fixture 通过组合构建复杂对象
  3. 真实性：mock 数据贴近真实数据结构，而非随意填充
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 将项目根加入 path（一次即可，子文件不再需要重复）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# 基础工厂函数
# ═══════════════════════════════════════════════════════════════


def make_config(api_key: str = "", mock_mode: bool = False) -> dict:
    """构建测试用配置（无 API Key 时走业务模块内置 mock 模式）。"""
    return {
        "api_keys": {
            "llm": api_key,
            "tts": api_key,
            "deepseek": "",
            "dashscope": "",
            "siliconflow": api_key,
            "github": "",
        },
        "crawler": {
            "jina_reader_url": "https://r.jina.ai",
            "max_readme_chars": 8000,
            "timeout": 30,
        },
        "llm": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3.5-9B",
            "enable_thinking": False,
            "temperature": 0.8,
            "max_tokens": 4000,
            "timeout": 120,
        },
        "tts": {
            "provider": "mock",
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "FunAudioLLM/CosyVoice2-0.5B",
            "response_format": "wav",
            "voice_mapping": {"host": "alex", "guest": "anna"},
            "sample_rate": 24000,
        },
        "audio": {
            "segment_silence_ms": 400,
            "sentence_silence_ms": 150,
            "target_lufs": -16.0,
            "output_format": "mp3",
            "output_bitrate": "192k",
            "bgm_path": "",
        },
        "discovery": {
            "rsshub_base_url": "https://rsshub.app",
            "trending_since": "daily",
            "language": "",
            "trending_api_url": "https://api.gitterapp.com/repositories",
            "max_projects": 3,
            "min_stars": 100,
            "keywords": [],
            "exclude_keywords": ["awesome", "interview", "leetcode"],
        },
        "podcast_style": "casual",
        "longform": False,
        "_mock_mode": mock_mode,
        "project_root": str(_PROJECT_ROOT),
    }


def make_repo(name: str = "test/repo", **overrides) -> "GitHubRepo":
    """构建测试用 GitHubRepo。"""
    from src.models import GitHubRepo

    defaults = dict(
        name=name,
        url=f"https://github.com/{name}",
        description="A test repository for unit testing",
        stars=1000,
        language="Python",
        topics=["python", "testing"],
        readme_markdown="# Test Repo\n\nThis is a test README.",
    )
    defaults.update(overrides)
    return GitHubRepo(**defaults)


def make_repo_with_readme(name: str = "test/repo", readme: str = "") -> "GitHubRepo":
    """构建带自定义 README 的 repo。"""
    if not readme:
        readme = """# Test Project

A comprehensive testing framework for Python.

## Features
- Async support
- Fixture system
- Parallel execution

## Installation
```bash
pip install test-framework
```

## Architecture
The framework uses a plugin system with hooks for each test phase.
"""
    return make_repo(name=name, readme_markdown=readme)


def make_script(n_segments: int = 3) -> "PodcastScript":
    """构建测试用 PodcastScript。"""
    from src.models import PodcastScript, PodcastHost, PodcastSegment

    host = PodcastHost("Alice", "主持人", "host")
    guest = PodcastHost("Bob", "嘉宾", "guest")
    segments = [
        PodcastSegment("Alice", "Hello everyone!", "excited", "host"),
        PodcastSegment("Bob", "Hi Alice, great to be here.", "neutral", "guest"),
        PodcastSegment("Alice", "Let's talk about the project.", "curious", "host"),
    ]
    # 如需更多段，循环追加
    while len(segments) < n_segments:
        speaker = "Bob" if len(segments) % 2 == 0 else "Alice"
        vkey = "guest" if speaker == "Bob" else "host"
        segments.append(PodcastSegment(speaker, f"Segment {len(segments)}", "neutral", vkey))

    return PodcastScript(
        title="Test Podcast",
        description="A test podcast episode",
        hosts=[host, guest],
        segments=segments,
        repo_names=["test/repo"],
    )


def make_analysis(repo_name: str = "test/repo") -> "ProjectAnalysis":
    """构建测试用 ProjectAnalysis。"""
    from src.models import ProjectAnalysis

    return ProjectAnalysis(
        repo_name=repo_name,
        summary="A test project for unit testing",
        tech_stack=["Python", "PyTorch"],
        architecture="Layered architecture with plugin system",
        key_modules=[
            {"name": "core", "description": "Core testing engine"},
            {"name": "runner", "description": "Test runner with parallel support"},
        ],
        quick_start="1. pip install test-framework\n2. Write tests\n3. Run pytest",
        highlights=["Plugin architecture", "Async native support"],
        use_cases=["Unit testing", "Integration testing"],
        comparison="Lighter than pytest, more features than unittest",
        code_insights="Clean separation of concerns with strategy pattern",
        mermaid_diagram="graph TD\n  A[Core] --> B[Runner]",
        dependencies=[
            {"name": "pytest", "version": ">=7.0"},
            {"name": "asyncio", "version": ">=3.4"},
        ],
    )


def make_health(repo_name: str = "test/repo") -> "RepoHealth":
    """构建测试用 RepoHealth。"""
    from src.models import RepoHealth

    return RepoHealth(
        repo_name=repo_name,
        commit_count_30d=42,
        contributor_count=8,
        release_count=5,
        open_issues=12,
        closed_issues=88,
        issue_close_rate=0.88,
        last_commit_date="2026-06-28",
        last_release_date="2026-06-15",
        top_contributors=[{"name": "dev1", "commits": 30}, {"name": "dev2", "commits": 12}],
        commit_activity_trend="active",
    )


def make_dependency_info() -> "DependencyInfo":
    """构建测试用 DependencyInfo。"""
    from src.models import DependencyInfo

    return DependencyInfo(
        file_name="requirements.txt",
        manager="pip",
        dependencies=[
            {"name": "requests", "version": ">=2.31.0"},
            {"name": "pydantic", "version": ">=2.0.0"},
        ],
    )


def make_episode():
    """构建测试用 Episode。"""
    from src.models import Episode, Chapter, ShowNotes

    script = make_script()
    return Episode(
        script=script,
        audio_path="/tmp/test_episode.mp3",
        duration_seconds=180.0,
        file_size_bytes=5000000,
        episode_number=1,
        chapters=[
            Chapter("Intro", 0.0, 60.0, "Introduction"),
            Chapter("Main", 60.0, 150.0, "Main discussion"),
        ],
        show_notes=ShowNotes(
            title="Test Episode",
            summary="A test episode",
            key_takeaways=["Key point 1", "Key point 2"],
        ),
    )


# ═══════════════════════════════════════════════════════════════
# pytest fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def config():
    """提供测试配置（无 API Key，走 mock 模式）。"""
    return make_config()


@pytest.fixture
def config_with_key():
    """提供带 API Key 的测试配置。"""
    return make_config(api_key="test-key-12345")


@pytest.fixture
def repo():
    """提供测试用 repo。"""
    return make_repo()


@pytest.fixture
def repos():
    """提供多个 repo（用于多项目测试）。"""
    return [
        make_repo("test/repo-a", stars=500),
        make_repo("test/repo-b", stars=1500),
        make_repo("test/repo-c", stars=800),
    ]


@pytest.fixture
def script():
    """提供测试用脚本。"""
    return make_script()


@pytest.fixture
def analysis():
    """提供测试用分析结果。"""
    return make_analysis()


@pytest.fixture
def health():
    """提供测试用健康度数据。"""
    return make_health()


@pytest.fixture
def tmp_output(tmp_path):
    """提供临时输出目录，并设置环境变量。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "episodes").mkdir()
    (output_dir / "scripts").mkdir()
    (output_dir / "audio").mkdir()
    (output_dir / "analyses").mkdir()
    return output_dir


# ═══════════════════════════════════════════════════════════════
# Stage 5: 测试标记自动化 — pytest_collection_modifyitems 钩子
# 根据测试文件名自动打上 unit / integration / system 标记，
# 支持 `pytest -m unit` 等选择性执行。
# ═══════════════════════════════════════════════════════════════

# 文件名 → 测试类型映射
_SYSTEM_TESTS = {"test_dry_run", "test_stage3_search"}
_INTEGRATION_TESTS = {
    "test_stage7_huey",
    "test_stage11_segmented",
    "test_stage15_providers",
    "test_stage16_pipeline",
    "test_stage18_oss_replace",
}


def _classify_test_module(module_name: str) -> str:
    """根据测试模块名返回分类标记：unit / integration / system。"""
    if module_name in _SYSTEM_TESTS:
        return "system"
    if module_name in _INTEGRATION_TESTS:
        return "integration"
    return "unit"


def pytest_collection_modifyitems(items):
    """收集测试后，自动为每个测试项添加分类标记。"""
    for item in items:
        # 从 nodeid 提取模块名（如 tests/test_stage1_llm.py::TestClass::test_method）
        parts = item.nodeid.split("::")
        module_path = parts[0]  # "tests/test_stage1_llm.py"
        module_name = Path(module_path).stem  # "test_stage1_llm"

        marker = _classify_test_module(module_name)
        item.add_marker(getattr(pytest.mark, marker))

        # 系统测试同时标记为 slow
        if marker == "system":
            item.add_marker(pytest.mark.slow)
