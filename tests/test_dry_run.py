"""测试脚本：验证 dry-run 模式下完整流水线可运行（无需 API Key）。

运行：python tests/test_dry_run.py
"""
import sys
from pathlib import Path

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import run_pipeline


def test_dry_run():
    """干跑测试：使用 mock 数据走完整流程。"""
    print("=" * 60)
    print("运行 dry-run 测试（无需任何 API Key）")
    print("=" * 60)
    episode = run_pipeline(dry_run=True)
    assert episode is not None, "流水线应返回 Episode"
    assert episode.audio_path, "应生成音频文件"
    assert Path(episode.audio_path).exists(), "音频文件应存在"
    print("\n✅ dry-run 测试通过！")
    print(f"   生成的音频：{episode.audio_path}")
    print(f"   时长：{episode.duration_seconds:.1f}s")


if __name__ == "__main__":
    test_dry_run()
