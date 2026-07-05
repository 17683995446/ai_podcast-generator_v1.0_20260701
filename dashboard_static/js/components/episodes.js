// ════════════════════════════════════════
// episodes.js — 节目列表组件 + 脚本/分析展开
// 渲染逻辑已提取至 utils/analysis-renderer.js 共享模块
// Stage 10: 新增分页加载（节目库页默认显示 10 期，点击"加载更多"展开）
// ════════════════════════════════════════
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { playEpisode, getCurrentPlaying } from '../player.js';
import { renderAnalysisContainer } from '../utils/analysis-renderer.js';

// ── 分页状态 ──
const PAGE_SIZE = 10;
let _allEpisodes = [];
let _visibleCount = PAGE_SIZE;

/**
 * 渲染单个节目卡片 HTML
 * 提取为独立函数，供初始渲染和"加载更多"复用
 */
function renderEpisodeCard(ep, playingEp) {
  const audioFile = (ep.audio_path || '').split('/').pop();
  const audioUrl = `/audio/${encodeURIComponent(audioFile)}`;
  // 空值安全：duration_seconds / file_size_bytes 可能为 null/undefined
  const duration = ep.duration_seconds ? (ep.duration_seconds / 60).toFixed(1) : '0.0';
  const size = ep.file_size_bytes ? (ep.file_size_bytes / 1024 / 1024).toFixed(2) : '0.00';
  const chars = ep.total_chars || 0;
  const isPlaying = playingEp === ep.episode_number;
  return `
  <article class="episode-item${isPlaying ? ' now-playing' : ''}" data-ep-num="${ep.episode_number}">
    <div class="ep-header">
      <div>
        <span class="ep-num">EP${String(ep.episode_number).padStart(3,'0')}</span>
        <span class="ep-title">${escapeHtml(ep.title)}</span>
        <div class="ep-meta">
          <span class="ep-badge"><span class="dot" style="background:var(--accent)"></span>⏱ ${duration} 分钟</span>
          <span class="ep-badge">📝 ${chars} 字</span>
          <span class="ep-badge">💾 ${size} MB</span>
        </div>
        ${ep.repo_names ? `<div class="ep-repos" style="margin-top:4px;">📦 ${ep.repo_names.map(escapeHtml).join(' · ')}</div>` : ''}
      </div>
      <div class="ep-actions">
        <button class="btn btn-secondary btn-sm ep-play-btn ${isPlaying ? 'playing' : ''}" data-ep="${ep.episode_number}" data-url="${audioUrl}" data-title="${escapeHtml(ep.title)}">${isPlaying ? '⏸ 暂停' : '▶ 播放'}</button>
        <button class="btn btn-secondary btn-sm" data-action="toggle-script" data-ep="${ep.episode_number}">📄 脚本</button>
        <button class="btn btn-secondary btn-sm" data-action="toggle-analysis" data-ep="${ep.episode_number}">📊 分析</button>
        <a class="btn btn-secondary btn-sm" href="${audioUrl}" download>⬇ 下载</a>
      </div>
    </div>
    <div class="script-view" id="script-${ep.episode_number}"></div>
    <div class="analysis-view" id="analysis-${ep.episode_number}"></div>
  </article>
  `;
}

/**
 * 从缓存渲染节目列表（分页模式，不发 API 请求）
 * 用于"加载更多"按钮点击后的局部更新
 */
