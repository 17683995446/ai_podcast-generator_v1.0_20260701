// ════════════════════════════════════════
// lodash-loader.js — 节流/防抖工具（基于 lodash-es）
// 通过 esm.sh 动态预加载 lodash-es，加载成功后使用 lodash 实现
// 加载失败时回退到内置的 lodash 兼容实现（含 .cancel()/.flush()）
// 替换原有的手写 throttle 和 search-panel.js 中的手写防抖
// ════════════════════════════════════════

const LODASH_CDN = 'https://esm.sh/lodash-es@4.17.21';

let _lodashThrottle = null;
let _lodashDebounce = null;
let _loading = null;

/**
 * 异步预加载 lodash-es
 * 加载成功后 _lodashThrottle / _lodashDebounce 被赋值
 * 后续调用 throttle() / debounce() 将使用 lodash 实现
 */
async function preloadLodash() {
  if (_lodashThrottle && _lodashDebounce) return;
  if (_loading) return _loading;

  _loading = (async () => {
    try {
      const mod = await import(LODASH_CDN);
      _lodashThrottle = mod.throttle;
      _lodashDebounce = mod.debounce;
    } catch (e) {
      console.warn('[lodash] esm.sh 加载失败，使用内置兼容实现');
    }
  })();

  return _loading;
}

// 启动预加载（非阻塞，不影响模块初始化）
preloadLodash();

/**
 * 节流函数（lodash 兼容 API）
 * lodash 加载后自动切换到 lodash.throttle 实现
 * 未加载时使用内置实现，API 完全兼容（含 .cancel() / .flush()）
 *
 * @param {Function} fn - 需要节流的函数
 * @param {number} [delay=100] - 延迟毫秒
 * @param {Object} [options={leading:true,trailing:true}] - 选项
 * @returns {Function} 节流后的函数（含 .cancel() / .flush() 方法）
 */
export function throttle(fn, delay = 100, options = {}) {
  // 如果 lodash 已加载，直接使用
  if (_lodashThrottle) {
    return _lodashThrottle(fn, delay, { leading: true, trailing: true, ...options });
  }

  // 内置兼容实现
  const { leading = true, trailing = true } = options;
  let lastCall = 0;
  let timer = null;
  let lastArgs = null;

  const throttled = function (...args) {
    const now = Date.now();

    if (leading && lastCall === 0) {
      lastCall = now;
      fn.apply(this, args);
      return;
    }

    const remaining = delay - (now - lastCall);

    if (remaining <= 0) {
      clearTimeout(timer);
      timer = null;
      lastCall = now;
      lastArgs = null;
      fn.apply(this, args);
    } else if (!timer && trailing) {
      lastArgs = args;
      timer = setTimeout(() => {
        lastCall = Date.now();
        timer = null;
        if (lastArgs) {
          fn.apply(this, lastArgs);
          lastArgs = null;
        }
      }, remaining);
    }
  };

  throttled.cancel = function () {
    clearTimeout(timer);
    timer = null;
    lastCall = 0;
    lastArgs = null;
  };

  throttled.flush = function () {
    if (timer) {
      clearTimeout(timer);
      timer = null;
      if (lastArgs) {
        fn.apply(this, lastArgs);
        lastArgs = null;
      }
      lastCall = Date.now();
    }
  };

  return throttled;
}

/**
 * 防抖函数（lodash 兼容 API）
 * lodash 加载后自动切换到 lodash.debounce 实现
 * 未加载时使用内置实现，API 完全兼容（含 .cancel() / .flush()）
 *
 * @param {Function} fn - 需要防抖的函数
 * @param {number} [delay=300] - 延迟毫秒
 * @param {Object} [options={leading:false,trailing:true}] - 选项
 * @returns {Function} 防抖后的函数（含 .cancel() / .flush() 方法）
 */
export function debounce(fn, delay = 300, options = {}) {
  // 如果 lodash 已加载，直接使用
  if (_lodashDebounce) {
    return _lodashDebounce(fn, delay, { leading: false, trailing: true, ...options });
  }

  // 内置兼容实现
  const { leading = false, trailing = true } = options;
  let timer = null;
  let canLeading = leading;

  const debounced = function (...args) {
    if (canLeading && !timer) {
      fn.apply(this, args);
      canLeading = false;
    }
    clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      if (trailing) {
        fn.apply(this, args);
      }
      canLeading = leading;
    }, delay);
  };

  debounced.cancel = function () {
    clearTimeout(timer);
    timer = null;
    canLeading = leading;
  };

  debounced.flush = function () {
    if (timer) {
      clearTimeout(timer);
      timer = null;
      fn.apply(this);
      canLeading = leading;
    }
  };

  return debounced;
}
