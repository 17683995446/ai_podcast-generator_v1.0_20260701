// ════════════════════════════════════════
// episodes.js — 节目库页
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { loadEpisodes, toggleScript, toggleAnalysis } from '../components/episodes.js';
import { createPollTask, setPollTaskRef } from '../components/task-panel.js';
import { POLL_INTERVAL } from '../constants.js';

export const { init, cleanup } = createPage({
  async init(ctx) {
    await loadEpisodes();

    // 轮询任务状态（任务完成时刷新节目列表）
    const pollTask = createPollTask(async () => {
      await loadEpisodes();
    });
    setPollTaskRef(pollTask);
    ctx.setInterval(pollTask, POLL_INTERVAL);

    // 事件委托：脚本/分析展开
    ctx.addListener(document, 'click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const epNum = parseInt(btn.dataset.ep);
      if (!epNum) return;

      if (btn.dataset.action === 'toggle-script') {
        toggleScript(epNum, btn);
      } else if (btn.dataset.action === 'toggle-analysis') {
        toggleAnalysis(epNum, btn);
      }
    });
  },
});

init();