function renderEpisodeListFromCache() {
  const box = document.getElementById('episodeList');
  if (!box || !_allEpisodes.length) return;

  const playingEp = getCurrentPlaying();
  const display = _allEpisodes.slice(0, _visibleCount);

  box.innerHTML = display.map(ep => renderEpisodeCard(ep, playingEp)).join('');

  // 添加"加载更多"按钮
  if (_visibleCount < _allEpisodes.length) {
    const remaining = _allEpisodes.length - _visibleCount;
    box.insertAdjacentHTML('beforeend', `
      <div class="load-more-wrap">
        <button class="btn btn-secondary load-more-btn" id="loadMoreBtn">
          <span class="load-more-icon">⬇</span>
          <span>加载更多</span>
          <span class="load-more-count">（剩余 ${remaining} 期）</span>
        </button>
      </div>
    `);
    const btn = box.querySelector('#loadMoreBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        _visibleCount = Math.min(_visibleCount + PAGE_SIZE, _allEpisodes.length);
        renderEpisodeListFromCache();
      });
    }
  }

  // 事件委托：播放按钮点击
  box.querySelectorAll('.ep-play-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      playEpisode(btn.dataset.url, btn.dataset.title, parseInt(btn.dataset.ep));
    });
  });

  // URL hash 定位到具体节目（从搜索页"查看详情"跳转过来）
  handleHash();
}

/**
 * 处理 URL hash 定位（#epXXX）
 */
function handleHash() {
  const box = document.getElementById('episodeList');
  if (!box) return;
  const hash = window.location.hash;
  if (hash && hash.startsWith('#ep')) {
    const epNum = hash.substring(3);
    const targetEl = box.querySelector(`[data-ep-num="${epNum}"]`);
    if (targetEl) {
      // 如果目标节目在可见范围之外，自动展开到该节目
      const epNumber = parseInt(epNum);
      if (epNumber > _visibleCount) {
        _visibleCount = Math.min(epNumber, _allEpisodes.length);
        renderEpisodeListFromCache();
        return; // 重新渲染后再滚动
      }
      setTimeout(() => {
        targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetEl.classList.add('highlight-flash');
        setTimeout(() => targetEl.classList.remove('highlight-flash'), 2000);
      }, 100);
    }
  }
}

export async function loadEpisodes(limit) {
  const box = document.getElementById('episodeList');
  if (!box) return;

  // 如果已经有数据，不显示骨架屏（避免闪烁）
  const hasContent = box.querySelector('.episode-item');
  if (!hasContent) {
    box.innerHTML = Array(3).fill(0).map(() => `
      <div class="skeleton-card">
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
    `).join('');
  }

  try {
    const eps = await api.getEpisodes();
    if (!eps || eps.length === 0) {
      box.innerHTML = `
        <div class="empty-state-enhanced">
          <span class="icon">📻</span>
          <div class="title">还没有生成任何节目</div>
          <div class="desc">点击上方「生成一期播客」按钮，自动获取 GitHub 前沿项目并生成音频内容。</div>
        </div>
      `;
      return;
    }

    const playingEp = getCurrentPlaying();

    if (limit) {
      // ── 首页模式：显示限定数量 + "查看全部"链接 ──
      const display = eps.slice(0, limit);
      box.innerHTML = display.map(ep => renderEpisodeCard(ep, playingEp)).join('');
      if (eps.length > limit) {
        box.insertAdjacentHTML('beforeend', `
          <div style="text-align:center;padding:16px;">
            <a class="link" href="/episodes">查看全部 ${eps.length} 期 →</a>
          </div>
        `);
      }
    } else {
      // ── 节目库页模式：分页加载 ──
      // 如果之前已加载全部，新节目加入后保持显示全部
      if (_allEpisodes.length > 0 && _visibleCount >= _allEpisodes.length) {
        _visibleCount = eps.length;
      }
      // 如果总数减少了（删除了节目），防止 visibleCount 超出
      if (_visibleCount > eps.length) {
        _visibleCount = eps.length;
      }
      // 首次加载时确保至少显示 PAGE_SIZE
      if (_allEpisodes.length === 0) {
        _visibleCount = Math.min(PAGE_SIZE, eps.length);
      }
      _allEpisodes = eps;

      renderEpisodeListFromCache();
      return; // renderEpisodeListFromCache 已处理事件绑定和 hash
    }

    // 事件委托：播放按钮点击（首页模式）
    box.querySelectorAll('.ep-play-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        playEpisode(btn.dataset.url, btn.dataset.title, parseInt(btn.dataset.ep));
      });
    });

    // URL hash 定位（首页模式）
    const hash = window.location.hash;
    if (hash && hash.startsWith('#ep')) {
      const epNum = hash.substring(3);
      const targetEl = box.querySelector(`[data-ep-num="${epNum}"]`);
      if (targetEl) {
        setTimeout(() => {
          targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
          targetEl.classList.add('highlight-flash');
          setTimeout(() => targetEl.classList.remove('highlight-flash'), 2000);
        }, 100);
      }
    }
  } catch (e) {
    box.innerHTML = `
      <div class="empty-state-enhanced">
        <span class="icon">⚠️</span>
        <div class="title">节目列表加载失败</div>
        <div class="desc">请检查网络连接后刷新页面重试。</div>
      </div>
    `;
    console.error('loadEpisodes 失败:', e);
  }
}

