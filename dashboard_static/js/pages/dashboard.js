// ════════════════════════════════════════
// dashboard.js — 概览页（抖音式知识卡片信息流）
// 主界面为全屏滑动信息流，生成面板改为底部抽屉
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { loadStats } from '../components/stats.js';
import { initFeed, cleanupFeed, updateFeedPlayState } from '../components/feed.js';
import { createPollTask, triggerRun, triggerBatch, setBatchCount, switchSource, switchStyle, cancelRunningTask, setPollTaskRef } from '../components/task-panel.js';
import { getCurrentPlaying } from '../player.js';
import { POLL_INTERVAL } from '../constants.js';

export const { init, cleanup } = createPage({
  async init(ctx) {
    // 初始化知识卡片信息流
    await initFeed('feedRoot');

    // 加载统计数据到抽屉
    await loadStats();

    // 启动任务轮询
    const pollTask = createPollTask(async () => {
      await loadStats();
      // 任务完成时刷新信息流
      await initFeed('feedRoot');
    });
    setPollTaskRef(pollTask);
    ctx.setInterval(pollTask, POLL_INTERVAL);

    // 事件委托：统一绑定所有 data-action 按钮
    ctx.addListener(document, 'click', handleClick);

    // Stage 3: ARIA 键盘导航 — source-tabs (tablist) 和 style-tabs (button group)
    ctx.addListener(document, 'keydown', handleTabKeyboardNav);

    // 键盘快捷键
    const keydownHandler = (e) => {
      // 如果抽屉打开或焦点在输入框中，不拦截导航键
      const drawer = document.getElementById('genDrawer');
      const isDrawerOpen = drawer && drawer.classList.contains('open');

      // Ctrl+Enter 生成
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        const runBtn = document.getElementById('runBtn');
        if (runBtn && !runBtn.disabled) triggerRun();
        return;
      }
      // Ctrl+Shift+B 批量生成
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
        e.preventDefault();
        const batchBtn = document.getElementById('batchBtn');
        if (batchBtn && !batchBtn.disabled) triggerBatch();
        return;
      }
      // Esc 关闭抽屉
      if (e.key === 'Escape' && isDrawerOpen) {
        closeDrawer();
        return;
      }
    };
    ctx.addListener(document, 'keydown', keydownHandler);

    // 页面可见性变化时自动刷新
    const visHandler = () => {
      if (!document.hidden) {
        loadStats();
      }
    };
    ctx.addListener(document, 'visibilitychange', visHandler);

    // 初始化批量预设按钮的默认选中态
    const defaultBatchCount = parseInt(document.getElementById('batchCount')?.value) || 5;
    setBatchCount(defaultBatchCount);

    // 监听播放状态变化，更新信息流中的播放按钮
    ctx.addListener(document, 'play-state-change', () => {
      updateFeedPlayState(getCurrentPlaying());
    });
  },

  cleanup() {
    cleanupFeed();
  },
});

// ════════════════════════════════════════
// 抽屉控制
// ════════════════════════════════════════
function openDrawer() {
  const drawer = document.getElementById('genDrawer');
  const overlay = document.getElementById('genDrawerOverlay');
  if (!drawer || !overlay) return;
  drawer.classList.add('open');
  overlay.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  // 锁定信息流滚动
  const feedContainer = document.getElementById('feedContainer');
  if (feedContainer) feedContainer.style.overflow = 'hidden';
}

function closeDrawer() {
  const drawer = document.getElementById('genDrawer');
  const overlay = document.getElementById('genDrawerOverlay');
  if (!drawer || !overlay) return;
  drawer.classList.remove('open');
  overlay.classList.remove('open');
  drawer.setAttribute('aria-hidden', 'true');
  // 恢复信息流滚动
  const feedContainer = document.getElementById('feedContainer');
  if (feedContainer) feedContainer.style.overflow = '';
}

// ════════════════════════════════════════
// 事件委托：统一处理页面内所有 data-action 按钮
// ════════════════════════════════════════
function handleClick(e) {
  // 抽屉控制
  if (e.target.id === 'genDrawerOverlay') {
    closeDrawer();
    return;
  }

  const closeBtn = e.target.closest('#genDrawerClose');
  if (closeBtn) {
    closeDrawer();
    return;
  }

  const handle = e.target.closest('#genDrawerHandle');
  if (handle) {
    closeDrawer();
    return;
  }

  const btn = e.target.closest('[data-action]');
  if (!btn) return;

  const action = btn.dataset.action;
  switch (action) {
    case 'toggle-drawer': {
      const drawer = document.getElementById('genDrawer');
      if (drawer && drawer.classList.contains('open')) {
        closeDrawer();
      } else {
        openDrawer();
      }
      break;
    }
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
    default:
      break;
  }
}

// ════════════════════════════════════════
// Stage 3: ARIA 键盘导航
// source-tabs: tablist 模式（Left/Up=前, Right/Down=后, Home=首, End=末）
// style-tabs: toggle button group 模式（同上快捷键，但所有按钮均可聚焦）
// ════════════════════════════════════════
function handleTabKeyboardNav(e) {
  // 仅在焦点位于 tab/button 上时响应
  const target = e.target.closest('.source-tab, .style-tab');
  if (!target) return;

  const isSourceTab = target.classList.contains('source-tab');
  const tabs = Array.from(document.querySelectorAll(isSourceTab ? '.source-tab' : '.style-tab'));
  const currentIdx = tabs.indexOf(target);
  if (currentIdx === -1) return;

  let nextIdx = null;
  switch (e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      nextIdx = (currentIdx + 1) % tabs.length;
      break;
    case 'ArrowLeft':
    case 'ArrowUp':
      nextIdx = (currentIdx - 1 + tabs.length) % tabs.length;
      break;
    case 'Home':
      nextIdx = 0;
      break;
    case 'End':
      nextIdx = tabs.length - 1;
      break;
    default:
      return; // 不拦截其他按键
  }

  e.preventDefault();
  const nextTab = tabs[nextIdx];
  nextTab.focus();

  // 自动切换到聚焦的 tab/button
  if (isSourceTab) {
    switchSource(nextTab.dataset.source);
  } else {
    switchStyle(nextTab.dataset.style);
  }
}

init();
