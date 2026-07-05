"""音频后期处理：拼接多段音频、响度归一化、输出 MP3。

流水线：
  段落 wav 文件 → 拼接（段间静音）→ 响度归一（-16 LUFS）→ 导出 MP3
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Chapter, Episode, PodcastScript

from src.logger import get_logger

logger = get_logger(__name__)


class AudioMixer:
    """音频拼接与后期处理。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["audio"]
        self.segment_silence_ms = self.cfg.get("segment_silence_ms", 400)
        self.target_lufs = self.cfg.get("target_lufs", -16.0)
        self.output_format = self.cfg.get("output_format", "mp3")
        self.output_bitrate = self.cfg.get("output_bitrate", "192k")
        self.bgm_path = self.cfg.get("bgm_path", "")
        # 最近一次 mix() 记录的段落时间戳（供 get_segment_timings /
        # generate_chapters_from_timings 使用），避免改动 mix() 的返回类型。
        self.last_segment_timings: list[dict] = []

    def mix(
        self,
        audio_files: list[str],
        script: PodcastScript,
        output_path: str | Path,
        episode_number: int = 1,
    ) -> Episode:
        """拼接段落音频并输出最终节目。

        Args:
            audio_files: 段落 wav 文件路径列表（按顺序）。
            script: 对应的播客脚本。
            output_path: 最终音频输出路径。
            episode_number: 节目编号。

        Returns:
            Episode 对象（含时长、文件大小等信息）。
        """
        from pydub import AudioSegment

        logger.info(f"拼接 {len(audio_files)} 段音频...")

        # 1. 加载并拼接段落
        combined = AudioSegment.empty()
        silence = AudioSegment.silent(duration=self.segment_silence_ms)

        # 计算项目边界（每期有多个项目，每个项目讨论约 total_segments / num_projects 段）
        num_projects = len(script.repo_names) if script.repo_names else 1
        total_segs = len(audio_files)
        segs_per_project = max(total_segs // num_projects, 3) if num_projects > 1 else total_segs

        # 章节时间戳追踪：记录每段在最终音频中的起止时间，用于生成章节
        segment_timings: list[dict] = []
        current_position_ms = 0
        silence_ms = self.segment_silence_ms

        for i, audio_path in enumerate(audio_files):
            seg = AudioSegment.from_file(audio_path)
            # 音量归一化（每段独立归一化）
            seg = self._normalize_segment(seg)
            combined += seg

            # 记录该段在最终音频中的时间戳（用于生成章节）
            seg_speaker = (
                script.segments[i].speaker if i < len(script.segments) else ""
            )
            seg_text = (
                script.segments[i].text[:100] if i < len(script.segments) else ""
            )
            segment_timings.append(
                {
                    "index": i,
                    "speaker": seg_speaker,
                    "start_time": current_position_ms / 1000.0,
                    "end_time": (current_position_ms + len(seg)) / 1000.0,
                    "text": seg_text,
                }
            )
            current_position_ms += len(seg)

            # 段间静音（保留原有行为）
            if i < total_segs - 1:
                combined += silence
                current_position_ms += silence_ms

            # 在项目边界插入过渡音
            if num_projects > 1 and i > 0 and (i + 1) % segs_per_project == 0 and i < total_segs - 2:
                transition = self._generate_transition(300)
                combined += transition
                current_position_ms += len(transition)
                logger.info(f"插入过渡音 @ segment {i+1}")

        # 保存时间戳供 get_segment_timings() / generate_chapters_from_timings() 使用
        self.last_segment_timings = segment_timings

        # 2. 响度归一化（-16 LUFS，播客标准）
        combined = self._normalize_loudness(combined)

        # 3. 添加背景音乐（可选）
        if self.bgm_path and Path(self.bgm_path).exists():
            combined = self._mix_bgm(combined)

        # 4. 导出
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        export_format = self.output_format
        export_params: dict[str, Any] = {}
        if export_format == "mp3":
            export_params["bitrate"] = self.output_bitrate

        combined.export(
            str(out_path),
            format=export_format,
            **export_params,
        )

        duration_sec = len(combined) / 1000.0
        file_size = out_path.stat().st_size

        logger.info(
            f"输出完成：{out_path.name} "
            f"({duration_sec:.1f}s, {file_size / 1024 / 1024:.2f} MB)"
        )

        return Episode(
            script=script,
            audio_path=str(out_path),
            duration_seconds=duration_sec,
            file_size_bytes=file_size,
            episode_number=episode_number,
        )

    # ------------------------------------------------------------------
    # 章节时间戳相关
    # ------------------------------------------------------------------
    def get_segment_timings(self) -> list[dict]:
        """返回最近一次 mix() 记录的段落时间戳。

        每项格式：
            {"index": int, "speaker": str,
             "start_time": float, "end_time": float, "text": str}
        若尚未调用过 mix()，返回空列表。
        """
        return self.last_segment_timings

    def generate_chapters_from_timings(
        self,
        script: PodcastScript,
        timings: list[dict],
        repo_names: list[str],
    ) -> list[Chapter]:
        """根据段落时间戳生成章节。

        策略（优先级从高到低）：
          1. 按项目边界切分：对每个 repo_name，找到首个在段落文本中提及它的
             段落，以该段起始时间作为新章节起点。若首个项目并非从第 0 段开始，
             会自动补一个"开场"章节。
          2. 若没有匹配到任何项目（repo_names 为空或脚本未提及），则按段落数量
             切分（每 5 段 1 章）。

        每个 Chapter 含 title / start_time / end_time / description。
        """
        if not timings:
            return []

        # 1. 检测项目边界：找到每个 repo 首次被提及的段落索引
        boundary_indices: list[tuple[int, str]] = []
        for repo_name in repo_names:
            # repo_name 可能是 owner/repo 形式，短名更易在台词中匹配
            short = repo_name.split("/")[-1]
            for t in timings:
                text = (t.get("text") or "").lower()
                if short.lower() in text or repo_name.lower() in text:
                    boundary_indices.append((t.get("index", 0), repo_name))
                    break

        # 按段落索引排序（同时去重同一索引的重复项）
        seen_idx: set[int] = set()
        unique_boundaries: list[tuple[int, str]] = []
        for idx, name in sorted(boundary_indices, key=lambda x: x[0]):
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            unique_boundaries.append((idx, name))

        chapters: list[Chapter] = []

        # 2a. 无项目匹配 → 按段落数切分（每 5 段 1 章）
        if not unique_boundaries:
            chunk_size = 5
            for start in range(0, len(timings), chunk_size):
                chunk = timings[start : start + chunk_size]
                if not chunk:
                    continue
                chapters.append(
                    Chapter(
                        title=f"第 {start // chunk_size + 1} 章",
                        start_time=float(chunk[0].get("start_time", 0.0)),
                        end_time=float(chunk[-1].get("end_time", 0.0)),
                        description=(
                            f"段落 {chunk[0].get('index', 0)}-"
                            f"{chunk[-1].get('index', 0)} 内容。"
                        ),
                    )
                )
            return chapters

        # 2b. 开场章节（第一个项目之前的内容）
        first_idx = unique_boundaries[0][0]
        if first_idx > 0:
            chapters.append(
                Chapter(
                    title="开场",
                    start_time=float(timings[0].get("start_time", 0.0)),
                    end_time=self._start_time_of_index(timings, first_idx),
                    description="节目开场与本期话题引入。",
                )
            )

        # 2c. 每个项目一个章节（从该项目的首段到下一个项目首段）
        for j, (seg_idx, repo_name) in enumerate(unique_boundaries):
            start_time = self._start_time_of_index(timings, seg_idx)
            if j + 1 < len(unique_boundaries):
                end_time = self._start_time_of_index(
                    timings, unique_boundaries[j + 1][0]
                )
            else:
                end_time = float(timings[-1].get("end_time", 0.0))
            short = repo_name.split("/")[-1]
            chapters.append(
                Chapter(
                    title=f"项目解读：{short}",
                    start_time=start_time,
                    end_time=end_time,
                    description=f"深入解读 {repo_name}。",
                )
            )
        return chapters

    @staticmethod
    def _start_time_of_index(timings: list[dict], idx: int) -> float:
        """在 timings 中查找指定 index 段落的 start_time；找不到返回 0.0。"""
        for t in timings:
            if t.get("index") == idx:
                return float(t.get("start_time", 0.0))
        return 0.0

    # ------------------------------------------------------------------
    def _generate_transition(self, duration_ms: int = 300) -> AudioSegment:
        """生成项目间的过渡音（简短的淡入淡出音效）。

        使用简单的正弦波生成柔和的过渡音，无需外部音频文件。
        """
        from pydub import AudioSegment
        import numpy as np
        sr = 22050
        t = np.linspace(0, duration_ms / 1000, int(sr * duration_ms / 1000))
        # 生成一个柔和的音调（C5 = 523Hz）
        freq = 523.25
        wave = np.sin(2 * np.pi * freq * t) * 0.3
        # 淡入淡出
        fade_samples = int(sr * 0.1)  # 100ms 淡入淡出
        if len(wave) > fade_samples * 2:
            wave[:fade_samples] *= np.linspace(0, 1, fade_samples)
            wave[-fade_samples:] *= np.linspace(1, 0, fade_samples)
        wave_int = (wave * 32767).astype(np.int16)
        return AudioSegment(
            wave_int.tobytes(),
            frame_rate=sr,
            sample_width=2,
            channels=1,
        )

    # ------------------------------------------------------------------
    def _normalize_segment(self, seg: AudioSegment) -> AudioSegment:
        """对单个段落进行音量归一化，确保各段音量一致。"""
        try:
            target_db = -20.0  # 目标分贝
            current_db = seg.dBFS
            if current_db == float('-inf'):
                return seg
            change = target_db - current_db
            if abs(change) > 2:  # 只在偏差大于2dB时调整
                return seg.apply_gain(change)
        except Exception as e:
            logger.warning("音频处理跳过: %s", e)
        return seg

    # ------------------------------------------------------------------
    def _normalize_loudness(self, audio) -> "AudioSegment":
        """使用 pyloudnorm 进行 EBU R128 响度归一化。

        目标：-16 LUFS（Apple Podcasts / Spotify 播客标准）。
        """
        try:
            import numpy as np
            import pyloudnorm as pyln
        except ImportError:
            logger.warning("pyloudnorm 未安装，跳过响度归一化")
            return audio

        try:
            from pydub import AudioSegment

            samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
            if audio.channels > 1:
                samples = samples.reshape(-1, audio.channels)
            # 归一化到 [-1, 1]
            samples = samples / (2 ** (audio.sample_width * 8 - 1))

            meter = pyln.Meter(audio.frame_rate)
            loudness = meter.integrated_loudness(samples)
            logger.info(f"当前响度: {loudness:.1f} LUFS → 目标 {self.target_lufs} LUFS")

            if loudness > -70:  # 避免对静音处理
                samples = pyln.normalize.loudness(
                    samples, loudness, self.target_lufs
                )
                # 防止削波
                peak = np.max(np.abs(samples))
                if peak > 0.99:
                    samples = samples / peak * 0.99
                samples = np.clip(samples, -1.0, 1.0)
                dtype_map = {1: np.int16, 2: np.int16, 4: np.int32}
                np_dtype = dtype_map.get(audio.sample_width, np.int16)
                samples = (samples * (2 ** (audio.sample_width * 8 - 1))).astype(np_dtype)
                normalized = AudioSegment(
                    samples.tobytes(),
                    frame_rate=audio.frame_rate,
                    sample_width=audio.sample_width,
                    channels=audio.channels,
                )
                return normalized
        except Exception as e:
            logger.error(f"响度归一化失败: {e}")
        return audio

    def _mix_bgm(self, voice_audio) -> "AudioSegment":
        """混入背景音乐（音量降低到人声的 -18dB）。"""
        from pydub import AudioSegment

        try:
            bgm = AudioSegment.from_file(self.bgm_path)
            # 循环 BGM 至人声长度
            if len(bgm) < len(voice_audio):
                loops = (len(voice_audio) // len(bgm)) + 1
                bgm = bgm * loops
            bgm = bgm[: len(voice_audio)]
            # BGM 降低音量
            bgm = bgm - 18  # 降低 18dB
            return voice_audio.overlay(bgm)
        except Exception as e:
            logger.error(f"BGM 混入失败: {e}")
            return voice_audio
