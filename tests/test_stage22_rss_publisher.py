"""Stage 22 单元测试：RSS Publisher 模块测试。

覆盖范围：
  1. _srt_timestamp —— SRT 时间戳格式化
  2. _episode_to_dict —— Episode 序列化
  3. _load_history / _save_history —— 历史持久化
  4. get_next_episode_number —— 编号递增
  5. generate_chapters_json —— Podcasting 2.0 chapters
  6. generate_transcript_srt —— SRT 字幕生成
  7. _extract_keywords —— 关键词提取与去重
  8. _generate_json_ld —— JSON-LD 结构化数据
  9. _generate_series_json_ld —— 频道级 JSON-LD
 10. _to_iso_date —— 日期格式转换
 11. _build_feed —— 完整 RSS feed 构建
 12. publish —— 完整发布流程
 13. _inject_podcast2_elements —— XML 后处理注入

运行：python -m pytest tests/test_stage22_rss_publisher.py -v
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rss_publisher import RSSPublisher, _srt_timestamp, PODCAST_NS
from src.models import Episode, PodcastScript, PodcastHost, PodcastSegment, Chapter, ShowNotes


# ═══════════════════════════════════════════════════════════════
# 测试夹具
# ═══════════════════════════════════════════════════════════════


def make_rss_config(project_root: str) -> dict:
    """构建 RSSPublisher 所需的配置。"""
    return {
        "project_root": project_root,
        "publish": {
            "language": "zh-cn",
            "category": "Technology",
            "explicit": False,
            "cover_art": "",
            "output_format": "mp3",
        },
        "output": {
            "feed_path": "output/feed.xml",
        },
        "podcast_meta": {
            "title": "GitHub 前沿观察",
            "author": "Test Author",
            "email": "test@example.com",
            "site_url": "https://github.com",
            "media_base_url": "http://localhost:5000/audio",
        },
    }


def make_test_script() -> PodcastScript:
    """构建测试用 PodcastScript。"""
    return PodcastScript(
        title="Test Episode Title",
        description="A test podcast episode description",
        hosts=[
            PodcastHost("Alice", "主持人", "host"),
            PodcastHost("Bob", "嘉宾", "guest"),
        ],
        segments=[
            PodcastSegment("Alice", "Hello everyone!", "excited", "host"),
            PodcastSegment("Bob", "Hi Alice!", "neutral", "guest"),
        ],
        repo_names=["test/repo"],
        repo_urls=["https://github.com/test/repo"],
        style="casual",
        target_minutes=8,
    )


def make_test_episode(episode_number: int = 1) -> Episode:
    """构建测试用 Episode。"""
    return Episode(
        script=make_test_script(),
        audio_path="/tmp/test_audio.mp3",
        duration_seconds=480.0,
        file_size_bytes=5000000,
        episode_number=episode_number,
        chapters=[
            Chapter("Intro", 0.0, 60.0, "Introduction"),
            Chapter("Main", 60.0, 420.0, "Main discussion"),
            Chapter("Outro", 420.0, 480.0, "Conclusion"),
        ],
        show_notes=ShowNotes(
            title="Test Episode",
            summary="A summary of the test episode",
            key_takeaways=["Point 1", "Point 2"],
            mentioned_tech=["Python", "PyTorch", "Python"],  # 含重复
            project_links=[
                {"name": "test/repo", "url": "https://github.com/test/repo", "stars": 100, "description": "A test repo"}
            ],
            timestamps=[{"time": 0, "title": "Intro", "description": ""}],
            social_quotes=["Great quote!"],
        ),
        transcript_path="/tmp/test_transcript.srt",
        status="published",
    )


@pytest.fixture
def rss_publisher(tmp_path):
    """创建使用临时目录的 RSSPublisher。"""
    config = make_rss_config(str(tmp_path))
    return RSSPublisher(config)


@pytest.fixture
def test_episode():
    """提供测试用 Episode。"""
    return make_test_episode()


# ═══════════════════════════════════════════════════════════════
# 1. _srt_timestamp 测试
# ═══════════════════════════════════════════════════════════════


class TestSrtTimestamp:
    """_srt_timestamp 函数测试。"""

    def test_zero_seconds(self):
        """0 秒应为 00:00:00,000。"""
        assert _srt_timestamp(0) == "00:00:00,000"

    def test_seconds_only(self):
        """纯秒数格式化。"""
        assert _srt_timestamp(5.5) == "00:00:05,500"

    def test_minutes(self):
        """分钟格式化。"""
        assert _srt_timestamp(65) == "00:01:05,000"

    def test_hours(self):
        """小时格式化。"""
        assert _srt_timestamp(3661) == "01:01:01,000"

    def test_negative_clamped_to_zero(self):
        """负数应被钳制为 0。"""
        assert _srt_timestamp(-10) == "00:00:00,000"

    def test_millisecond_rounding(self):
        """毫秒四舍五入。"""
        assert _srt_timestamp(1.9999) == "00:00:02,000"

    def test_millisecond_overflow(self):
        """毫秒溢出到 1000 应进位到秒。"""
        result = _srt_timestamp(1.9999)
        # 应正确进位
        assert ",000" in result or ",999" in result

    def test_large_value(self):
        """大数值格式化。"""
        result = _srt_timestamp(3600 * 2 + 60 * 30 + 15)
        assert result == "02:30:15,000"


# ═══════════════════════════════════════════════════════════════
# 2. _episode_to_dict 测试
# ═══════════════════════════════════════════════════════════════


class TestEpisodeToDict:
    """Episode 序列化测试。"""

    def test_basic_fields(self, rss_publisher, test_episode):
        """基本字段应正确序列化。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert d["episode_number"] == test_episode.episode_number
        assert d["title"] == test_episode.script.title
        assert d["description"] == test_episode.script.description
        assert d["audio_path"] == test_episode.audio_path
        assert d["duration_seconds"] == test_episode.duration_seconds
        assert d["file_size_bytes"] == test_episode.file_size_bytes

    def test_audio_filename_extracted(self, rss_publisher, test_episode):
        """audio_filename 应从 audio_path 提取。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert d["audio_filename"] == "test_audio.mp3"

    def test_chapters_serialized(self, rss_publisher, test_episode):
        """chapters 应序列化为 dict 列表。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert len(d["chapters"]) == 3
        assert d["chapters"][0]["title"] == "Intro"
        assert d["chapters"][0]["start_time"] == 0.0

    def test_show_notes_serialized(self, rss_publisher, test_episode):
        """show_notes 应同时包含 dict 和 markdown。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert "show_notes" in d
        assert "show_notes_markdown" in d
        assert isinstance(d["show_notes"], dict)
        assert isinstance(d["show_notes_markdown"], str)

    def test_transcript_path(self, rss_publisher, test_episode):
        """transcript_path 和 transcript_filename 应正确序列化。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert d["transcript_path"] == "/tmp/test_transcript.srt"
        assert d["transcript_filename"] == "test_transcript.srt"

    def test_repo_names_and_urls(self, rss_publisher, test_episode):
        """repo_names 和 repo_urls 应正确序列化。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert d["repo_names"] == ["test/repo"]
        assert d["repo_urls"] == ["https://github.com/test/repo"]

    def test_status_field(self, rss_publisher, test_episode):
        """status 应正确序列化。"""
        d = rss_publisher._episode_to_dict(test_episode)
        assert d["status"] == "published"


# ═══════════════════════════════════════════════════════════════
# 3. 历史持久化测试
# ═══════════════════════════════════════════════════════════════


class TestHistoryPersistence:
    """_load_history / _save_history 测试。"""

    def test_load_empty_history(self, rss_publisher):
        """无历史文件时应返回空列表。"""
        assert rss_publisher._load_history() == []

    def test_save_and_load_history(self, rss_publisher, test_episode):
        """保存后应能正确加载。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        rss_publisher._save_history([ep_dict])

        loaded = rss_publisher._load_history()
        assert len(loaded) == 1
        assert loaded[0]["episode_number"] == test_episode.episode_number
        assert loaded[0]["title"] == test_episode.script.title

    def test_save_multiple_episodes(self, rss_publisher):
        """保存多期节目应正确持久化。"""
        episodes = []
        for i in range(1, 4):
            ep = make_test_episode(i)
            episodes.append(rss_publisher._episode_to_dict(ep))
        rss_publisher._save_history(episodes)

        loaded = rss_publisher._load_history()
        assert len(loaded) == 3
        assert loaded[0]["episode_number"] == 1
        assert loaded[2]["episode_number"] == 3

    def test_load_corrupted_history(self, rss_publisher, tmp_path):
        """损坏的 JSON 文件应返回空列表。"""
        rss_publisher.history_path.parent.mkdir(parents=True, exist_ok=True)
        rss_publisher.history_path.write_text("not valid json", encoding="utf-8")
        assert rss_publisher._load_history() == []

    def test_atomic_write(self, rss_publisher, test_episode):
        """保存应使用原子写入（临时文件 + os.replace）。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        rss_publisher._save_history([ep_dict])

        # 历史文件应存在
        assert rss_publisher.history_path.exists()
        # 临时文件不应残留
        tmp_path = rss_publisher.history_path.with_suffix(".tmp")
        assert not tmp_path.exists()


# ═══════════════════════════════════════════════════════════════
# 4. get_next_episode_number 测试
# ═══════════════════════════════════════════════════════════════


class TestGetNextEpisodeNumber:
    """get_next_episode_number 测试。"""

    def test_empty_history_returns_1(self, rss_publisher):
        """无历史时编号应为 1。"""
        assert rss_publisher.get_next_episode_number() == 1

    def test_after_first_episode_returns_2(self, rss_publisher, test_episode):
        """有一期节目后编号应为 2。"""
        rss_publisher._save_history([rss_publisher._episode_to_dict(test_episode)])
        assert rss_publisher.get_next_episode_number() == 2

    def test_multiple_episodes(self, rss_publisher):
        """有多期节目后编号应为最大值 + 1。"""
        episodes = []
        for i in [1, 3, 5]:
            ep = make_test_episode(i)
            episodes.append(rss_publisher._episode_to_dict(ep))
        rss_publisher._save_history(episodes)
        assert rss_publisher.get_next_episode_number() == 6


# ═══════════════════════════════════════════════════════════════
# 5. generate_chapters_json 测试
# ═══════════════════════════════════════════════════════════════


class TestGenerateChaptersJson:
    """generate_chapters_json 测试。"""

    def test_generates_valid_json(self, rss_publisher, test_episode):
        """应生成有效的 JSON 文件。"""
        path = rss_publisher.generate_chapters_json(test_episode)
        assert Path(path).exists()

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["version"] == "1.2.0"
        assert isinstance(data["chapters"], list)
        assert len(data["chapters"]) == 3

    def test_chapter_fields(self, rss_publisher, test_episode):
        """章节应包含 startTime 和 title。"""
        path = rss_publisher.generate_chapters_json(test_episode)
        data = json.loads(Path(path).read_text(encoding="utf-8"))

        for ch in data["chapters"]:
            assert "startTime" in ch
            assert "title" in ch

    def test_chapter_start_times(self, rss_publisher, test_episode):
        """章节起始时间应正确。"""
        path = rss_publisher.generate_chapters_json(test_episode)
        data = json.loads(Path(path).read_text(encoding="utf-8"))

        assert data["chapters"][0]["startTime"] == 0.0
        assert data["chapters"][1]["startTime"] == 60.0
        assert data["chapters"][2]["startTime"] == 420.0

    def test_filename_format(self, rss_publisher, test_episode):
        """文件名应符合 episode_XXX_chapters.json 格式。"""
        path = rss_publisher.generate_chapters_json(test_episode)
        filename = Path(path).name
        assert filename == "episode_001_chapters.json"

    def test_empty_chapters_fallback(self, rss_publisher):
        """无章节时应生成兜底开场章节。"""
        ep = make_test_episode(1)
        ep.chapters = []
        path = rss_publisher.generate_chapters_json(ep)

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert len(data["chapters"]) == 1
        assert data["chapters"][0]["startTime"] == 0
        assert data["chapters"][0]["title"] == "开场"


# ═══════════════════════════════════════════════════════════════
# 6. generate_transcript_srt 测试
# ═══════════════════════════════════════════════════════════════


class TestGenerateTranscriptSrt:
    """generate_transcript_srt 测试。"""

    def test_generates_srt_file(self, rss_publisher, test_episode):
        """应生成 SRT 文件。"""
        script = test_episode.script
        path = rss_publisher.generate_transcript_srt(script)
        assert Path(path).exists()

        content = Path(path).read_text(encoding="utf-8")
        assert "-->" in content  # SRT 时间戳格式

    def test_srt_entry_count(self, rss_publisher, test_episode):
        """SRT 条目数应与段落数一致。"""
        script = test_episode.script
        path = rss_publisher.generate_transcript_srt(script)
        content = Path(path).read_text(encoding="utf-8")
        # SRT 条目以序号开头，空行分隔
        entries = [s for s in content.split("\n\n") if s.strip()]
        assert len(entries) == len(script.segments)

    def test_srt_contains_speaker_and_text(self, rss_publisher, test_episode):
        """SRT 应包含说话人和文本。"""
        script = test_episode.script
        path = rss_publisher.generate_transcript_srt(script)
        content = Path(path).read_text(encoding="utf-8")
        assert "Alice" in content
        assert "Bob" in content
        assert "Hello" in content

    def test_srt_with_segment_timings(self, rss_publisher, test_episode):
        """使用 segment_timings 时应正确应用时间。"""
        script = test_episode.script
        timings = [
            {"index": 0, "start_time": 0.0, "end_time": 10.0},
            {"index": 1, "start_time": 10.0, "end_time": 20.0},
        ]
        path = rss_publisher.generate_transcript_srt(script, timings)
        content = Path(path).read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:10,000" in content
        assert "00:00:10,000 --> 00:00:20,000" in content

    def test_empty_script_returns_empty(self, rss_publisher):
        """空脚本应返回空字符串。"""
        script = PodcastScript(
            title="Empty",
            description="No segments",
            hosts=[],
            segments=[],
        )
        result = rss_publisher.generate_transcript_srt(script)
        assert result == ""

    def test_estimated_timings_when_none(self, rss_publisher, test_episode):
        """无 timings 时应按字符数估算时间。"""
        script = test_episode.script
        path = rss_publisher.generate_transcript_srt(script)
        content = Path(path).read_text(encoding="utf-8")
        # 第一段应从 0 开始
        assert "00:00:00,000" in content


# ═══════════════════════════════════════════════════════════════
# 7. _extract_keywords 测试
# ═══════════════════════════════════════════════════════════════


class TestExtractKeywords:
    """关键词提取测试。"""

    def test_extracts_mentioned_tech(self, rss_publisher, test_episode):
        """应从 show_notes.mentioned_tech 提取关键词。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert "Python" in keywords
        assert "PyTorch" in keywords

    def test_extracts_repo_short_names(self, rss_publisher, test_episode):
        """应从 repo_names 提取短名。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert "repo" in keywords  # "test/repo" → "repo"

    def test_deduplication(self, rss_publisher, test_episode):
        """重复关键词应去重。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        # mentioned_tech 含两个 "Python"
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert keywords.count("Python") == 1

    def test_max_12_keywords(self, rss_publisher):
        """关键词应限制在 12 个以内。"""
        ep_dict = {
            "show_notes": {
                "mentioned_tech": [f"tech{i}" for i in range(20)],
            },
            "repo_names": [],
        }
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert len(keywords) <= 12

    def test_empty_episode(self, rss_publisher):
        """空节目应返回空列表。"""
        ep_dict = {"show_notes": {}, "repo_names": []}
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert keywords == []

    def test_no_show_notes(self, rss_publisher):
        """无 show_notes 字段应不崩溃。"""
        ep_dict = {"repo_names": ["user/repo"]}
        keywords = rss_publisher._extract_keywords(ep_dict)
        assert "repo" in keywords


