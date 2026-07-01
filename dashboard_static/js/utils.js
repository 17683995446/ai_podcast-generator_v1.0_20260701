// ════════════════════════════════════════
// 工具函数（不依赖其他模块，避免循环依赖）
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
  if (running) {
    badge.className = 'badge badge-busy';
    badge.innerHTML = '<span class="pulse" style="background:var(--orange)"></span> 运行中';
  } else {
    badge.className = 'badge badge-online';
    badge.innerHTML = '<span class="pulse"></span> 空闲';
  }
}
