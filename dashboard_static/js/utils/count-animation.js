// ════════════════════════════════════════
// count-animation.js — 数字计数动画（基于 CountUp.js）
// 通过 CDN 动态加载，失败时回退到直接赋值
// 替换原有的手写 requestAnimationFrame + ease-out 实现
// ════════════════════════════════════════

const COUNTUP_CDN = 'https://cdn.jsdelivr.net/npm/countup.js@4/dist/countUp.umd.js';

let _CountUp = null;
let _loading = null;

/**
 * 动态加载 CountUp.js CDN
 * @returns {Promise<Function|null>} CountUp 构造函数，加载失败返回 null
 */
async function ensureCountUp() {
  if (_CountUp) return _CountUp;
  if (_loading) return _loading;

  _loading = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = COUNTUP_CDN;
    script.onload = () => {
      _CountUp = window.CountUp || null;
      resolve(_CountUp);
    };
    script.onerror = () => {
      console.warn('[countup] CDN 加载失败，使用直接赋值');
      resolve(null);
    };
    document.head.appendChild(script);
  });

  return _loading;
}

// 预加载（非阻塞）
ensureCountUp();

/**
 * 数字计数动画（从 0 到目标值）
 * 使用 CountUp.js 渲染，支持平滑动画和缓动函数
 * CDN 加载失败时回退到直接赋值
 *
 * @param {HTMLElement} el - 目标元素
 * @param {number} target - 目标数值
 * @param {number} [duration=800] - 动画时长（毫秒）
 * @param {string} [prefix=''] - 前缀
 * @param {string} [suffix=''] - 后缀
 * @param {number} [decimals=0] - 小数位数
 */
export async function animateCount(el, target, duration = 800, prefix = '', suffix = '', decimals = 0) {
  if (!el) return;

  const CountUp = await ensureCountUp();

  if (CountUp) {
    try {
      el.classList.add('counting');
      const cu = new CountUp(el, target, {
        duration: duration / 1000,
        decimalPlaces: decimals,
        prefix,
        suffix,
        useEasing: true,
        easingFn: (t) => 1 - Math.pow(1 - t, 3), // ease-out cubic，与原实现一致
      });
      cu.start(() => {
        setTimeout(() => el.classList.remove('counting'), 300);
      });
      return;
    } catch (e) {
      console.warn('[countup] CountUp.js 执行失败，使用直接赋值:', e);
    }
  }

  // 回退方案：直接赋值
  el.textContent = prefix + (typeof target === 'number' ? target.toFixed(decimals) : target) + suffix;
}
