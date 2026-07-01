// ════════════════════════════════════════
// analysis.js — 项目深度分析页
// ════════════════════════════════════════
import { createPage } from '../page-base.js';
import { api } from '../api.js';
import { escapeHtml, pickTagColor } from '../utils.js';

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

    await loadAllAnalyses();

    // Q&A 事件委托（绑定到 container，SPA 切换时随 DOM 自动清理）
    setupQAListeners(ctx);
  },
});

// 动态加载 Mermaid CDN
function loadMermaid() {
  return new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js';
    script.onload = () => resolve();
    script.onerror = () => resolve();
    document.head.appendChild(script);
  });
}

// 加载所有期数的分析数据
async function loadAllAnalyses() {
  const container = document.getElementById('analysisList');
  if (!container) return;

  try {
    const episodes = await api.getEpisodes();
    if (!episodes || episodes.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📭</div><div>暂无节目</div></div>';
      return;
    }

    // 逐个获取分析数据
    const analyses = [];
    for (const ep of episodes) {
      try {
        const data = await api.getAnalysis(ep.episode_number);
        if (!data.error) {
          analyses.push({ episode: ep, analysis: data });
        }
      } catch (e) {
        // 跳过无分析的节目
      }
    }

    if (analyses.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="icon">📊</div><div>暂无项目分析数据</div></div>';
      return;
    }

    container.innerHTML = analyses.map(({ episode, analysis }) => {
      const projs = analysis.analyses || [];
      const comparisonHtml = renderComparisonSection(analysis.comparison);
      return `
        <div class="card" style="margin-bottom:16px;">
          <div class="card-title">
            <span>EP${String(episode.episode_number).padStart(3,'0')} · ${escapeHtml(episode.title)}</span>
            <span style="font-size:12px;color:var(--text-dim);">${projs.length} 个项目</span>
          </div>
          ${projs.map((proj, idx) => renderProjectCard(proj, idx, projs.length, episode.episode_number)).join('')}
          ${comparisonHtml}
        </div>
      `;
    }).join('');

    // Mermaid 图表手动触发渲染
    if (window.mermaid) {
      try {
        await window.mermaid.run();
      } catch (e) {
        console.warn('Mermaid 渲染失败:', e);
      }
    }
  } catch (e) {
    container.innerHTML = '<div class="empty-state"><div class="icon">⚠️</div><div>加载失败</div></div>';
  }
}

// ════════════════════════════════════════
// Q&A 交互事件（事件委托）
// ════════════════════════════════════════
function setupQAListeners(ctx) {
  const list = document.getElementById('analysisList');
  if (!list) return;

  // 提交按钮点击
  ctx.addListener(list, 'click', async (e) => {
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
        const html = escapeHtml(data.answer)
          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.+?)\*/g, '<em>$1</em>')
          .replace(/\n/g, '<br>');
        answerDiv.innerHTML = `<div class="qa-answer-text">${html}</div>`;
      }
    } catch (err) {
      answerDiv.innerHTML = `<div class="qa-error">网络错误：${escapeHtml(String(err))}</div>`;
    } finally {
      e.target.disabled = false;
      e.target.textContent = '提问';
    }
  });

  // 回车键提交
  ctx.addListener(list, 'keypress', (e) => {
    if (e.key !== 'Enter' || !e.target.classList.contains('qa-input')) return;
    e.preventDefault();
    const panel = e.target.closest('.qa-panel');
    if (!panel) return;
    const btn = panel.querySelector('.qa-submit-btn');
    if (btn) btn.click();
  });
}

