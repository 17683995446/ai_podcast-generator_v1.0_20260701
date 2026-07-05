"""阶段 5 测试：代码级分析 — CodeAnalyzer + CodeMetrics。

测试覆盖：
  1. CodeMetrics 数据类序列化
  2. 代码规模分析（LOC、文件数、语言分布）
  3. 架构模式检测（MVC/微服务/插件式/库/CLI/框架/单体）
  4. 复杂度估算（分支、函数、嵌套）
  5. 质量评估（测试覆盖、文档、CI/CD、Lint）
  6. 可维护性指数
  7. DeepExtractor 集成（原始数据存储）
  8. ProjectAnalysis 集成（code_metrics 字段序列化）
  9. 端到端：mock 流水线 + 代码分析
"""
import pytest

from src.code_analyzer import CodeAnalyzer, CodeMetrics
from src.models import ProjectAnalysis


# ════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════

def _make_python_project():
    """构建一个典型的 Python 项目文件树和源码。"""
    file_tree = [
        "src/",
        "src/main.py",
        "src/utils.py",
        "src/models.py",
        "tests/",
        "tests/test_main.py",
        "tests/test_utils.py",
        "README.md",
        "setup.py",
        "requirements.txt",
        ".github/workflows/ci.yml",
        "pyproject.toml",
    ]
    source_code = {
        "src/main.py": (
            "import sys\n"
            "def main():\n"
            "    if len(sys.argv) > 1:\n"
            "        for arg in sys.argv[1:]:\n"
            "            if arg == '--help':\n"
            "                print('Help')\n"
            "            else:\n"
            "                print(f'Arg: {arg}')\n"
            "    else:\n"
            "        print('No args')\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        "src/utils.py": (
            "def helper(x):\n"
            "    if x > 0:\n"
            "        return x * 2\n"
            "    return 0\n"
        ),
        "setup.py": (
            "from setuptools import setup\n"
            "setup(name='test', version='1.0.0')\n"
        ),
    }
    return file_tree, source_code


def _make_mvc_project():
    """构建一个 MVC 架构项目文件树。"""
    return [
        "app/",
        "app/models/",
        "app/models/user.py",
        "app/models/post.py",
        "app/views/",
        "app/views/index.py",
        "app/controllers/",
        "app/controllers/user_controller.py",
        "app/controllers/post_controller.py",
        "config/",
        "config/database.yml",
        "README.md",
    ], {}


def _make_microservice_project():
    """构建一个微服务架构项目文件树。"""
    return [
        "services/",
        "services/auth/",
        "services/auth/Dockerfile",
        "services/auth/main.py",
        "services/api/",
        "services/api/Dockerfile",
        "services/api/main.py",
        "services/worker/",
        "services/worker/Dockerfile",
        "docker-compose.yml",
        "README.md",
    ], {}


def _make_plugin_project():
    """构建一个插件式架构项目文件树。"""
    return [
        "core/",
        "core/engine.py",
        "plugins/",
        "plugins/plugin_a.py",
        "plugins/plugin_b.py",
        "plugins/plugin_c.py",
        "extensions/",
        "extensions/ext1.py",
        "main.py",
        "README.md",
    ], {}


def _make_cli_project():
    """构建一个 CLI 工具项目文件树。"""
    return [
        "cli.py",
        "bin/",
        "bin/mytool",
        "src/commands.py",
        "README.md",
        "setup.py",
    ], {}


def _make_library_project():
    """构建一个库/SDK 项目文件树。"""
    return [
        "lib/",
        "lib/index.js",
        "lib/utils.js",
        "package.json",
        "README.md",
        ".eslintrc",
    ], {}


# ════════════════════════════════════════
# 1. CodeMetrics 数据类
# ════════════════════════════════════════
class TestCodeMetrics:
    """CodeMetrics 序列化与默认值。"""

    def test_default_values(self):
        """新建 CodeMetrics 默认值正确。"""
        m = CodeMetrics()
        assert m.total_loc == 0
        assert m.file_count == 0
        assert m.architecture_pattern == "unknown"
        assert m.complexity_score == 0.0
        assert m.quality_score == 0.0
        assert m.maintainability_index == 0.0
        assert m.code_smells == []
        assert m.largest_files == []

    def test_to_dict_contains_all_fields(self):
        """to_dict 应包含所有字段。"""
        m = CodeMetrics(
            total_loc=500,
            file_count=10,
            architecture_pattern="MVC",
            complexity_score=5.5,
            quality_score=75.0,
        )
        d = m.to_dict()
        assert d["total_loc"] == 500
        assert d["file_count"] == 10
        assert d["architecture_pattern"] == "MVC"
        assert d["complexity_score"] == 5.5
        assert d["quality_score"] == 75.0
        assert "loc_by_language" in d
        assert "code_smells" in d
        assert "largest_files" in d
        assert "maintainability_index" in d


