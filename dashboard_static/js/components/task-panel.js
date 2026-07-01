// ════════════════════════════════════════
// task-panel.js — 生成面板 + 日志 + 任务轮询
// ════════════════════════════════════════
import { api } from '../api.js';
import { setButtonsDisabled, getPollState, setPollState } from '../state.js';
import { escapeHtml, updateStatusBadge } from '../utils.js';
import { toast } from '../toast.js';

// 两步生成「大纲完成」通知去重标志（避免轮询时重复 console.info）
let _outlineNotified = false;

// ════════════════════════════════════════
// 任务触发
// ════════════════════════════════════════
export async function triggerRun() {
  _outlineNotified = false; // 新任务开始，重置大纲通知标志
  const mockEl = document.getElementById('runMock');
  const dryEl = document.getElementById('runDry');
  const mock = mockEl ? mockEl.checked : false;
  const dry = dryEl ? dryEl.checked : false;

  // 读取内容来源
  const source = document.querySelector('.source-tab.active')?.dataset.source || 'trending';
  let repoUrls = [];
  let topic = '';
  if (source === 'repos') {
    const text = document.getElementById('repoUrlsInput')?.value || '';
    repoUrls = text.split('\n').map(s => s.trim()).filter(s => s);
    if (repoUrls.length === 0) {
      toast.warning('请输入至少一个 GitHub 仓库 URL');
      return;
    }
  } else if (source === 'topic') {
    topic = document.getElementById('topicInput')?.value || '';
    if (!topic.trim()) {
      toast.warning('请输入主题关键词');
      return;
    }
  }

  // 读取风格
  const style = document.querySelector('.style-tab.active')?.dataset.style || 'casual';
  const longform = document.getElementById('longformToggle')?.checked || false;

  // 按钮加载状态
  const btn = document.getElementById('runBtn');
  if (btn) { btn.disabled = true; btn.classList.add('btn-loading'); btn.dataset.originalText = btn.innerHTML; btn.innerHTML = '⏳ 提交中...'; }

  try {
    const d = await api.run({
      mock_data: mock, dry_run: dry,
      repo_urls: repoUrls, topic: topic,
      style: style, longform: longform,
    });
    if (d.error) {
      // 409 冲突：已有任务在运行，提供取消选项
      toast.error(d.error, { duration: 6000, action: { label: '强制停止', callback: () => cancelRunningTask() } });
      return;
    }
    toast.success('播客生成任务已启动');
    setButtonsDisabled(true);
  } catch (e) {
    // HTTP 409 等错误
    if (e.message.includes('409')) {
      toast.error('已有任务在运行中，请等待完成或点击"强制停止"', { duration: 6000, action: { label: '强制停止', callback: () => cancelRunningTask() } });
    } else {
      toast.error('请求失败: ' + e.message);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove('btn-loading'); btn.innerHTML = btn.dataset.originalText || '▶ 生成一期播客'; }
  }
}

export async function triggerBatch() {
  _outlineNotified = false; // 新任务开始，重置大纲通知标志
  const count = parseInt(document.getElementById('batchCount').value) || 5;
  const mockEl = document.getElementById('batchMock');
  const dryEl = document.getElementById('batchDry');
  const resumeEl = document.getElementById('batchResume');
  const mock = mockEl ? mockEl.checked : false;
  const dry = dryEl ? dryEl.checked : false;
  const resume = resumeEl ? resumeEl.checked : false;

  const btn = document.getElementById('batchBtn');
  if (btn) { btn.disabled = true; btn.classList.add('btn-loading'); btn.dataset.originalText = btn.innerHTML; btn.innerHTML = '⏳ 提交中...'; }

  try {
    const d = await api.batch({count, mock_data: mock, dry_run: dry, resume});
    if (d.error) {
      toast.error(d.error, { duration: 6000, action: { label: '强制停止', callback: () => cancelRunningTask() } });
      return;
    }
    toast.success(`批量生成 ${count} 期播客任务已启动`);
    setButtonsDisabled(true);
  } catch (e) {
    if (e.message.includes('409')) {
      toast.error('已有任务在运行中，请等待完成或点击"强制停止"', { duration: 6000, action: { label: '强制停止', callback: () => cancelRunningTask() } });
    } else {
      toast.error('请求失败: ' + e.message);
    }
  } finally {
    if (btn) { btn.disabled = false; btn.classList.remove('btn-loading'); btn.innerHTML = btn.dataset.originalText || '⚡ 开始批量生成'; }
  }
}

// 批量预设
export function setBatchCount(n) {
  const el = document.getElementById('batchCount');
  if (el) el.value = n;
}

// ════════════════════════════════════════
// 日志渲染
// ════════════════════════════════════════
export function renderLog(logLines) {
  const box = document.getElementById('logBox');
  if (!box) return;
  box.innerHTML = logLines.map(line => {
    let cls = 'log-line';
    if (/完成|✅|success/.test(line)) cls += ' success';
    else if (/失败|❌|error|异常/.test(line)) cls += ' error';
    else if (/警告|⚠|warn/.test(line)) cls += ' warn';
    else if (/\[1\/6\]|\[2\/6\]|\[3\/6\]|\[4\/6\]|\[6\/6\]|阶段/.test(line)) cls += ' info';
    return `<div class="${cls}">${escapeHtml(line)}</div>`;
  }).join('');
  box.scrollTop = box.scrollHeight;
}

