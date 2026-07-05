"""Stage 6 单元测试：验证 edge-tts 后端集成。

覆盖范围：
  1. TTSSynthesizer 初始化 — 无 API Key 时回退到 edge-tts
  2. TTSSynthesizer 初始化 — 显式指定 provider="edge" / "mock"
  3. TTSSynthesizer 初始化 — SiliconFlow/DashScope 失败时回退到 edge-tts
  4. EDGE_EMOTION_PARAMS / EDGE_VOICE_MAPPING 常量完整性
  5. _call_edge_tts — 模拟 edge-tts 返回 MP3 → WAV 转换
  6. _call_edge_tts — 空音频 / 异常 / 未安装 返回 False
  7. _synthesize_segment — edge 路由 + mock 回退
  8. synthesize_script — 完整流程（mock edge-tts）
  9. WAV 文件格式验证（采样率、声道、位深）
  10. 音色映射和情感参数

运行：python -m pytest tests/test_stage6_edge_tts.py -v
"""
import io
import sys
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tts_synth import (
    TTSSynthesizer,
    EDGE_EMOTION_PARAMS,
    EDGE_VOICE_MAPPING,
    EMOTION_MAP,
)
from src.models import PodcastScript, PodcastSegment, PodcastHost


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════


def make_config(api_key: str = "", provider: str = None) -> dict:
    """构建测试用 TTS 配置。"""
    tts_cfg = {
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        "voice_mapping": {"host": "alex", "guest": "anna"},
        "sample_rate": 24000,
        "response_format": "wav",
    }
    if provider:
        tts_cfg["provider"] = provider
    return {
        "api_keys": {"tts": api_key, "dashscope": ""},
        "tts": tts_cfg,
    }


def make_segment(
    text: str = "你好，欢迎收听本期播客。",
    speaker: str = "小明",
    emotion: str = "neutral",
    voice_key: str = "host",
) -> PodcastSegment:
    """构建测试用 PodcastSegment。"""
    return PodcastSegment(
        speaker=speaker,
        text=text,
        emotion=emotion,
        voice_key=voice_key,
    )


def make_script(n: int = 3) -> PodcastScript:
    """构建测试用 PodcastScript（n 段对话）。"""
    return PodcastScript(
        title="测试播客",
        description="单元测试用脚本",
        hosts=[PodcastHost(name="小明", persona="主持人"), PodcastHost(name="小红", persona="嘉宾", voice_key="guest")],
        segments=[make_segment(f"这是第{i+1}段台词内容。", speaker="小明" if i % 2 == 0 else "小红", voice_key="host" if i % 2 == 0 else "guest") for i in range(n)],
        repo_names=["test/repo"],
    )


def generate_silent_mp3(duration_ms: int = 200, sample_rate: int = 24000) -> bytes:
    """生成一段静音 MP3 字节流（用于 mock edge-tts 返回）。"""
    from pydub import AudioSegment
    silence = AudioSegment.silent(duration=duration_ms, frame_rate=sample_rate)
    buf = io.BytesIO()
    silence.export(buf, format="mp3")
    return buf.getvalue()


class FakeCommunicate:
    """模拟 edge_tts.Communicate 的异步流。"""

    def __init__(self, mp3_data: bytes, fail: bool = False):
        self._mp3_data = mp3_data
        self._fail = fail

    async def stream(self):
        if self._fail:
            raise ConnectionError("模拟网络错误")
        yield {"type": "audio", "data": self._mp3_data}


# ═══════════════════════════════════════════════════════════════
# 1. 初始化测试
# ═══════════════════════════════════════════════════════════════


class TestInitEdgeTTS:
    """TTSSynthesizer 初始化 — edge-tts 回退逻辑。"""

    def test_no_api_key_falls_back_to_edge(self):
        """无 API Key 时 provider 应为 edge（而非 mock）。"""
        cfg = make_config(api_key="")
        tts = TTSSynthesizer(cfg)
        assert tts.provider == "edge"

    def test_explicit_edge_provider(self):
        """显式指定 provider='edge' 时应正确设置。"""
        cfg = make_config(api_key="some-key", provider="edge")
        tts = TTSSynthesizer(cfg)
        assert tts.provider == "edge"

    def test_explicit_mock_provider(self):
        """显式指定 provider='mock' 时应尊重配置。"""
        cfg = make_config(api_key="", provider="mock")
        tts = TTSSynthesizer(cfg)
        assert tts.provider == "mock"

    def test_siliconflow_with_api_key(self):
        """有 API Key 且 provider=siliconflow 时应初始化 SiliconFlow 客户端。"""
        cfg = make_config(api_key="sk-test-key", provider="siliconflow")
        tts = TTSSynthesizer(cfg)
        assert tts.provider == "siliconflow"
        assert tts._client is not None

    @patch.dict(sys.modules, {"openai": None})
    def test_siliconflow_no_openai_falls_to_edge(self):
        """SiliconFlow 但 openai 未安装时回退到 edge-tts。"""
        # 模拟 openai 导入失败
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            cfg = make_config(api_key="sk-test-key", provider="siliconflow")
            tts = TTSSynthesizer(cfg)
            assert tts.provider == "edge"


