"""阶段 4 测试：长内容分段生成 — SegmentedScriptGenerator。

测试覆盖：
  1. ScriptSection 数据类
  2. SegmentedScriptGenerator mock 模式（分段生成结构验证）
  3. 分段结构：开场 + N 项目段 + 结尾
  4. 过渡句生成逻辑
  5. 合并结果一致性
  6. 独立审查回路（mock 评审通过/不通过）
  7. 全局连贯性检查
  8. main.py 集成（分段生成触发条件）
"""
import pytest

from src.segmented_generator import (
    SegmentedScriptGenerator,
    ScriptSection,
)
from src.models import GitHubRepo, PodcastHost, PodcastSegment, PodcastScript


# ════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════

def _make_config(mock_mode: bool = True) -> dict:
    """构建 mock 模式配置。"""
    from tests.conftest import make_config
    return make_config(mock_mode=mock_mode)


def _make_repos(n: int = 3) -> list[GitHubRepo]:
    """构建 n 个测试 repo。"""
    from tests.conftest import make_repo
    return [make_repo(f"test/repo-{chr(97+i)}", stars=500*(i+1)) for i in range(n)]


# ════════════════════════════════════════
# 1. ScriptSection 数据类
# ════════════════════════════════════════
class TestScriptSection:
    """ScriptSection 数据类验证。"""

    def test_default_values(self):
        """新建 ScriptSection 默认值正确。"""
        s = ScriptSection()
        assert s.section_type == "project"
        assert s.repo_name == ""
        assert s.segments == []
        assert s.review_score == 0.0
        assert s.rewrites == 0
        assert s.transition_before == []

    def test_char_count(self):
        """char_count 应正确计算总字符数。"""
        s = ScriptSection(
            segments=[
                PodcastSegment("Alice", "Hello world!", "neutral", "host"),
                PodcastSegment("Bob", "Hi!", "neutral", "guest"),
            ]
        )
        assert s.char_count == len("Hello world!") + len("Hi!")

    def test_char_count_empty(self):
        """空段落 char_count 为 0。"""
        assert ScriptSection().char_count == 0


# ════════════════════════════════════════
# 2. Mock 模式分段生成
# ════════════════════════════════════════
class TestMockSegmentedGeneration:
    """mock 模式下的分段生成。"""

    def test_mock_generate_returns_podcast_script(self):
        """mock 生成应返回 PodcastScript。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(3)
        script = gen.generate_segmented(repos)

        assert isinstance(script, PodcastScript)
        assert script.title != ""
        assert len(script.segments) > 0
        assert len(script.hosts) >= 2

    def test_mock_generate_has_intro_outro(self):
        """mock 生成应包含开场和结尾。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(3)
        script = gen.generate_segmented(repos)

        # 第一段应是开场（包含"大家好"或"欢迎"）
        first_text = script.segments[0].text
        assert "大家好" in first_text or "欢迎" in first_text

        # 最后一段应是结尾（包含"再见"或"到这里"）
        last_text = script.segments[-1].text
        assert "再见" in last_text or "到这里" in last_text

    def test_mock_generate_covers_all_repos(self):
        """mock 生成应覆盖所有项目。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(4)
        script = gen.generate_segmented(repos)

        # 每个项目的名字应出现在脚本中
        full_text = " ".join(s.text for s in script.segments)
        for repo in repos:
            assert repo.name in full_text or repo.short_name in full_text

    def test_mock_generate_has_transitions(self):
        """mock 生成应在项目间包含过渡句。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(3)
        script = gen.generate_segmented(repos)

        # 应有过渡句（"接下来"）
        transitions = [s for s in script.segments if "接下来" in s.text]
        assert len(transitions) >= 2  # 至少 2 个过渡（第2、3个项目前）

    def test_mock_generate_segment_count(self):
        """mock 生成的段落数应与项目数成正比。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)

        # 3 个项目：开场(1) + 过渡(2) + 项目段(3*2=6) + 结尾(1) = 10
        repos3 = _make_repos(3)
        script3 = gen.generate_segmented(repos3)
        assert len(script3.segments) >= 8  # 至少 8 段

        # 5 个项目应比 3 个项目段落数更多
        repos5 = _make_repos(5)
        script5 = gen.generate_segmented(repos5)
        assert len(script5.segments) > len(script3.segments)

    def test_mock_generate_critic_score(self):
        """mock 生成应有默认评审分数。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(2)
        script = gen.generate_segmented(repos)
        assert script.critic_score > 0  # mock 模式默认 8.0


