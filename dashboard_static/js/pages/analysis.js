// ════════════════════════════════════════
// analysis.js — 项目深度分析页
// 渲染逻辑已提取至 utils/analysis-renderer.js 共享模块
// Stage 10: 懒加载模式 — 初始仅渲染期数标题，点击后按需加载分析数据
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';
import { highlightAll } from '../utils/highlight.js';
import { renderMarkdown } from '../utils/marked.js';
import { renderProjectCard, renderComparisonSection } from '../utils/analysis-renderer.js';

// Mermaid 动态加载（仅加载一次）
let _mermaidLoaded = false;

export const { init, cleanup } = createPage({
  async init(ctx) {
    // SPA 导航时 Mermaid 可能尚未加载，动态加载
    if (!window.mermaid && !_mermaidLoaded) {
      await loadMermaid();
      _mermaidLoaded = true;
    }
    if (window.mermaid) {
      window.mermaid.initialize({ startOnLoad: false, theme: 'dark' });
    }

    await loadAnalysisIndex();

    // 事件委托（绑定到 container，SPA 切换时随 DOM 自动清理）
    setupListeners(ctx);
  },
});

// 动态加载 Mermaid CDN
function loadMermaid() {
  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    script.onload = () => resolve();
    script.onerror = () => {
      console.warn('Mermaid CDN 加载失败，架构图将无法渲染');
      resolve();
    };
    document.head.appendChild(script);
  });
}

/**
 * 加载分析索引（仅节目标题列表，不加载分析详情）
 * Stage 10 优化：从一次性渲染所有分析数据 → 仅渲染标题行
 * 初始 DOM 元素从 ~1700 降至 ~17，大幅减少首屏渲染时间和内存占用
 */
async function loadAnalysisIndex() {
  const container = document.getElementById('analysisList');
  if (!container) return;

  try {
    const episodes = await api.getEpisodes();
    if (!episodes || episodes.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><div>暂无节目</div></div>';
      return;
    }

    // 懒加载模式：仅渲染期数标题行，点击后加载分析数据
    container.innerHTML = episodes.map(ep => `
      <div class="card analysis-card" data-ep="${ep.episode_number}">
        <div class="analysis-card-header" data-action="toggle-analysis-card" role="button" tabindex="0" aria-expanded="false">
          <div class="analysis-card-left">
            <span class="ep-num">EP${String(ep.episode_number).padStart(3,'0')}</span>
            <span class="analysis-card-title">${escapeHtml(ep.title)}</span>
          </div>
          <div class="analysis-card-right">
            <span class="analysis-card-hint">点击展开分析</span>
            <span class="analysis-card-chevron">▶</span>
          </div>
        </div>
        <div class="analysis-card-body" hidden></div>
      </div>
    `).join('');
  } catch (e) {
    console.error('[analysis] 加载分析索引失败:', e);
    container.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><div>加载失败，请刷新重试</div></div>';
  }
}

/**
 * 切换分析卡片展开/收起（懒加载）
 * 首次展开时从 API 加载分析数据，后续切换仅显示/隐藏
 */
