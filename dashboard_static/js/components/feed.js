// ════════════════════════════════════════
// feed.js — 抖音式知识卡片信息流
// 全屏滑动 · 上下切换 · 右侧操作栏 · 键盘导航
// ════════════════════════════════════════
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { playEpisode, getCurrentPlaying } from '../player.js';

// ── 状态 ──
let _episodes = [];
let _currentIndex = 0;
let _touchStartY = 0;
let _touchStartX = 0;
let _isScrolling = false;

/**
 * 初始化知识卡片信息流
 * @param {string} containerId - 信息流容器元素 ID
 */
export async function initFeed(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // 骨架屏
  container.innerHTML = `
    <div class="feed-container" id="feedContainer">
      <div class="feed-card feed-skeleton">
        <div class="skeleton skeleton-line large"></div>
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
      </div>
    </div>
  `;

  try {
    _episodes = await api.getEpisodes();
    if (!_episodes || _episodes.length === 0) {
      renderEmptyState(container);
      return;
    }
    renderFeed(container);
    setupNavigation(container);
  } catch (e) {
    container.innerHTML = `
      <div class="feed-container">
        <div class="feed-error">
          <span class="icon">⚠️</span>
          <div>加载失败，请刷新重试</div>
        </div>
      </div>
    `;
    console.error('[feed] 加载失败:', e);
  }
}

/**
 * 渲染信息流
 */
function renderFeed(container) {
  const playingEp = getCurrentPlaying();

  container.innerHTML = `
    <div class="feed-container" id="feedContainer">
      ${_episodes.map((ep, idx) => renderKnowledgeCard(ep, idx, playingEp)).join('')}
    </div>
    <!-- 右侧进度指示器 -->
    <div class="feed-progress-dots" id="feedProgressDots" aria-hidden="true">
      ${_episodes.map((_, idx) => `<div class="feed-dot${idx === 0 ? ' active' : ''}" data-idx="${idx}"></div>`).join('')}
    </div>
    <!-- 上滑提示 -->
    <div class="feed-swipe-hint" id="feedSwipeHint">
      <span class="swipe-icon">⌃</span>
      <span class="swipe-text">上滑查看下一期</span>
    </div>
  `;
}

/**
 * 渲染单个知识卡片
 */
function renderKnowledgeCard(ep, idx, playingEp) {
  const audioFile = (ep.audio_path || '').split('/').pop();
  const audioUrl = `/audio/${encodeURIComponent(audioFile)}`;
  const duration = ep.duration_seconds ? (ep.duration_seconds / 60).toFixed(1) : '0.0';
  const size = ep.file_size_bytes ? (ep.file_size_bytes / 1024 / 1024).toFixed(2) : '0.00';
  const chars = ep.total_chars || 0;
  const isPlaying = playingEp === ep.episode_number;
  const repos = ep.repo_names || [];
  const isActive = idx === 0;

  // 为每张卡片分配背景图（基于期数循环 6 张图）
  const bgImages = [
    '/images/feed-bg-1.jpg',
    '/images/feed-bg-2.jpg',
    '/images/feed-bg-3.jpg',
    '/images/feed-bg-4.jpg',
    '/images/feed-bg-5.jpg',
    '/images/feed-bg-6.jpg',
  ];
  const bgImage = bgImages[ep.episode_number % bgImages.length];

  return `
    <div class="feed-card${isActive ? ' active' : ''}" data-idx="${idx}" data-ep="${ep.episode_number}" style="--card-bg-image: url('${bgImage}')">
      <!-- 背景图 + 暗色叠层 -->
      <div class="feed-card-bg"></div>

      <!-- 卡片内容 -->
      <div class="feed-card-content">
        <!-- 顶部：期数标签 -->
        <div class="feed-card-top">
          <span class="feed-ep-badge">EP${String(ep.episode_number).padStart(3, '0')}</span>
          <span class="feed-ep-date">${escapeHtml(ep.created_at || '')}</span>
        </div>

        <!-- 中间：标题 + 描述 -->
        <div class="feed-card-body">
          <h2 class="feed-card-title">${escapeHtml(ep.title)}</h2>
          ${repos.length > 0 ? `
            <div class="feed-card-repos">
              ${repos.map(r => `<span class="feed-repo-tag">📦 ${escapeHtml(r)}</span>`).join('')}
            </div>
          ` : ''}
          <div class="feed-card-stats">
            <span class="feed-stat">⏱ ${duration} 分钟</span>
            <span class="feed-stat">📝 ${chars} 字</span>
            <span class="feed-stat">💾 ${size} MB</span>
          </div>
        </div>

        <!-- 底部：音频波形 + 播放按钮 -->
        <div class="feed-card-bottom">
          <div class="feed-waveform" data-ep="${ep.episode_number}">
            ${Array(40).fill(0).map(() => `<div class="wave-bar" style="height:${20 + Math.random() * 60}%"></div>`).join('')}
          </div>
        </div>
      </div>

      <!-- 右侧操作栏（抖音风格） -->
      <div class="feed-action-bar">
        <button class="feed-action-btn feed-play-btn ${isPlaying ? 'playing' : ''}" data-action="feed-play" data-ep="${ep.episode_number}" data-url="${audioUrl}" data-title="${escapeHtml(ep.title)}" aria-label="${isPlaying ? '暂停' : '播放'}">
          <span class="action-icon">${isPlaying ? '⏸' : '▶'}</span>
          <span class="action-label">播放</span>
        </button>
        <button class="feed-action-btn" data-action="feed-script" data-ep="${ep.episode_number}" aria-label="查看脚本">
          <span class="action-icon">📄</span>
          <span class="action-label">脚本</span>
        </button>
        <button class="feed-action-btn" data-action="feed-analysis" data-ep="${ep.episode_number}" aria-label="项目分析">
          <span class="action-icon">🔬</span>
          <span class="action-label">分析</span>
        </button>
        <a class="feed-action-btn" href="${audioUrl}" download aria-label="下载音频">
          <span class="action-icon">⬇</span>
          <span class="action-label">下载</span>
        </a>
        <a class="feed-action-btn" href="/episodes#ep${ep.episode_number}" aria-label="详情页">
          <span class="action-icon">↗</span>
          <span class="action-label">详情</span>
        </a>
      </div>

      <!-- 展开区域：脚本/分析（默认隐藏） -->
      <div class="feed-expand-area" id="feed-expand-${ep.episode_number}" hidden></div>
    </div>
  `;
}

