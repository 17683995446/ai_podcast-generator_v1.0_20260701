"""TTS 语音合成模块：支持多后端。

后端 1: SiliconFlow CosyVoice2-0.5B（OpenAI 兼容 /audio/speech）
后端 2: 阿里云百炼 dashscope（CosyVoice v3）
后端 3: mock 静音占位（无 API Key 时）

SiliconFlow 系统预置音色：
  男声: alex(沉稳) benjamin(低沉) charles(磁性) david(欢快)
  女声: anna(沉稳) bella(激情) claire(温柔) diana(欢快)
音色格式: "FunAudioLLM/CosyVoice2-0.5B:alex"
"""
from __future__ import annotations

import random
import re
import wave
from pathlib import Path
from typing import Any

from .models import PodcastScript, PodcastSegment

# 情感标签映射（emotion -> CosyVoice 情感指令）
EMOTION_MAP = {
    "excited": "兴奋地",
    "happy": "开心地",
    "curious": "好奇地",
    "sad": "难过地",
    "neutral": "",
    "angry": "生气地",
}


class TTSSynthesizer:
    """多后端文本转语音合成器。"""

    def __init__(self, config: dict[str, Any]):
        self.cfg = config["tts"]
        self.provider = self.cfg.get("provider", "siliconflow")
        self.model = self.cfg.get("model", "FunAudioLLM/CosyVoice2-0.5B")
        self.voice_mapping: dict[str, str] = self.cfg.get("voice_mapping", {
            "host": "alex",
            "guest": "anna",
        })
        self.sample_rate = self.cfg.get("sample_rate", 24000)
        self.response_format = self.cfg.get("response_format", "wav")

        # 读取 API Key
        self.api_key = config["api_keys"].get("tts", "") or config["api_keys"].get("dashscope", "")
        self.base_url = self.cfg.get("base_url", "https://api.siliconflow.cn/v1")

        if not self.api_key:
            print("[tts] 警告：未配置 TTS API Key，将使用 mock 模式（静音占位）")
            self.provider = "mock"

        # 初始化后端客户端
        self._client = None
        if self.provider == "siliconflow" and self.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=60,
                )
                print(f"[tts] 使用 SiliconFlow TTS（{self.model}）")
            except Exception:
                print("[tts] openai 未安装，使用 mock 模式")
                self.provider = "mock"
        elif self.provider == "dashscope" and self.api_key:
            try:
                import dashscope
                dashscope.api_key = self.api_key
                self._dashscope_ready = True
                print(f"[tts] 使用阿里云 CosyVoice（{self.model}）")
            except Exception:
                print("[tts] dashscope 未安装，使用 mock 模式")
                self.provider = "mock"

    def synthesize_script(
        self, script: PodcastScript, output_dir: str | Path
    ) -> list[str]:
        """合成整期脚本，每段台词输出一个音频文件。"""
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        audio_files: list[str] = []
        for i, segment in enumerate(script.segments):
            audio_path = out_dir / f"segment_{i:03d}.{self.response_format}"
            # 预处理文本（添加自然停顿和语气词）
            processed_text = self._preprocess_text(
                segment.text, segment.speaker, segment.emotion, i
            )
            self._synthesize_segment(segment, audio_path, processed_text)
            audio_files.append(str(audio_path))
            print(
                f"[tts] 段 {i+1}/{len(script.segments)} 完成 "
                f"({segment.speaker}, {len(segment.text)} 字)"
            )
        print(f"[tts] 全部 {len(audio_files)} 段合成完成")
        return audio_files

    # ------------------------------------------------------------------
    def _preprocess_text(self, text: str, speaker: str, emotion: str, segment_index: int) -> str:
        """预处理 TTS 文本，增加自然停顿和语气词。

        借鉴 IndexTTS 2.0 的语义停顿控制和专业播客制作经验。
        """
        result = text

        # 1. 在问号后增加思考停顿
        result = re.sub(r'([？?])', r'\1...', result)

        # 2. 在长句中间增加微停顿（逗号已有自然停顿，在分号/冒号后加）
        result = re.sub(r'([；;：:])', r'\1 ', result)

        # 3. 根据情感添加语气词
        if emotion == "excited" and speaker == "guest":
            # 激动时偶尔在句首加"哇"
            if random.random() < 0.15 and not result.startswith(("哇", "啊", "哦", "对")):
                result = "哇，" + result
        elif emotion == "curious":
            # 好奇时偶尔在句首加"嗯"
            if random.random() < 0.15 and not result.startswith(("嗯", "让我", "这个")):
                result = "嗯，" + result
        elif emotion == "neutral" and segment_index > 0:
            # 中性陈述偶尔加"对"作为回应
            if random.random() < 0.1 and not result.startswith(("对", "是的", "没错")):
                result = "对，" + result

        # 4. 在句子末尾的句号前增加微小停顿（如果句子较长）
        sentences = result.split('。')
        processed = []
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if len(s) > 40:
                # 长句末尾加微停顿
                processed.append(s + '。...')
            else:
                processed.append(s + '。')
        result = ' '.join(processed) if processed else result

        return result

    # ------------------------------------------------------------------
    def _synthesize_segment(self, segment: PodcastSegment, output_path: Path, processed_text: str | None = None) -> None:
        """合成单段台词。"""
        text = (processed_text if processed_text is not None else segment.text).strip()
        if not text:
            self._write_silence(output_path, 0.3)
            return

        if self.provider == "siliconflow":
            success = self._call_siliconflow(text, segment.voice_key, segment.emotion, output_path)
            if not success:
                self._mock_synthesize(text, output_path)
        elif self.provider == "dashscope":
            success = self._call_dashscope(text, segment.voice_key, segment.emotion, output_path)
            if not success:
                self._mock_synthesize(text, output_path)
        else:
            self._mock_synthesize(text, output_path)

    # ------------------------------------------------------------------
    # SiliconFlow 后端
    # ------------------------------------------------------------------
    def _call_siliconflow(
        self, text: str, voice_key: str, emotion: str, output_path: Path
    ) -> bool:
        """调用 SiliconFlow TTS API（OpenAI 兼容 /audio/speech）。"""
        voice_name = self.voice_mapping.get(voice_key, "alex")
        # 音色格式: "FunAudioLLM/CosyVoice2-0.5B:alex"
        full_voice = f"{self.model}:{voice_name}" if ":" not in voice_name else voice_name

        # 情感控制：在文本前加自然语言情感指令
        emotion_prefix = EMOTION_MAP.get(emotion, "")
        input_text = f"{emotion_prefix}{text}" if emotion_prefix else text

        if self._client is None:
            print("[tts] SiliconFlow 客户端未初始化，回退到 mock")
            return False

        try:
            response = self._client.audio.speech.with_streaming_response.create(
                model=self.model,
                voice=full_voice,
                input=input_text,
                response_format=self.response_format,
            )
            with response as r:
                r.stream_to_file(output_path)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception as e:
            print(f"[tts] SiliconFlow 调用失败: {e}")
            return False

    # ------------------------------------------------------------------
    # DashScope 后端（保留原有实现）
    # ------------------------------------------------------------------
    def _call_dashscope(
        self, text: str, voice_key: str, emotion: str, output_path: Path
    ) -> bool:
        """调用阿里云百炼 CosyVoice SDK 合成。"""
        collector = None
        try:
            from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat

            voice = self.voice_mapping.get(voice_key, "longxiaocheng")
            emotion_text = EMOTION_MAP.get(emotion, "")
            instruction = f"情感：{emotion_text}。" if emotion_text else ""

            collector = _WavCollector(open(output_path, "wb"), self.sample_rate)
            synthesizer = SpeechSynthesizer(
                model=self.model,
                voice=voice,
                format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                callback=collector,
            )
            synthesizer.call(instruction + text)
            if collector.total_bytes == 0:
                return False
            return True
        except Exception as e:
            print(f"[tts] DashScope 调用异常: {e}")
            return False
        finally:
            if collector:
                collector.file_obj.close()

    # ------------------------------------------------------------------
    # Mock 后端
    # ------------------------------------------------------------------
    def _mock_synthesize(self, text: str, output_path: Path) -> None:
        """无 API Key 时生成静音占位音频。"""
        duration = max(0.3, len(text) * 0.17)
        self._write_silence(output_path, duration)

    def _write_silence(self, output_path: Path, duration_sec: float) -> None:
        """写入指定时长的静音 wav 文件。"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        n_frames = int(duration_sec * self.sample_rate)
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"\x00\x00" * n_frames)


class _WavCollector:
    """dashscope 流式回调：收集 PCM 数据并写入 wav 文件。"""

    def __init__(self, file_obj, sample_rate: int):
        self.file_obj = file_obj
        self.sample_rate = sample_rate
        self.total_bytes = 0
        self._header_written = False

    def on_open(self): pass
    def on_start(self, message): pass

    def on_event(self, message):
        audio_data = getattr(message, "get", lambda *a: None)("audio")
        if not audio_data and isinstance(message, dict):
            audio_data = message.get("audio")
        if audio_data:
            if not self._header_written:
                self._write_wav_header()
                self._header_written = True
            self.file_obj.write(audio_data)
            self.total_bytes += len(audio_data)

    def on_data_flow(self, data: bytes, **kwargs):
        if data:
            if not self._header_written:
                self._write_wav_header()
                self._header_written = True
            self.file_obj.write(data)
            self.total_bytes += len(data)

    def on_complete(self, message=None):
        if self._header_written:
            self._patch_wav_header()

    def on_error(self, message):
        print(f"[tts] CosyVoice 错误: {message}")

    def on_close(self):
        if self._header_written:
            self._patch_wav_header()

    def _write_wav_header(self):
        import struct
        sr = self.sample_rate
        self.file_obj.write(b"RIFF")
        self.file_obj.write(struct.pack("<I", 0))
        self.file_obj.write(b"WAVE")
        self.file_obj.write(b"fmt ")
        self.file_obj.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        self.file_obj.write(b"data")
        self.file_obj.write(struct.pack("<I", 0))

    def _patch_wav_header(self):
        import struct
        pos = self.file_obj.tell()
        data_size = self.total_bytes
        file_size = 36 + data_size
        self.file_obj.seek(4)
        self.file_obj.write(struct.pack("<I", file_size))
        self.file_obj.seek(40)
        self.file_obj.write(struct.pack("<I", data_size))
        self.file_obj.seek(pos)
