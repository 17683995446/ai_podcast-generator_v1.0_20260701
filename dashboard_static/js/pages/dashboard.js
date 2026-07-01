// ════════════════════════════════════════
// dashboard.js — 概览页
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { loadStats } from '../components/stats.js';
import { loadEpisodes, toggleScript, toggleAnalysis } from '../components/episodes.js';
import { createPollTask, triggerRun, triggerBatch, setBatchCount, switchSource, switchStyle, cancelRunningTask, setPollTaskRef } from '../components/task-panel.js';
import { POLL_INTERVAL } from '../constants.js';

export const { init, cleanup } = createPage({
  async init(ctx) {
    // 并行加载统计和节目数据
    await Promise.all([loadStats(), loadEpisodes(3)]);

    // 启动任务轮询
    const pollTask = createPollTask(async () => {
      await loadStats();
      await loadEpisodes(3);
    });
    setPollTaskRef(pollTask);
    ctx.setInterval(pollTask, POLL_INTERVAL);

    // 事件委托：统一绑定所有按钮交互（消除 inline onclick）
    ctx.addListener(document, 'click', handleClick);

    // 键盘快捷键
    const keydownHandler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        const runBtn = document.getElementById('runBtn');
        if (runBtn && !runBtn.disabled) triggerRun();
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
        e.preventDefault();
        const batchBtn = document.getElementById('batchBtn');
        if (batchBtn && !batchBtn.disabled) triggerBatch();
      }
    };
    ctx.addListener(document, 'keydown', keydownHandler);

    // 页面可见性变化时自动刷新
    const visHandler = () => {
      if (!document.hidden) {
        loadStats();
        loadEpisodes(3);
      }
    };
    ctx.addListener(document, 'visibilitychange', visHandler);
  },
});

// ════════════════════════════════════════
// 事件委托：统一处理页面内所有 data-action 按钮
// ════════════════════════════════════════
function handleClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;

  const action = btn.dataset.action;
  switch (action) {
    case 'run':
      triggerRun();
      break;
    case 'batch':
      triggerBatch();
      break;
    case 'set-batch-count': {
      const n = parseInt(btn.dataset.count);
      if (n) setBatchCount(n);
      break;
    }
    case 'switch-source':
      switchSource(btn.dataset.source);
      break;
    case 'switch-style':
      switchStyle(btn.dataset.style);
      break;
    case 'cancel-task':
      cancelRunningTask();
      break;
    case 'toggle-script': {
      const epNum = parseInt(btn.dataset.ep);
      if (epNum) toggleScript(epNum, btn);
      break;
    }
    case 'toggle-analysis': {
      const epNum = parseInt(btn.dataset.ep);
      if (epNum) toggleAnalysis(epNum, btn);
      break;
    }
    default:
      break;
  }
}

init();
