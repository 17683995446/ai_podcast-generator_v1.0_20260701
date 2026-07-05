// ════════════════════════════════════════
// page-base.js — 页面生命周期基类
// 标准化 SPA 页面的 init/cleanup 模式，自动追踪资源
// ════════════════════════════════════════
import { renderNav, getCurrentPath } from './nav.js';
import { POLL_INTERVAL } from './constants.js';

// 全局清理函数追踪
// 解决问题：首次完整加载时，HTML <script> 加载的初始页面模块不受 SPA router 追踪，
// 导致导航到其他页面时初始页面的事件监听器不会被清理，造成重复 handler 冲突。
// 每次 init() 前自动调用上一页的 cleanup()，确保旧监听器被移除。
let _globalCleanup = null;

/**
 * 创建标准化页面实例
 * @param {Object} opts
 * @param {Function} opts.init - 页面初始化异步函数，接收 ctx 参数
 * @param {Function} [opts.onCleanup] - 自定义清理回调
 * @returns {{ init: Function, cleanup: Function }}
 */
export function createPage({ init, onCleanup }) {
  let _intervals = [];
  let _listeners = [];
  let _timeouts = [];
  let _abortControllers = [];
  let _initialized = false;

  /** 资源上下文 — 传递给 init 函数 */
  const ctx = {
    /** 注册 setInterval，自动在 cleanup 时清除 */
    setInterval(fn, ms = POLL_INTERVAL) {
      const id = window.setInterval(fn, ms);
      _intervals.push(id);
      return id;
    },
    /** 注册 setTimeout，自动在 cleanup 时清除 */
    setTimeout(fn, ms) {
      const id = window.setTimeout(fn, ms);
      _timeouts.push(id);
      return id;
    },
    /** 注册事件监听器，自动在 cleanup 时移除 */
    addListener(el, type, fn, opts) {
      el.addEventListener(type, fn, opts);
      _listeners.push([el, type, fn, opts]);
    },
    /** 创建 AbortController，自动在 cleanup 时 abort */
    createAbort() {
      const ac = new AbortController();
      _abortControllers.push(ac);
      return ac;
    },
  };

  const pageObj = {
    async init() {
      if (_initialized) return;
      _initialized = true;
      // 清理上一页的资源（处理 SPA 首次导航时 router 未追踪初始页面的情况）
      // router 的 currentCleanup 为 null 时，这里作为兜底确保旧监听器被移除
      if (_globalCleanup) {
        try { _globalCleanup(); } catch (e) { console.warn('上一页清理失败:', e); }
      }
      _globalCleanup = pageObj.cleanup;
      renderNav(getCurrentPath());
      await init(ctx);
    },

    cleanup() {
      _intervals.forEach(id => clearInterval(id));
      _timeouts.forEach(id => clearTimeout(id));
      _listeners.forEach(([el, type, fn, opts]) => el.removeEventListener(type, fn, opts));
      _abortControllers.forEach(ac => { try { ac.abort(); } catch (_) {} });
      if (onCleanup) onCleanup();

      _intervals = [];
      _timeouts = [];
      _listeners = [];
      _abortControllers = [];
      _initialized = false;
    },
  };

  return pageObj;
}
