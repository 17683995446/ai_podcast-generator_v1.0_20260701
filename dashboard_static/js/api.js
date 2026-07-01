// ════════════════════════════════════════
// api.js — 统一 API 客户端
// 所有网络请求经过此模块，统一错误处理与日志
// ════════════════════════════════════════
import { API } from './constants.js';

/**
 * 基础请求方法
 * @param {string} url - 请求地址
 * @param {RequestInit} [options] - fetch 配置
 * @returns {Promise<any>} 解析后的 JSON
 * @throws {Error} 含 status 字段的错误
 */
async function request(url, options = {}) {
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

/** GET 请求 */
export async function fetchJSON(url) {
  return request(url);
}

/** POST JSON 请求 */
export async function postJSON(url, data = {}) {
  return request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

/** POST 请求（无 body） */
export async function postEmpty(url) {
  return request(url, { method: 'POST' });
}

// ════════════════════════════════════════
// 业务 API 封装 — 语义化调用，消除散落的 URL 字符串
// ════════════════════════════════════════
export const api = {
  getStats:           () => fetchJSON(API.STATS),
  getEpisodes:        () => fetchJSON(API.EPISODES),
  getConfig:          () => fetchJSON(API.CONFIG),
  getTaskStatus:      () => fetchJSON(API.TASK_STATUS),
  cancelTask:         () => postEmpty(API.TASK_CANCEL),
  resetTask:          () => postEmpty(API.TASK_RESET),
  run:         (params) => postJSON(API.RUN, params),
  batch:      (params) => postJSON(API.BATCH, params),
  getScript:      (ep) => fetchJSON(API.EPISODE_SCRIPT(ep)),
  getAnalysis:    (ep) => fetchJSON(API.EPISODE_ANALYSIS(ep)),
  askQuestion: (params) => postJSON(API.QA_ASK, params),
  search:         (q) => fetchJSON(`${API.SEARCH}?q=${encodeURIComponent(q)}`),
};