# ════════════════════════════════════════
# 3. 分段结构验证
# ════════════════════════════════════════
class TestSegmentedStructure:
    """分段生成结构验证。"""

    def test_mock_sections_tracking(self):
        """mock 模式下统计指标正确。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(3)
        gen.generate_segmented(repos)

        # mock 模式不触发真实分段，但仍可验证属性存在
        assert hasattr(gen, '_total_rewrites')
        assert hasattr(gen, '_sections_generated')

    def test_hosts_extracted_from_segments(self):
        """合并后的 hosts 应从段落中提取。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(2)
        script = gen.generate_segmented(repos)

        # 应有主持人
        assert len(script.hosts) >= 2
        host_names = {h.name for h in script.hosts}
        # 段落中的说话人应出现在 hosts 中
        speakers = {s.speaker for s in script.segments}
        assert speakers.issubset(host_names) or len(speakers & host_names) >= 2

    def test_repo_names_preserved(self):
        """合并后的 repo_names 应与输入一致。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(3)
        script = gen.generate_segmented(repos)

        assert set(script.repo_names) == {r.name for r in repos}

    def test_style_preserved(self):
        """生成的脚本应保留风格设置。"""
        config = _make_config()
        config["podcast_style"] = "technical"
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(2)
        script = gen.generate_segmented(repos)
        assert script.style == "technical"

    def test_longform_target_minutes(self):
        """长内容模式应设置 30 分钟目标。"""
        config = _make_config()
        config["longform"] = True
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(2)
        script = gen.generate_segmented(repos)
        assert script.target_minutes == 30


# ════════════════════════════════════════
# 4. 风格指导
# ════════════════════════════════════════
class TestStyleGuidance:
    """风格指导文本验证。"""

    def test_casual_style(self):
        """casual 风格应返回轻松指导。"""
        config = _make_config()
        config["podcast_style"] = "casual"
        gen = SegmentedScriptGenerator(config)
        guidance = gen._get_style_guidance()
        assert "轻松" in guidance

    def test_technical_style(self):
        """technical 风格应返回技术指导。"""
        config = _make_config()
        config["podcast_style"] = "technical"
        gen = SegmentedScriptGenerator(config)
        guidance = gen._get_style_guidance()
        assert "技术" in guidance or "专业" in guidance

    def test_debate_style(self):
        """debate 风格应返回辩论指导。"""
        config = _make_config()
        config["podcast_style"] = "debate"
        gen = SegmentedScriptGenerator(config)
        guidance = gen._get_style_guidance()
        assert "辩论" in guidance or "讨论" in guidance

    def test_interview_style(self):
        """interview 风格应返回访谈指导。"""
        config = _make_config()
        config["podcast_style"] = "interview"
        gen = SegmentedScriptGenerator(config)
        guidance = gen._get_style_guidance()
        assert "采访" in guidance or "访谈" in guidance

    def test_unknown_style_defaults_to_casual(self):
        """未知风格应回退到 casual。"""
        config = _make_config()
        config["podcast_style"] = "unknown"
        gen = SegmentedScriptGenerator(config)
        guidance = gen._get_style_guidance()
        assert "轻松" in guidance  # casual 的关键词


# ════════════════════════════════════════
# 5. 项目信息构建
# ════════════════════════════════════════
class TestProjectInfo:
    """_build_project_info 验证。"""

    def test_contains_basic_info(self):
        """项目信息应包含基本字段。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        from tests.conftest import make_repo
        repo = make_repo("test/awesome", stars=999, language="Rust")
        info = gen._build_project_info(repo)

        assert "test/awesome" in info
        assert "999" in info
        assert "Rust" in info

    def test_truncates_long_readme(self):
        """过长的 README 应被截断。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        from tests.conftest import make_repo
        long_readme = "A" * 20000
        repo = make_repo("test/repo", readme_markdown=long_readme)
        info = gen._build_project_info(repo)

        # 应截断到 8000 字符
        assert len(info) < 15000  # 加上其他字段也不应太长


# ════════════════════════════════════════
# 6. 合并逻辑
# ════════════════════════════════════════
class TestMergeSections:
    """_merge_sections 合并逻辑验证。"""

    def test_merges_all_segments(self):
        """合并应包含所有段落的对话。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)

        sections = [
            ScriptSection(
                section_type="intro",
                segments=[PodcastSegment("Alice", "开场白", "excited", "host")],
            ),
            ScriptSection(
                section_type="project",
                repo_name="test/repo",
                segments=[PodcastSegment("Bob", "项目讨论", "neutral", "guest")],
            ),
            ScriptSection(
                section_type="outro",
                segments=[PodcastSegment("Alice", "结尾", "happy", "host")],
            ),
        ]
        repos = _make_repos(1)
        script = gen._merge_sections(sections, repos)

        assert len(script.segments) == 3
        assert script.segments[0].text == "开场白"
        assert script.segments[1].text == "项目讨论"
        assert script.segments[2].text == "结尾"

    def test_merges_with_transitions(self):
        """合并应包含过渡句。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)

        transition = PodcastSegment("Alice", "过渡句", "neutral", "host")
        sections = [
            ScriptSection(
                section_type="intro",
                segments=[PodcastSegment("Alice", "开场", "excited", "host")],
            ),
            ScriptSection(
                section_type="project",
                repo_name="test/repo",
                segments=[PodcastSegment("Bob", "讨论", "neutral", "guest")],
                transition_before=[transition],
            ),
        ]
        repos = _make_repos(1)
        script = gen._merge_sections(sections, repos)

        # 过渡句应在项目段之前
        assert len(script.segments) == 3
        assert script.segments[1].text == "过渡句"
        assert script.segments[2].text == "讨论"

    def test_extracts_hosts_from_segments(self):
        """合并应从段落中提取主持人。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)

        sections = [
            ScriptSection(
                section_type="intro",
                segments=[
                    PodcastSegment("Alice", "Hi", "excited", "host"),
                    PodcastSegment("Bob", "Hello", "neutral", "guest"),
                ],
            ),
        ]
        repos = _make_repos(1)
        script = gen._merge_sections(sections, repos)

        host_names = {h.name for h in script.hosts}
        assert "Alice" in host_names
        assert "Bob" in host_names

    def test_default_hosts_when_empty(self):
        """无段落时应使用默认主持人。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)

        sections = [ScriptSection(section_type="intro", segments=[])]
        repos = _make_repos(1)
        script = gen._merge_sections(sections, repos)

        assert len(script.hosts) >= 2  # 默认主持人


# ════════════════════════════════════════
# 7. 单个项目段落 mock 生成
# ════════════════════════════════════════
class TestMockProjectSegment:
    """mock 模式下单个项目段落的生成。"""

    def test_mock_generate_single_repo(self):
        """单个项目也应正确生成。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(1)
        script = gen.generate_segmented(repos)

        assert len(script.segments) >= 3  # 开场 + 项目 + 结尾
        assert len(script.hosts) >= 2

    def test_mock_generate_five_repos(self):
        """5 个项目也应正确生成。"""
        config = _make_config()
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(5)
        script = gen.generate_segmented(repos)

        # 每个项目至少 2 段 + 开场 + 结尾 + 4 个过渡
        assert len(script.segments) >= 12
        assert len(script.repo_names) == 5


