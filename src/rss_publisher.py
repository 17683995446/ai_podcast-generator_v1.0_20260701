"""RSS 播客发布模块：生成 Apple Podcasts 兼容的播客 RSS feed。

使用 feedgen 生成标准的 podcast RSS 2.0 feed，含 iTunes 标签。
支持追加新节目，历史节目持久化到 JSON 文件。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import Episode, PodcastScript

from src.logger import get_logger

logger = get_logger(__name__)


# Podcasting 2.0 命名空间（podcast:chapters / podcast:transcript 等）
PODCAST_NS = "https://podcastindex.org/namespace/1.0"


def _srt_timestamp(seconds: float) -> str:
    """将秒数转为 SRT 时间戳 HH:MM:SS,mmm。"""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    # 处理四舍五入到 1000 的边界情况
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class RSSPublisher:
    """播客 RSS feed 生成与发布。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["publish"]
        self.output_cfg = config["output"]
        self.meta = config["podcast_meta"]
        self.feed_path = Path(config["project_root"]) / self.output_cfg["feed_path"]
        # 历史节目索引（用于追加 + 编号）
        self.history_path = self.feed_path.parent / "episodes_history.json"

    def publish(self, episode: Episode) -> str:
        """发布一期节目：更新 RSS feed。

        Args:
            episode: 已生成音频的节目。

        Returns:
            RSS feed 文件路径。
        """
        # 加载历史
        history = self._load_history()

        # 若节目含章节，确保 chapters JSON 文件已生成（供 <podcast:chapters> 引用）
        if episode.chapters:
            try:
                self.generate_chapters_json(episode)
            except Exception as e:
                logger.error(f"chapters JSON 生成失败: {e}")

        history.append(self._episode_to_dict(episode))
        self._save_history(history)

        # 重新生成完整 feed
        feed_xml = self._build_feed(history)
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(feed_xml, bytes):
            self.feed_path.write_bytes(feed_xml)
        else:
            self.feed_path.write_text(feed_xml, encoding="utf-8")
        logger.info(f"RSS feed 已更新：{self.feed_path}（共 {len(history)} 期）")
        return str(self.feed_path)

    # ------------------------------------------------------------------
    def _build_feed(self, history: list[dict]) -> str:
        """构建完整 RSS feed XML。"""
        from feedgen.feed import FeedGenerator

        fg = FeedGenerator()
        fg.load_extension("podcast")

        title = self.meta.get("title", "GitHub 前沿观察")
        fg.title(title)
        fg.link(href=self.meta.get("site_url", "") or "https://github.com")
        # 频道描述内嵌 series 级别 JSON-LD 结构化数据（SEO）
        base_desc = "自动追踪 GitHub 前沿研究项目，转化为中文音频播客"
        fg.description(f"{base_desc}\n{self._generate_series_json_ld()}")
        fg.language(self.cfg.get("language", "zh-cn"))

        # iTunes 标签
        author = self.meta.get("author", "Anonymous") or "Anonymous"
        email = self.meta.get("email", "") or "noreply@example.com"
        fg.podcast.itunes_author(author)
        fg.podcast.itunes_owner(name=author, email=email)
        fg.podcast.itunes_category(self.cfg.get("category", "Technology"))
        # itunes_explicit 仅接受 'yes'/'no'/'clean' 字符串
        explicit_val = self.cfg.get("explicit", False)
        fg.podcast.itunes_explicit("yes" if explicit_val else "no")
        fg.podcast.itunes_summary(base_desc)

        # 封面图
        cover = self.cfg.get("cover_art", "")
        if cover:
            project_root = self.feed_path.parent.parent
            cover_abs = (project_root / cover).resolve()
            if cover_abs.exists():
                fg.podcast.itunes_image(str(cover_abs))
            else:
                # 即使文件不存在也设置相对路径
                fg.podcast.itunes_image(cover)

        # 添加每期节目
        media_base = self.meta.get("media_base_url", "").rstrip("/")
        if not media_base:
            media_base = "http://localhost:5000/audio"

        # 记录每期节目的 podcasting 2.0 扩展信息（供 XML 后处理注入）
        # {episode_number: {"chapters_url": ..., "transcript_url": ..., "keywords": [...]}}
        podcast2_meta: dict[int, dict] = {}

        for ep in history:  # feedgen 内部会反转条目顺序，传入正序即得到最新在前
            fe = fg.add_entry()
            fe.id(f"episode-{ep['episode_number']}")
            fe.title(ep["title"])
            fe.description(ep["description"])
            fe.published(ep["published_at"])

            # 音频 enclosure
            audio_url = ep.get("audio_url") or (
                f"{media_base}/{Path(ep['audio_path']).name}" if media_base else ""
            )
            if audio_url:
                fe.enclosure(
                    audio_url,
                    str(ep.get("file_size_bytes", 0)),
                    f"audio/{self.cfg.get('output_format', 'mp3')}",
                )
            fe.podcast.itunes_duration(int(ep.get("duration_seconds", 0)))

            # iTunes episode 编号
            try:
                fe.podcast.itunes_episode(ep["episode_number"])
            except Exception as e:
                logger.warning("RSS 节目编号设置失败: %s", e)

            # Rich show notes（content:encoded，Markdown 格式）
            show_notes_md = ep.get("show_notes_markdown", "")

            # SEO 结构化数据：PodcastEpisode + PodcastSeries JSON-LD
            # feedgen 的 content() 仅支持单个 content:encoded 元素，故将 JSON-LD
            # 以 <script> 标签与 show notes 合并写入，避免互相覆盖
            json_ld = self._generate_json_ld(ep, show_notes_md)
            json_ld_script = f'<script type="application/ld+json">\n{json_ld}\n</script>'

            if show_notes_md:
                combined_content = f"{show_notes_md}\n\n{json_ld_script}"
                try:
                    fe.content(combined_content, type="text/markdown")
                except Exception as e:
                    logger.warning("RSS content 写入失败: %s", e)
                    # 回退：将 show notes + JSON-LD 追加到 description
                    fe.description(ep["description"] + "\n\n" + combined_content)
            else:
                # 无 show notes，content:encoded 直接放 JSON-LD（application/ld+json）
                fe.content(json_ld, type="application/ld+json")

            # 收集 podcasting 2.0 扩展信息
            ep_meta: dict[str, Any] = {}
            # chapters：若有章节列表，指向 chapters JSON
            if ep.get("chapters"):
                chapters_filename = f"episode_{ep['episode_number']:03d}_chapters.json"
                ep_meta["chapters_url"] = f"{media_base}/{chapters_filename}"
            # transcript：若已生成字幕文件，指向 SRT
            transcript_path = ep.get("transcript_path", "")
            if transcript_path:
                transcript_filename = Path(transcript_path).name
                ep_meta["transcript_url"] = f"{media_base}/{transcript_filename}"
            # iTunes keywords（从 mentioned_tech 与仓库名提取）
            keywords = self._extract_keywords(ep)
            if keywords:
                ep_meta["keywords"] = keywords
            if ep_meta:
                podcast2_meta[ep["episode_number"]] = ep_meta

        feed_xml = fg.rss_str(pretty=True)

        # 后处理：注入 <podcast:chapters> / <podcast:transcript> /
        # <itunes:keywords> 等 feedgen 原生不支持的元素
        if podcast2_meta:
            injected = self._inject_podcast2_elements(feed_xml, podcast2_meta)
            if injected is not None:
                feed_xml = injected

        return feed_xml

    # ------------------------------------------------------------------
    # SEO 结构化数据（JSON-LD，借鉴播客 SEO 最佳实践）
    # ------------------------------------------------------------------
    def _generate_json_ld(self, ep: dict, show_notes_md: str = "") -> str:
        """生成单期节目的 JSON-LD 结构化数据（PodcastEpisode + PodcastSeries）。

        便于搜索引擎 / 播客聚合器识别节目元信息，提升 SEO 可见性。

        Args:
            ep: 节目 dict（来自 episodes_history.json）。
            show_notes_md: 可选的 show notes Markdown，用于补充 description。

        Returns:
            JSON-LD 字符串（PodcastEpisode 类型）。
        """
        description = ep.get("description", "") or ""
        if show_notes_md:
            description = f"{description}\n\n{show_notes_md}" if description else show_notes_md

        # ISO 8601 时长：PT8M / PT1H2M3S
        total = int(ep.get("duration_seconds", 0) or 0)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours > 0:
            duration = f"PT{hours}H{minutes}M{seconds}S"
        elif seconds > 0:
            duration = f"PT{minutes}M{seconds}S"
        else:
            duration = f"PT{minutes}M"

        date_published = self._to_iso_date(ep.get("published_at", ""))

        # 音频地址：优先 audio_url，否则由 media_base + 文件名拼装
        media_base = self.meta.get("media_base_url", "").rstrip("/")
        if not media_base:
            media_base = "http://localhost:5000/audio"
        audio_url = ep.get("audio_url")
        if not audio_url:
            fname = ep.get("audio_filename") or Path(ep.get("audio_path", "")).name
            audio_url = f"{media_base}/{fname}" if (media_base and fname) else ""

        series_name = self.meta.get("title", "GitHub 前沿观察")
        series_desc = "自动追踪 GitHub 前沿研究项目，转化为中文音频播客"

        json_ld = {
            "@context": "https://schema.org",
            "@type": "PodcastEpisode",
            "name": ep.get("title", ""),
            "description": description,
            "episodeNumber": ep.get("episode_number", 0),
            "datePublished": date_published,
            "duration": duration,
            "associatedMedia": {
                "@type": "MediaObject",
                "contentUrl": audio_url,
            },
            "partOfSeries": {
                "@type": "PodcastSeries",
                "name": series_name,
                "description": series_desc,
            },
        }
        return json.dumps(json_ld, ensure_ascii=False)

    def _generate_series_json_ld(self) -> str:
        """生成播客频道级别的 PodcastSeries JSON-LD 结构化数据。"""
        series_name = self.meta.get("title", "GitHub 前沿观察")
        series_desc = "自动追踪 GitHub 前沿研究项目，转化为中文音频播客"
        author = self.meta.get("author", "Anonymous") or "Anonymous"
        site_url = self.meta.get("site_url", "") or "https://github.com"
        json_ld = {
            "@context": "https://schema.org",
            "@type": "PodcastSeries",
            "name": series_name,
            "description": series_desc,
            "url": site_url,
            "inLanguage": self.cfg.get("language", "zh-cn"),
            "author": {
                "@type": "Person",
                "name": author,
            },
        }
        return json.dumps(json_ld, ensure_ascii=False)

    def _to_iso_date(self, date_str: str) -> str:
        """将 RFC 2822 格式日期转为 ISO 8601 日期（YYYY-MM-DD）。"""
        if not date_str:
            return ""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return date_str[:10]

    # ------------------------------------------------------------------
    def _episode_to_dict(self, episode: Episode) -> dict:
        """将 Episode 序列化为可存储的 dict。"""
        show_notes = episode.show_notes
        return {
            "episode_number": episode.episode_number,
            "title": episode.script.title,
            "description": episode.script.description,
            "audio_path": episode.audio_path,
            "audio_filename": Path(episode.audio_path).name,
            "duration_seconds": episode.duration_seconds,
            "file_size_bytes": episode.file_size_bytes,
            "published_at": episode.published_at,
            "repo_names": episode.script.repo_names,
            "repo_urls": episode.script.repo_urls,
            "total_chars": episode.script.total_chars(),
            "style": episode.script.style,
            "target_minutes": episode.script.target_minutes,
            "chapters": [c.to_dict() for c in episode.chapters],
            "show_notes": show_notes.to_dict(),
            "show_notes_markdown": show_notes.to_markdown(),
            "transcript_path": episode.transcript_path,
            "transcript_filename": (
                Path(episode.transcript_path).name if episode.transcript_path else ""
            ),
            "status": episode.status,
        }

    def _load_history(self) -> list[dict]:
        if self.history_path.exists():
            try:
                return json.loads(self.history_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                return []
        return []

    def _save_history(self, history: list[dict]) -> None:
        import os
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.history_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(str(tmp_path), str(self.history_path))

    def get_next_episode_number(self) -> int:
        """获取下一期编号。"""
        history = self._load_history()
        if not history:
            return 1
        return max(ep["episode_number"] for ep in history) + 1

    # ------------------------------------------------------------------
    # Podcasting 2.0：chapters JSON 与 SRT 字幕生成
    # ------------------------------------------------------------------
    def _episodes_dir(self) -> Path:
        """返回节目产物输出目录（output/episodes）。"""
        return self.feed_path.parent / "episodes"

    def generate_chapters_json(self, episode: Episode) -> str:
        """生成 Podcasting 2.0 chapters JSON 文件。

        格式参见 https://podcasting2.org/podcast-namespace/tags/chapters :
        {
          "version": "1.2.0",
          "chapters": [
            {"startTime": 0, "title": "开场"},
            {"startTime": 30, "title": "项目1: xxx"},
            ...
          ]
        }

        Args:
            episode: 已生成音频的节目（含 chapters 列表）。

        Returns:
            chapters JSON 文件路径。
        """
        if episode.chapters:
            chapters = [
                {
                    "startTime": round(c.start_time, 1),
                    "title": c.title,
                }
                for c in episode.chapters
            ]
        else:
            # 无章节时构造一个兜底开场章节
            chapters = [{"startTime": 0, "title": "开场"}]

        chapters_data = {"version": "1.2.0", "chapters": chapters}

        out_dir = self._episodes_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"episode_{episode.episode_number:03d}_chapters.json"
        out_path.write_text(
            json.dumps(chapters_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"chapters JSON 已生成：{out_path}")
        return str(out_path)

    def generate_transcript_srt(
        self,
        script: PodcastScript,
        segment_timings: list[dict] | None = None,
    ) -> str:
        """将 PodcastScript 分段 + 时间数据转为 SRT 字幕文件。

        Args:
            script: 播客脚本。
            segment_timings: 每段的时间信息，每项可包含 index / start_time / end_time
                （兼容 audio_mixer.get_segment_timings() 的输出）。若为 None，则按
                中文播客约 350 字/分钟估算每段时长。

        Returns:
            SRT 文件路径。若脚本无分段则返回空字符串。
        """
        segments = script.segments
        if not segments:
            return ""

        # 构建每段的 (start, end) 时间表
        timings: list[tuple[float, float]] = []
        if segment_timings:
            timing_map: dict[int, tuple[float, float]] = {}
            for t in segment_timings:
                idx = t.get("index")
                if idx is None:
                    continue
                start = t.get("start_time", t.get("start", 0.0))
                end = t.get("end_time", t.get("end", start))
                timing_map[int(idx)] = (float(start), float(end))
            for i in range(len(segments)):
                timings.append(timing_map.get(i, (0.0, 0.0)))
        else:
            # 按字符数估算（约 350 字/分钟 ≈ 5.83 字/秒）
            rate = 350 / 60.0
            cur = 0.0
            for seg in segments:
                dur = max(1.0, len(seg.text) / rate)
                timings.append((cur, cur + dur))
                cur += dur

        # episode 编号：优先用 get_next_episode_number（建议在 publish 前调用）
        ep_num = self.get_next_episode_number()

        lines: list[str] = []
        for i, (seg, (start, end)) in enumerate(zip(segments, timings), 1):
            lines.append(str(i))
            lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
            speaker = seg.speaker or ""
            text = seg.text or ""
            if speaker:
                lines.append(f"{speaker}: {text}")
            else:
                lines.append(text)
            lines.append("")  # 空行分隔

        out_dir = self._episodes_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"episode_{ep_num:03d}_transcript.srt"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"transcript SRT 已生成：{out_path}")
        return str(out_path)

    # ------------------------------------------------------------------
    # 辅助：关键词提取 / XML 后处理
    # ------------------------------------------------------------------
    def _extract_keywords(self, ep: dict) -> list[str]:
        """从 show notes 的 mentioned_tech 与仓库名提取关键词。

        iTunes <itunes:keywords> 已废弃，但部分播放器仍读取，作为补充信息。
        """
        keywords: list[str] = []
        show_notes = ep.get("show_notes") or {}
        keywords.extend(show_notes.get("mentioned_tech", []))
        # 仓库名（短名）作为关键词补充（repo topics 不在 Episode 中，故用仓库名替代）
        for name in ep.get("repo_names", []):
            short = name.split("/")[-1]
            if short:
                keywords.append(short)
        # 去重并限制数量（iTunes 最多 12 个）
        seen: set[str] = set()
        uniq: list[str] = []
        for k in keywords:
            if k and k not in seen:
                seen.add(k)
                uniq.append(k)
        return uniq[:12]

    def _inject_podcast2_elements(
        self, feed_bytes: bytes, podcast2_meta: dict[int, dict]
    ) -> bytes | None:
        """后处理 RSS XML，注入 feedgen 原生不支持的元素：

        - <podcast:chapters url="..." type="application/json+chapters" />
        - <podcast:transcript url="..." type="application/srt" rel="captions" />
        - <itunes:keywords>...</itunes:keywords>

        通过 <guid> 文本（"episode-{num}"）匹配每期节目。

        Args:
            feed_bytes: feedgen 生成的 RSS XML 字节串。
            podcast2_meta: {episode_number: {"chapters_url", "transcript_url", "keywords"}}。

        Returns:
            注入后的 XML 字节串；若处理失败返回 None（调用方将使用原始 feed）。
        """
        try:
            from lxml import etree
        except ImportError:
            logger.warning("lxml 不可用，跳过 podcasting 2.0 元素注入")
            return None

        try:
            # 注册 podcast 前缀，使序列化输出使用 <podcast:xxx> 形式
            etree.register_namespace("podcast", PODCAST_NS)
            root = etree.fromstring(feed_bytes)
        except Exception as e:
            logger.error(f"RSS XML 后处理解析失败: {e}")
            return None

        # itunes 命名空间（feedgen 已在根节点声明）
        itunes_ns_uri = root.nsmap.get("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")

        items = root.findall(".//item")
        if not items:
            return None

        modified = False
        for item in items:
            guid_el = item.find("guid")
            if guid_el is None or not guid_el.text:
                continue
            guid = guid_el.text.strip()
            try:
                ep_num = int(guid.replace("episode-", ""))
            except ValueError:
                continue
            meta = podcast2_meta.get(ep_num)
            if not meta:
                continue

            # <podcast:chapters>
            chapters_url = meta.get("chapters_url")
            if chapters_url:
                etree.SubElement(
                    item,
                    f"{{{PODCAST_NS}}}chapters",
                    url=chapters_url,
                    type="application/json+chapters",
                )
                modified = True

            # <podcast:transcript>
            transcript_url = meta.get("transcript_url")
            if transcript_url:
                etree.SubElement(
                    item,
                    f"{{{PODCAST_NS}}}transcript",
                    url=transcript_url,
                    type="application/srt",
                    rel="captions",
                )
                modified = True

            # <itunes:keywords>
            keywords = meta.get("keywords") or []
            if keywords:
                kw_el = etree.SubElement(item, f"{{{itunes_ns_uri}}}keywords")
                kw_el.text = ", ".join(keywords)
                modified = True

        if not modified:
            return None

        try:
            return etree.tostring(
                root, pretty_print=True, xml_declaration=True, encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"RSS XML 后处理序列化失败: {e}")
            return None
