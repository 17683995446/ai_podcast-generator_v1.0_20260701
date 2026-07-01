// ════════════════════════════════════════
// config.js — 配置页
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { loadConfig } from '../components/config-panel.js';

export const { init, cleanup } = createPage({
  async init(ctx) {
    await loadConfig();
  },
});

init();
