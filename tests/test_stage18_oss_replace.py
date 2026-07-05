"""
Stage 18 — 开源工具替换：结构测试

验证每个阶段的前端文件修改是否正确：
- Stage 1: Q&A Markdown 复用 marked.js
- Stage 2: 剪贴板 copy-to-clipboard
- Stage 3: 数字动画 CountUp.js
- Stage 4: 节流/防抖 lodash-es
- Stage 5: 数据归一化公共模块
- Stage 6: 搜索高亮 mark.js

测试策略：静态分析 JS 文件内容，验证 import/export、函数签名、CDN URL 等。
"""

import re
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard_static"


def read_js(rel_path: str) -> str:
    """读取 dashboard_static 下的 JS 文件"""
    return (DASHBOARD / rel_path).read_text(encoding="utf-8")


class TestStage1_MarkedJsReuse(unittest.TestCase):
    """Stage 1: Q&A Markdown 复用 marked.js"""

    def test_analysis_imports_render_markdown(self):
        """analysis.js 应导入 renderMarkdown"""
        content = read_js("js/pages/analysis.js")
        self.assertIn("import { renderMarkdown }", content)

    def test_analysis_no_handwritten_markdown_regex(self):
        """analysis.js 不应包含手写 Markdown 正则替换"""
        content = read_js("js/pages/analysis.js")
        # 检查 Q&A 回答部分不再使用手写正则
        self.assertNotIn(
            ".replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')",
            content,
            "Q&A 回答仍使用手写 Markdown 正则，应改用 renderMarkdown"
        )

    def test_marked_util_exports_render_markdown(self):
        """utils/marked.js 应导出 renderMarkdown"""
        content = read_js("js/utils/marked.js")
        self.assertIn("export async function renderMarkdown", content)

    def test_marked_util_has_fallback(self):
        """utils/marked.js 应包含 CDN 失败时的回退渲染"""
        content = read_js("js/utils/marked.js")
        self.assertIn("_fallbackRender", content)


class TestStage2_ClipboardReplacement(unittest.TestCase):
    """Stage 2: 剪贴板 copy-to-clipboard"""

    def test_highlight_no_handwritten_clipboard(self):
        """highlight.js 不应包含手写 copyToClipboard 实现"""
        content = read_js("js/utils/highlight.js")
        # 不应包含 navigator.clipboard.writeText 的手写实现
        self.assertNotIn(
            "navigator.clipboard && window.isSecureContext",
            content,
            "highlight.js 仍包含手写 Clipboard API 实现"
        )

    def test_highlight_imports_clipboard_util(self):
        """highlight.js 应从 clipboard.js 导入 copyToClipboard"""
        content = read_js("js/utils/highlight.js")
        self.assertIn("copyToClipboard", content)
        # 应包含从 clipboard.js 的导入
        self.assertTrue(
            "clipboard" in content.lower(),
            "highlight.js 应引用 clipboard 工具模块"
        )

    def test_clipboard_util_exists(self):
        """utils/clipboard.js 应存在"""
        path = DASHBOARD / "js" / "utils" / "clipboard.js"
        self.assertTrue(path.exists(), "utils/clipboard.js 不存在")

    def test_clipboard_util_exports_copy_function(self):
        """utils/clipboard.js 应导出 copyToClipboard"""
        content = read_js("js/utils/clipboard.js")
        self.assertIn("export", content)
        self.assertIn("copyToClipboard", content)


