"""Stage 2 规则校验层 —— 单元测试 + 集成测试。

覆盖范围：
  1. ValidationIssue / ValidationReport 数据类
  2. validate_analysis 技术栈校验
  3. validate_analysis 关键模块校验
  4. 校验分数计算
  5. validate_batch 批量校验
  6. filter_unverified_tech_stack 过滤
  7. 文件名模式匹配（Docker/K8s/CI-CD）
  8. 端到端：深提取证据 → 分析 → 校验
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestValidationDataClasses:
    """数据类序列化测试。"""

    def test_validation_issue_to_dict(self):
        from src.analysis_validator import ValidationIssue

        issue = ValidationIssue(
            field="tech_stack",
            value="Rust",
            issue_type="unverified_tech",
            severity="warning",
            message="未找到证据",
            suggestion="检查依赖",
        )
        d = issue.to_dict()
        assert d["field"] == "tech_stack"
        assert d["value"] == "Rust"
        assert d["issue_type"] == "unverified_tech"
        assert d["severity"] == "warning"

    def test_validation_report_to_dict(self):
        from src.analysis_validator import ValidationReport

        report = ValidationReport(
            repo_name="test/repo",
            tech_stack_verified=["Python"],
            tech_stack_unverified=["Rust"],
            key_modules_verified=["core"],
            key_modules_unverified=[],
            passed=True,
            score=0.75,
        )
        d = report.to_dict()
        assert d["repo_name"] == "test/repo"
        assert d["tech_stack_verified"] == ["Python"]
        assert d["tech_stack_unverified"] == ["Rust"]
        assert d["passed"] is True
        assert d["score"] == 0.75


class TestTechStackValidation:
    """技术栈校验测试。"""

    def test_verified_tech_in_dependencies(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "Flask"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "dependencies", "value": "flask>=2.0, requests, pydantic",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "Flask" in report.tech_stack_verified
        assert "Python" in report.tech_stack_verified
        assert len(report.tech_stack_unverified) == 0
        assert report.passed is True

    def test_unverified_tech_not_in_evidence(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "NonExistentFramework"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "dependencies", "value": "requests, pydantic",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "Python" in report.tech_stack_verified or "python" in [v.lower() for v in report.tech_stack_verified]
        assert "NonExistentFramework" in report.tech_stack_unverified
        assert any(i.value == "NonExistentFramework" for i in report.issues)

    def test_docker_detected_via_file_pattern(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Docker", "Python"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "file_tree", "value": "src/ tests/ Dockerfile docker-compose.yml README.md",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
            {"field": "dependencies", "value": "requests",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "Docker" in report.tech_stack_verified
        assert report.passed is True

    def test_kubernetes_detected_via_file_pattern(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Kubernetes", "Go"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "file_tree", "value": "cmd/ internal/ deploy/helm/chart.yaml go.mod",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
            {"field": "dependencies", "value": "go.mod",
             "source_type": "dependency_file", "source_detail": "go.mod", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "Kubernetes" in report.tech_stack_verified
        assert "Go" in report.tech_stack_verified


class TestKeyModulesValidation:
    """关键模块校验测试。"""

    def test_verified_module_in_file_tree(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=[],
            architecture="",
            key_modules=[
                {"name": "core", "description": "Core engine"},
                {"name": "runner", "description": "Test runner"},
            ],
        )
        evidence = [
            {"field": "file_tree", "value": "src/core/ src/runner/ tests/ README.md",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "core" in report.key_modules_verified
        assert "runner" in report.key_modules_verified
        assert len(report.key_modules_unverified) == 0

    def test_unverified_module_not_in_file_tree(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=[],
            architecture="",
            key_modules=[
                {"name": "real_module", "description": "Exists"},
                {"name": "phantom_module", "description": "Does not exist"},
            ],
        )
        evidence = [
            {"field": "file_tree", "value": "src/real_module/ tests/",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert "real_module" in report.key_modules_verified
        assert "phantom_module" in report.key_modules_unverified
        assert any(i.value == "phantom_module" for i in report.issues)


class TestValidationScore:
    """校验分数计算测试。"""

    def test_full_score_when_all_verified(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python"],
            architecture="",
            key_modules=[{"name": "core", "description": "Core"}],
        )
        evidence = [
            {"field": "dependencies", "value": "python, requests",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
            {"field": "file_tree", "value": "src/core/",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        assert report.score == 1.0
        assert report.passed is True

    def test_partial_score(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "FakeTech"],
            architecture="",
            key_modules=[{"name": "core", "description": "Core"}, {"name": "phantom", "description": "X"}],
        )
        evidence = [
            {"field": "dependencies", "value": "python",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
            {"field": "file_tree", "value": "src/core/",
             "source_type": "file_tree", "source_detail": "git_tree", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        # 2 verified out of 4 total
        assert report.score == 0.5
        assert report.passed is True  # score >= 0.5

    def test_fail_when_score_below_threshold(self):
        from src.analysis_validator import validate_analysis
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["FakeTech1", "FakeTech2", "FakeTech3"],
            architecture="",
            key_modules=[{"name": "phantom", "description": "X"}],
        )
        evidence = []
        report = validate_analysis(analysis, evidence)
        assert report.score == 0.0
        assert report.passed is False


class TestBatchValidation:
    """批量校验测试。"""

    def test_validate_batch_multiple_repos(self):
        from src.analysis_validator import validate_batch
        from src.models import ProjectAnalysis

        analyses = [
            ProjectAnalysis(repo_name="a/b", tech_stack=["Python"], architecture="", key_modules=[]),
            ProjectAnalysis(repo_name="c/d", tech_stack=["Rust"], architecture="", key_modules=[]),
        ]
        evidence_map = {
            "a/b": [{"field": "dependencies", "value": "python", "source_type": "dependency_file",
                     "source_detail": "requirements.txt", "confidence": "verified"}],
            "c/d": [],
        }
        reports = validate_batch(analyses, evidence_map)
        assert len(reports) == 2
        assert "a/b" in reports
        assert "c/d" in reports
        assert reports["a/b"].passed is True
        assert reports["c/d"].passed is False

    def test_filter_unverified_tech_stack(self):
        from src.analysis_validator import validate_analysis, filter_unverified_tech_stack
        from src.models import ProjectAnalysis

        analysis = ProjectAnalysis(
            repo_name="test/repo",
            tech_stack=["Python", "FakeTech"],
            architecture="",
            key_modules=[],
        )
        evidence = [
            {"field": "dependencies", "value": "python",
             "source_type": "dependency_file", "source_detail": "requirements.txt", "confidence": "verified"},
        ]
        report = validate_analysis(analysis, evidence)
        filtered = filter_unverified_tech_stack(analysis, report)
        assert "Python" in filtered
        assert "FakeTech" not in filtered


class TestEndToEndValidation:
    """端到端校验测试：深提取 → 分析 → 校验。"""

    def test_mock_pipeline_with_validation(self):
        """mock 模式下完整链路：深提取 → mock 分析 → 规则校验。"""
        from src.deep_extractor import DeepExtractor
        from src.project_analyzer import ProjectAnalyzer
        from src.analysis_validator import validate_analysis

        config = {
            "api_keys": {"llm": "", "tts": "", "deepseek": "", "dashscope": "", "siliconflow": "", "github": ""},
            "llm": {"base_url": "", "model": "test", "enable_thinking": False,
                     "temperature": 0.4, "max_tokens": 4000, "timeout": 120},
            "project_root": ".",
            "_mock_mode": True,
        }

        # 深提取
        extractor = DeepExtractor(config)
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

        # 分析
        analyzer = ProjectAnalyzer(config)
        analysis = analyzer.analyze_single(repo, evidence_list=evidence)

        # 校验
        report = validate_analysis(analysis, evidence)
        assert report.repo_name == "test/repo"
        assert isinstance(report.score, float)
        assert 0.0 <= report.score <= 1.0
        assert isinstance(report.passed, bool)
        # mock 数据应有一些已验证项
        assert len(report.tech_stack_verified) + len(report.tech_stack_unverified) > 0
