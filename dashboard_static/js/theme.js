// ════════════════════════════════════════
// 主题管理 — 浅色/深色模式切换
// 优先级：localStorage > 系统偏好 > 默认深色
// ════════════════════════════════════════

const STORAGE_KEY = 'podcast-theme';

// 获取当前已保存的主题（null 表示未手动设置，跟随系统）
function getSavedTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch (e) {
    return null;
  }
}

// 获取系统偏好
function getSystemTheme() {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

// 获取当前实际生效的主题
export function getCurrentTheme() {
  const saved = getSavedTheme();
  if (saved === 'light' || saved === 'dark') return saved;
  return getSystemTheme();
}

// 应用主题到 DOM
export function applyTheme(theme) {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
  updateToggleButton(theme);
}

// 切换主题并持久化
export function toggleTheme() {
  const current = getCurrentTheme();
  const next = current === 'dark' ? 'light' : 'dark';
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch (e) {}
  applyTheme(next);
}

// 更新切换按钮图标
function updateToggleButton(theme) {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  btn.setAttribute('title', theme === 'dark' ? '切换到浅色模式' : '切换到深色模式');
  btn.setAttribute('aria-label', theme === 'dark' ? '切换到浅色模式' : '切换到深色模式');
}

// 初始化主题（在页面加载时尽早调用）
export function initTheme() {
  // 应用已保存或系统偏好主题
  applyTheme(getCurrentTheme());

  // 监听系统主题变化（仅当用户未手动设置时跟随）
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
    const saved = getSavedTheme();
    if (saved !== 'light' && saved !== 'dark') {
      applyTheme(e.matches ? 'light' : 'dark');
    }
  });

  // 绑定切换按钮（延迟绑定，确保导航栏已渲染）
  document.addEventListener('click', (e) => {
    if (e.target.closest('#themeToggle')) {
      e.preventDefault();
      toggleTheme();
    }
  });
}
