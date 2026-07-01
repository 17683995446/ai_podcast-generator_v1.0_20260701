// ════════════════════════════════════════
// search-panel.js — 搜索面板组件
// 防抖输入 + 事件委托 + 结果渲染
// ════════════════════════════════════════
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { playEpisode, getCurrentPlaying } from '../player.js';

/** 防抖延迟（毫秒） */
const DEBOUNCE_MS = 300;

/** 最小搜索词长度 */
const MIN_QUERY_LEN = 1;

// 命中字段 → 中文标签 + 颜色
const MATCH_LABELS = {
  title:  { text: '标题命中', color: 'var(--accent)' },
  repo:   { text: '仓库命中', color: 'var(--blue)' },
  script: { text: '脚本命中', color: 'var(--green)' },
};

/**
 * 初始化搜索面板
 * @param {Object} ctx — createPage 提供的资源上下文
 */
export async function initSearchPanel(ctx) {
  const input = document.getElementById('searchInput');
  const clearBtn = document.getElementById('searchClearBtn');
  const resultsBox = document.getElementById('searchResults');

  if (!input || !resultsBox) return;

  // ── 防抖搜索 ──
  let debounceTimer = null;
  let lastQuery = '';

  const doSearch = async (query) => {
    query = query.trim();
    if (query.length < MIN_QUERY_LEN) {
      clearBtn.style.display = 'none';
      renderEmpty(resultsBox);
      return;
    }

    clearBtn.style.display = 'block';

    // 避免重复搜索相同词
    if (query === lastQuery) return;
    lastQuery = query;

    renderLoading(resultsBox);

    try {
      const res = await api.search(query);
      // API 返回 { ok, data, total, query }
      const results = res.data || res || [];
      renderResults(resultsBox, results, query);
    } catch (e) {
      renderError(resultsBox, e.message);
    }
  };

  // 输入事件（防抖）
  ctx.addListener(input, 'input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = ctx.setTimeout(() => doSearch(input.value), DEBOUNCE_MS);
  });

  // 回车立即搜索
  ctx.addListener(input, 'keydown', (e) => {
    if (e.key === 'Enter') {
      clearTimeout(debounceTimer);
      doSearch(input.value);
    }
  });

  // 清除按钮
  ctx.addListener(clearBtn, 'click', () => {
    input.value = '';
    clearBtn.style.display = 'none';
    lastQuery = '';
    renderEmpty(resultsBox);
    input.focus();
  });

  // 建议词点击
  ctx.addListener(document, 'click', (e) => {
    const chip = e.target.closest('.suggestion-chip');
    if (!chip) return;
    input.value = chip.dataset.q;
    doSearch(chip.dataset.q);
  });

  // 结果区事件委托（播放 / 脚本 / 分析）
  ctx.addListener(resultsBox, 'click', (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;

    switch (btn.dataset.action) {
      case 'play': {
        const ep = parseInt(btn.dataset.ep);
        const url = btn.dataset.url;
        const title = btn.dataset.title;
        playEpisode(url, title, ep);
        break;
      }
      case 'view-episode': {
        // 跳转到节目库页面
        window.location.href = '/episodes';
        break;
      }
    }
  });

  // 自动聚焦输入框
  input.focus();
}

// ════════════════════════════════════════
// 渲染函数
// ════════════════════════════════════════

function renderEmpty(box) {
  box.innerHTML = `
    <div class="search-empty-state">
      <span class="icon">🔍</span>
      <div class="title">输入关键词开始搜索</div>
      <div class="desc">搜索范围涵盖节目标题、涉及的 GitHub 仓库名，以及每期播客的完整脚本内容。</div>
    </div>
  `;
}

function renderLoading(box) {
  box.innerHTML = `
    <div class="search-loading">
      <div class="skeleton-card">
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
      <div class="skeleton-card">
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
    </div>
  `;
}

function renderError(box, msg) {
  box.innerHTML = `
    <div class="search-empty-state">
      <span class="icon">⚠️</span>
      <div class="title">搜索失败</div>
      <div class="desc">${escapeHtml(msg)}</div>
    </div>
  `;
}

function renderResults(box, results, query) {
  if (!results || results.length === 0) {
    box.innerHTML = `
      <div class="search-empty-state">
        <span class="icon">📭</span>
        <div class="title">未找到匹配「${escapeHtml(query)}」的节目</div>
        <div class="desc">试试其他关键词，或检查拼写。</div>
      </div>
    `;
    return;
  }

  const playingEp = getCurrentPlaying();
  const cards = results.map(r => {
    const matchInfo = MATCH_LABELS[r.matched_in] || MATCH_LABELS.title;
    const epNum = String(r.episode_number).padStart(3, '0');
    const duration = (r.duration_seconds / 60).toFixed(1);
    const isPlaying = playingEp === r.episode_number;

    // 音频 URL
    const audioFile = (r.audio_path || '').split('/').pop() || `ep${r.episode_number}.mp3`;
    const audioUrl = `/audio/${encodeURIComponent(audioFile)}`;

    // 仓库列表
    const reposHtml = (r.repo_names && r.repo_names.length > 0)
      ? `<div class="search-result-repos">📦 ${r.repo_names.map(escapeHtml).join(' · ')}</div>`
      : '';

    // 命中片段（脚本命中时显示）
    const snippetHtml = r.snippet && r.matched_in === 'script'
      ? `<div class="search-result-snippet">${highlightKeyword(escapeHtml(r.snippet), query)}</div>`
      : '';

    return `
      <div class="card search-result-item fade-in">
        <div class="search-result-header">
          <div class="search-result-info">
            <span class="ep-num">EP${epNum}</span>
            <span class="search-result-title">${highlightKeyword(escapeHtml(r.title), query)}</span>
            <span class="match-badge" style="background:${matchInfo.color}1a;color:${matchInfo.color};border-color:${matchInfo.color}33;">
              ${matchInfo.text}
            </span>
          </div>
          <div class="search-result-actions">
            <button class="btn btn-secondary btn-sm ${isPlaying ? 'playing' : ''}"
                    data-action="play" data-ep="${r.episode_number}"
                    data-url="${audioUrl}" data-title="${escapeHtml(r.title)}">
              ${isPlaying ? '⏸ 暂停' : '▶ 播放'}
            </button>
            <a class="btn btn-secondary btn-sm" data-action="view-episode" href="/episodes">查看详情</a>
          </div>
        </div>
        <div class="search-result-meta">
          <span class="ep-badge"><span class="dot" style="background:var(--accent)"></span>⏱ ${duration} 分钟</span>
          <span class="ep-badge">📝 ${r.total_chars || 0} 字</span>
        </div>
        ${reposHtml}
        ${snippetHtml}
      </div>
    `;
  }).join('');

  box.innerHTML = `
    <div class="search-results-header">
      找到 <strong>${results.length}</strong> 条与「${escapeHtml(query)}」相关的结果
    </div>
    ${cards}
  `;
}

/**
 * 高亮关键词（在已转义的 HTML 文本中标记关键词）
 */
function highlightKeyword(escapedText, query) {
  if (!query) return escapedText;
  const escapedQuery = escapeHtml(query);
  const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return escapedText.replace(regex, '<mark class="search-highlight">$1</mark>');
}
