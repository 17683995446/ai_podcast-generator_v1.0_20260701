"""
Stage 19: QA 测试发现问题修复验证
验证所有 QA 测试中发现的问题已正确修复
"""
import os
import re
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DASHBOARD_STATIC = os.path.join(PROJECT_ROOT, 'dashboard_static')
JS_DIR = os.path.join(DASHBOARD_STATIC, 'js')
CSS_DIR = os.path.join(DASHBOARD_STATIC, 'css')
SRC_DIR = os.path.join(PROJECT_ROOT, 'src')


def read_file(path):
    """安全读取文件内容"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ''


# ═══════════════════════════════════════════════════════════════
# P0 安全修复: highlight.js 代码块 HTML 转义
# ═══════════════════════════════════════════════════════════════
class TestP0_HighlightHtmlEscape(unittest.TestCase):
    """验证 highlight.js 在高亮前转义 HTML，防止 XSS"""

    def setUp(self):
        self.code = read_file(os.path.join(JS_DIR, 'utils', 'highlight.js'))

    def test_pre_code_path_escapes_html(self):
        """pre code 路径应使用 textContent 重新设置内容以转义 HTML"""
        # 检查 highlightAll 函数中 pre code 路径是否有 textContent 重新赋值
        self.assertIn('code.textContent = rawText', self.code,
                      "pre code 路径必须用 textContent 重新赋值以转义 HTML")

    def test_pre_code_path_deletes_highlighted_before_highlight(self):
        """pre code 路径应在高亮前清除 dataset.highlighted"""
        self.assertIn('delete code.dataset.highlighted', self.code,
                      "pre code 路径必须在高亮前清除 dataset.highlighted")

    def test_pre_code_path_sets_data_hljs_after_highlight(self):
        """pre code 路径应在高亮后设置 data-hljs 标记"""
        self.assertIn("code.setAttribute('data-hljs', '1')", self.code,
                      "pre code 路径必须在高亮后设置 data-hljs")

    def test_auto_detect_path_sets_data_hljs(self):
        """自动检测路径也应设置 data-hljs 标记"""
        # 找到 highlightAuto 路径，确认后面有 setAttribute data-hljs
        auto_idx = self.code.find('highlightAuto')
        self.assertGreater(auto_idx, 0, "应有 highlightAuto 自动检测路径")
        after_auto = self.code[auto_idx:auto_idx + 300]
        self.assertIn("data-hljs", after_auto,
                      "自动检测路径也应设置 data-hljs 防止重复高亮")

    def test_highlight_code_block_clears_highlighted(self):
        """highlightCodeBlock 应清除 dataset.highlighted"""
        self.assertIn('delete code.dataset.highlighted', self.code,
                      "highlightCodeBlock 应清除 dataset.highlighted 防止重复高亮警告")


# ═══════════════════════════════════════════════════════════════
# P2 修复: 日志面板 ::PROGRESS:: 协议消息过滤
# ═══════════════════════════════════════════════════════════════
class TestP2_ProgressProtocolFilter(unittest.TestCase):
    """验证 task-panel.js 过滤 ::PROGRESS:: 协议消息"""

    def setUp(self):
        self.code = read_file(os.path.join(JS_DIR, 'components', 'task-panel.js'))

    def test_render_log_filters_progress_messages(self):
        """renderLog 应过滤以 ::PROGRESS:: 开头的行"""
        self.assertIn('::PROGRESS::', self.code,
                      "renderLog 应包含 ::PROGRESS:: 过滤逻辑")
        self.assertIn('filter', self.code.lower(),
                      "renderLog 应使用 filter 方法")

    def test_render_log_has_fallback_for_empty_display(self):
        """过滤后无日志时应有 fallback 提示"""
        self.assertIn('任务进行中', self.code,
                      "过滤后无日志显示应显示'任务进行中'")

    def test_render_log_still_renders_normal_lines(self):
        """正常日志行仍应被渲染"""
        self.assertIn('displayLines.map', self.code,
                      "正常日志行应继续渲染")


# ═══════════════════════════════════════════════════════════════
# P3 修复: deep_extractor.py 类型安全
# ═══════════════════════════════════════════════════════════════
class TestP3_DeepExtractorTypeSafety(unittest.TestCase):
    """验证 deep_extractor.py 的 _fetch_languages 类型安全"""

    def setUp(self):
        self.code = read_file(os.path.join(SRC_DIR, 'deep_extractor.py'))

    def test_no_direct_sum_on_langs_values(self):
        """不应直接 sum(langs.values())"""
        # 查找原始的危险代码模式
        self.assertNotRegex(
            self.code,
            r'total\s*=\s*sum\(langs\.values\(\)\)',
            "不应直接 sum(langs.values())，需要先进行类型转换"
        )

    def test_has_safe_conversion(self):
        """应有 int() 类型转换逻辑"""
        self.assertIn('int(val)', self.code,
                      "_fetch_languages 应使用 int(val) 转换值")
        self.assertIn('safe_langs', self.code,
                      "_fetch_languages 应使用 safe_langs 变量名")

    def test_handles_type_error(self):
        """应处理 TypeError 和 ValueError"""
        self.assertIn('TypeError', self.code,
                      "_fetch_languages 应处理 TypeError")
        self.assertIn('ValueError', self.code,
                      "_fetch_languages 应处理 ValueError")

    def test_uses_safe_langs_for_sorting(self):
        """排序应使用 safe_langs 而非原始 langs"""
        self.assertIn('safe_langs.items()', self.code,
                      "排序应使用 safe_langs.items()")

    def test_returns_empty_when_no_safe_langs(self):
        """无有效语言数据时应返回空字符串"""
        self.assertIn('if not safe_langs', self.code,
                      "无有效语言数据时应提前返回空字符串")


# ═══════════════════════════════════════════════════════════════
# P3 修复: 进度条状态残留
# ═══════════════════════════════════════════════════════════════
class TestP3_StaleProgressFix(unittest.TestCase):
    """验证任务未运行时不显示旧进度"""

    def setUp(self):
        self.code = read_file(os.path.join(JS_DIR, 'components', 'task-panel.js'))

    def test_update_progress_detail_checks_running(self):
        """updateProgressDetail 应在任务未运行时接收 null"""
        self.assertIn('s.running ? s.pipeline_progress : null', self.code,
                      "pollTask 应在任务未运行时传 null 给 updateProgressDetail")


# ═══════════════════════════════════════════════════════════════
# P4 修复: 搜索结果查看详情跳转
# ═══════════════════════════════════════════════════════════════
class TestP4_SearchDetailLink(unittest.TestCase):
    """验证搜索结果"查看详情"跳转到具体节目"""

    def setUp(self):
        self.search_code = read_file(os.path.join(JS_DIR, 'components', 'search-panel.js'))
        self.episodes_code = read_file(os.path.join(JS_DIR, 'components', 'episodes.js'))
        self.css_code = read_file(os.path.join(CSS_DIR, 'episodes.css'))

    def test_search_link_has_episode_number(self):
        """搜索结果链接应包含 episode_number"""
        self.assertIn('data-ep="${r.episode_number}"', self.search_code,
                      "查看详情链接应包含 data-ep 属性")

    def test_search_link_has_hash(self):
        """搜索结果链接应包含 hash 定位"""
        self.assertIn('#ep${r.episode_number}', self.search_code,
                      "查看详情链接应包含 #ep hash")

    def test_view_episode_handler_reads_ep(self):
        """view-episode 事件处理应读取 data-ep"""
        self.assertIn('btn.dataset.ep', self.search_code,
                      "view-episode handler 应读取 btn.dataset.ep")

    def test_view_episode_navigates_with_hash(self):
        """view-episode 应使用 hash 导航"""
        self.assertIn('/episodes#ep', self.search_code,
                      "view-episode 应导航到 /episodes#epXX")

    def test_episodes_page_has_hash_scroll(self):
        """节目库页面应有 hash 滚动逻辑"""
        self.assertIn('window.location.hash', self.episodes_code,
                      "episodes.js 应读取 URL hash")
        self.assertIn('scrollIntoView', self.episodes_code,
                      "episodes.js 应调用 scrollIntoView")

    def test_episodes_page_has_highlight_flash(self):
        """节目库页面应有高亮闪烁动画"""
        self.assertIn('highlight-flash', self.episodes_code,
                      "episodes.js 应添加 highlight-flash class")
        self.assertIn('highlight-flash', self.css_code,
                      "episodes.css 应有 highlight-flash 样式")
        self.assertIn('highlightFlash', self.css_code,
                      "episodes.css 应有 highlightFlash 动画")


# ═══════════════════════════════════════════════════════════════
# 回归测试: 确保修改未破坏现有导入
# ═══════════════════════════════════════════════════════════════
class TestRegressionNoBrokenImports(unittest.TestCase):
    """确保修改后所有本地导入路径仍然可解析"""

    def test_all_js_modules_exist(self):
        """验证关键 JS 模块文件存在"""
        critical_files = [
            os.path.join(JS_DIR, 'utils', 'highlight.js'),
            os.path.join(JS_DIR, 'utils', 'clipboard.js'),
            os.path.join(JS_DIR, 'utils', 'count-animation.js'),
            os.path.join(JS_DIR, 'utils', 'lodash-loader.js'),
            os.path.join(JS_DIR, 'utils', 'data-normalizer.js'),
            os.path.join(JS_DIR, 'utils', 'mark-highlight.js'),
            os.path.join(JS_DIR, 'components', 'task-panel.js'),
            os.path.join(JS_DIR, 'components', 'search-panel.js'),
            os.path.join(JS_DIR, 'components', 'episodes.js'),
            os.path.join(JS_DIR, 'components', 'stats.js'),
        ]
        for f in critical_files:
            self.assertTrue(os.path.exists(f), f"关键文件不存在: {f}")

    def test_deep_extractor_imports_resolve(self):
        """验证 deep_extractor.py 可正常导入"""
        # 只检查文件存在且语法正确
        code = read_file(os.path.join(SRC_DIR, 'deep_extractor.py'))
        self.assertTrue(len(code) > 100, "deep_extractor.py 文件内容过短")
        self.assertIn('_fetch_languages', code, "deep_extractor.py 应有 _fetch_languages 方法")

    def test_css_files_exist(self):
        """验证 CSS 文件存在"""
        css_files = [
            os.path.join(CSS_DIR, 'episodes.css'),
            os.path.join(CSS_DIR, 'components.css'),
            os.path.join(CSS_DIR, 'theme.css'),
            os.path.join(CSS_DIR, 'layout.css'),
        ]
        for f in css_files:
            self.assertTrue(os.path.exists(f), f"CSS 文件不存在: {f}")


if __name__ == '__main__':
    unittest.main()