// ════════════════════════════════════════
// 脚本查看
// ════════════════════════════════════════
export async function toggleScript(epNum, btn) {
  const el = document.getElementById(`script-${epNum}`);
  if (el.classList.contains('open')) {
    el.classList.remove('open');
    btn.textContent = '📄 脚本';
    return;
  }
  el.classList.add('open');
  btn.textContent = '📄 收起';
  if (!el.dataset.loaded) {
    el.innerHTML = `
      <div class="skeleton-line medium"></div>
      <div class="skeleton-line short"></div>
      <div class="skeleton-line medium"></div>
    `;
    try {
      const data = await api.getScript(epNum);
      if (data.error) {
        el.innerHTML = `<div class="log-empty">${escapeHtml(data.error)}</div>`;
        return;
      }
      el.innerHTML = `
        <div style="font-size:13px;font-weight:700;margin-bottom:10px;">${escapeHtml(data.title)}</div>
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px;">${escapeHtml(data.description || '')}</div>
        ${data.segments.map(s => `
          <div class="script-seg ${s.voice_key}">
            <div class="seg-speaker">${escapeHtml(s.speaker)} · ${escapeHtml(s.emotion || '')}</div>
            <div class="seg-text">${escapeHtml(s.text)}</div>
          </div>
        `).join('')}
      `;
      el.dataset.loaded = '1';
    } catch(e) {
      el.innerHTML = '<div class="log-empty">加载失败，请重试</div>';
      console.error('toggleScript 失败:', e);
    }
  }
}

// ════════════════════════════════════════
// 项目深度分析展开
// 使用共享渲染器 analysis-renderer.js，与分析页渲染逻辑完全一致
// ════════════════════════════════════════
export async function toggleAnalysis(epNum, btn) {
  const el = document.getElementById(`analysis-${epNum}`);
  if (el.classList.contains('open')) {
    el.classList.remove('open');
    btn.textContent = '📊 分析';
    return;
  }
  el.classList.add('open');
  btn.textContent = '📊 收起';
  if (!el.dataset.loaded) {
    el.innerHTML = `
      <div class="skeleton-card">
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
    `;
    try {
      const data = await api.getAnalysis(epNum);
      if (data.error) {
        el.innerHTML = `<div class="log-empty">${escapeHtml(data.error)}</div>`;
        return;
      }
      el.innerHTML = renderAnalysisContainer(data, epNum);
      el.dataset.loaded = '1';

      // 内联展开时也触发 Mermaid 渲染（如果已加载）
      if (window.mermaid) {
        try {
          await window.mermaid.run();
        } catch (e) {
          console.warn('Mermaid 渲染失败:', e);
        }
      }

      // 代码语法高亮
      try {
        const { highlightAll } = await import('../utils/highlight.js');
        await highlightAll(el);
      } catch (e) {
        console.warn('[episodes] 代码高亮失败:', e);
      }
    } catch (e) {
      el.innerHTML = '<div class="log-empty">分析数据加载失败，请重试</div>';
      console.error('toggleAnalysis 失败:', e);
    }
  }
}
