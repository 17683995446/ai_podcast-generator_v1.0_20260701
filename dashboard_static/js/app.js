// ════════════════════════════════════════
// app.js — 全局 Shell：初始化主题 + SPA 路由 + 持久播放器 + UI 增强
// 在每个 HTML 页面中通过 <script type="module" src="/js/app.js"> 加载
// ════════════════════════════════════════
import { initTheme } from './theme.js';
import { initRouter } from './router.js';
import { initPlayer } from './player.js';
import { throttle } from './utils/lodash-loader.js';

// ════════════════════════════════════════
// WebView 检测 — 尽早执行
// 在 WebView（如 TRAE App 内置浏览器）中，env(safe-area-inset-bottom)
// 通常返回 0，但 App 原生底栏仍会遮挡页面底部内容。
// 检测到 WebView 后添加 .in-webview 类，CSS 通过 --safe-bottom 追加偏移。
// ════════════════════════════════════════
function detectWebView() {
  const ua = navigator.userAgent || '';
  // Android WebView: UA 中包含 "; wv)" 标记
  const isAndroidWV = /; wv\)/i.test(ua);
  // iOS WebView: UA 中含 iPhone/iPad 但不含 "Safari/"
  const isIOSWV = /(iphone|ipad|ipod)/i.test(ua) && !/safari\/\d/i.test(ua);
  // 字节系 App（TRAE / 抖音 / 飞书等）
  const isBytedanceApp = /trae|bytedance|tiktok|douyin|lark|feishu/i.test(ua);
  // WebView 子类标记
  const isWebViewMarker = /webview|android-chrome|chromium-webview/i.test(ua);

  if (isAndroidWV || isIOSWV || isBytedanceApp || isWebViewMarker) {
    document.documentElement.classList.add('in-webview');
  }
}
detectWebView();

// ════════════════════════════════════════
// 动态测量底部安全区域
// 在 TRAE 等 App 的 WebView 中，原生底栏高度因设备/版本不同而异。
// 使用 visualViewport API 测量实际可见区域与完整窗口的差值，
// 动态设置 --safe-bottom CSS 变量，确保内容不被原生底栏遮挡。
// ════════════════════════════════════════
function measureSafeBottom() {
  const html = document.documentElement;
  // 仅在 WebView 环境中执行动态测量
  if (!html.classList.contains('in-webview')) return;

  let nativeBarHeight = 0;

  // 方法 1: visualViewport API — 可见视口与窗口高度的差值即为原生底栏高度
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const diff = window.innerHeight - vv.height;
    // 差值 > 8px 才认为是原生底栏（排除浮点误差）
    if (diff > 8) {
      nativeBarHeight = diff;
    }
  }

  // 方法 2: 兜底 — 如果 visualViewport 未检测到，使用 env(safe-area-inset-bottom) + 默认偏移
  if (nativeBarHeight === 0) {
    // 读取 CSS 中已设置的 --safe-bottom 作为兜底（CSS 中 .in-webview 设为 72px）
    // 此处不再额外设置，保留 CSS 的默认值
    return;
  }

  // 将测得的原生底栏高度写入 CSS 变量
  html.style.setProperty('--safe-bottom', Math.ceil(nativeBarHeight) + 'px');
}

// 页面加载后立即测量
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', measureSafeBottom);
} else {
  measureSafeBottom();
}

// 可见视口变化时重新测量（如键盘弹出/收起、原生底栏显隐）
if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', () => {
    // 延迟执行，避免频繁触发
    clearTimeout(window._safeBottomTimer);
    window._safeBottomTimer = setTimeout(measureSafeBottom, 100);
  });
}

// 初始化主题（尽早执行，避免闪烁）
initTheme();

// 初始化 SPA 路由（拦截后续导航，避免完整页面重载）
initRouter();

// 初始化持久化音频播放器（悬浮在底部，跨页面持续播放）
initPlayer();

// ════════════════════════════════════════
// UI 增强：回到顶部按钮 + 键盘快捷键
// ════════════════════════════════════════

// 回到顶部按钮
function initScrollTop() {
  const btn = document.createElement('button');
  btn.className = 'scroll-top-btn';
  btn.innerHTML = '↑';
  btn.setAttribute('aria-label', '回到顶部');
  btn.title = '回到顶部';
  document.body.appendChild(btn);

  const onScroll = throttle(() => {
    if (window.scrollY > 400) {
      btn.classList.add('visible');
    } else {
      btn.classList.remove('visible');
    }
  }, 150);

  window.addEventListener('scroll', onScroll, { passive: true });

  btn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
}

// 键盘快捷键
function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    // 忽略输入框中的按键
    const tag = e.target.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;

    // `/` 聚焦搜索页搜索框
    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const searchInput = document.querySelector('.search-input');
      if (searchInput) {
        searchInput.focus();
      } else {
        // 不在搜索页，跳转过去
        window.location.href = '/search';
      }
    }

    // `g` 然后 `h` 回首页
    if (e.key === 'g') {
      const handler = (e2) => {
        if (e2.key === 'h') {
          window.location.href = '/';
        }
        document.removeEventListener('keydown', handler);
      };
      document.addEventListener('keydown', handler, { once: true });
      setTimeout(() => document.removeEventListener('keydown', handler), 1000);
    }

    // `Esc` 关闭展开的脚本/分析面板
    if (e.key === 'Escape') {
      const openViews = document.querySelectorAll('.script-view.open, .analysis-view.open');
      openViews.forEach(v => {
        v.classList.remove('open');
        const btn = v.previousElementSibling?.querySelector('[data-action="toggle-script"], [data-action="toggle-analysis"]');
        if (btn) {
          btn.textContent = btn.dataset.action === 'toggle-script' ? '📄 脚本' : '📊 分析';
        }
      });
    }
  });
}

// 页面过渡动画
function initPageTransitions() {
  // 为容器添加进入动画
  const container = document.querySelector('.container');
  if (container) {
    container.classList.add('page-enter');
  }
}

// 初始化所有 UI 增强
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initScrollTop();
    initKeyboardShortcuts();
    initPageTransitions();
  });
} else {
  initScrollTop();
  initKeyboardShortcuts();
  initPageTransitions();
}
