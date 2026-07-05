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
    const ariaCurrent = item.href === activePath ? ' aria-current="page"' : '';
    return `<a class="nav-link ${active}" href="${item.href}" title="${item.label}"${ariaCurrent}>${item.icon} <span class="nav-label">${item.label}</span></a>`;
  }).join('');

  const mobileLinks = navItems.map(item => {
    const active = item.href === activePath ? 'active' : '';
    const ariaCurrent = item.href === activePath ? ' aria-current="page"' : '';
    return `<a class="mobile-nav-link ${active}" href="${item.href}"${ariaCurrent}><span class="mobile-nav-icon">${item.icon}</span><span class="mobile-nav-text">${item.label}</span></a>`;
  }).join('');

  const themeIcon = getCurrentTheme() === 'dark' ? '☀️' : '🌙';
  const themeTitle = getCurrentTheme() === 'dark' ? '切换到浅色模式' : '切换到深色模式';

  container.innerHTML = `
    <nav class="nav-bar" aria-label="主导航">
      <div class="nav-left">
        <a class="nav-logo" href="/" aria-label="GitHub 播客工具首页">
          <div class="logo-icon">🎧</div>
          <span class="nav-logo-text">GitHub 播客工具</span>
        </a>
        <div class="nav-links">${links}</div>
        <button class="nav-hamburger" id="navHamburger" aria-label="打开菜单" aria-expanded="false" aria-controls="mobileNavMenu">
          <span></span><span></span><span></span>
        </button>
      </div>
      <div class="nav-right">
        <button id="themeToggle" class="theme-toggle-btn" title="${themeTitle}" aria-label="${themeTitle}">${themeIcon}</button>
        <span id="statusBadge" class="badge badge-online" role="status"><span class="pulse"></span> <span class="badge-text">空闲</span></span>
      </div>
    </nav>
    <div class="mobile-nav-menu" id="mobileNavMenu" role="menu" aria-hidden="true">
      ${mobileLinks}
    </div>
  `;

  // 汉堡菜单切换逻辑
  const hamburger = container.querySelector('#navHamburger');
  const mobileMenu = container.querySelector('#mobileNavMenu');

  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', () => {
      const isOpen = mobileMenu.classList.toggle('open');
      hamburger.classList.toggle('active', isOpen);
      hamburger.setAttribute('aria-expanded', String(isOpen));
      mobileMenu.setAttribute('aria-hidden', String(!isOpen));
      hamburger.setAttribute('aria-label', isOpen ? '关闭菜单' : '打开菜单');
    });

    // 点击菜单项后关闭
    mobileMenu.querySelectorAll('.mobile-nav-link').forEach(link => {
      link.addEventListener('click', () => {
        mobileMenu.classList.remove('open');
        hamburger.classList.remove('active');
        hamburger.setAttribute('aria-expanded', 'false');
        mobileMenu.setAttribute('aria-hidden', 'true');
      });
    });

    // 点击外部关闭
    document.addEventListener('click', (e) => {
      if (!hamburger.contains(e.target) && !mobileMenu.contains(e.target)) {
        mobileMenu.classList.remove('open');
        hamburger.classList.remove('active');
        hamburger.setAttribute('aria-expanded', 'false');
        mobileMenu.setAttribute('aria-hidden', 'true');
      }
    });
  }
}

// 获取当前页面路径
export function getCurrentPath() {
  return window.location.pathname;
}