// 渲染单个项目分析卡片
function renderProjectCard(proj, idx, total, epNum) {
  const title = escapeHtml(proj.repo_name || proj.title || '未命名项目');
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
    ? `<div class="section-label"><span class="sl-icon">🏗️</span>架构设计</div><div class="proj-text">${escapeHtml(proj.architecture)}</div>`
    : '';

  // 关键模块
  const keyModules = Array.isArray(proj.key_modules) ? proj.key_modules : [];
  const modulesHtml = keyModules.length > 0
    ? `<div class="section-label"><span class="sl-icon">🧩</span>关键模块</div>
       <div class="module-grid">${keyModules.map(m => `
         <div class="module-item">
           <div class="module-name"><span class="mn-dot"></span>${escapeHtml(m.name || '')}</div>
           <div class="module-desc">${escapeHtml(m.description || m.desc || '')}</div>
         </div>`).join('')}</div>`
    : '';

  // 快速上手
  const quickStartHtml = proj.quick_start
    ? `<div class="section-label"><span class="sl-icon">🚀</span>快速上手</div><div class="code-block">${escapeHtml(proj.quick_start)}</div>`
    : '';

  // 技术亮点
  const highlights = Array.isArray(proj.highlights) ? proj.highlights : [];
  const highlightsHtml = highlights.length > 0
    ? `<div class="section-label"><span class="sl-icon">✨</span>技术亮点</div>
       <ul class="insight-list">${highlights.map(h => `<li>${escapeHtml(h)}</li>`).join('')}</ul>`
    : '';

  // 应用场景
  const useCases = Array.isArray(proj.use_cases) ? proj.use_cases : [];
  const useCasesHtml = useCases.length > 0
    ? `<div class="section-label"><span class="sl-icon">🎯</span>应用场景</div>
       <ul class="insight-list use-cases">${useCases.map(u => `<li>${escapeHtml(u)}</li>`).join('')}</ul>`
    : '';

  // 同类对比
  const comparisonHtml = proj.comparison
    ? `<div class="section-label"><span class="sl-icon">⚖️</span>同类对比</div><div class="proj-text">${escapeHtml(proj.comparison)}</div>`
    : '';

  // 代码洞察
  const codeInsightsHtml = proj.code_insights
    ? `<div class="section-label"><span class="sl-icon">🔬</span>代码洞察</div><div class="proj-text">${escapeHtml(proj.code_insights)}</div>`
    : '';

  // 质量评分徽章（标题旁）
  const reviewBadgeHtml = renderReviewBadge(proj.review_score);

  // 健康度面板
  const healthPanelHtml = renderHealthPanel(proj.health_data);

  // 提交动态叙述
  const commitNarrativeHtml = proj.commit_narrative
    ? `<div class="section-label"><span class="sl-icon">📝</span>提交动态</div><div class="health-narrative-text">${escapeHtml(proj.commit_narrative)}</div>`
    : '';

  // 架构图（Mermaid 语法，原样注入由 mermaid.run() 渲染）
  const mermaidDiagram = typeof proj.mermaid_diagram === 'string' ? proj.mermaid_diagram.trim() : '';
  const mermaidHtml = mermaidDiagram
    ? `<div class="section-label"><span class="sl-icon">🧬</span>架构图</div>
       <div class="mermaid-container"><div class="mermaid">${mermaidDiagram}</div></div>`
    : '';

  // 依赖清单
  const dependenciesHtml = renderDependencies(proj.dependencies);

  // 项目间分隔符
  const divider = idx < total - 1 ? '<div class="proj-divider"></div>' : '';

  return `
    <div class="proj-card">
      <div class="proj-head">
        <div class="proj-icon">📦</div>
        <div class="proj-title">${title}</div>
        ${reviewBadgeHtml}
      </div>
      ${summary ? `<div class="proj-summary">${summary}</div>` : ''}
      ${techTagsHtml ? `<div class="section-label"><span class="sl-icon">🛠️</span>技术栈</div>${techTagsHtml}` : ''}
      ${healthPanelHtml}
      ${commitNarrativeHtml}
      ${archHtml}
      ${mermaidHtml}
      ${modulesHtml}${quickStartHtml}${highlightsHtml}${useCasesHtml}${comparisonHtml}${codeInsightsHtml}
      ${dependenciesHtml}
      ${renderQASection(proj, epNum)}
    </div>
    ${divider}
  `;
}