async function toggleAnalysisCard(card) {
  const body = card.querySelector('.analysis-card-body');
  const header = card.querySelector('.analysis-card-header');
  const chevron = card.querySelector('.analysis-card-chevron');
  const hint = card.querySelector('.analysis-card-hint');
  const epNum = parseInt(card.dataset.ep);

  // 已展开 → 收起
  if (!body.hidden) {
    body.hidden = true;
    chevron.textContent = '▶';
    hint.textContent = '点击展开分析';
    header.setAttribute('aria-expanded', 'false');
    return;
  }

  // 展开
  body.hidden = false;
  chevron.textContent = '▼';
  hint.textContent = '点击收起';
  header.setAttribute('aria-expanded', 'true');

  // 首次加载分析数据
  if (!card.dataset.loaded) {
    body.innerHTML = `
      <div class="skeleton-card">
        <div class="skeleton skeleton-line medium"></div>
        <div class="skeleton skeleton-line short"></div>
        <div class="skeleton skeleton-line medium"></div>
      </div>
    `;

    try {
      const analysis = await api.getAnalysis(epNum);
      if (analysis.error) {
        body.innerHTML = `<div class="log-empty">${escapeHtml(analysis.error)}</div>`;
        card.dataset.loaded = '1';
        return;
      }

      const projs = analysis.analyses || [];
      const comparisonHtml = renderComparisonSection(analysis.comparison);

      body.innerHTML = `
        <div class="analysis-card-meta">
          <span style="font-size:13px;color:var(--text-dim);">${projs.length} 个项目 · ${escapeHtml(analysis.episode_title || '')}</span>
        </div>
        ${projs.map((proj, idx) => renderProjectCard(proj, idx, projs.length, epNum)).join('')}
        ${comparisonHtml}
      `;
      card.dataset.loaded = '1';

      // Mermaid 图表渲染
      if (window.mermaid) {
        try {
          await window.mermaid.run();
        } catch (e) {
          console.warn('Mermaid 渲染失败:', e);
        }
      }

      // 代码语法高亮
      try {
        await highlightAll(body);
      } catch (e) {
        console.warn('[analysis] 代码高亮失败:', e);
      }
    } catch (e) {
      body.innerHTML = '<div class="log-empty">分析数据加载失败，请重试</div>';
      console.error('[analysis] 加载分析失败:', e);
    }
  }
}

// ════════════════════════════════════════
// 事件委托：分析卡片展开 + Q&A 交互
// ════════════════════════════════════════
function setupListeners(ctx) {
  const list = document.getElementById('analysisList');
  if (!list) return;

  ctx.addListener(list, 'click', async (e) => {
    // ── 分析卡片展开/收起 ──
    const cardHeader = e.target.closest('[data-action="toggle-analysis-card"]');
    if (cardHeader) {
      const card = cardHeader.closest('.analysis-card');
      if (card) {
        await toggleAnalysisCard(card);
      }
      return;
    }

    // ── Q&A 提交按钮点击 ──
    if (!e.target.classList.contains('qa-submit-btn')) return;
    const panel = e.target.closest('.qa-panel');
    if (!panel) return;
    const input = panel.querySelector('.qa-input');
    const answerDiv = panel.querySelector('.qa-answer');
    const question = input.value.trim();
    if (!question) return;

    const repoName = panel.dataset.repo;
    const epNum = parseInt(panel.dataset.ep);

    e.target.disabled = true;
    e.target.textContent = '思考中...';
    answerDiv.innerHTML = '<div class="qa-loading">正在生成回答...</div>';

    try {
      const data = await api.askQuestion({ question, episode_number: epNum, repo_name: repoName });
      if (data.error) {
        answerDiv.innerHTML = `<div class="qa-error">${escapeHtml(data.error)}</div>`;
      } else {
        // 使用项目已有的 marked.js 渲染完整 Markdown（支持代码块、列表、链接等）
        const html = await renderMarkdown(data.answer);
        answerDiv.innerHTML = `<div class="qa-answer-text">${html}</div>`;
      }
    } catch (err) {
      answerDiv.innerHTML = `<div class="qa-error">网络错误：${escapeHtml(String(err))}</div>`;
    } finally {
      e.target.disabled = false;
      e.target.textContent = '提问';
    }
  });

  // ── 分析卡片键盘交互（Enter/Space 展开）──
  ctx.addListener(list, 'keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const cardHeader = e.target.closest('[data-action="toggle-analysis-card"]');
    if (!cardHeader) return;
    e.preventDefault();
    const card = cardHeader.closest('.analysis-card');
    if (card) {
      toggleAnalysisCard(card);
    }
  });

  // ── Q&A 回车键提交 ──
  ctx.addListener(list, 'keypress', (e) => {
    if (e.key !== 'Enter' || !e.target.classList.contains('qa-input')) return;
    e.preventDefault();
    const panel = e.target.closest('.qa-panel');
    if (!panel) return;
    const btn = panel.querySelector('.qa-submit-btn');
    if (btn) btn.click();
  });
}

init();
