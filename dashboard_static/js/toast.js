// ════════════════════════════
// 全局 Toast 通知系统
// 替换所有 alert() 调用，提供非阻塞式反馈
// ════════════════════════════

let _toastContainer = null;

function _getContainer() {
  if (!_toastContainer) {
    _toastContainer = document.createElement('div');
    _toastContainer.id = 'toastContainer';
    _toastContainer.className = 'toast-container';
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

const _icons = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
};

const _colors = {
  success: '#10b981',
  error: '#ef4444',
  warning: '#f59e0b',
  info: '#6366f1',
};

/**
 * 显示 Toast 通知
 * @param {string} message - 消息内容
 * @param {'success'|'error'|'warning'|'info'} type - 通知类型
 * @param {number} duration - 显示时长（毫秒），默认 3000
 * @param {object} [opts] - 额外选项 { action: { label, callback } }
 */
export function showToast(message, type = 'info', duration = 3000, opts = null) {
  const container = _getContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  // 解析 action 选项
  const action = opts && opts.action ? opts.action : null;
  const actionHtml = action
    ? `<button class="toast-action-btn">${action.label}</button>`
    : '';

  toast.innerHTML = `
    <span class="toast-icon" style="color: ${_colors[type] || _colors.info}">${_icons[type] || _icons.info}</span>
    <span class="toast-msg">${message}</span>
    ${actionHtml}
  `;
  container.appendChild(toast);

  // action 按钮事件
  if (action) {
    const btn = toast.querySelector('.toast-action-btn');
    if (btn) {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        clearTimeout(timer);
        _removeToast(toast);
        try { action.callback(); } catch (_) {}
      });
    }
  }

  // 入场动画
  requestAnimationFrame(() => toast.classList.add('toast-show'));

  // 自动消失
  const timer = setTimeout(() => _removeToast(toast), duration);

  // 点击关闭
  toast.addEventListener('click', () => {
    clearTimeout(timer);
    _removeToast(toast);
  });
}

function _removeToast(toast) {
  toast.classList.remove('toast-show');
  toast.classList.add('toast-hide');
  setTimeout(() => toast.remove(), 300);
}

// 便捷方法：支持 showToast(msg, type, duration) 和 showToast(msg, type, opts)
// opts 可以是数字（duration）或对象 { duration, action }
function _parseOpts(arg) {
  if (typeof arg === 'number') return { duration: arg };
  if (arg && typeof arg === 'object') return arg;
  return {};
}

export const toast = {
  success: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'success', o.duration || 3000, o); },
  error: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'error', o.duration || 5000, o); },
  warning: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'warning', o.duration || 3000, o); },
  info: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'info', o.duration || 3000, o); },
};
