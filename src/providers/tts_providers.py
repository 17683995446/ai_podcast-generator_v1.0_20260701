"""TTS Provider 实现 — SiliconFlow / DashScope / Edge-TTS / Mock。

将现有 TTSSynthesizer 中的后端逻辑适配为独立 Provider 类，
每个 Provider 独立管理自己的初始化和调用逻辑。
"""
from __future__ import annotations

from typing import Any

from .base import BaseTTSProvider
from .registry import register_tts_provider
from ..logger import get_logger

logger = get_logger(__name__)


@register_tts_provider("siliconflow")
class SiliconFlowTTSProvider(BaseTTSProvider):
    """SiliconFlow TTS Provider。"""

    def __init__(self):
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        """配置 provider（由 TTSSynthesizer 调用）。"""
        self._config = config

    @property
    def name(self) -> str:
        return "siliconflow"

    def synthesize_segment(
        self, text: str, voice: str, emotion: str = "neutral"
    ) -> bytes | None:
        """通过 SiliconFlow API 合成语音。"""
        from ..tts_synth import TTSSynthesizer
        synth = TTSSynthesizer(self._config)
        return synth._call_siliconflow(text, voice, emotion)

    def is_available(self, config: dict[str, Any]) -> bool:
        api_keys = config.get("api_keys", {})
        return bool(api_keys.get("tts", "") or api_keys.get("siliconflow", ""))


@register_tts_provider("dashscope")
class DashScopeTTSProvider(BaseTTSProvider):
    """DashScope (阿里云) TTS Provider。"""

    def __init__(self):
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "dashscope"

    def synthesize_segment(
        self, text: str, voice: str, emotion: str = "neutral"
    ) -> bytes | None:
        from ..tts_synth import TTSSynthesizer
        synth = TTSSynthesizer(self._config)
        return synth._call_dashscope(text, voice, emotion)

    def is_available(self, config: dict[str, Any]) -> bool:
        api_keys = config.get("api_keys", {})
        return bool(api_keys.get("dashscope", ""))


@register_tts_provider("edge")
class EdgeTTSProvider(BaseTTSProvider):
    """Edge-TTS Provider（免费，无需 API Key）。"""

    def __init__(self):
        self._config: dict[str, Any] = {}

    def configure(self, config: dict[str, Any]) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "edge"

    def synthesize_segment(
        self, text: str, voice: str, emotion: str = "neutral"
    ) -> bytes | None:
        from ..tts_synth import TTSSynthesizer
        synth = TTSSynthesizer(self._config)
        return synth._call_edge_tts(text, voice, emotion)

    def is_available(self, config: dict[str, Any]) -> bool:
        return True  # Edge-TTS 无需 API Key


@register_tts_provider("mock")
class MockTTSProvider(BaseTTSProvider):
    """Mock TTS Provider（生成静音音频，用于测试）。"""

    @property
    def name(self) -> str:
        return "mock"

    def synthesize_segment(
        self, text: str, voice: str, emotion: str = "neutral"
    ) -> bytes | None:
        # 生成最小 WAV 头 + 静音数据
        import struct
        sample_rate = 24000
        duration_ms = max(100, len(text) * 80)  # 粗略估算时长
        num_samples = int(sample_rate * duration_ms / 1000)
        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + num_samples * 2, b"WAVE",
            b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
            b"data", num_samples * 2,
        )
        return wav_header + b"\x00" * (num_samples * 2)

    def is_available(self, config: dict[str, Any]) -> bool:
        return True
