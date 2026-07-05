// ════════════════════════════════════════
// api.js — 统一 API 客户端
// 所有网络请求经过此模块，统一错误处理与日志
// Stage 2: TTL 常量化、内部函数改私有、消除魔法数字
// ════════════════════════════════════════
import { API } from './constants.js';

// ── 缓存 TTL 常量（毫秒）──
const CACHE_TTL = {
  STATS:    15_000,   // 状态轮询频繁，15s
  EPISODES: 20_000,   // 轮询 + 切页复用，20s
  CONFIG:   30_000,   // 配置不常变，30s
  SCRIPT:   60_000,   // 脚本不变，60s
  ANALYSIS: 60_000,   // 分析不变，60s
  DEFAULT:  30_000,   // 默认 TTL
};

// ── 内存缓存 ──
// 缓存 GET 请求结果，避免 SPA 切页时重复请求相同数据
// TTL 到期后自动失效，下次请求重新获取
const _cache = new Map();

/**
 * 带缓存功能的 GET 请求
 * @param {string} url - 请求地址
 * @param {number} [ttl] - 缓存有效期（毫秒），默认 CACHE_TTL.DEFAULT
 * @returns {Promise<any>} 解析后的 JSON
 */
async function cachedGet(url, ttl = CACHE_TTL.DEFAULT) {
  const cached = _cache.get(url);
  if (cached && Date.now() - cached.ts < ttl) {
    return cached.data;
  }
  const data = await _request(url);
  _cache.set(url, { data, ts: Date.now() });
  return data;
}

/**
 * 清除指定 URL 的缓存（或全部清除）
 * @param {string} [url] - 要清除的 URL，不传则清除全部
 */
export function clearCache(url) {
  if (url) {
    _cache.delete(url);
  } else {
    _cache.clear();
  }
}

/**
 * 基础请求方法（私有，不导出）
 * @param {string} url - 请求地址
 * @param {RequestInit} [options] - fetch 配置
 * @returns {Promise<any>} 解析后的 JSON
 * @throws {Error} 含 status 字段的错误
 */
async function _request(url, options = {}) {
  const r = await fetch(url, options);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const t = await r.text();
      if (t) {
        try { msg += ': ' + JSON.parse(t).error || t; }
        catch (_) { msg += ': ' + t; }
      }
    } catch (_) {}
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ── 内部 HTTP 方法（私有，不导出）──
function _get(url) { return _request(url); }
function _postJSON(url, data = {}) {
  return _request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}
function _postEmpty(url) { return _request(url, { method: 'POST' }); }

// ════════════════════════════════════════
// 业务 API 封装 — 语义化调用，消除散落的 URL 字符串
// GET 请求使用缓存，减少 SPA 切页时的重复请求
// ════════════════════════════════════════
export const api = {
  getStats:           () => cachedGet(API.STATS, CACHE_TTL.STATS),
  getEpisodes:        () => cachedGet(API.EPISODES, CACHE_TTL.EPISODES),
  getConfig:          () => cachedGet(API.CONFIG, CACHE_TTL.CONFIG),
  getTaskStatus:      () => _get(API.TASK_STATUS),                 // 不缓存（实时状态）
  cancelTask:         () => _postEmpty(API.TASK_CANCEL),
  resetTask:          () => _postEmpty(API.TASK_RESET),
  run:         (params) => _postJSON(API.RUN, params),
  batch:      (params) => _postJSON(API.BATCH, params),
  getScript:      (ep) => cachedGet(API.EPISODE_SCRIPT(ep), CACHE_TTL.SCRIPT),
  getAnalysis:    (ep) => cachedGet(API.EPISODE_ANALYSIS(ep), CACHE_TTL.ANALYSIS),
  askQuestion: (params) => _postJSON(API.QA_ASK, params),
  search:         (q) => _get(`${API.SEARCH}?q=${encodeURIComponent(q)}`),  // 不缓存
};
