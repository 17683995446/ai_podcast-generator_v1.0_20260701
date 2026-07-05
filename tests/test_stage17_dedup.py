"""阶段 5 测试：代码去重与规范统一。

测试覆盖：
  1. LLMClientMixin 被所有 LLM 模块使用
  2. 无 bare except 块（except Exception: 无 as e）
  3. 无 Optional[ 类型提示（统一使用 X | None）
  4. 前端 ROUTES 仅在一处定义
  5. pytest markers 正确定义
  6. llm_helper 模块功能验证
  7. LLMClientMixin 行为验证
  8. 代码规范一致性
"""
import re
import ast
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

from src.llm_helper import LLMClientMixin
from src.llm_client import build_kwargs


PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"


def _read_src_files() -> dict[str, str]:
    """读取所有 src/ 下的 .py 文件内容。"""
    files = {}
    for py in SRC_DIR.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        files[str(py.relative_to(PROJECT_ROOT))] = py.read_text("utf-8")
    return files


# ════════════════════════════════════════
# 1. LLMClientMixin 使用验证
# ════════════════════════════════════════
class TestLLMClientMixinUsage:
    """验证所有 LLM 模块都使用了 LLMClientMixin。"""

    LLM_MODULES = [
        "src/llm_script.py",
        "src/project_analyzer.py",
        "src/script_critic.py",
        "src/show_notes_generator.py",
        "src/cross_project_comparator.py",
        "src/segmented_generator.py",
        "src/qa_engine.py",
    ]

    @pytest.mark.parametrize("module_path", LLM_MODULES)
    def test_module_imports_llm_mixin(self, module_path):
        """每个 LLM 模块都应导入 LLMClientMixin。"""
        content = (PROJECT_ROOT / module_path).read_text("utf-8")
        assert "LLMClientMixin" in content, f"{module_path} 未导入 LLMClientMixin"

    @pytest.mark.parametrize("module_path", LLM_MODULES)
    def test_module_uses_init_llm(self, module_path):
        """每个 LLM 模块都应调用 self._init_llm()。"""
        content = (PROJECT_ROOT / module_path).read_text("utf-8")
        assert "_init_llm" in content, f"{module_path} 未使用 _init_llm()"

    def test_no_direct_create_llm_client_calls_in_modules(self):
        """LLM 模块不应直接调用 create_llm_client（应由 Mixin 处理）。"""
        # llm_client.py 和 llm_helper.py 可以调用，其他不行
        skip = {"src/llm_client.py", "src/llm_helper.py"}
        for path, content in _read_src_files().items():
            if path in skip:
                continue
            # 不应直接调用 create_llm_client 或 create_raw_client
            # （但可以引用 provider 层的 get_llm_provider）
            assert "create_llm_client(" not in content or "create_raw_client(" not in content or "def create_" in content, \
                f"{path} 直接调用了 create_llm_client/create_raw_client，应使用 LLMClientMixin"


# ════════════════════════════════════════
# 2. 无 bare except 块
# ════════════════════════════════════════
class TestNoBareExcept:
    """验证 src/ 下无 bare except Exception: 块（无 as e）。"""

    def test_no_bare_except_exception_pass(self):
        """不应有 'except Exception: pass'（完全吞掉错误）。"""
        for path, content in _read_src_files().items():
            # 匹配 except Exception: 后面紧跟 pass（允许中间有注释）
            lines = content.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "except Exception:":
                    # 检查下一个非空行是否是 pass
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_stripped = lines[j].strip()
                        if next_stripped and not next_stripped.startswith("#"):
                            assert next_stripped != "pass", \
                                f"{path}:{i+1} 有 'except Exception: pass' (bare except + pass)"
                            break

    def test_no_bare_except_without_as_e(self):
        """不应有 'except Exception:' 不带 'as e' 的块。"""
        for path, content in _read_src_files().items():
            lines = content.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped == "except Exception:":
                    pytest.fail(
                        f"{path}:{i+1} 有 'except Exception:' 不带 'as e'，"
                        f"应改为 'except Exception as e:' 并添加日志"
                    )


# ════════════════════════════════════════
# 3. 无 Optional[ 类型提示
# ════════════════════════════════════════
class TestNoOptionalTypeHints:
    """验证 src/ 下无 Optional[ 类型提示（统一使用 X | None）。"""

    def test_no_optional_in_src(self):
        """src/ 下不应使用 Optional[ 类型提示。"""
        for path, content in _read_src_files().items():
            assert "Optional[" not in content, \
                f"{path} 使用了 Optional[ 类型提示，应改为 X | None"