/**
 * 渲染空状态
 */
function renderEmptyState(container) {
  container.innerHTML = `
    <div class="feed-container">
      <div class="feed-empty">
        <div class="feed-empty-icon">📻</div>
        <div class="feed-empty-title">还没有播客节目</div>
        <div class="feed-empty-desc">点击右下角按钮生成第一期播客</div>
      </div>
    </div>
  `;
}

// ════════════════════════════════════════
// 导航逻辑：滚动捕捉 + 触摸滑动 + 键盘
// ════════════════════════════════════════
function setupNavigation(container) {
  const feedContainer = document.getElementById('feedContainer');
  if (!feedContainer) return;

  // ── 滚动捕捉导航 ──
  let scrollTimeout;
  feedContainer.addEventListener('scroll', () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      const cards = feedContainer.querySelectorAll('.feed-card');
      const cardHeight = feedContainer.clientHeight;
      const newIndex = Math.round(feedContainer.scrollTop / cardHeight);
      if (newIndex !== _currentIndex && newIndex >= 0 && newIndex < cards.length) {
        _currentIndex = newIndex;
        updateActiveCard(feedContainer, newIndex);
      }
    }, 80);
  }, { passive: true });

  // ── 触摸滑动（移动端增强） ──
  feedContainer.addEventListener('touchstart', (e) => {
    _touchStartY = e.touches[0].clientY;
    _touchStartX = e.touches[0].clientX;
    _isScrolling = false;
  }, { passive: true });

  feedContainer.addEventListener('touchmove', (e) => {
    const deltaY = e.touches[0].clientY - _touchStartY;
    const deltaX = e.touches[0].clientX - _touchStartX;
    if (Math.abs(deltaY) > Math.abs(deltaX)) {
      _isScrolling = true;
    }
  }, { passive: true });

  // ── 键盘导航 ──
  document.addEventListener('keydown', handleKeydown);

  // ── 操作栏点击 ──
  feedContainer.addEventListener('click', handleFeedClick);

  // ── 进度点点击 ──
  const dots = document.getElementById('feedProgressDots');
  if (dots) {
    dots.addEventListener('click', (e) => {
      const dot = e.target.closest('.feed-dot');
      if (dot) {
        const idx = parseInt(dot.dataset.idx);
        scrollToCard(feedContainer, idx);
      }
    });
  }
}

/**
 * 键盘导航处理
 */
function handleKeydown(e) {
  // 如果焦点在输入框中，不拦截
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.key) {
    case 'ArrowDown':
    case 'ArrowRight':
    case 'PageDown':
      e.preventDefault();
      navigateNext();
      break;
    case 'ArrowUp':
    case 'ArrowLeft':
    case 'PageUp':
      e.preventDefault();
      navigatePrev();
      break;
    case 'Home':
      e.preventDefault();
      scrollToCard(document.getElementById('feedContainer'), 0);
      break;
    case 'End':
      e.preventDefault();
      scrollToCard(document.getElementById('feedContainer'), _episodes.length - 1);
      break;
  }
}