# ═══════════════════════════════════════════════════════════════
# 2. 常量完整性测试
# ═══════════════════════════════════════════════════════════════


class TestConstants:
    """edge-tts 相关常量验证。"""

    def test_edge_emotion_params_has_all_emotions(self):
        """EDGE_EMOTION_PARAMS 应覆盖所有情感标签。"""
        for emotion in EMOTION_MAP:
            assert emotion in EDGE_EMOTION_PARAMS, f"缺少情感: {emotion}"

    def test_edge_emotion_params_neutral_is_empty(self):
        """neutral 情感不应有 rate/pitch 调整。"""
        assert EDGE_EMOTION_PARAMS["neutral"] == {}

    def test_edge_emotion_params_excited_increases_rate(self):
        """excited 情感应加快语速。"""
        rate = EDGE_EMOTION_PARAMS["excited"]["rate"]
        assert rate.startswith("+")

    def test_edge_emotion_params_sad_decreases_rate(self):
        """sad 情感应减慢语速。"""
        rate = EDGE_EMOTION_PARAMS["sad"]["rate"]
        assert rate.startswith("-")

    def test_edge_voice_mapping_has_host_and_guest(self):
        """EDGE_VOICE_MAPPING 应包含 host 和 guest 映射。"""
        assert "host" in EDGE_VOICE_MAPPING
        assert "guest" in EDGE_VOICE_MAPPING
        assert EDGE_VOICE_MAPPING["host"].startswith("zh-CN-")
        assert EDGE_VOICE_MAPPING["guest"].startswith("zh-CN-")

    def test_edge_voice_mapping_host_is_male(self):
        """host 应映射到男声（Yunxi/Yunjian）。"""
        voice = EDGE_VOICE_MAPPING["host"]
        assert "Yunxi" in voice or "Yunjian" in voice

    def test_edge_voice_mapping_guest_is_female(self):
        """guest 应映射到女声（Xiaoxiao/Xiaoyi）。"""
        voice = EDGE_VOICE_MAPPING["guest"]
        assert "Xiaoxiao" in voice or "Xiaoyi" in voice


# ═══════════════════════════════════════════════════════════════
# 3. _call_edge_tts 方法测试
# ═══════════════════════════════════════════════════════════════


class TestCallEdgeTTS:
    """_call_edge_tts 方法测试。"""

    def test_successful_synthesis_produces_wav(self, tmp_path):
        """模拟 edge-tts 返回 MP3 → 成功生成 WAV 文件。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        mp3_data = generate_silent_mp3(duration_ms=300)
        output_path = tmp_path / "test_output.wav"

        with patch("edge_tts.Communicate", return_value=FakeCommunicate(mp3_data)):
            result = tts._call_edge_tts("测试文本", "host", "neutral", output_path)

        assert result is True
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # 验证 WAV 格式
        with wave.open(str(output_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 24000
            assert wf.getsampwidth() == 2

    def test_empty_audio_returns_false(self, tmp_path):
        """edge-tts 返回空音频时应返回 False。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        output_path = tmp_path / "empty.wav"

        with patch("edge_tts.Communicate", return_value=FakeCommunicate(b"")):
            result = tts._call_edge_tts("测试文本", "host", "neutral", output_path)

        assert result is False

    def test_network_error_returns_false(self, tmp_path):
        """edge-tts 网络异常时应返回 False。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        output_path = tmp_path / "error.wav"

        with patch("edge_tts.Communicate", return_value=FakeCommunicate(b"", fail=True)):
            result = tts._call_edge_tts("测试文本", "host", "neutral", output_path)

        assert result is False

    @patch.dict(sys.modules, {"edge_tts": None})
    def test_edge_tts_not_installed_returns_false(self, tmp_path):
        """edge-tts 未安装时应返回 False。"""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "edge_tts":
                raise ImportError("No module named 'edge_tts'")
            return real_import(name, *args, **kwargs)

        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        # 强制设置 provider 为 edge（绕过 __init__ 检查）
        tts.provider = "edge"
        output_path = tmp_path / "no_module.wav"

        with patch("builtins.__import__", side_effect=mock_import):
            result = tts._call_edge_tts("测试文本", "host", "neutral", output_path)

        assert result is False

    def test_voice_mapping_from_config(self, tmp_path):
        """配置中的 edge_voice_mapping 应覆盖默认映射。"""
        cfg = make_config(api_key="", provider="edge")
        cfg["tts"]["edge_voice_mapping"] = {
            "host": "zh-CN-YunjianNeural",
            "guest": "zh-CN-XiaoyiNeural",
        }
        tts = TTSSynthesizer(cfg)
        mp3_data = generate_silent_mp3(duration_ms=100)
        output_path = tmp_path / "voice_config.wav"

        captured_voice = {}

        def capture_communicate(text, voice, **kwargs):
            captured_voice["voice"] = voice
            return FakeCommunicate(mp3_data)

        with patch("edge_tts.Communicate", side_effect=capture_communicate):
            tts._call_edge_tts("测试", "host", "neutral", output_path)

        assert captured_voice["voice"] == "zh-CN-YunjianNeural"

    def test_emotion_params_applied(self, tmp_path):
        """不同情感应映射到不同的 rate/pitch 参数。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        mp3_data = generate_silent_mp3(duration_ms=100)
        output_path = tmp_path / "emotion.wav"

        captured_params = {}

        def capture_communicate(text, voice, **kwargs):
            captured_params.update(kwargs)
            return FakeCommunicate(mp3_data)

        with patch("edge_tts.Communicate", side_effect=capture_communicate):
            tts._call_edge_tts("太棒了！", "guest", "excited", output_path)

        assert captured_params.get("rate") == "+15%"
        assert captured_params.get("pitch") == "+10Hz"


