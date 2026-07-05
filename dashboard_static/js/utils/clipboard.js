// ════════════════════════════════════════
// clipboard.js — 剪贴板工具（基于 copy-to-clipboard）
// 通过 esm.sh 动态加载，失败时回退到内置 execCommand 实现
// 替换原有的手写 Clipboard API + execCommand 降级逻辑
// ════════════════════════════════════════

const CLIPBOARD_CDN = 'https://esm.sh/copy-to-clipboard@3.3.3';

let _copyFn = null;
let _loading = null;

/**
 * 动态加载 copy-to-clipboard ESM 模块
 * @returns {Promise<Function|null>} copy 函数，加载失败返回 null
 */
async function ensureCopy() {
  if (_copyFn) return _copyFn;
  if (_loading) return _loading;

  _loading = (async () => {
    try {
      const mod = await import(CLIPBOARD_CDN);
      _copyFn = mod.default;
      return _copyFn;
    } catch (e) {
      console.warn('[clipboard] esm.sh 加载失败，使用内置 fallback');
      return null;
    }
  })();

  return _loading;
}

// 预加载（非阻塞）
ensureCopy();

/**
 * 复制文本到剪贴板
 * 优先使用 copy-to-clipboard 库（更好的 iOS Safari 和非安全上下文兼容性）
 * 加载失败时回退到 execCommand('copy')
 *
 * @param {string} text - 要复制的文本
 * @returns {Promise<boolean>} 是否复制成功
 */
export async function copyToClipboard(text) {
  const copy = await ensureCopy();

  if (copy) {
    try {
      copy(text);
      return true;
    } catch (e) {
      console.warn('[clipboard] copy-to-clipboard 执行失败，降级到 execCommand:', e);
    }
  }

  // 回退方案：execCommand('copy')
  return _fallbackCopy(text);
}

/**
 * 内置 execCommand 回退（当 CDN 加载失败时使用）
 */
function _fallbackCopy(text) {
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(textarea);
    return ok;
  } catch (e) {
    console.warn('[clipboard] execCommand 复制失败:', e);
    return false;
  }
}