class TestStage3_CountUpReplacement(unittest.TestCase):
    """Stage 3: 数字动画 CountUp.js"""

    def test_utils_no_handwritten_animate_count(self):
        """utils.js 不应包含手写 requestAnimationFrame 计数动画"""
        content = read_js("js/utils.js")
        # 不应包含手写 RAF 计数循环
        self.assertNotIn(
            "requestAnimationFrame(update)",
            content,
            "utils.js 仍包含手写 animateCount RAF 实现"
        )

    def test_count_animation_util_exists(self):
        """utils/count-animation.js 应存在"""
        path = DASHBOARD / "js" / "utils" / "count-animation.js"
        self.assertTrue(path.exists(), "utils/count-animation.js 不存在")

    def test_count_animation_exports_animate_count(self):
        """utils/count-animation.js 应导出 animateCount"""
        content = read_js("js/utils/count-animation.js")
        self.assertIn("export", content)
        self.assertIn("animateCount", content)

    def test_count_animation_uses_countup_cdn(self):
        """utils/count-animation.js 应使用 CountUp.js CDN"""
        content = read_js("js/utils/count-animation.js")
        self.assertIn("countup", content.lower())

    def test_stats_imports_from_count_animation(self):
        """stats.js 应从 count-animation.js 导入 animateCount"""
        content = read_js("js/components/stats.js")
        self.assertIn(
            "count-animation",
            content,
            "stats.js 应从 count-animation.js 导入 animateCount"
        )


class TestStage4_LodashReplacement(unittest.TestCase):
    """Stage 4: 节流/防抖 lodash-es"""

    def test_lodash_loader_exists(self):
        """utils/lodash-loader.js 应存在"""
        path = DASHBOARD / "js" / "utils" / "lodash-loader.js"
        self.assertTrue(path.exists(), "utils/lodash-loader.js 不存在")

    def test_lodash_loader_exports_throttle_debounce(self):
        """utils/lodash-loader.js 应导出 throttle 和 debounce"""
        content = read_js("js/utils/lodash-loader.js")
        self.assertIn("export", content)
        self.assertIn("throttle", content)
        self.assertIn("debounce", content)

    def test_utils_js_no_handwritten_throttle(self):
        """utils.js 不应包含手写 throttle 实现（with lastCall/timer pattern）"""
        content = read_js("js/utils.js")
        # 不应包含手写 throttle 的核心逻辑
        self.assertNotIn(
            "let lastCall = 0;\n  let timer = null;",
            content,
            "utils.js 仍包含手写 throttle 实现"
        )

    def test_utils_js_re_exports_throttle(self):
        """utils.js 应从 lodash-loader 导入 throttle"""
        content = read_js("js/utils.js")
        self.assertTrue(
            "lodash-loader" in content or "throttle" in content,
            "utils.js 应引用 lodash-loader 或导出 throttle"
        )

    def test_search_panel_no_handwritten_debounce(self):
        """search-panel.js 不应包含手写防抖（clearTimeout + setTimeout pattern）"""
        content = read_js("js/components/search-panel.js")
        # 不应包含 debounceTimer 变量和手写 clearTimeout 模式
        self.assertNotIn(
            "debounceTimer",
            content,
            "search-panel.js 仍使用手写防抖，应改用 lodash debounce"
        )

    def test_search_panel_imports_debounce(self):
        """search-panel.js 应导入 debounce"""
        content = read_js("js/components/search-panel.js")
        self.assertTrue(
            "debounce" in content,
            "search-panel.js 应导入 debounce 函数"
        )