# ═══════════════════════════════════════════════════════════════
# 4. _synthesize_segment 路由测试
# ═══════════════════════════════════════════════════════════════


class TestSynthesizeSegmentRouting:
    """_synthesize_segment 路由逻辑测试。"""

    def test_edge_provider_routes_to_edge_tts(self, tmp_path):
        """provider='edge' 时应调用 _call_edge_tts。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        segment = make_segment("测试台词")
        output_path = tmp_path / "segment.wav"

        with patch.object(tts, "_call_edge_tts", return_value=True) as mock_edge:
            tts._synthesize_segment(segment, output_path)

        mock_edge.assert_called_once()
        assert output_path.exists() or mock_edge.called

    def test_edge_failure_falls_back_to_mock(self, tmp_path):
        """edge-tts 失败时应回退到 mock 静音。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        segment = make_segment("测试台词")
        output_path = tmp_path / "fallback.wav"

        with patch.object(tts, "_call_edge_tts", return_value=False):
            tts._synthesize_segment(segment, output_path)

        # mock 应生成静音 WAV
        assert output_path.exists()
        with wave.open(str(output_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 24000

    def test_mock_provider_routes_to_mock(self, tmp_path):
        """provider='mock' 时应直接调用 mock 合成。"""
        cfg = make_config(api_key="", provider="mock")
        tts = TTSSynthesizer(cfg)
        segment = make_segment("测试台词")
        output_path = tmp_path / "mock.wav"

        tts._synthesize_segment(segment, output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_empty_text_writes_silence(self, tmp_path):
        """空文本应写入短静音。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        segment = make_segment("")
        output_path = tmp_path / "empty.wav"

        tts._synthesize_segment(segment, output_path)

        assert output_path.exists()
        with wave.open(str(output_path), "rb") as wf:
            # 0.3 秒静音
            duration = wf.getnframes() / wf.getframerate()
            assert 0.2 < duration < 0.5


# ═══════════════════════════════════════════════════════════════
# 5. synthesize_script 完整流程测试
# ═══════════════════════════════════════════════════════════════


class TestSynthesizeScript:
    """synthesize_script 完整流程测试。"""

    def test_full_pipeline_with_mocked_edge_tts(self, tmp_path):
        """使用 mock edge-tts 完成完整脚本合成。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        script = make_script(3)
        mp3_data = generate_silent_mp3(duration_ms=200)

        with patch("edge_tts.Communicate", return_value=FakeCommunicate(mp3_data)):
            audio_files = tts.synthesize_script(script, tmp_path)

        assert len(audio_files) == 3
        for f in audio_files:
            p = Path(f)
            assert p.exists()
            assert p.suffix == ".wav"
            assert p.stat().st_size > 0

    def test_full_pipeline_with_mock_provider(self, tmp_path):
        """mock provider 完整流程。"""
        cfg = make_config(api_key="", provider="mock")
        tts = TTSSynthesizer(cfg)
        script = make_script(2)

        audio_files = tts.synthesize_script(script, tmp_path)

        assert len(audio_files) == 2
        for f in audio_files:
            assert Path(f).exists()

    def test_wav_format_consistency(self, tmp_path):
        """所有段落 WAV 格式应一致（采样率、声道、位深）。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        script = make_script(2)
        mp3_data = generate_silent_mp3(duration_ms=200)

        with patch("edge_tts.Communicate", return_value=FakeCommunicate(mp3_data)):
            audio_files = tts.synthesize_script(script, tmp_path)

        for f in audio_files:
            with wave.open(f, "rb") as wf:
                assert wf.getframerate() == 24000
                assert wf.getnchannels() == 1
                assert wf.getsampwidth() == 2


# ═══════════════════════════════════════════════════════════════
# 6. _preprocess_text 测试（确保预处理不破坏 edge-tts 文本）
# ═══════════════════════════════════════════════════════════════


class TestPreprocessText:
    """文本预处理测试（与 edge-tts 兼容性）。"""

    def test_question_mark_gets_pause(self):
        """问号后应增加停顿。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        result = tts._preprocess_text("这是什么？", "host", "neutral", 0)
        assert "..." in result

    def test_preprocess_preserves_text(self):
        """预处理后原文核心内容应保留。"""
        cfg = make_config(api_key="", provider="edge")
        tts = TTSSynthesizer(cfg)
        original = "这是一个测试句子"
        result = tts._preprocess_text(original, "host", "neutral", 0)
        assert original in result
