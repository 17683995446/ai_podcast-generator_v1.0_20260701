"""
Stage 20: 播放器连续点击防抖修复验证

验证 player.js 中防止连续乱点导致播放混乱的三重防护机制：
  1. isLoading — playEpisode 执行期间拒绝重入
  2. playRequestId — 代际计数器，await 后若已被后续调用超越则放弃
  3. playPending — play() 已调用但 play 事件未触发时阻止再次 play()

同时验证 rAF 泄漏修复和 fallback 路径的同步防护。
"""
import os
import re
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(PROJECT_ROOT, 'dashboard_static', 'js')
PLAYER_JS = os.path.join(JS_DIR, 'player.js')


def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return ''


# ═══════════════════════════════════════════════════════════════
# 防护机制存在性验证
# ═══════════════════════════════════════════════════════════════
class TestPlayerGuardVariables(unittest.TestCase):
    """验证播放器防抖所需的状态变量已声明"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_isLoading_variable_declared(self):
        """isLoading 变量必须声明，用于防止 playEpisode 重入"""
        self.assertIn('let isLoading = false', self.code,
                      "isLoading 变量必须声明并初始化为 false")

    def test_playRequestId_variable_declared(self):
        """playRequestId 代际计数器必须声明"""
        self.assertIn('let playRequestId = 0', self.code,
                      "playRequestId 变量必须声明并初始化为 0")

    def test_playPending_variable_declared(self):
        """playPending 标志必须声明，防止双重播放"""
        self.assertIn('let playPending = false', self.code,
                      "playPending 变量必须声明并初始化为 false")

    def test_globalRafId_variable_declared(self):
        """globalRafId 必须声明，用于卸载 Howl 时取消进度轮询"""
        self.assertIn('let globalRafId = null', self.code,
                      "globalRafId 变量必须声明并初始化为 null")


# ═══════════════════════════════════════════════════════════════
# playEpisode 重入防护验证
# ═══════════════════════════════════════════════════════════════
class TestPlayEpisodeReentryGuard(unittest.TestCase):
    """验证 playEpisode 函数的重入防护逻辑"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_play_episode_checks_isLoading_at_entry(self):
        """playEpisode 入口处必须检查 isLoading 并提前返回"""
        # 找到 playEpisode 函数体
        match = re.search(r'export\s+async\s+function\s+playEpisode.*?\{', self.code, re.DOTALL)
        self.assertIsNotNone(match, "playEpisode 函数必须存在")
        # 取函数体前 200 字符检查
        func_body_start = match.end()
        entry_code = self.code[func_body_start:func_body_start + 200]
        self.assertIn('if (isLoading) return', entry_code,
                      "playEpisode 必须在入口处检查 isLoading 并提前返回")

    def test_play_episode_uses_playRequestId_after_await(self):
        """playEpisode 在 await 后必须使用 playRequestId 检查是否被超越"""
        self.assertIn('const myRequestId = ++playRequestId', self.code,
                      "playEpisode 必须分配 myRequestId")
        self.assertIn('if (myRequestId !== playRequestId)', self.code,
                      "playEpisode 必须在 await 后检查 myRequestId 是否仍为当前请求")

    def test_play_episode_sets_isLoading_for_new_episode(self):
        """playEpisode 切换新节目前必须设置 isLoading = true"""
        self.assertIn('isLoading = true', self.code,
                      "playEpisode 必须在切换新节目前设置 isLoading = true")

    def test_play_episode_has_timeout_fallback(self):
        """playEpisode 必须有超时兜底，防止 play 事件未触发导致死锁"""
        self.assertIn('setTimeout', self.code,
                      "playEpisode 必须有 setTimeout 超时兜底")
        # 检查超时后会清除 isLoading
        timeout_section = re.search(r'setTimeout\(\(\)\s*=>\s*\{[^}]+isLoading\s*=\s*false', self.code)
        self.assertIsNotNone(timeout_section,
                             "setTimeout 中必须清除 isLoading")

    def test_play_episode_checks_playPending_for_same_episode(self):
        """同一节目切换播放/暂停时必须检查 playPending"""
        # 验证同一节目路径中有 playPending 检查
        same_ep_section = re.search(
            r'currentEp\.url\s*===\s*url.*?if\s*\(playPending\)\s*return',
            self.code, re.DOTALL
        )
        self.assertIsNotNone(same_ep_section,
                             "同一节目切换时必须检查 playPending 并提前返回")