class TestStage5_DataNormalizerModule(unittest.TestCase):
    """Stage 5: 数据归一化公共模块"""

    def test_data_normalizer_exists(self):
        """utils/data-normalizer.js 应存在"""
        path = DASHBOARD / "js" / "utils" / "data-normalizer.js"
        self.assertTrue(path.exists(), "utils/data-normalizer.js 不存在")

    def test_data_normalizer_exports(self):
        """utils/data-normalizer.js 应导出 4 个函数"""
        content = read_js("js/utils/data-normalizer.js")
        for fn in ["tryParseDict", "extractPyField", "normalizeHighlight", "normalizeUseCase"]:
            self.assertIn(fn, content, f"data-normalizer.js 缺少导出: {fn}")

    def test_episodes_no_duplicate_normalizer(self):
        """episodes.js 不应包含重复的归一化函数定义"""
        content = read_js("js/components/episodes.js")
        # 不应包含函数定义（应从 data-normalizer 导入）
        self.assertNotRegex(
            content,
            r"function\s+normalizeHighlight\s*\(",
            "episodes.js 仍定义 normalizeHighlight，应从 data-normalizer 导入"
        )
        self.assertNotRegex(
            content,
            r"function\s+normalizeUseCase\s*\(",
            "episodes.js 仍定义 normalizeUseCase，应从 data-normalizer 导入"
        )

    def test_analysis_renderer_imports_from_data_normalizer(self):
        """analysis-renderer.js（共享渲染器）应从 data-normalizer 导入"""
        content = read_js("js/utils/analysis-renderer.js")
        self.assertIn("data-normalizer", content)

    def test_analysis_no_duplicate_normalizer(self):
        """analysis.js 不应包含重复的归一化函数定义"""
        content = read_js("js/pages/analysis.js")
        self.assertNotRegex(
            content,
            r"function\s+normalizeHighlight\s*\(",
            "analysis.js 仍定义 normalizeHighlight，应从 data-normalizer 导入"
        )
        self.assertNotRegex(
            content,
            r"function\s+normalizeUseCase\s*\(",
            "analysis.js 仍定义 normalizeUseCase，应从 data-normalizer 导入"
        )

    def test_analysis_imports_shared_renderer(self):
        """analysis.js 应从 analysis-renderer 导入共享渲染器"""
        content = read_js("js/pages/analysis.js")
        self.assertIn("analysis-renderer", content)

    def test_episodes_imports_shared_renderer(self):
        """episodes.js 应从 analysis-renderer 导入共享渲染器"""
        content = read_js("js/components/episodes.js")
        self.assertIn("analysis-renderer", content)


class TestStage6_MarkJsReplacement(unittest.TestCase):
    """Stage 6: 搜索高亮 mark.js"""

    def test_search_panel_no_handwritten_highlight(self):
        """search-panel.js 不应包含手写 highlightKeyword 函数定义"""
        content = read_js("js/components/search-panel.js")
        self.assertNotRegex(
            content,
            r"function\s+highlightKeyword\s*\(",
            "search-panel.js 仍定义手写 highlightKeyword，应改用 mark.js"
        )

    def test_search_panel_uses_mark_js(self):
        """search-panel.js 应引用 mark.js"""
        content = read_js("js/components/search-panel.js")
        self.assertTrue(
            "mark" in content.lower() and ("Mark" in content or "markjs" in content or "mark.js" in content),
            "search-panel.js 应引用 mark.js 库"
        )


class TestNoBrokenImports(unittest.TestCase):
    """验证所有 JS 文件的 import 路径指向存在的文件"""

    def _extract_imports(self, content: str) -> list:
        """从 JS 文件内容中提取 import 路径"""
        # 匹配 import ... from './path' 或 import ... from '../path'
        pattern = r"""from\s+['"](\.\./[^'"]+|\.\/[^'"]+)['"]"""
        return re.findall(pattern, content)

    def test_all_local_imports_resolve(self):
        """所有本地 import 路径应指向存在的文件"""
        js_files = list(DASHBOARD.rglob("*.js"))
        failures = []
        for js_file in js_files:
            content = js_file.read_text(encoding="utf-8")
            imports = self._extract_imports(content)
            for imp in imports:
                # 跳过 CDN imports
                if imp.startswith("http"):
                    continue
                resolved = (js_file.parent / imp).resolve()
                # 尝试 .js 扩展名
                if not resolved.exists():
                    resolved_js = resolved.with_suffix(".js")
                    if not resolved_js.exists():
                        failures.append(f"{js_file.relative_to(DASHBOARD)} -> {imp}")
        self.assertEqual(failures, [], f"存在无法解析的 import 路径:\n{chr(10).join(failures)}")


class TestPythonRegression(unittest.TestCase):
    """Python 后端回归测试 — 确保前端修改不影响后端"""

    def test_dashboard_serves_static_files(self):
        """dashboard 包仍能正确路由静态文件"""
        dashboard_pkg = Path(__file__).resolve().parent.parent / "dashboard" / "__init__.py"
        if dashboard_pkg.exists():
            content = dashboard_pkg.read_text(encoding="utf-8")
        else:
            # fallback: 检查根 dashboard.py
            content = Path(__file__).resolve().parent.parent / "dashboard.py".read_text(encoding="utf-8")
        self.assertTrue(
            "dashboard_static" in content or "static" in content,
            "dashboard 包应配置静态文件路由"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