# ═══════════════════════════════════════════════════════════════
# 8. _generate_json_ld 测试
# ═══════════════════════════════════════════════════════════════


class TestGenerateJsonLd:
    """JSON-LD 结构化数据测试。"""

    def test_generates_valid_json(self, rss_publisher, test_episode):
        """应生成有效 JSON。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        json_ld = rss_publisher._generate_json_ld(ep_dict)
        data = json.loads(json_ld)
        assert data["@context"] == "https://schema.org"
        assert data["@type"] == "PodcastEpisode"

    def test_episode_number(self, rss_publisher, test_episode):
        """应包含 episodeNumber。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        data = json.loads(rss_publisher._generate_json_ld(ep_dict))
        assert data["episodeNumber"] == test_episode.episode_number

    def test_duration_iso8601(self, rss_publisher, test_episode):
        """时长应为 ISO 8601 格式。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        data = json.loads(rss_publisher._generate_json_ld(ep_dict))
        assert data["duration"].startswith("PT")
        # 480 秒 = 8 分钟 → PT8M
        assert "8M" in data["duration"]

    def test_duration_with_hours(self, rss_publisher):
        """超过 1 小时应含 H。"""
        ep_dict = {
            "duration_seconds": 3725,  # 1h 2m 5s
            "title": "Long Episode",
            "description": "A long episode",
            "episode_number": 1,
            "published_at": "Mon, 01 Jan 2024 00:00:00 +0000",
        }
        data = json.loads(rss_publisher._generate_json_ld(ep_dict))
        assert "1H" in data["duration"]
        assert "2M" in data["duration"]
        assert "5S" in data["duration"]

    def test_associated_media(self, rss_publisher, test_episode):
        """应包含 associatedMedia。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        data = json.loads(rss_publisher._generate_json_ld(ep_dict))
        assert data["associatedMedia"]["@type"] == "MediaObject"
        assert "contentUrl" in data["associatedMedia"]

    def test_part_of_series(self, rss_publisher, test_episode):
        """应包含 partOfSeries。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        data = json.loads(rss_publisher._generate_json_ld(ep_dict))
        assert data["partOfSeries"]["@type"] == "PodcastSeries"
        assert data["partOfSeries"]["name"] == "GitHub 前沿观察"

    def test_show_notes_merged_into_description(self, rss_publisher, test_episode):
        """show_notes_md 应合并到 description。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        json_ld = rss_publisher._generate_json_ld(ep_dict, show_notes_md="## Custom Notes")
        data = json.loads(json_ld)
        assert "Custom Notes" in data["description"]