# ═══════════════════════════════════════════════════════════════
# playPending 状态管理验证
# ═══════════════════════════════════════════════════════════════
class TestPlayPendingManagement(unittest.TestCase):
    """验证 playPending 标志在所有关键路径中正确设置和清除"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_play_pending_set_before_howl_play(self):
        """调用 howl.play() 前必须设置 playPending = true"""
        # 在 playEpisode 中
        match = re.search(r'playPending\s*=\s*true;\s*\n\s*howl\.play\(\)', self.code)
        self.assertIsNotNone(match,
                             "playEpisode 中 howl.play() 前必须设置 playPending = true")

    def test_play_pending_cleared_on_play_event(self):
        """Howl 'play' 事件中必须清除 playPending"""
        play_event = re.search(r"newHowl\.on\('play'.*?playPending\s*=\s*false", self.code, re.DOTALL)
        self.assertIsNotNone(play_event,
                             "Howl 'play' 事件中必须清除 playPending = false")

    def test_play_pending_cleared_on_loaderror(self):
        """Howl 'loaderror' 事件中必须清除 playPending"""
        loaderror_event = re.search(r"newHowl\.on\('loaderror'.*?playPending\s*=\s*false", self.code, re.DOTALL)
        self.assertIsNotNone(loaderror_event,
                             "Howl 'loaderror' 事件中必须清除 playPending = false")

    def test_play_pending_cleared_on_playerror(self):
        """Howl 'playerror' 事件中必须清除 playPending"""
        playerror_event = re.search(r"newHowl\.on\('playerror'.*?playPending\s*=\s*false", self.code, re.DOTALL)
        self.assertIsNotNone(playerror_event,
                             "Howl 'playerror' 事件中必须清除 playPending = false")

    def test_is_loading_cleared_on_play_event(self):
        """Howl 'play' 事件中必须清除 isLoading"""
        play_event = re.search(r"newHowl\.on\('play'.*?isLoading\s*=\s*false", self.code, re.DOTALL)
        self.assertIsNotNone(play_event,
                             "Howl 'play' 事件中必须清除 isLoading = false")


# ═══════════════════════════════════════════════════════════════
# rAF 泄漏修复验证
# ═══════════════════════════════════════════════════════════════
class TestRafLeakFix(unittest.TestCase):
    """验证 requestAnimationFrame 在卸载 Howl 时被正确取消"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_no_closure_raf_variable(self):
        """createHowl 内不应有局部 rafId 变量（改为全局 globalRafId）"""
        # 不应有 "let rafId = null" 模式
        self.assertNotIn('let rafId = null', self.code,
                         "createHowl 内不应有局部 rafId 变量，应使用全局 globalRafId")

    def test_global_raf_used_in_update_progress(self):
        """updateProgress 应使用 globalRafId"""
        self.assertIn('globalRafId = requestAnimationFrame(updateProgress)', self.code,
                      "updateProgress 应使用 globalRafId")

    def test_raf_cancelled_before_unload(self):
        """卸载 Howl 前必须取消 globalRafId"""
        # 在 playEpisode 中卸载 Howl 前
        unload_section = re.search(
            r'if\s*\(globalRafId\)\s*\{[^}]*cancelAnimationFrame\(globalRafId\)',
            self.code
        )
        self.assertIsNotNone(unload_section,
                             "卸载 Howl 前必须检查并取消 globalRafId")

    def test_raf_cancelled_in_close_button(self):
        """关闭按钮中必须取消 globalRafId"""
        close_section = re.search(
            r"player-close-btn.*?if\s*\(globalRafId\).*?cancelAnimationFrame",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(close_section,
                             "关闭按钮处理中必须取消 globalRafId")


# ═══════════════════════════════════════════════════════════════
# 底部播放器按钮防抖验证
# ═══════════════════════════════════════════════════════════════
class TestBottomPlayerButtonDebounce(unittest.TestCase):
    """验证底部播放器的播放/暂停按钮有防抖保护"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_bottom_play_btn_checks_play_pending(self):
        """底部播放器按钮点击时必须检查 playPending"""
        # 第一个 play-btn 事件监听器（Howler 路径）
        btn_handler = re.search(
            r"player-play-btn.*?addEventListener\('click'.*?if\s*\(!howl\s*\|\|\s*playPending",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(btn_handler,
                             "底部播放器按钮必须检查 playPending")

    def test_bottom_play_btn_checks_isLoading(self):
        """底部播放器按钮点击时必须检查 isLoading"""
        btn_handler = re.search(
            r"player-play-btn.*?addEventListener\('click'.*?isLoading",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(btn_handler,
                             "底部播放器按钮必须检查 isLoading")

    def test_bottom_play_btn_sets_play_pending(self):
        """底部播放器按钮调用 play() 前必须设置 playPending"""
        # 找到按钮处理器中 play() 调用
        btn_handler = re.search(
            r"player-play-btn.*?addEventListener\('click'.*?playPending\s*=\s*true.*?howl\.play\(\)",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(btn_handler,
                             "底部播放器按钮调用 howl.play() 前必须设置 playPending = true")


# ═══════════════════════════════════════════════════════════════
# Fallback 路径同步防护验证
# ═══════════════════════════════════════════════════════════════
class TestFallbackPathGuards(unittest.TestCase):
    """验证 HTML5 Audio 降级路径也有同步防护"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_fallback_play_checks_play_pending_for_same_episode(self):
        """fallbackPlay 同一节目路径必须检查 playPending"""
        fallback_section = re.search(
            r"fallbackPlay.*?currentEp\.url\s*===\s*url.*?if\s*\(playPending\)\s*return",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(fallback_section,
                             "fallbackPlay 同一节目路径必须检查 playPending")

    def test_fallback_play_sets_isLoading_for_new_episode(self):
        """fallbackPlay 新节目前必须设置 isLoading"""
        fallback_section = re.search(
            r"fallbackPlay.*?isLoading\s*=\s*true",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(fallback_section,
                             "fallbackPlay 新节目前必须设置 isLoading = true")

    def test_fallback_audio_play_event_clears_playPending(self):
        """fallbackAudio play 事件必须清除 playPending"""
        play_event = re.search(
            r"fallbackAudio\.addEventListener\('play'.*?playPending\s*=\s*false",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(play_event,
                             "fallbackAudio 'play' 事件中必须清除 playPending = false")

    def test_fallback_play_btn_checks_play_pending(self):
        """fallback 播放按钮必须检查 playPending"""
        btn_handler = re.search(
            r"绑定控制按钮到 fallback audio.*?if\s*\(!fallbackAudio\s*\|\|\s*playPending",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(btn_handler,
                             "fallback 播放按钮必须检查 playPending")


# ═══════════════════════════════════════════════════════════════
# 关闭按钮状态重置验证
# ═══════════════════════════════════════════════════════════════
class TestCloseButtonStateReset(unittest.TestCase):
    """验证关闭按钮正确重置所有新增状态变量"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_howler_close_resets_isLoading(self):
        """Howler 路径关闭按钮必须重置 isLoading"""
        # 第一个 close-btn handler
        close_section = re.search(
            r"player-close-btn.*?isLoading\s*=\s*false",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(close_section,
                             "Howler 路径关闭按钮必须重置 isLoading = false")

    def test_howler_close_resets_playPending(self):
        """Howler 路径关闭按钮必须重置 playPending"""
        close_section = re.search(
            r"player-close-btn.*?playPending\s*=\s*false",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(close_section,
                             "Howler 路径关闭按钮必须重置 playPending = false")

    def test_howler_close_increments_playRequestId(self):
        """Howler 路径关闭按钮必须递增 playRequestId（使过期请求失效）"""
        close_section = re.search(
            r"player-close-btn.*?playRequestId\+\+",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(close_section,
                             "Howler 路径关闭按钮必须递增 playRequestId")

    def test_fallback_close_resets_state(self):
        """fallback 路径关闭按钮必须重置 isLoading 和 playPending"""
        # 第二个 close-btn handler（fallback 路径）
        fallback_close = re.search(
            r"绑定控制按钮到 fallback audio.*?player-close-btn.*?isLoading\s*=\s*false.*?playPending\s*=\s*false",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(fallback_close,
                             "fallback 路径关闭按钮必须重置 isLoading 和 playPending")


# ═══════════════════════════════════════════════════════════════
# Howl 卸载安全性验证
# ═══════════════════════════════════════════════════════════════
class TestHowlUnloadSafety(unittest.TestCase):
    """验证卸载 Howl 时的安全性（防止状态不一致）"""

    def setUp(self):
        self.code = read_file(PLAYER_JS)

    def test_howl_set_to_null_after_unload(self):
        """卸载 Howl 后必须将 howl 设为 null"""
        self.assertIn('howl = null', self.code,
                      "卸载 Howl 后必须将 howl 设为 null，防止引用已卸载的实例")

    def test_is_playing_reset_before_new_howl(self):
        """创建新 Howl 前必须重置 isPlaying"""
        # 在 playEpisode 中，unload 之后、createHowl 之前
        reset_section = re.search(
            r"howl\.unload\(\).*?isPlaying\s*=\s*false.*?createHowl",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(reset_section,
                             "卸载旧 Howl 后、创建新 Howl 前必须重置 isPlaying = false")

    def test_play_pending_reset_before_new_howl(self):
        """创建新 Howl 前必须重置 playPending"""
        reset_section = re.search(
            r"howl\.unload\(\).*?playPending\s*=\s*false.*?createHowl",
            self.code, re.DOTALL
        )
        self.assertIsNotNone(reset_section,
                             "卸载旧 Howl 后、创建新 Howl 前必须重置 playPending = false")


if __name__ == '__main__':
    unittest.main()