// ════════════════════════════════════════
// 任务状态轮询
// pollTask 需要访问 loadStats 和 loadEpisodes，通过回调避免循环依赖
// ════════════════════════════════════════
export function createPollTask(onTaskDone) {
  return async function pollTask() {
    let s;
    try {
      s = await api.getTaskStatus();
    } catch (e) {
      console.error('pollTask 失败:', e);
      return;
    }
    updateStatusBadge(s.running);
    const taskLabel = document.getElementById('taskLabel');
    if (taskLabel) {
      taskLabel.textContent = s.running ? `⏳ ${s.type}` : (s.done ? `✅ ${s.type}` : '');
    }
    updateStepper(s.log || []);

    // 任务运行时显示"停止"按钮
    const cancelBtn = document.getElementById('cancelTaskBtn');
    if (cancelBtn) {
      cancelBtn.style.display = s.running ? 'inline-block' : 'none';
    }

    let { lastLogJson, prevDone } = getPollState();

    if (s.log && s.log.length > 0) {
      // 用 JSON.stringify 比较完整内容，避免日志被后端截断到 50 行后长度恒定而不更新
      const logJson = JSON.stringify(s.log);
      if (logJson !== lastLogJson) {
        renderLog(s.log);
        lastLogJson = logJson;
      }
    }

    // 任务结束时刷新数据：仅在 done 从 false→true 跃变时刷新一次，避免无限刷新破坏音频播放
    const isDone = s.done && !s.running;
    if (isDone) {
      setButtonsDisabled(false);
      if (!prevDone) {
        // 任务完成通知
        const hasError = (s.log || []).some(l => /失败|❌|error|异常/.test(l));
        if (hasError) {
          toast.error('播客生成完成（含警告），请查看日志');
        } else {
          toast.success('播客生成完成！可在节目库收听');
        }
        await onTaskDone(); // 回调：刷新 stats 和 episodes
      }
    }
    prevDone = isDone;

    setPollState(lastLogJson, prevDone);
  };
}

// ════════════════════════════════════════
// 进度步骤指示器
// ════════════════════════════════════════
function updateStepper(logLines) {
  const stepper = document.getElementById('stepper');
  if (!stepper) return;

  const steps = stepper.querySelectorAll('.step');
  const lines = stepper.querySelectorAll('.step-line');
  
  // 从日志中检测当前阶段
  let currentStep = 0;
  const fullLog = logLines.join('\n');

  // 两步生成：检测「大纲完成」（步骤1 生成节目大纲 → 大纲完成）
  if (!_outlineNotified && /大纲完成/.test(fullLog)) {
    toast.info('节目大纲已生成，正在展开完整脚本...');
    _outlineNotified = true;
  }
  
  const stepPatterns = [
    { num: 1,   regex: /\[1\/6\]|\[1\/7\]|发现/ },
    { num: 2,   regex: /\[2\/6\]|\[2\/7\]|抓取|README/ },
    { num: 2.1, regex: /\[2\.1|深度内容提取|深提取|文件树|源码/ },
    { num: 2.5, regex: /\[2\.5|项目深度分析|分析/ },
    { num: 3,   regex: /\[3\/6\]|\[3\/7\]|脚本|LLM/ },
    { num: 4,   regex: /\[4\/6\]|\[4\/7\]|TTS|语音合成/ },
    { num: 5,   regex: /\[5\/6\]|\[5\/7\]|拼接|混音|归一化/ },
    { num: 6,   regex: /\[6\/6\]|\[6\/7\]|RSS|发布/ },
  ];
  
  for (const { num, regex } of stepPatterns) {
    if (regex.test(fullLog)) {
      currentStep = num;
    }
  }
  
  // 检测是否全部完成
  const allDone = /完成|✅.*播客生成/.test(fullLog);
  
  steps.forEach(stepEl => {
    const stepNum = parseFloat(stepEl.dataset.step);
    stepEl.classList.remove('active', 'done');
    if (allDone || (currentStep > 0 && stepNum < currentStep)) {
      stepEl.classList.add('done');
    } else if (stepNum === currentStep) {
      stepEl.classList.add('active');
    }
  });
  
  lines.forEach(lineEl => {
    lineEl.classList.remove('active');
  });
  // 激活当前步骤之前的连接线
  if (currentStep > 0) {
    const stepEls = Array.from(steps);
    const currentIdx = stepEls.findIndex(e => parseFloat(e.dataset.step) === currentStep);
    for (let i = 0; i < currentIdx && i < lines.length; i++) {
      lines[i].classList.add('active');
    }
  }
}

// ════════════════════════════════════════
// 内容来源 / 播客风格 切换
// ════════════════════════════════════════
// 切换内容来源
export function switchSource(source) {
  document.querySelectorAll('.source-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.source === source);
  });
  const reposEl = document.getElementById('sourceRepos');
  const topicEl = document.getElementById('sourceTopic');
  if (reposEl) reposEl.style.display = source === 'repos' ? 'block' : 'none';
  if (topicEl) topicEl.style.display = source === 'topic' ? 'block' : 'none';
}

// 切换播客风格
export function switchStyle(style) {
  document.querySelectorAll('.style-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.style === style);
  });
}

// ════════════════════════════
// 任务取消 / 强制重置
// ════════════════════════════
export async function cancelRunningTask() {
  try {
    await api.cancelTask();
    toast.success('任务已停止');
    setButtonsDisabled(false);
    setTimeout(() => pollTaskRef && pollTaskRef(), 500);
  } catch (e) {
    toast.warning('停止失败，正在强制重置...');
    await forceResetTask();
  }
}

export async function forceResetTask() {
  try {
    await api.resetTask();
    toast.success('任务状态已重置');
    setButtonsDisabled(false);
    setTimeout(() => pollTaskRef && pollTaskRef(), 500);
  } catch (e) {
    toast.error('重置失败: ' + e.message);
  }
}

// 保存 pollTask 引用，供 cancelRunningTask 调用
let pollTaskRef = null;
export function setPollTaskRef(fn) {
  pollTaskRef = fn;
}