// Q&A 交互面板（借鉴 NotebookLM 交互模式）
function renderQASection(proj, epNum) {
  const repoName = escapeHtml(proj.repo_name || '');
  const epNumStr = String(epNum || '');
  return `
    <div class="section-label"><span class="sl-icon">💬</span>互动问答</div>
    <div class="qa-panel" data-repo="${repoName}" data-ep="${epNumStr}">
      <div class="qa-input-row">
        <input type="text" class="qa-input" placeholder="针对这个项目提问...（如：它的架构有什么亮点？）" />
        <button class="qa-submit-btn">提问</button>
      </div>
      <div class="qa-answer"></div>
    </div>
  `;
}

// ════════════════════════════════════════
// 增强可视化：质量评分 / 健康面板 / 依赖 / 对比
// ════════════════════════════════════════

// 质量评分徽章（0-10，标题旁）
function renderReviewBadge(score) {
  const n = typeof score === 'number' ? score : parseFloat(score);
  if (!n || isNaN(n) || n <= 0) return '';
  const cls = n >= 7 ? 'review-good' : (n >= 4 ? 'review-mid' : 'review-low');
  return `<span class="review-badge ${cls}">质量评分: ${n.toFixed(1)}/10</span>`;
}

// 健康等级 → CSS 类
function gradeClass(grade) {
  const g = String(grade == null ? '' : grade).toUpperCase().trim();
  const map = {
    'A+': 'grade-ap', 'A': 'grade-a', 'B': 'grade-b',
    'C': 'grade-c', 'D': 'grade-d', 'F': 'grade-f',
  };
  return map[g] || 'grade-d';
}

// 健康度面板
function renderHealthPanel(hd) {
  if (!hd || typeof hd !== 'object') return '';

  const grade = hd.health_grade != null ? String(hd.health_grade) : '';
  const gradeBadge = grade
    ? `<span class="health-grade-badge ${gradeClass(hd.health_grade)}">${escapeHtml(grade)}</span>`
    : '';

  const score = typeof hd.health_score === 'number' ? hd.health_score : null;
  const scoreHtml = score !== null
    ? `<span class="health-score"><span class="hs-label">健康分</span>${score.toFixed(1)}/100</span>`
    : '';

  // issue_close_rate 兼容小数(0-1)与百分比(0-100)
  const fmtRate = (v) => {
    if (typeof v !== 'number') return v;
    return (v <= 1 ? v * 100 : v).toFixed(0) + '%';
  };

  const metrics = [
    { label: '提交(30天)', value: hd.commit_count_30d },
    { label: '贡献者', value: hd.contributor_count },
    { label: '发布数', value: hd.release_count },
    { label: '待处理Issue', value: hd.open_issues },
    { label: 'Issue关闭率', value: fmtRate(hd.issue_close_rate) },
  ].filter(m => m.value !== undefined && m.value !== null && m.value !== '');

  const metricsHtml = metrics.length
    ? `<div class="health-metrics-grid">${metrics.map(m => `
        <div class="health-metric">
          <div class="hm-value">${escapeHtml(String(m.value))}</div>
          <div class="hm-label">${escapeHtml(m.label)}</div>
        </div>`).join('')}</div>`
    : '';

  const topContrib = Array.isArray(hd.top_contributors) ? hd.top_contributors : [];
  const contribHtml = topContrib.length
    ? `<div class="health-contributors">
         <div class="hm-sublabel">主要贡献者</div>
         <div class="contrib-list">${topContrib.map(c => {
           const name = typeof c === 'string' ? c : (c && (c.name || c.login)) || '';
           return name ? `<span class="contrib-chip">${escapeHtml(String(name))}</span>` : '';
         }).join('')}</div>
       </div>`
    : '';

  const trendHtml = hd.commit_activity_trend
    ? `<div class="health-trend">
         <span class="hm-sublabel">活跃趋势</span>
         <div class="health-trend-text">${escapeHtml(String(hd.commit_activity_trend))}</div>
       </div>`
    : '';

  if (!gradeBadge && !scoreHtml && !metricsHtml && !contribHtml && !trendHtml) return '';

  return `
    <div class="section-label"><span class="sl-icon">📈</span>健康度</div>
    <div class="health-panel">
      <div class="health-panel-head">${gradeBadge}${scoreHtml}</div>
      ${metricsHtml}${contribHtml}${trendHtml}
    </div>
  `;
}

