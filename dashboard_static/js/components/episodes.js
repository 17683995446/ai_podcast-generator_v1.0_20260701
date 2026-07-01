// ════════════════════════════════════════
// episodes.js — 节目列表组件 + 脚本/分析展开
// ════════════════════════════════════════
import { api } from '../api.js';
import { escapeHtml, pickTagColor } from '../utils.js';
import { playEpisode, getCurrentPlaying } from '../player.js';

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
    const display = limit ? eps.slice(0, limit) : eps;
    const playingEp = getCurrentPlaying();
    box.innerHTML = display.map(ep => {
      const audioFile = (ep.audio_path || '').split('/').pop();
      const audioUrl = `/audio/${encodeURIComponent(audioFile)}`;
      const duration = (ep.duration_seconds/60).toFixed(1);
      const size = (ep.file_size_bytes/1024/1024).toFixed(2);
      const chars = ep.total_chars || 0;
      const isPlaying = playingEp === ep.episode_number;
      return `
      <div class="episode-item">
        <div class="ep-header">
          <div>
            <span class="ep-num">EP${String(ep.episode_number).padStart(3,'0')}</span>
            <span class="ep-title">${escapeHtml(ep.title)}</span>
            <div class="ep-meta">
              <span class="ep-badge"><span class="dot" style="background:var(--accent)"></span>⏱ ${duration} 分钟</span>
              <span class="ep-badge">📝 ${chars} 字</span>
              <span class="ep-badge">💾 ${size} MB</span>
            </div>
            ${ep.repo_names ? `<div class="ep-meta" style="margin-top:4px;">📦 ${ep.repo_names.map(escapeHtml).join(' · ')}</div>` : ''}
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
      </div>
      `;
    }).join('');
    if (limit && eps.length > limit) {
      box.innerHTML += `<div style="text-align:center;padding:16px;"><a class="link" href="/episodes">查看全部 ${eps.length} 期 →</a></div>`;
    }
    // 事件委托：播放按钮点击
    box.querySelectorAll('.ep-play-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        playEpisode(btn.dataset.url, btn.dataset.title, parseInt(btn.dataset.ep));
      });
    });
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
      el.innerHTML = renderAnalysis(data);
      el.dataset.loaded = '1';
    } catch (e) {
      el.innerHTML = '<div class="log-empty">暂无分析数据</div>';
      console.error('toggleAnalysis 失败:', e);
    }
  }
}

// ════════════════════════════════════════
// 分析 JSON → HTML 渲染（内部函数）
// 与 analysis.js 页面共享 renderProjectCard 逻辑
// ════════════════════════════════════════
function renderAnalysis(data) {
  const analyses = data.analyses || [];
  if (analyses.length === 0) {
    return '<div class="log-empty">暂无分析数据</div>';
  }

  const cards = analyses.map((proj, idx) => {
    const title = escapeHtml(proj.title || '未命名项目');
    const summary = escapeHtml(proj.summary || '');

    // 技术栈标签
    const techStack = Array.isArray(proj.tech_stack) ? proj.tech_stack : [];
    const techTagsHtml = techStack.length > 0
      ? `<div class="tech-tags">${techStack.map(t => {
          const color = pickTagColor(String(t));
          return `<span class="tech-tag" style="background:${color}">${escapeHtml(t)}</span>`;
        }).join('')}</div>`
      : '';

    // 架构设计
    const archHtml = proj.architecture
      ? `<div class="section-label"><span class="sl-icon">🏗️</span>架构设计</div>
         <div class="proj-text">${escapeHtml(proj.architecture)}</div>`
      : '';

    // 关键模块
    const keyModules = Array.isArray(proj.key_modules) ? proj.key_modules : [];
    const modulesHtml = keyModules.length > 0
      ? `<div class="section-label"><span class="sl-icon">🧩</span>关键模块</div>
         <div class="module-grid">
           ${keyModules.map(m => `
             <div class="module-item">
               <div class="module-name"><span class="mn-dot"></span>${escapeHtml(m.name || '')}</div>
               <div class="module-desc">${escapeHtml(m.description || m.desc || '')}</div>
             </div>
           `).join('')}
         </div>`
      : '';

    // 快速上手
    const quickStartHtml = proj.quick_start
      ? `<div class="section-label"><span class="sl-icon">🚀</span>快速上手</div>
         <div class="code-block">${escapeHtml(proj.quick_start)}</div>`
      : '';

    // 技术亮点
    const highlights = Array.isArray(proj.highlights) ? proj.highlights : [];
    const highlightsHtml = highlights.length > 0
      ? `<div class="section-label"><span class="sl-icon">✨</span>技术亮点</div>
         <ul class="insight-list">
           ${highlights.map(h => `<li>${escapeHtml(h)}</li>`).join('')}
         </ul>`
      : '';

    // 应用场景
    const useCases = Array.isArray(proj.use_cases) ? proj.use_cases : [];
    const useCasesHtml = useCases.length > 0
      ? `<div class="section-label"><span class="sl-icon">🎯</span>应用场景</div>
         <ul class="insight-list use-cases">
           ${useCases.map(u => `<li>${escapeHtml(u)}</li>`).join('')}
         </ul>`
      : '';

    // 同类对比
    const comparisonHtml = proj.comparison
      ? `<div class="section-label"><span class="sl-icon">⚖️</span>同类对比</div>
         <div class="proj-text">${escapeHtml(proj.comparison)}</div>`
      : '';

    // 代码洞察
    const codeInsightsHtml = proj.code_insights
      ? `<div class="section-label"><span class="sl-icon">🔬</span>代码洞察</div>
         <div class="proj-text">${escapeHtml(proj.code_insights)}</div>`
      : '';

    // 项目间分隔符
    const divider = idx < analyses.length - 1 ? '<div class="proj-divider"></div>' : '';

    return `
      <div class="proj-card">
        <div class="proj-head">
          <div class="proj-icon">📦</div>
          <div class="proj-title">${title}</div>
        </div>
        ${summary ? `<div class="proj-summary">${summary}</div>` : ''}
        ${techTagsHtml ? `<div class="section-label"><span class="sl-icon">🛠️</span>技术栈</div>${techTagsHtml}` : ''}
        ${archHtml}
        ${modulesHtml}
        ${quickStartHtml}
        ${highlightsHtml}
        ${useCasesHtml}
        ${comparisonHtml}
        ${codeInsightsHtml}
      </div>
      ${divider}
    `;
  }).join('');

  return `
    <div class="analysis-header">📊 项目深度分析 · 共 ${analyses.length} 个项目</div>
    ${cards}
  `;
}