function navigateNext() {
  if (_currentIndex < _episodes.length - 1) {
    scrollToCard(document.getElementById('feedContainer'), _currentIndex + 1);
  }
}

function navigatePrev() {
  if (_currentIndex > 0) {
    scrollToCard(document.getElementById('feedContainer'), _currentIndex - 1);
  }
}

function scrollToCard(container, idx) {
  if (!container) return;
  const cardHeight = container.clientHeight;
  container.scrollTo({ top: idx * cardHeight, behavior: 'smooth' });
}

/**
 * 更新激活卡片状态
 */
function updateActiveCard(container, idx) {
  const cards = container.querySelectorAll('.feed-card');
  cards.forEach((card, i) => {
    card.classList.toggle('active', i === idx);
  });

  // 更新进度点
  const dots = document.querySelectorAll('.feed-dot');
  dots.forEach((dot, i) => {
    dot.classList.toggle('active', i === idx);
  });

  // 隐藏上滑提示（第一张之后）
  const hint = document.getElementById('feedSwipeHint');
  if (hint) {
    hint.style.opacity = idx > 0 ? '0' : '';
  }
}

/**
 * 处理信息流内点击事件
 */
function handleFeedClick(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;

  const action = btn.dataset.action;
  const epNum = parseInt(btn.dataset.ep);

  switch (action) {
    case 'feed-play': {
      const url = btn.dataset.url;
      const title = btn.dataset.title;
      playEpisode(url, title, epNum);
      // 更新按钮状态
      const isPlaying = getCurrentPlaying() === epNum;
      btn.classList.toggle('playing', isPlaying);
      btn.querySelector('.action-icon').textContent = isPlaying ? '⏸' : '▶';
      break;
    }
    case 'feed-script': {
      toggleFeedExpand(epNum, 'script');
      break;
    }
    case 'feed-analysis': {
      toggleFeedExpand(epNum, 'analysis');
      break;
    }
  }
}

/**
 * 展开/收起脚本或分析
 */
async function toggleFeedExpand(epNum, type) {
  const area = document.getElementById(`feed-expand-${epNum}`);
  if (!area) return;

  // 已展开 → 收起
  if (!area.hidden && area.dataset.type === type) {
    area.hidden = true;
    area.dataset.type = '';
    return;
  }

  // 展开并加载数据
  area.hidden = false;
  area.dataset.type = type;
  area.innerHTML = `<div class="feed-expand-loading">加载中...</div>`;

  try {
    if (type === 'script') {
      const data = await api.getScript(epNum);
      if (data.error) {
        area.innerHTML = `<div class="feed-expand-error">${escapeHtml(data.error)}</div>`;
        return;
      }
      area.innerHTML = `
        <div class="feed-script-content">
          <div class="feed-script-title">${escapeHtml(data.title)}</div>
          <div class="feed-script-desc">${escapeHtml(data.description || '')}</div>
          ${data.segments.map(s => `
            <div class="feed-script-seg ${s.voice_key}">
              <div class="seg-speaker">${escapeHtml(s.speaker)} · ${escapeHtml(s.emotion || '')}</div>
              <div class="seg-text">${escapeHtml(s.text)}</div>
            </div>
          `).join('')}
        </div>
      `;
    } else if (type === 'analysis') {
      const data = await api.getAnalysis(epNum);
      if (data.error) {
        area.innerHTML = `<div class="feed-expand-error">${escapeHtml(data.error)}</div>`;
        return;
      }
      const projs = data.analyses || [];
      area.innerHTML = `
        <div class="feed-analysis-content">
          ${projs.map(proj => `
            <div class="feed-proj-card">
              <div class="feed-proj-name">${escapeHtml(proj.repo_name || '')}</div>
              <div class="feed-proj-desc">${escapeHtml(proj.description || '')}</div>
              ${proj.tech_stack ? `<div class="feed-proj-tags">${proj.tech_stack.map(t => `<span class="feed-tech-tag">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch (e) {
    area.innerHTML = `<div class="feed-expand-error">加载失败，请重试</div>`;
    console.error('[feed] 展开失败:', e);
  }
}

/**
 * 更新播放状态（供外部调用）
 */
export function updateFeedPlayState(playingEp) {
  document.querySelectorAll('.feed-play-btn').forEach(btn => {
    const ep = parseInt(btn.dataset.ep);
    const isPlaying = ep === playingEp;
    btn.classList.toggle('playing', isPlaying);
    const icon = btn.querySelector('.action-icon');
    if (icon) icon.textContent = isPlaying ? '⏸' : '▶';
  });
}

/**
 * 清理信息流（页面切换时调用）
 */
export function cleanupFeed() {
  document.removeEventListener('keydown', handleKeydown);
  _episodes = [];
  _currentIndex = 0;
}
