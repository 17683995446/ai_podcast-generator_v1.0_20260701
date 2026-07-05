// ════════════════════════════════════════
// SPA 路由器 — 拦截内部导航，无刷新切换页面
// 保持 DOM 不被销毁，音频播放器持续运行
// ════════════════════════════════════════
import { renderNav } from './nav.js';

const ROUTES = {
  '/':        { script: '/js/pages/dashboard.js', css: ['/css/dashboard.css'], title: '概览 · GitHub 播客工具', description: '自动获取 GitHub 前沿项目并生成深度播客节目，包含项目分析、技术解读和音频内容。' },
  '/episodes':{ script: '/js/pages/episodes.js',  css: ['/css/episodes.css'], title: '节目库 · GitHub 播客工具', description: '浏览所有已生成的播客节目，查看节目脚本和项目深度分析。' },
  '/analysis':{ script: '/js/pages/analysis.js',  css: ['/css/analysis.css'], title: '项目深度分析 · GitHub 播客工具', description: '对 GitHub 前沿项目进行深度技术分析，包含架构设计、代码指标、健康度评估和项目对比。' },
  '/config':  { script: '/js/pages/config.js',    css: ['/css/config.css'],    title: '配置 · GitHub 播客工具', description: '查看和管理 GitHub 播客工具的 LLM、TTS 和项目发现配置。' },
  '/search':  { script: '/js/pages/search.js',    css: ['/css/search.css'],    title: '搜索 · GitHub 播客工具', description: '全文搜索播客节目内容，快速定位感兴趣的技术话题和项目。' },
};

let currentCleanup = null;
let isNavigating = false;

export function initRouter() {
  // 拦截内部链接点击
  document.addEventListener('click', (e) => {
    const link = e.target.closest('a');
    if (!link) return;

    const href = link.getAttribute('href');
    if (!href || !ROUTES[href]) return;
    if (link.hasAttribute('download')) return;
    if (e.ctrlKey || e.metaKey || e.shiftKey) return; // 新标签打开

    e.preventDefault();
    navigate(href);
  });

  // 浏览器前进/后退
  window.addEventListener('popstate', () => {
    const path = window.location.pathname;
    if (ROUTES[path]) navigate(path, false);
  });
}

export async function navigate(path, pushState = true) {
  if (isNavigating) return;
  isNavigating = true;

  try {
    // 清理上一页的资源（intervals、listeners）
    if (currentCleanup) {
      try { currentCleanup(); } catch (e) { console.warn('cleanup error:', e); }
      currentCleanup = null;
    }

    // 清理上一页的 body class（防止 feed-mode 等页面专属样式跨页泄漏）
    document.body.className = document.body.className
      .split(' ')
      .filter(cls => cls && cls !== 'feed-mode')
      .join(' ');

    const route = ROUTES[path];
    if (!route) {
      window.location.href = path;
      return;
    }

    // 预加载页面专属 CSS（在获取 HTML 之前启动下载，避免 FOUC）
    // CSS 只加载一次，后续导航复用已缓存的 <link>
    route.css.forEach(href => {
      if (!document.querySelector(`link[href="${href}"]`)) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        document.head.appendChild(link);
      }
    });

    // 获取目标页面 HTML（与 CSS 下载并行进行）
    const response = await fetch(path);
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, 'text/html');

    // 提取 container 内容
    const newContainer = doc.querySelector('.container');
    const currentContainer = document.querySelector('.container');

    if (!newContainer || !currentContainer) {
      window.location.href = path;
      return;
    }

    // 替换内容（nav 和 player 不在 container 内，不受影响）
    currentContainer.innerHTML = newContainer.innerHTML;

    // 更新标题
    document.title = route.title;

    // 更新 SEO 元数据（SPA 导航时同步 meta 标签）
    updateSEO(route, path);

    // 更新 URL
    if (pushState) {
      history.pushState({ path }, '', path);
    }

    // 重新渲染导航栏（高亮新页面）
    renderNav(path);

    // 动态导入页面模块（使用浏览器原生 ES 模块缓存）
    // 首次导航：下载并执行模块，模块底部的 init() 自动调用
    // 后续导航：返回缓存的模块命名空间，需显式调用 init()
    const module = await import(route.script);
    if (module.cleanup) {
      currentCleanup = module.cleanup;
    }
    // 显式调用 init() — 首次加载时 _initialized 守卫阻止重复执行，
    // 后续导航时 cleanup() 已重置 _initialized，init() 将正常执行
    if (module.init) {
      await module.init();
    }

    // 焦点管理：将焦点移至主内容区域，辅助屏幕阅读器和键盘用户感知页面切换
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
      mainContent.setAttribute('tabindex', '-1');
      mainContent.focus({ preventScroll: true });
    }

    // 滚动到顶部
    window.scrollTo(0, 0);
  } catch (e) {
    console.error('SPA 导航失败，回退到完整加载:', e);
    window.location.href = path;
  } finally {
    isNavigating = false;
  }
}

// ════════════════════════════════════════
// SEO 元数据同步 — SPA 导航时更新 meta 标签
// ════════════════════════════════════════

/**
 * 更新页面的 SEO 元数据
 * @param {Object} route - 路由配置对象
 * @param {string} path - 当前路径
 */
function updateSEO(route, path) {
  const origin = window.location.origin;
  const fullUrl = origin + path;

  // 更新 meta description
  _setMeta('name', 'description', route.description);

  // 更新 canonical
  _setLink('canonical', fullUrl);

  // 更新 Open Graph 标签
  _setMeta('property', 'og:title', route.title);
  _setMeta('property', 'og:description', route.description);
  _setMeta('property', 'og:url', fullUrl);
}

/** 设置或更新 <meta> 标签内容 */
function _setMeta(attr, key, content) {
  if (!content) return;
  let el = document.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

/** 设置或更新 <link> 标签 href */
function _setLink(rel, href) {
  if (!href) return;
  let el = document.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
}