# ═══════════════════════════════════════════════════════════════
# 9. _generate_series_json_ld 测试
# ═══════════════════════════════════════════════════════════════


class TestGenerateSeriesJsonLd:
    """频道级 JSON-LD 测试。"""

    def test_generates_valid_json(self, rss_publisher):
        """应生成有效 JSON。"""
        json_ld = rss_publisher._generate_series_json_ld()
        data = json.loads(json_ld)
        assert data["@context"] == "https://schema.org"
        assert data["@type"] == "PodcastSeries"

    def test_contains_series_name(self, rss_publisher):
        """应包含频道名称。"""
        data = json.loads(rss_publisher._generate_series_json_ld())
        assert data["name"] == "GitHub 前沿观察"

    def test_contains_author(self, rss_publisher):
        """应包含 author。"""
        data = json.loads(rss_publisher._generate_series_json_ld())
        assert data["author"]["@type"] == "Person"
        assert data["author"]["name"] == "Test Author"

    def test_contains_url(self, rss_publisher):
        """应包含 url。"""
        data = json.loads(rss_publisher._generate_series_json_ld())
        assert data["url"] == "https://github.com"

    def test_contains_language(self, rss_publisher):
        """应包含 inLanguage。"""
        data = json.loads(rss_publisher._generate_series_json_ld())
        assert data["inLanguage"] == "zh-cn"