# ════════════════════════════════════════
# 4. 前端 ROUTES 单一定义
# ════════════════════════════════════════
class TestFrontendRoutesSingleDefinition:
    """验证前端 ROUTES 仅在 router.js 中定义。"""

    def test_routes_only_in_router(self):
        """ROUTES 仅在 router.js 中定义。"""
        frontend_dir = PROJECT_ROOT / "dashboard_static" / "js"
        routes_files = []
        for js in frontend_dir.rglob("*.js"):
            content = js.read_text("utf-8")
            if re.search(r'\bROUTES\s*=\s*\{', content) or re.search(r'export\s+const\s+ROUTES', content):
                routes_files.append(str(js.relative_to(PROJECT_ROOT)))
        assert len(routes_files) == 1, \
            f"ROUTES 在 {len(routes_files)} 个文件中定义: {routes_files}，应仅在一处定义"
        assert "router.js" in routes_files[0], \
            f"ROUTES 应在 router.js 中定义，实际在 {routes_files[0]}"


# ════════════════════════════════════════
# 5. pytest markers 正确定义
# ════════════════════════════════════════
class TestPytestMarkers:
    """验证 pytest.ini 中定义了正确的 markers。"""

    def test_pytest_ini_exists(self):
        """pytest.ini 存在。"""
        assert (PROJECT_ROOT / "pytest.ini").exists()

    def test_markers_defined(self):
        """pytest.ini 定义了 unit/integration/system markers。"""
        content = (PROJECT_ROOT / "pytest.ini").read_text("utf-8")
        assert "unit" in content
        assert "integration" in content
        assert "system" in content


# ════════════════════════════════════════
# 6. LLMClientMixin 功能验证
# ════════════════════════════════════════
class TestLLMClientMixinFunctionality:
    """LLMClientMixin 行为测试。"""

    def test_mixin_can_be_inherited(self):
        """LLMClientMixin 可被继承。"""

        class TestModule(LLMClientMixin):
            def __init__(self, config):
                self._init_llm(config)
                self.cfg = config.get("llm", {})

        config = {"llm": {"model": "test"}, "api_keys": {"llm": "key"}}
        with patch("src.llm_helper.create_llm_client") as mock_create:
            mock_create.return_value = (MagicMock(), {"api_key": "key", "model": "test", "enable_thinking": False})
            module = TestModule(config)
            assert module.api_key == "key"
            assert module.enable_thinking is False
            assert module.cfg["model"] == "test"

    def test_mixin_init_raw(self):
        """_init_llm(raw=True) 使用 create_raw_client。"""
        class TestModule(LLMClientMixin):
            def __init__(self, config):
                self._init_llm(config, raw=True)

        config = {"llm": {"model": "test"}, "api_keys": {"llm": "key"}}
        with patch("src.llm_helper.create_raw_client") as mock_create:
            mock_create.return_value = (MagicMock(), {"api_key": "key", "model": "test", "enable_thinking": None})
            module = TestModule(config)
            assert module.api_key == "key"
            mock_create.assert_called_once()

    def test_mixin_init_without_key(self):
        """无 API Key 时 client 为 None 但不崩溃。"""
        class TestModule(LLMClientMixin):
            def __init__(self, config):
                self._init_llm(config)

        config = {"llm": {"model": "test"}, "api_keys": {"llm": ""}}
        with patch("src.llm_helper.create_llm_client") as mock_create:
            mock_create.return_value = (None, {"api_key": "", "model": "test", "enable_thinking": None})
            module = TestModule(config)
            assert module.api_key == ""
            assert module.client is None

    def test_mixin_build_llm_kwargs(self):
        """build_llm_kwargs 委托给 build_kwargs。"""
        class TestModule(LLMClientMixin):
            def __init__(self, config):
                self._init_llm(config)

        config = {"llm": {"model": "test"}, "api_keys": {"llm": "key"}}
        with patch("src.llm_helper.create_llm_client") as mock_create:
            mock_create.return_value = (MagicMock(), {"api_key": "key", "model": "test-model", "enable_thinking": False})
            module = TestModule(config)
            kwargs = module.build_llm_kwargs(messages=[{"role": "user", "content": "hi"}], temperature=0.8)
            assert kwargs["model"] == "test-model"
            assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
            assert kwargs["temperature"] == 0.8


