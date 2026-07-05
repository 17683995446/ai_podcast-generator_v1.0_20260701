"""Stage 1 证据链可视化 —— 单元测试 + 集成测试。

覆盖范围：
  1. EvidenceItem 数据类序列化/反序列化
  2. DeepExtractor.extract_with_evidence() 证据收集
  3. EvidenceTracker 技术栈匹配、模块匹配、摘要统计
  4. ProjectAnalyzer._attach_evidence() 集成
  5. ProjectAnalysis.to_dict()/from_dict() 包含 evidence_sources
  6. 端到端：mock 模式下从深提取到分析器的完整证据链
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestEvidenceItem:
    """EvidenceItem 数据类测试。"""

    def test_to_dict_contains_all_fields(self):
        from src.models import EvidenceItem

        ev = EvidenceItem(
            field="tech_stack",
            value="Python",
            source_type="dependency_file",
            source_detail="requirements.txt",
            confidence="verified",
        )
        d = ev.to_dict()
        assert d["field"] == "tech_stack"
        assert d["value"] == "Python"
        assert d["source_type"] == "dependency_file"
        assert d["source_detail"] == "requirements.txt"
        assert d["confidence"] == "verified"

    def test_default_confidence_is_verified(self):
        from src.models import EvidenceItem

        ev = EvidenceItem(field="test", value="x", source_type="file_tree", source_detail="tree")
        assert ev.confidence == "verified"


class TestProjectAnalysisEvidence:
    """ProjectAnalysis evidence_sources 字段测试。"""

    def test_to_dict_includes_evidence_sources(self):
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(repo_name="test/repo")
        analysis.evidence_sources = [
            {"field": "tech_stack", "value": "Python", "source_type": "dependency_file",
             "source_detail": "requirements.txt", "confidence": "verified"}
        ]
        d = analysis.to_dict()
        assert "evidence_sources" in d
        assert len(d["evidence_sources"]) == 1
        assert d["evidence_sources"][0]["value"] == "Python"

    def test_from_dict_includes_evidence_sources(self):
        from src.models import ProjectAnalysis

        data = {
            "repo_name": "test/repo",
            "summary": "test",
            "tech_stack": ["Python"],
            "architecture": "",
            "key_modules": [],
            "quick_start": "",
            "highlights": [],
            "use_cases": [],
            "comparison": "",
            "code_insights": "",
            "evidence_sources": [
                {"field": "tech_stack", "value": "Python", "source_type": "dependency_file",
                 "source_detail": "requirements.txt", "confidence": "verified"}
            ],
        }
        analysis = ProjectAnalysis.from_dict(data)
        assert len(analysis.evidence_sources) == 1
        assert analysis.evidence_sources[0]["source_type"] == "dependency_file"

    def test_empty_evidence_sources_by_default(self):
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(repo_name="test/repo")
        assert analysis.evidence_sources == []


class TestDeepExtractorEvidence:
    """DeepExtractor 证据收集测试。"""

    def _make_mock_config(self):
        """构建强制 mock 模式的深提取配置。"""
        return {
            "api_keys": {"github": "", "llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": ""},
            "project_root": ".",
            "_mock_mode": True,  # 强制 mock 模式，避免访问真实 GitHub API
        }

    def test_extract_with_evidence_returns_tuple(self):
        from src.deep_extractor import DeepExtractor

        extractor = DeepExtractor(self._make_mock_config())

        from src.models import GitHubRepo
        repo = GitHubRepo(
            name="test/repo",
            url="https://github.com/test/repo",
            description="test",
            stars=100,
            language="Python",
            topics=[],
            readme_markdown="# Test",
        )
        result = extractor.extract_with_evidence(repo)
        assert isinstance(result, tuple)
        assert len(result) == 2
        markdown, evidence = result
        assert isinstance(markdown, str)
        assert isinstance(evidence, list)

    def test_mock_extract_records_evidence(self):
        from src.deep_extractor import DeepExtractor

        extractor = DeepExtractor(self._make_mock_config())

        from src.models import GitHubRepo
        repo = GitHubRepo(
            name="test/repo",
            url="https://github.com/test/repo",
            description="test",
            stars=100,
            language="Python",
            topics=[],
            readme_markdown="# Test",
        )
        _, evidence = extractor.extract_with_evidence(repo)
        # mock 模式应记录至少 5 条证据
        assert len(evidence) >= 5
        # 每条证据都有必需字段
        for ev in evidence:
            assert "field" in ev
            assert "value" in ev
            assert "source_type" in ev
            assert "source_detail" in ev
            assert "confidence" in ev

    def test_mock_evidence_marked_as_mock_source(self):
        from src.deep_extractor import DeepExtractor

        extractor = DeepExtractor(self._make_mock_config())

        from src.models import GitHubRepo
        repo = GitHubRepo(name="test/repo", url="", description="", stars=0, language="", topics=[], readme_markdown="")
        _, evidence = extractor.extract_with_evidence(repo)
        # mock 数据的 source_detail 应包含 "mock"
        assert any("mock" in ev["source_detail"].lower() for ev in evidence)


class TestEvidenceTracker:
    """EvidenceTracker 匹配逻辑测试。"""

    def test_match_tech_to_dependency_verified(self):
        from src.evidence_tracker import match_evidence_to_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "Flask", "NonExistentTech"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "dependencies", "value": "flask>=2.0, requests, pydantic", "source_type": "dependency_file",
             "source_detail": "requirements.txt", "confidence": "verified"},
            {"field": "file_tree", "value": "src/ tests/ README.md", "source_type": "file_tree",
             "source_detail": "GitHub API: git_tree", "confidence": "verified"},
        ]
        matched = match_evidence_to_analysis(analysis, evidence)

        # Python 和 Flask 应匹配到依赖文件
        tech_entries = [e for e in matched if e["field"] == "tech_stack"]
        assert len(tech_entries) == 3

        flask_entry = next(e for e in tech_entries if e["value"] == "Flask")
        assert flask_entry["source_type"] == "dependency_file"
        assert flask_entry["confidence"] == "verified"

        python_entry = next(e for e in tech_entries if e["value"] == "Python")
        assert python_entry["confidence"] == "verified"

        # NonExistentTech 应标注为推断
        nonexist = next(e for e in tech_entries if e["value"] == "NonExistentTech")
        assert nonexist["source_type"] == "llm_inference"
        assert nonexist["confidence"] == "inferred"

    def test_match_module_to_file_tree(self):
        from src.evidence_tracker import match_evidence_to_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=[],
            architecture="",
            key_modules=[
                {"name": "core", "description": "Core engine"},
                {"name": "runner", "description": "Test runner"},
                {"name": "phantom", "description": "Does not exist"},
            ],
        )
        evidence = [
            {"field": "file_tree", "value": "src/core/ src/runner/ tests/ README.md", "source_type": "file_tree",
             "source_detail": "GitHub API: git_tree", "confidence": "verified"},
        ]
        matched = match_evidence_to_analysis(analysis, evidence)

        module_entries = [e for e in matched if e["field"] == "key_modules"]
        assert len(module_entries) == 3

        core_entry = next(e for e in module_entries if e["value"] == "core")
        assert core_entry["source_type"] == "file_tree"
        assert core_entry["confidence"] == "verified"

        phantom_entry = next(e for e in module_entries if e["value"] == "phantom")
        assert phantom_entry["source_type"] == "llm_inference"
        assert phantom_entry["confidence"] == "inferred"

    def test_empty_evidence_returns_empty(self):
        from src.evidence_tracker import match_evidence_to_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(repo_name="test/repo", tech_stack=["Python"])
        matched = match_evidence_to_analysis(analysis, [])
        assert matched == []

    def test_summarize_evidence(self):
        from src.evidence_tracker import summarize_evidence

        evidence = [
            {"field": "tech_stack", "value": "Python", "source_type": "dependency_file", "confidence": "verified"},
            {"field": "tech_stack", "value": "Rust", "source_type": "llm_inference", "confidence": "inferred"},
            {"field": "key_modules", "value": "core", "source_type": "file_tree", "confidence": "verified"},
        ]
        summary = summarize_evidence(evidence)
        assert summary["total"] == 3
        assert summary["verified"] == 2
        assert summary["inferred"] == 1
        assert summary["coverage"] == 0.67
        assert summary["by_source"]["dependency_file"] == 1
        assert summary["by_source"]["file_tree"] == 1
        assert summary["by_source"]["llm_inference"] == 1

    def test_summarize_empty_evidence(self):
        from src.evidence_tracker import summarize_evidence

        summary = summarize_evidence([])
        assert summary["total"] == 0
        assert summary["coverage"] == 0.0

    def test_architecture_marked_as_inferred(self):
        from src.evidence_tracker import match_evidence_to_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=[],
            architecture="Layered architecture with plugin system",
            key_modules=[],
        )
        evidence = [
            {"field": "file_tree", "value": "src/", "source_type": "file_tree", "confidence": "verified"},
        ]
        matched = match_evidence_to_analysis(analysis, evidence)
        arch_entries = [e for e in matched if e["field"] == "architecture"]
        assert len(arch_entries) == 1
        assert arch_entries[0]["confidence"] == "inferred"
        assert arch_entries[0]["source_type"] == "llm_inference"


class TestAnalyzerEvidenceIntegration:
    """ProjectAnalyzer 证据集成测试。"""

    def test_analyze_single_attaches_evidence_mock_mode(self):
        from src.project_analyzer import ProjectAnalyzer

        config = {
            "api_keys": {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""},
            "llm": {"base_url": "", "model": "test", "enable_thinking": False, "temperature": 0.4, "max_tokens": 4000, "timeout": 120},
            "project_root": ".",
        }
        analyzer = ProjectAnalyzer(config)

        from src.models import GitHubRepo
        repo = GitHubRepo(
            name="test/repo",
            url="https://github.com/test/repo",
            description="test",
            stars=100,
            language="Python",
            topics=[],
            readme_markdown="# Test",
        )
        evidence = [
            {"field": "dependencies", "value": "flask, requests", "source_type": "dependency_file",
             "source_detail": "requirements.txt", "confidence": "verified"},
        ]
        analysis = analyzer.analyze_single(repo, evidence_list=evidence)
        # mock 分析应有内容
        assert analysis.summary
        # 证据应被附加
        assert len(analysis.evidence_sources) > 0

    def test_analyze_single_without_evidence(self):
        from src.project_analyzer import ProjectAnalyzer

        config = {
            "api_keys": {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""},
            "llm": {"base_url": "", "model": "test", "enable_thinking": False, "temperature": 0.4, "max_tokens": 4000, "timeout": 120},
            "project_root": ".",
        }
        analyzer = ProjectAnalyzer(config)

        from src.models import GitHubRepo
        repo = GitHubRepo(name="test/repo", url="", description="", stars=0, language="", topics=[], readme_markdown="# T")
        analysis = analyzer.analyze_single(repo)
        # 无证据时 evidence_sources 应为空
        assert analysis.evidence_sources == []

    def test_analyze_passes_evidence_map(self):
        from src.project_analyzer import ProjectAnalyzer

        config = {
            "api_keys": {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""},
            "llm": {"base_url": "", "model": "test", "enable_thinking": False, "temperature": 0.4, "max_tokens": 4000, "timeout": 120},
            "project_root": ".",
        }
        analyzer = ProjectAnalyzer(config)

        from src.models import GitHubRepo
        repos = [
            GitHubRepo(name="a/b", url="", description="", stars=0, language="", topics=[], readme_markdown="# A"),
            GitHubRepo(name="c/d", url="", description="", stars=0, language="", topics=[], readme_markdown="# C"),
        ]
        evidence_map = {
            "a/b": [{"field": "dependencies", "value": "flask", "source_type": "dependency_file",
                     "source_detail": "requirements.txt", "confidence": "verified"}],
            "c/d": [],
        }
        analyses = analyzer.analyze(repos, evidence_map=evidence_map)
        assert len(analyses) == 2
        # a/b 应有证据
        assert len(analyses[0].evidence_sources) > 0
        # c/d 应无证据
        assert analyses[1].evidence_sources == []


class TestEndToEndEvidenceChain:
    """端到端测试：深提取 → 证据追踪 → 分析器集成。"""

    def test_full_mock_pipeline_evidence_chain(self):
        """mock 模式下从深提取到分析器的完整证据链。"""
        from src.deep_extractor import DeepExtractor
        from src.project_analyzer import ProjectAnalyzer

        config = {
            "api_keys": {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""},
            "llm": {"base_url": "", "model": "test", "enable_thinking": False, "temperature": 0.4, "max_tokens": 4000, "timeout": 120},
            "project_root": ".",
            "_mock_mode": True,  # 强制 mock 模式
        }

        # Step 1: 深提取
        extractor = DeepExtractor(config)
        from src.models import GitHubRepo
        repo = GitHubRepo(
            name="test/repo",
            url="https://github.com/test/repo",
            description="A test repo",
            stars=500,
            language="Python",
            topics=["python"],
            readme_markdown="# Test Repo\n\nA Python project.",
        )
        markdown, evidence = extractor.extract_with_evidence(repo)
        assert len(evidence) > 0

        # Step 2: 将深提取内容注入 README（模拟 pipeline 行为）
        repo.readme_markdown += f"\n\n{markdown}"

        # Step 3: 分析器集成证据
        analyzer = ProjectAnalyzer(config)
        analysis = analyzer.analyze_single(repo, evidence_list=evidence)

        # 验证证据链完整性
        assert len(analysis.evidence_sources) > 0
        # 应有 verified 项
        verified_count = sum(1 for e in analysis.evidence_sources if e.get("confidence") == "verified")
        assert verified_count > 0
        # 应有原始深提取证据（dependencies/health 等）
        source_types = {e.get("source_type") for e in analysis.evidence_sources}
        assert "dependency_file" in source_types or "github_stats" in source_types

    def test_evidence_summary_in_analysis_dict(self):
        """分析结果序列化后包含证据摘要。"""
        from src.evidence_tracker import summarize_evidence, match_evidence_to_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "Flask"],
            architecture="Layered",
            key_modules=[{"name": "core", "description": "Core"}],
        )
        evidence = [
            {"field": "dependencies", "value": "flask, requests", "source_type": "dependency_file",
             "source_detail": "requirements.txt", "confidence": "verified"},
            {"field": "file_tree", "value": "src/core/", "source_type": "file_tree",
             "source_detail": "git_tree", "confidence": "verified"},
        ]
        analysis.evidence_sources = match_evidence_to_analysis(analysis, evidence)
        d = analysis.to_dict()
        assert "evidence_sources" in d

        summary = summarize_evidence(d["evidence_sources"])
        assert summary["total"] > 0
        assert summary["verified"] > 0