// 依赖清单
function renderDependencies(deps) {
  if (!Array.isArray(deps) || deps.length === 0) return '';
  const tags = deps.map(d => {
    let name = '', ver = '';
    if (typeof d === 'string') {
      name = d;
    } else if (d && typeof d === 'object') {
      name = d.name || d.package || '';
      ver = d.version || d.v || '';
    }
    if (!name) return '';
    const verHtml = ver ? `<span class="dep-ver">${escapeHtml(String(ver))}</span>` : '';
    return `<span class="dep-tag">${escapeHtml(String(name))}${verHtml}</span>`;
  }).filter(Boolean).join('');
  if (!tags) return '';
  return `
    <div class="section-label"><span class="sl-icon">📚</span>依赖清单</div>
    <div class="dependency-tags">${tags}</div>
  `;
}

// 跨项目对比（响应级 comparison 对象）
function renderComparisonSection(cmp) {
  if (!cmp || typeof cmp !== 'object') return '';

  // 技术重叠：共享技术高亮标签
  const overlap = Array.isArray(cmp.tech_overlap) ? cmp.tech_overlap : [];
  const overlapHtml = overlap.length
    ? `<div class="cmp-block">
         <div class="cmp-label">技术重叠</div>
         <div class="dependency-tags">${overlap.map(t =>
           `<span class="tech-tag cmp-overlap-tag">${escapeHtml(String(t))}</span>`).join('')}</div>
       </div>`
    : '';

  // 定位差异
  const posHtml = cmp.positioning_diff
    ? `<div class="cmp-block">
         <div class="cmp-label">定位差异</div>
         <div class="proj-text">${escapeHtml(String(cmp.positioning_diff))}</div>
       </div>`
    : '';

  // 活跃度排名
  const ranking = Array.isArray(cmp.activity_ranking) ? cmp.activity_ranking : [];
  const rankingHtml = ranking.length
    ? `<div class="cmp-block">
         <div class="cmp-label">活跃度排名</div>
         <ol class="activity-ranking">${ranking.map(r => {
           let name = '', score = null;
           if (typeof r === 'string') {
             name = r;
           } else if (r && typeof r === 'object') {
             name = r.name || r.repo || r.project || '';
             score = r.health_score != null ? r.health_score : (r.score != null ? r.score : null);
           }
           if (!name) return '';
           const scoreHtml = (typeof score === 'number')
             ? `<span class="rank-score">${score.toFixed(1)}</span>`
             : (score ? `<span class="rank-score">${escapeHtml(String(score))}</span>` : '');
           return `<li><span class="rank-name">${escapeHtml(String(name))}</span>${scoreHtml}</li>`;
         }).filter(Boolean).join('')}</ol>
       </div>`
    : '';

  // 结论
  const verdictHtml = cmp.verdict
    ? `<div class="comparison-verdict">${escapeHtml(String(cmp.verdict))}</div>`
    : '';

  if (!overlapHtml && !posHtml && !rankingHtml && !verdictHtml) return '';

  return `
    <div class="comparison-section">
      <div class="section-label"><span class="sl-icon">🆚</span>项目对比</div>
      ${overlapHtml}${posHtml}${rankingHtml}${verdictHtml}
    </div>
  `;
}

init();