# ════════════════════════════════════════
# 7. LLMClientMixin 属性一致性
# ════════════════════════════════════════
class TestLLMClientMixinAttributes:
    """验证 Mixin 设置的属性与原代码一致。"""

    def test_mixin_sets_client(self):
        """Mixin 设置 self.client。"""
        class TestModule(LLMClientMixin):
            pass
        module = TestModule()
        assert hasattr(module, "client")
        assert module.client is None  # 默认值

    def test_mixin_sets_meta(self):
        """Mixin 设置 self.meta。"""
        class TestModule(LLMClientMixin):
            pass
        module = TestModule()
        assert hasattr(module, "meta")
        assert module.meta == {}  # 默认值

    def test_mixin_sets_api_key(self):
        """Mixin 设置 self.api_key。"""
        class TestModule(LLMClientMixin):
            pass
        module = TestModule()
        assert hasattr(module, "api_key")
        assert module.api_key == ""  # 默认值

    def test_mixin_sets_enable_thinking(self):
        """Mixin 设置 self.enable_thinking。"""
        class TestModule(LLMClientMixin):
            pass
        module = TestModule()
        assert hasattr(module, "enable_thinking")

    def test_mixin_sets_llm_cfg(self):
        """Mixin 设置 self.llm_cfg。"""
        class TestModule(LLMClientMixin):
            pass
        module = TestModule()
        assert hasattr(module, "llm_cfg")
        assert module.llm_cfg == {}  # 默认值


# ════════════════════════════════════════
# 8. 代码规范一致性
# ════════════════════════════════════════
class TestCodeStandardsConsistency:
    """验证代码规范一致性。"""

    def test_all_src_files_use_future_annotations(self):
        """所有 src/ 文件使用 from __future__ import annotations。"""
        for path, content in _read_src_files().items():
            if "__init__" in path:
                continue  # __init__.py 可以不导入
            assert "from __future__ import annotations" in content, \
                f"{path} 缺少 'from __future__ import annotations'"

    def test_all_src_files_use_get_logger(self):
        """所有 src/ 文件使用 get_logger 而非 print。"""
        for path, content in _read_src_files().items():
            if "__init__" in path or "logger.py" in path:
                continue
            # 不应有裸 print() 调用（除特殊场景）
            lines = content.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                # 允许的情况：注释中的 print、sys.stdout.write、字符串中的 print
                if stripped.startswith("#"):
                    continue
                if "sys.stdout" in stripped:
                    continue
                # 检查是否有裸 print() 调用
                if re.match(r'^print\s*\(', stripped):
                    pytest.fail(f"{path}:{i+1} 使用了 print()，应使用 logger")

    def test_llm_helper_module_exists(self):
        """llm_helper.py 模块存在。"""
        assert (SRC_DIR / "llm_helper.py").exists()

    def test_pipeline_package_exists(self):
        """pipeline/ 包存在。"""
        assert (SRC_DIR / "pipeline").is_dir()
        assert (SRC_DIR / "pipeline" / "__init__.py").exists()

    def test_providers_package_exists(self):
        """providers/ 包存在。"""
        assert (SRC_DIR / "providers").is_dir()
        assert (SRC_DIR / "providers" / "__init__.py").exists()

    def test_config_defaults_module_exists(self):
        """config_defaults.py 模块存在。"""
        assert (SRC_DIR / "config_defaults.py").exists()

    def test_config_accessor_module_exists(self):
        """config_accessor.py 模块存在。"""
        assert (SRC_DIR / "config_accessor.py").exists()

    def test_main_py_uses_pipeline_class(self):
        """main.py 使用 Pipeline 类而非内联流水线。"""
        content = (PROJECT_ROOT / "main.py").read_text("utf-8")
        assert "from src.pipeline import Pipeline" in content
        assert "Pipeline(" in content

    def test_main_py_no_emit_progress(self):
        """main.py 不再包含 _emit_progress 函数。"""
        content = (PROJECT_ROOT / "main.py").read_text("utf-8")
        assert "def _emit_progress" not in content

    def test_main_py_no_private_attribute_access(self):
        """main.py 不直接访问私有属性。"""
        content = (PROJECT_ROOT / "main.py").read_text("utf-8")
        assert "._last_" not in content
        assert "._events" not in content
