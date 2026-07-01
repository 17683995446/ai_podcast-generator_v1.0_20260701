// ════════════════════════════════════════
// constants.js — 全局常量定义
// 统一管理 API 端点、路由路径、轮询间隔等常量
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

/** 前端路由路径 */
export const ROUTES = {
  DASHBOARD: '/',
  EPISODES:  '/episodes',
  ANALYSIS:  '/analysis',
  CONFIG:    '/config',
  SEARCH:    '/search',
};

/** 轮询间隔（毫秒） */
export const POLL_INTERVAL = 1500;

/** Toast 自动消失时长（毫秒） */
export const TOAST_DURATION = 3500;
