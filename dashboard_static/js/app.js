// ════════════════════════════════════════
// app.js — 全局 Shell：初始化主题 + SPA 路由 + 持久播放器
// 在每个 HTML 页面中通过 <script type="module" src="/js/app.js"> 加载
// ════════════════════════════════════════
import { initTheme } from './theme.js';
import { initRouter } from './router.js';
import { initPlayer } from './player.js';

// 初始化主题（尽早执行，避免闪烁）
initTheme();

// 初始化 SPA 路由（拦截后续导航，避免完整页面重载）
initRouter();

// 初始化持久化音频播放器（悬浮在底部，跨页面持续播放）
initPlayer();