# ═══════════════════════════════════════════════════════════════
# 10. _to_iso_date 测试
# ═══════════════════════════════════════════════════════════════


class TestToIsoDate:
    """日期格式转换测试。"""

    def test_rfc2822_to_iso(self, rss_publisher):
        """RFC 2822 日期应转为 ISO 格式。"""
        result = rss_publisher._to_iso_date("Mon, 01 Jan 2024 12:00:00 +0000")
        assert result == "2024-01-01"

    def test_empty_string(self, rss_publisher):
        """空字符串应返回空。"""
        assert rss_publisher._to_iso_date("") == ""

    def test_already_short_date(self, rss_publisher):
        """短日期应直接返回前 10 字符。"""
        assert rss_publisher._to_iso_date("2024-01-01") == "2024-01-01"

    def test_invalid_date(self, rss_publisher):
        """无效日期应返回前 10 字符作为兜底。"""
        result = rss_publisher._to_iso_date("not-a-date")
        assert result == "not-a-date"


# ═══════════════════════════════════════════════════════════════
# 11. _build_feed 测试
# ═══════════════════════════════════════════════════════════════


class TestBuildFeed:
    """RSS feed 构建测试。"""

    def test_builds_valid_xml(self, rss_publisher, test_episode):
        """应生成有效的 RSS XML。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_xml = rss_publisher._build_feed([ep_dict])

        assert isinstance(feed_xml, (str, bytes))
        content = feed_xml if isinstance(feed_xml, str) else feed_xml.decode("utf-8")
        assert "<?xml" in content
        assert "<rss" in content
        assert "<channel" in content

    def test_feed_contains_episode(self, rss_publisher, test_episode):
        """feed 应包含节目条目。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        content = rss_publisher._build_feed([ep_dict])
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        assert "<item>" in content
        assert test_episode.script.title in content

    def test_feed_contains_itunes_tags(self, rss_publisher, test_episode):
        """feed 应包含 iTunes 标签。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        content = rss_publisher._build_feed([ep_dict])
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        assert "itunes:" in content.lower()

    def test_feed_contains_enclosure(self, rss_publisher, test_episode):
        """feed 应包含音频 enclosure。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        content = rss_publisher._build_feed([ep_dict])
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        assert "<enclosure" in content

    def test_multiple_episodes(self, rss_publisher):
        """多期节目应都出现在 feed 中。"""
        episodes = []
        for i in range(1, 4):
            ep = make_test_episode(i)
            episodes.append(rss_publisher._episode_to_dict(ep))

        content = rss_publisher._build_feed(episodes)
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        # 应有 3 个 <item>
        assert content.count("<item>") == 3

    def test_episodes_in_reverse_order(self, rss_publisher):
        """最新节目应在最前面（feedgen 内部反转条目，传入正序即得到最新在前）。"""
        episodes = []
        for i in [1, 2, 3]:
            ep = make_test_episode(i)
            episodes.append(rss_publisher._episode_to_dict(ep))

        content = rss_publisher._build_feed(episodes)
        if isinstance(content, bytes):
            content = content.decode("utf-8")

        # episode 3 应在 episode 1 之前（feedgen 输出 <guid isPermaLink="false">episode-X</guid>）
        pos3 = content.find("episode-3</guid>")
        pos1 = content.find("episode-1</guid>")
        assert pos3 != -1, "episode-3 guid not found in feed"
        assert pos1 != -1, "episode-1 guid not found in feed"
        assert pos3 < pos1


