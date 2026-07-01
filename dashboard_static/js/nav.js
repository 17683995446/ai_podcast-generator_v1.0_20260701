// ════════════════════════════════════════
// 共享导航栏（多页面复用）
// ════════════════════════════════════════
import { updateStatusBadge } from './utils.js';
import { getCurrentTheme } from './theme.js';

// 导航配置
const navItems = [
  { href: '/', label: '概览', icon: '📊' },
  { href: '/episodes', label: '节目库', icon: '📻' },
  { href: '/search', label: '搜索', icon: '🔍' },
  { href: '/analysis', label: '项目分析', icon: '🔬' },
  { href: '/config', label: '配置', icon: '⚙️' },
];

export function renderNav(activePath) {
  const container = document.getElementById('nav-container');
  if (!container) return;

  const links = navItems.map(item => {
    const active = item.href === activePath ? 'active' : '';
    return `<a class="nav-link ${active}" href="${item.href}">${item.icon} ${item.label}</a>`;
  }).join('');

  const themeIcon = getCurrentTheme() === 'dark' ? '☀️' : '🌙';
  const themeTitle = getCurrentTheme() === 'dark' ? '切换到浅色模式' : '切换到深色模式';

  container.innerHTML = `
    <nav class="nav-bar">
      <div class="nav-left">
        <a class="nav-logo" href="/">
          <div class="logo-icon">🎧</div>
          <h1>GitHub 播客工具</h1>
        </a>
        <div class="nav-links">${links}</div>
      </div>
      <div class="nav-right">
        <button id="themeToggle" class="theme-toggle-btn" title="${themeTitle}" aria-label="${themeTitle}">${themeIcon}</button>
        <span id="statusBadge" class="badge badge-online"><span class="pulse"></span> 空闲</span>
      </div>
    </nav>
  `;
}

// 获取当前页面路径
export function getCurrentPath() {
  return window.location.pathname;
}