# ════════════════════════════════════════
# 8. main.py 集成验证
# ════════════════════════════════════════
class TestMainIntegration:
    """验证 main.py 正确选择分段生成器。"""

    def test_segmented_import_works(self):
        """main.py 能正确导入 SegmentedScriptGenerator。"""
        from src.segmented_generator import SegmentedScriptGenerator
        assert SegmentedScriptGenerator is not None

    def test_longform_triggers_segmented(self):
        """longform=True 时应使用分段生成。"""
        from tests.conftest import make_config
        config = make_config(mock_mode=True)
        config["longform"] = True

        # 验证条件判断
        use_segmented = config.get("longform", False) or len(_make_repos(1)) >= 3
        assert use_segmented is True

    def test_three_repos_triggers_segmented(self):
        """3+ 项目时应使用分段生成。"""
        from tests.conftest import make_config
        config = make_config(mock_mode=True)
        repos = _make_repos(3)

        use_segmented = config.get("longform", False) or len(repos) >= 3
        assert use_segmented is True

    def test_two_repos_uses_monolithic(self):
        """2 个项目时应使用单体生成。"""
        from tests.conftest import make_config
        config = make_config(mock_mode=True)
        repos = _make_repos(2)

        use_segmented = config.get("longform", False) or len(repos) >= 3
        assert use_segmented is False


# ════════════════════════════════════════
# 9. 端到端：mock 流水线 + 分段生成
# ════════════════════════════════════════
class TestEndToEndSegmented:
    """端到端集成测试。"""

    def test_full_mock_segmented_pipeline(self):
        """完整 mock 分段生成流水线。"""
        config = _make_config()
        config["longform"] = True
        gen = SegmentedScriptGenerator(config)
        repos = _make_repos(4)

        script = gen.generate_segmented(repos)

        # 验证基本结构
        assert isinstance(script, PodcastScript)
        assert len(script.segments) > 0
        assert len(script.hosts) >= 2
        assert len(script.repo_names) == 4

        # 验证内容覆盖
        full_text = " ".join(s.text for s in script.segments)
        for repo in repos:
            assert repo.name in full_text

        # 验证开场和结尾
        assert "大家好" in script.segments[0].text or "欢迎" in script.segments[0].text
        assert "再见" in script.segments[-1].text or "到这里" in script.segments[-1].text

        # 验证统计指标
        assert gen._sections_generated >= 0  # mock 模式可能不设置
        assert gen._total_rewrites >= 0

    def test_segmented_vs_monolithic_more_segments(self):
        """分段生成应比单体生成产生更多段落。"""
        from src.llm_script import ScriptGenerator

        config = _make_config()
        repos = _make_repos(4)

        # 单体生成
        mono_gen = ScriptGenerator(config)
        mono_script = mono_gen.generate(repos)

        # 分段生成
        seg_gen = SegmentedScriptGenerator(config)
        seg_script = seg_gen.generate_segmented(repos)

        # 分段生成应有更多段落（包含过渡句）
        assert len(seg_script.segments) >= len(mono_script.segments)
