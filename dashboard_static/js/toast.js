// ════════════════════════════
// 全局 Toast 通知系统（基于 Notyf）
// 替换原有手写 Toast 实现，使用 Notyf 开源库
// CDN 动态加载，失败时回退到简易 DOM 通知
// ════════════════════════════
import { TOAST_DURATION } from './constants.js';

const NOTYF_CSS_CDN = 'https://cdn.jsdelivr.net/npm/notyf@3/notyf.min.css';
const NOTYF_JS_CDN = 'https://cdn.jsdelivr.net/npm/notyf@3/notyf.min.js';

let _notyf = null;
let _notyfLoading = null;

// 类型配置（颜色与默认时长）
// Stage 2: 统一使用 constants.js 的 TOAST_DURATION，错误类延长 1.5x
const _typeConfig = {
  success: { bg: '#10b981', duration: TOAST_DURATION },
  error:   { bg: '#ef4444', duration: Math.round(TOAST_DURATION * 1.5) },
  warning: { bg: '#f59e0b', duration: TOAST_DURATION },
  info:    { bg: '#6366f1', duration: TOAST_DURATION },
};

/**
 * 动态加载 Notyf CDN（CSS + JS），返回 Notyf 实例。
 * 加载失败时 reject，调用方回退到简易 DOM 通知。
 */
async function _ensureNotyf() {
  if (_notyf) return _notyf;
  if (_notyfLoading) return _notyfLoading;

  _notyfLoading = new Promise((resolve, reject) => {
    // 加载 CSS
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = NOTYF_CSS_CDN;
    document.head.appendChild(link);

    // 加载 JS
    const script = document.createElement('script');
    script.src = NOTYF_JS_CDN;
    script.onload = () => {
      _notyf = new Notyf({
        duration: TOAST_DURATION,
        position: { x: 'right', y: 'top' },
        dismissible: true,
        ripple: true,
        types: [
          { type: 'success', backgroundColor: _typeConfig.success.bg, icon: false, duration: _typeConfig.success.duration },
          { type: 'error',   backgroundColor: _typeConfig.error.bg,   icon: false, duration: _typeConfig.error.duration },
          { type: 'warning', backgroundColor: _typeConfig.warning.bg, icon: false, duration: _typeConfig.warning.duration },
          { type: 'info',    backgroundColor: _typeConfig.info.bg,    icon: false, duration: _typeConfig.info.duration },
        ],
      });
      resolve(_notyf);
    };
    script.onerror = () => reject(new Error('Notyf CDN 加载失败'));
    document.head.appendChild(script);
  });

  return _notyfLoading;
}

/**
 * Notyf 加载失败时的简易 DOM 回退通知
 */
function _fallbackToast(message, type, duration) {
  const bg = (_typeConfig[type] || _typeConfig.info).bg;
  const div = document.createElement('div');
  div.style.cssText = [
    'position:fixed', 'top:16px', 'right:16px',
    'padding:12px 20px', 'border-radius:8px',
    'color:#fff', 'z-index:99999', 'font-size:13px',
    'max-width:400px', `background:${bg}`,
    'box-shadow:0 4px 12px rgba(0,0,0,0.3)',
    'transition:opacity 0.3s', 'opacity:1',
  ].join(';');
  div.textContent = message;
  document.body.appendChild(div);
  setTimeout(() => {
    div.style.opacity = '0';
    setTimeout(() => div.remove(), 300);
  }, duration || TOAST_DURATION);
}

/**
 * 显示 Toast 通知（API 与旧版完全一致）
 * @param {string} message - 消息内容
 * @param {'success'|'error'|'warning'|'info'} type - 通知类型
 * @param {number} [duration] - 显示时长（毫秒）
 * @param {object} [opts] - 额外选项 { duration, action: { label, callback } }
 */
export function showToast(message, type = 'info', duration = null, opts = null) {
  const config = _typeConfig[type] || _typeConfig.info;
  const actualDuration = duration || (opts && opts.duration) || config.duration;
  const action = opts && opts.action ? opts.action : null;

  _ensureNotyf().then(notyf => {
    // 如果有 action 按钮，将按钮 HTML 注入消息
    let msgHtml = message;
    if (action) {
      msgHtml = `${message} <button class="notyf-action-btn">${action.label}</button>`;
    }

    const notification = notyf.open({
      type: type,
      message: msgHtml,
      duration: actualDuration,
    });

    // 为 action 按钮绑定事件（Notyf 渲染后异步查找）
    if (action) {
      setTimeout(() => {
        const buttons = document.querySelectorAll('.notyf-action-btn');
        const btn = buttons[buttons.length - 1]; // 取最新创建的按钮
        if (btn) {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            notyf.dismiss(notification);
            try { action.callback(); } catch (_) {}
          });
        }
      }, 50);
    }
  }).catch(() => {
    // Notyf 加载失败，回退到简易 DOM 通知
    _fallbackToast(message, type, actualDuration);
  });
}

// 便捷方法：支持 showToast(msg, type, duration) 和 showToast(msg, type, opts)
// opts 可以是数字（duration）或对象 { duration, action }
function _parseOpts(arg) {
  if (typeof arg === 'number') return { duration: arg };
  if (arg && typeof arg === 'object') return arg;
  return {};
}

export const toast = {
  success: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'success', o.duration, o); },
  error:   (msg, d) => { const o = _parseOpts(d); showToast(msg, 'error',   o.duration, o); },
  warning: (msg, d) => { const o = _parseOpts(d); showToast(msg, 'warning', o.duration, o); },
  info:    (msg, d) => { const o = _parseOpts(d); showToast(msg, 'info',    o.duration, o); },
};
