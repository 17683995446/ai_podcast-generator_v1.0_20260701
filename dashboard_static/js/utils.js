// ════════════════════════════════════════
// 工具函数（不依赖其他模块，避免循环依赖）
// animateCount → utils/count-animation.js（直接导入）
// throttle / debounce → utils/lodash-loader.js（直接导入）
// Stage 2: 移除 barrel re-export，消除双重导入路径
// ════════════════════════════════════════

// HTML 转义，防止 XSS
export function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// 技术栈标签预定义色板
const tagColors = ['#6c5ce7', '#00b894', '#fdcb6e', '#74b9ff', '#e17055', '#a29bfe', '#55efc4', '#fab1a0'];

// 为每个标签稳定分配颜色（基于字符串 hash，保证同标签同色）
export function pickTagColor(tag) {
  let h = 0;
  for (let i = 0; i < tag.length; i++) {
    h = (h * 31 + tag.charCodeAt(i)) >>> 0;
  }
  return tagColors[h % tagColors.length];
}

// 更新顶部状态徽章（运行中 / 空闲）
export function updateStatusBadge(running) {
  const badge = document.getElementById('statusBadge');
  if (!badge) return;
  if (running) {
    badge.className = 'badge badge-busy';
    badge.innerHTML = '<span class="pulse" style="background:var(--orange)"></span> <span class="badge-text">运行中</span>';
  } else {
    badge.className = 'badge badge-online';
    badge.innerHTML = '<span class="pulse"></span> <span class="badge-text">空闲</span>';
  }
}

// ════════════════════════════════════════
// UI 增强工具函数
// ════════════════════════════════════════

/**
 * 自动滚动元素到底部
 * @param {HTMLElement} el - 需要滚动的元素
 */
export function autoScrollToBottom(el) {
  if (!el) return;
  el.scrollTop = el.scrollHeight;
}