# ════════════════════════════════════════
# 2. 代码规模分析
# ════════════════════════════════════════
class TestScaleAnalysis:
    """代码规模分析验证。"""

    def test_counts_python_files(self):
        """应正确统计 Python 文件。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert metrics.file_count > 0
        assert metrics.total_loc > 0
        assert "Python" in metrics.loc_by_language

    def test_avg_file_loc(self):
        """平均文件行数应正确计算。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        if metrics.file_count > 0:
            expected_avg = metrics.total_loc / metrics.file_count
            assert abs(metrics.avg_file_loc - expected_avg) < 0.1

    def test_max_file_loc(self):
        """最大文件行数应正确。"""
        source_code = {
            "big.py": "a = 1\nb = 2\nc = 3\n",
            "small.py": "x = 1\n",
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["big.py", "small.py"], source_code)
        assert metrics.max_file_loc == 3

    def test_largest_files_sorted(self):
        """最大文件列表应按行数降序排列。"""
        source_code = {
            "a.py": "x = 1\n",
            "b.py": "x = 1\ny = 2\nz = 3\n",
            "c.py": "x = 1\ny = 2\n",
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["a.py", "b.py", "c.py"], source_code)

        assert len(metrics.largest_files) <= 5
        if len(metrics.largest_files) >= 2:
            assert metrics.largest_files[0]["loc"] >= metrics.largest_files[1]["loc"]

    def test_empty_file_tree(self):
        """空文件树应返回零值指标。"""
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze([], {})

        assert metrics.total_loc == 0
        assert metrics.file_count == 0

    def test_string_file_tree(self):
        """字符串形式的文件树应能正确解析。"""
        tree_str = "src/main.py\nsrc/utils.py\nREADME.md\n"
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(tree_str, {})

        assert metrics.file_count >= 2  # 至少 2 个 .py 文件

    def test_loc_excludes_comments_and_blanks(self):
        """LOC 统计应排除空行和注释行。"""
        source_code = {
            "test.py": (
                "# This is a comment\n"
                "\n"
                "x = 1  # inline comment\n"
                "y = 2\n"
                "# another comment\n"
            ),
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["test.py"], source_code)

        # 有效代码行: x = 1 和 y = 2 = 2 行
        assert metrics.total_loc == 2

    def test_multiple_languages(self):
        """应正确统计多语言项目。"""
        file_tree = ["app.py", "utils.js", "main.go", "README.md"]
        source_code = {
            "app.py": "x = 1\ny = 2\n",
            "utils.js": "const x = 1;\nconst y = 2;\n",
            "main.go": "package main\nfunc main() {}\n",
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert "Python" in metrics.loc_by_language
        assert "JavaScript" in metrics.loc_by_language
        assert "Go" in metrics.loc_by_language


# ════════════════════════════════════════
# 3. 架构模式检测
# ════════════════════════════════════════
class TestArchitectureDetection:
    """架构模式检测验证。"""

    def test_detects_mvc(self):
        """应检测 MVC 架构。"""
        file_tree, _ = _make_mvc_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.architecture_pattern == "MVC"
        assert metrics.architecture_confidence > 0
        assert len(metrics.architecture_signals) > 0

    def test_detects_microservices(self):
        """应检测微服务架构。"""
        file_tree, _ = _make_microservice_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.architecture_pattern == "微服务"
        assert metrics.architecture_confidence > 0

    def test_detects_plugin_architecture(self):
        """应检测插件式架构。"""
        file_tree, _ = _make_plugin_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.architecture_pattern == "插件式"

    def test_detects_cli(self):
        """应检测 CLI 工具架构。"""
        file_tree, _ = _make_cli_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.architecture_pattern == "CLI 工具"

    def test_detects_library(self):
        """应检测库/SDK 架构。"""
        file_tree, _ = _make_library_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        # 库/SDK 或 CLI 工具（取决于信号强度）
        assert metrics.architecture_pattern in ("库/SDK", "CLI 工具")

    def test_defaults_to_monolith(self):
        """无特定架构信号时应默认为单体应用。"""
        file_tree = ["main.py", "utils.py", "README.md"]
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.architecture_pattern == "单体应用"

    def test_architecture_signals_recorded(self):
        """架构检测信号应被记录。"""
        file_tree, _ = _make_mvc_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert len(metrics.architecture_signals) > 0
        # MVC 信号应包含目录信息
        assert any("MVC" in s or "目录" in s for s in metrics.architecture_signals)


# ════════════════════════════════════════
# 4. 复杂度估算
# ════════════════════════════════════════
class TestComplexityEstimation:
    """复杂度估算验证。"""

    def test_complexity_score_in_range(self):
        """复杂度评分应在 1-10 范围内。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert 1.0 <= metrics.complexity_score <= 10.0

    def test_complexity_factors_populated(self):
        """复杂度因子应被填充。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert "total_branches" in metrics.complexity_factors
        assert "total_functions" in metrics.complexity_factors
        assert "max_nesting_depth" in metrics.complexity_factors

    def test_counts_python_branches(self):
        """应正确统计 Python 分支语句。"""
        source_code = {
            "test.py": (
                "if x > 0:\n"
                "    for i in range(10):\n"
                "        while True:\n"
                "            try:\n"
                "                pass\n"
                "            except:\n"
                "                pass\n"
            ),
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["test.py"], source_code)

        assert metrics.complexity_factors["total_branches"] >= 5

    def test_counts_python_functions(self):
        """应正确统计 Python 函数。"""
        source_code = {
            "test.py": (
                "def foo():\n"
                "    pass\n"
                "\n"
                "def bar():\n"
                "    pass\n"
                "\n"
                "def baz():\n"
                "    pass\n"
            ),
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["test.py"], source_code)

        assert metrics.complexity_factors["total_functions"] == 3

    def test_nesting_depth_python(self):
        """应正确计算 Python 嵌套深度。"""
        source_code = {
            "deep.py": (
                "def outer():\n"
                "    if True:\n"
                "        for i in range(10):\n"
                "            while True:\n"
                "                pass\n"
            ),
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["deep.py"], source_code)

        # 4 层缩进（函数体 + if + for + while）
        assert metrics.complexity_factors["max_nesting_depth"] >= 3

    def test_code_smells_detected(self):
        """应检测代码异味。"""
        # 构建大文件
        big_content = "\n".join(f"x{i} = {i}" for i in range(400))
        source_code = {"big.py": big_content}
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["big.py"], source_code)

        # 平均文件 > 300 行应触发异味
        assert len(metrics.code_smells) > 0
        assert any("文件" in s for s in metrics.code_smells)

    def test_no_smells_for_clean_code(self):
        """简洁代码不应有代码异味。"""
        source_code = {
            "clean.py": "def hello():\n    return 'world'\n",
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["clean.py"], source_code)

        assert len(metrics.code_smells) == 0