# ═══════════════════════════════════════════════════════════════
# 12. publish 完整流程测试
# ═══════════════════════════════════════════════════════════════


class TestPublish:
    """完整发布流程测试。"""

    def test_publish_creates_feed_file(self, rss_publisher, test_episode):
        """publish 应创建 RSS feed 文件。"""
        path = rss_publisher.publish(test_episode)
        assert Path(path).exists()

        content = Path(path).read_text(encoding="utf-8")
        assert "<?xml" in content
        assert "<rss" in content

    def test_publish_updates_history(self, rss_publisher, test_episode):
        """publish 后历史应更新。"""
        rss_publisher.publish(test_episode)
        history = rss_publisher._load_history()
        assert len(history) == 1
        assert history[0]["episode_number"] == test_episode.episode_number

    def test_publish_multiple_episodes(self, rss_publisher):
        """多次 publish 应追加到历史。"""
        for i in range(1, 4):
            ep = make_test_episode(i)
            rss_publisher.publish(ep)

        history = rss_publisher._load_history()
        assert len(history) == 3

    def test_publish_generates_chapters_json(self, rss_publisher, test_episode):
        """publish 应生成 chapters JSON。"""
        rss_publisher.publish(test_episode)

        chapters_path = (
            rss_publisher.feed_path.parent
            / "episodes"
            / f"episode_{test_episode.episode_number:03d}_chapters.json"
        )
        assert chapters_path.exists()

    def test_publish_without_chapters(self, rss_publisher):
        """无章节的节目应仍能正常发布。"""
        ep = make_test_episode(1)
        ep.chapters = []
        path = rss_publisher.publish(ep)
        assert Path(path).exists()

    def test_publish_returns_feed_path(self, rss_publisher, test_episode):
        """publish 应返回 feed 文件路径。"""
        path = rss_publisher.publish(test_episode)
        assert str(rss_publisher.feed_path) == path

    def test_publish_creates_output_directory(self, rss_publisher, test_episode):
        """publish 应自动创建输出目录。"""
        # 删除目录确保测试干净
        if rss_publisher.feed_path.parent.exists():
            import shutil
            shutil.rmtree(rss_publisher.feed_path.parent)

        rss_publisher.publish(test_episode)
        assert rss_publisher.feed_path.parent.exists()


