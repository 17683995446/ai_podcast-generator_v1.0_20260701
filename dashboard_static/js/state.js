// ════════════════════════════════════════
// state.js — 全局状态管理
// ════════════════════════════════════════

// 任务轮询状态
let lastLogJson = '';
let prevDone = false;

export function getPollState() {
  return { lastLogJson, prevDone };
}

export function setPollState(log, done) {
  lastLogJson = log;
  prevDone = done;
}

// 按钮状态（生成一期 / 批量生成）
export function setButtonsDisabled(disabled) {
  const runBtn = document.getElementById('runBtn');
  const batchBtn = document.getElementById('batchBtn');
  if (runBtn) runBtn.disabled = disabled;
  if (batchBtn) batchBtn.disabled = disabled;
}