# ════════════════════════════════════════
# 5. 质量评估
# ════════════════════════════════════════
class TestQualityAssessment:
    """代码质量评估验证。"""

    def test_quality_score_in_range(self):
        """质量评分应在 0-100 范围内。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert 0 <= metrics.quality_score <= 100

    def test_test_coverage_detected(self):
        """应检测到测试文件。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert metrics.test_coverage_level != "unknown"
        assert metrics.quality_factors["test_file_count"] > 0

    def test_no_tests_detected(self):
        """无测试文件时应标记为无。"""
        file_tree = ["main.py", "utils.py", "README.md"]
        source_code = {"main.py": "x = 1\n", "utils.py": "y = 2\n"}
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert metrics.test_coverage_level == "无"

    def test_ci_cd_detected(self):
        """应检测到 CI/CD 配置。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert metrics.quality_factors.get("has_ci") is True

    def test_no_ci_cd(self):
        """无 CI/CD 配置时应标记为 False。"""
        file_tree = ["main.py", "README.md"]
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        assert metrics.quality_factors.get("has_ci") is False

    def test_documentation_ratio(self):
        """文档比例应正确计算。"""
        file_tree = ["main.py", "utils.py", "README.md", "docs.md"]
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, {})

        # 2 个文档文件 / 2 个代码文件 = 1.0
        assert metrics.documentation_ratio > 0

    def test_quality_factors_populated(self):
        """质量因子应被填充。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert "test_file_count" in metrics.quality_factors
        assert "doc_file_count" in metrics.quality_factors
        assert "has_ci" in metrics.quality_factors
        assert "has_lint_config" in metrics.quality_factors

    def test_high_quality_project_scores_well(self):
        """高质量项目应有较高质量评分。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        # 有测试、CI、文档、lint 配置 → 应得分较高
        assert metrics.quality_score > 30


# ════════════════════════════════════════
# 6. 可维护性指数
# ════════════════════════════════════════
class TestMaintainabilityIndex:
    """可维护性指数验证。"""

    def test_maintainability_in_range(self):
        """可维护性指数应在 0-100 范围内。"""
        file_tree, source_code = _make_python_project()
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        assert 0 <= metrics.maintainability_index <= 100

    def test_simple_code_high_maintainability(self):
        """简洁代码应有较高可维护性。"""
        source_code = {
            "simple.py": "def hello():\n    return 'world'\n",
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["simple.py"], source_code)

        # 简单代码：低复杂度、小文件 → 高可维护性
        assert metrics.maintainability_index > 50

    def test_complex_code_lower_maintainability(self):
        """复杂代码应有较低可维护性。"""
        # 构建高复杂度代码
        branches = "\n".join(f"    if x > {i}:" for i in range(50))
        complex_code = f"def complex():\n{branches}\n        pass\n"
        source_code = {"complex.py": complex_code}
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(["complex.py"], source_code)

        # 复杂代码可维护性应低于简单代码
        simple_metrics = analyzer.analyze(
            ["simple.py"], {"simple.py": "def f():\n    pass\n"}
        )
        assert metrics.maintainability_index <= simple_metrics.maintainability_index


# ════════════════════════════════════════
# 7. DeepExtractor 集成
# ════════════════════════════════════════
class TestDeepExtractorIntegration:
    """DeepExtractor 原始数据存储验证。"""

    def test_mock_extract_populates_file_tree(self):
        """mock 提取应填充 _last_file_tree。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo("test/repo")
        extractor.extract(repo)

        assert len(extractor._last_file_tree) > 0
        assert any("main.py" in p for p in extractor._last_file_tree)

    def test_mock_extract_populates_source_code(self):
        """mock 提取应填充 _last_source_code。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo("test/repo")
        extractor.extract(repo)

        assert len(extractor._last_source_code) > 0
        assert "setup.py" in extractor._last_source_code

    def test_parse_tree_paths(self):
        """_parse_tree_paths 应正确解析文件树文本。"""
        from src.deep_extractor import DeepExtractor

        tree_text = "📁 src/\n  📄 src/main.py\n  📄 src/utils.py\n📁 tests/\n  📄 tests/test_main.py"
        paths = DeepExtractor._parse_tree_paths(tree_text)

        assert "src/" in paths
        assert "src/main.py" in paths
        assert "src/utils.py" in paths
        assert "tests/" in paths
        assert "tests/test_main.py" in paths


# ════════════════════════════════════════
# 8. ProjectAnalysis 集成
# ════════════════════════════════════════
class TestProjectAnalysisCodeMetrics:
    """ProjectAnalysis code_metrics 字段序列化。"""

    def test_code_metrics_default_empty(self):
        """ProjectAnalysis 默认 code_metrics 为空字典。"""
        pa = ProjectAnalysis(repo_name="test/repo")
        assert pa.code_metrics == {}

    def test_code_metrics_serialized(self):
        """code_metrics 应被正确序列化到 dict。"""
        metrics = CodeMetrics(
            total_loc=500,
            file_count=10,
            architecture_pattern="MVC",
            complexity_score=5.0,
        )
        pa = ProjectAnalysis(
            repo_name="test/repo",
            code_metrics=metrics.to_dict(),
        )
        d = pa.to_dict()
        assert d["code_metrics"]["total_loc"] == 500
        assert d["code_metrics"]["architecture_pattern"] == "MVC"

    def test_code_metrics_deserialized(self):
        """code_metrics 应能从 dict 反序列化。"""
        data = {
            "repo_name": "test/repo",
            "code_metrics": {
                "total_loc": 300,
                "architecture_pattern": "微服务",
                "complexity_score": 7.5,
            },
        }
        pa = ProjectAnalysis.from_dict(data)
        assert pa.code_metrics["total_loc"] == 300
        assert pa.code_metrics["architecture_pattern"] == "微服务"
        assert pa.code_metrics["complexity_score"] == 7.5

    def test_code_metrics_roundtrip(self):
        """序列化→反序列化应保持一致。"""
        metrics = CodeMetrics(
            total_loc=1000,
            file_count=25,
            architecture_pattern="插件式",
            complexity_score=6.5,
            quality_score=80.0,
            maintainability_index=72.5,
        )
        pa = ProjectAnalysis(
            repo_name="test/repo",
            code_metrics=metrics.to_dict(),
        )
        d = pa.to_dict()
        pa2 = ProjectAnalysis.from_dict(d)

        assert pa2.code_metrics["total_loc"] == 1000
        assert pa2.code_metrics["architecture_pattern"] == "插件式"
        assert pa2.code_metrics["complexity_score"] == 6.5
        assert pa2.code_metrics["quality_score"] == 80.0


# ════════════════════════════════════════
# 9. 端到端：mock 流水线 + 代码分析
# ════════════════════════════════════════
class TestEndToEndCodeAnalysis:
    """端到端集成测试。"""

    def test_mock_pipeline_with_code_analysis(self):
        """mock 流水线应包含代码级分析。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo("test/awesome-project")
        extractor.extract(repo)

        # 使用提取的原始数据进行代码分析
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(
            file_tree=extractor._last_file_tree,
            source_code=extractor._last_source_code,
        )

        # 验证分析结果
        assert metrics.file_count > 0
        assert metrics.total_loc > 0
        assert metrics.architecture_pattern != "unknown"
        assert 1.0 <= metrics.complexity_score <= 10.0
        assert 0 <= metrics.quality_score <= 100
        assert 0 <= metrics.maintainability_index <= 100

    def test_code_metrics_attached_to_analysis(self):
        """代码指标应能附加到 ProjectAnalysis。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        repo = make_repo("test/repo")
        extractor.extract(repo)

        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(
            extractor._last_file_tree,
            extractor._last_source_code,
        )

        analysis = ProjectAnalysis(repo_name="test/repo")
        analysis.code_metrics = metrics.to_dict()

        # 验证附加成功
        assert analysis.code_metrics["file_count"] > 0
        assert analysis.code_metrics["architecture_pattern"] != "unknown"

    def test_multiple_projects_code_analysis(self):
        """多个项目的代码分析应各自独立。"""
        from tests.conftest import make_config, make_repo
        from src.deep_extractor import DeepExtractor

        config = make_config(mock_mode=True)
        extractor = DeepExtractor(config)
        analyzer = CodeAnalyzer()

        results = {}
        for name in ["test/repo-a", "test/repo-b", "test/repo-c"]:
            repo = make_repo(name)
            extractor.extract(repo)
            metrics = analyzer.analyze(
                extractor._last_file_tree,
                extractor._last_source_code,
            )
            results[name] = metrics

        # 每个项目应有独立的指标
        assert len(results) == 3
        for name, metrics in results.items():
            assert metrics.file_count > 0
            assert metrics.architecture_pattern != "unknown"

    def test_real_world_project_structure(self):
        """模拟真实项目结构的完整分析。"""
        file_tree = [
            "src/",
            "src/main.py",
            "src/api/",
            "src/api/routes.py",
            "src/api/auth.py",
            "src/models/",
            "src/models/user.py",
            "src/models/post.py",
            "src/views/",
            "src/views/templates.py",
            "src/controllers/",
            "src/controllers/user_ctrl.py",
            "tests/",
            "tests/test_api.py",
            "tests/test_models.py",
            "tests/test_views.py",
            ".github/workflows/ci.yml",
            "pyproject.toml",
            "README.md",
            "docs/",
            "docs/guide.md",
        ]
        source_code = {
            "src/main.py": (
                "from api.routes import app\n"
                "if __name__ == '__main__':\n"
                "    app.run()\n"
            ),
            "src/api/routes.py": (
                "from flask import Flask\n"
                "app = Flask(__name__)\n"
                "@app.route('/')\n"
                "def index():\n"
                "    return 'Hello'\n"
            ),
            "src/models/user.py": (
                "class User:\n"
                "    def __init__(self, name):\n"
                "        self.name = name\n"
                "    def get_name(self):\n"
                "        return self.name\n"
            ),
        }
        analyzer = CodeAnalyzer()
        metrics = analyzer.analyze(file_tree, source_code)

        # 验证各维度指标
        assert metrics.architecture_pattern == "MVC"  # 有 models/views/controllers
        assert metrics.file_count > 5
        assert metrics.total_loc > 5
        assert metrics.test_coverage_level in ("高", "中")  # 有多个测试文件
        assert metrics.quality_factors.get("has_ci") is True
        assert metrics.quality_score > 30  # 有测试+CI+文档+lint
        assert 1.0 <= metrics.complexity_score <= 10.0
        assert 0 <= metrics.maintainability_index <= 100
