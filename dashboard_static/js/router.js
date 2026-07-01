// ════════════════════════════════════════
// SPA 路由器 — 拦截内部导航，无刷新切换页面
// 保持 DOM 不被销毁，音频播放器持续运行
// ════════════════════════════════════════
import { renderNav } from './nav.js';

const ROUTES = {
  '/':        { script: '/js/pages/dashboard.js', css: ['/css/dashboard.css'], title: '概览 · GitHub 播客工具' },
  '/episodes':{ script: '/js/pages/episodes.js',  css: ['/css/episodes.css'], title: '节目库 · GitHub 播客工具' },
  '/analysis':{ script: '/js/pages/analysis.js',  css: ['/css/analysis.css'], title: '项目深度分析 · GitHub 播客工具' },
  '/config':  { script: '/js/pages/config.js',    css: [],                     title: '配置 · GitHub 播客工具' },
  '/search':  { script: '/js/pages/search.js',    css: ['/css/search.css'],    title: '搜索 · GitHub 播客工具' },
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

    const route = ROUTES[path];
    if (!route) {
      window.location.href = path;
      return;
    }

    // 获取目标页面 HTML
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

    // 加载页面专属 CSS（如果尚未加载）
    route.css.forEach(href => {
      if (!document.querySelector(`link[href="${href}"]`)) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        document.head.appendChild(link);
      }
    });

    // 更新 URL
    if (pushState) {
      history.pushState({ path }, '', path);
    }

    // 重新渲染导航栏（高亮新页面）
    renderNav(path);

    // 动态导入页面模块（加时间戳避免 ES6 模块缓存）
    const module = await import(route.script + '?t=' + Date.now());
    if (module.cleanup) {
      currentCleanup = module.cleanup;
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
