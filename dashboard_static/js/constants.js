// ════════════════════════════════════════
// constants.js — 全局常量定义
// 统一管理 API 端点、轮询间隔等常量
// ════════════════════════════════════════

/** API 端点路径 */
export const API = {
  STATS:        '/api/stats',
  EPISODES:     '/api/episodes',
  CONFIG:       '/api/config',
  FEED:         '/api/feed',
  TASK_STATUS:  '/api/task/status',
  TASK_CANCEL:  '/api/task/cancel',
  TASK_RESET:   '/api/task/reset',
  RUN:          '/api/run',
  BATCH:        '/api/batch',
  EPISODE_SCRIPT:   (epNum) => `/api/episode/${epNum}/script`,
  EPISODE_ANALYSIS: (epNum) => `/api/episode/${epNum}/analysis`,
  QA_ASK:           '/api/qa/ask',
  SEARCH:           '/api/search',
};

// 注意：前端路由路径统一定义在 router.js 的 ROUTES 对象中，
// 此处不再重复定义，避免多处维护导致不一致。

/** 轮询间隔（毫秒） */
export const POLL_INTERVAL = 1500;

/** Toast 自动消失时长（毫秒） */
export const TOAST_DURATION = 3500;
