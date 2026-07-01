// ════════════════════════════════════════
// search.js — 搜索页
// 使用 createPage 标准生命周期，事件委托 + 防抖
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { initSearchPanel } from '../components/search-panel.js';

export const { init, cleanup } = createPage({
  async init(ctx) {
    await initSearchPanel(ctx);
  },
});

init();