# ═══════════════════════════════════════════════════════════════
# 13. _inject_podcast2_elements 测试
# ═══════════════════════════════════════════════════════════════


class TestInjectPodcast2Elements:
    """XML 后处理注入测试。"""

    def test_injects_chapters_element(self, rss_publisher, test_episode):
        """应注入 <podcast:chapters>。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_bytes = rss_publisher._build_feed([ep_dict])
        if isinstance(feed_bytes, str):
            feed_bytes = feed_bytes.encode("utf-8")

        podcast2_meta = {
            test_episode.episode_number: {
                "chapters_url": "http://example.com/chapters.json",
                "transcript_url": "http://example.com/transcript.srt",
                "keywords": ["Python", "PyTorch"],
            }
        }

        result = rss_publisher._inject_podcast2_elements(feed_bytes, podcast2_meta)
        assert result is not None

        content = result.decode("utf-8")
        assert "podcast:chapters" in content
        assert "podcast:transcript" in content

    def test_injects_itunes_keywords(self, rss_publisher, test_episode):
        """应注入 <itunes:keywords>。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_bytes = rss_publisher._build_feed([ep_dict])
        if isinstance(feed_bytes, str):
            feed_bytes = feed_bytes.encode("utf-8")

        podcast2_meta = {
            test_episode.episode_number: {
                "keywords": ["Python", "PyTorch"],
            }
        }

        result = rss_publisher._inject_podcast2_elements(feed_bytes, podcast2_meta)
        assert result is not None
        content = result.decode("utf-8")
        assert "Python" in content
        assert "PyTorch" in content

    def test_no_meta_returns_none(self, rss_publisher, test_episode):
        """无匹配 meta 时应返回 None。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_bytes = rss_publisher._build_feed([ep_dict])
        if isinstance(feed_bytes, str):
            feed_bytes = feed_bytes.encode("utf-8")

        # episode 999 不存在于 feed 中
        podcast2_meta = {999: {"chapters_url": "http://example.com"}}
        result = rss_publisher._inject_podcast2_elements(feed_bytes, podcast2_meta)
        assert result is None

    def test_empty_meta_returns_none(self, rss_publisher, test_episode):
        """空 meta 应返回 None。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_bytes = rss_publisher._build_feed([ep_dict])
        if isinstance(feed_bytes, str):
            feed_bytes = feed_bytes.encode("utf-8")

        result = rss_publisher._inject_podcast2_elements(feed_bytes, {})
        assert result is None

    def test_lxml_unavailable_falls_back(self, rss_publisher, test_episode):
        """lxml 不可用时应返回 None（不崩溃）。"""
        ep_dict = rss_publisher._episode_to_dict(test_episode)
        feed_bytes = rss_publisher._build_feed([ep_dict])
        if isinstance(feed_bytes, str):
            feed_bytes = feed_bytes.encode("utf-8")

        with patch("builtins.__import__", side_effect=ImportError("no lxml")):
            result = rss_publisher._inject_podcast2_elements(feed_bytes, {1: {}})
            assert result is None


# ═══════════════════════════════════════════════════════════════
# 14. RSSPublisher 初始化测试
# ═══════════════════════════════════════════════════════════════


class TestRSSPublisherInit:
    """RSSPublisher 初始化测试。"""

    def test_feed_path_correct(self, tmp_path):
        """feed_path 应基于 project_root + output.feed_path。"""
        config = make_rss_config(str(tmp_path))
        publisher = RSSPublisher(config)
        assert publisher.feed_path == tmp_path / "output" / "feed.xml"

    def test_history_path_correct(self, tmp_path):
        """history_path 应在 feed_path 同目录。"""
        config = make_rss_config(str(tmp_path))
        publisher = RSSPublisher(config)
        assert publisher.history_path == publisher.feed_path.parent / "episodes_history.json"

    def test_config_stored(self, tmp_path):
        """配置应正确存储。"""
        config = make_rss_config(str(tmp_path))
        publisher = RSSPublisher(config)
        assert publisher.cfg == config["publish"]
        assert publisher.output_cfg == config["output"]
        assert publisher.meta == config["podcast_meta"]
