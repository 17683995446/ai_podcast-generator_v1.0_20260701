// ════════════════════════════════════════
// analysis-renderer.js — 项目分析卡片共享渲染器
// 提取自 analysis.js 和 episodes.js 中重复的渲染逻辑
// 统一渲染逻辑，确保内联展开和独立页面展示一致
// ════════════════════════════════════════
import { escapeHtml, pickTagColor } from '../utils.js';
import { normalizeHighlight, normalizeUseCase, renderInsightItem } from './data-normalizer.js';

// ════════════════════════════════════════
// 证据链可视化辅助函数
// ════════════════════════════════════════

/**
 * 根据字段名和值查找匹配的证据
 * @param {Array} evidenceSources - 证据来源数组
 * @param {string} field - 字段名
 * @param {string} value - 字段值
 * @returns {Object|null} 匹配的证据对象
 */
function findEvidence(evidenceSources, field, value) {
  if (!Array.isArray(evidenceSources)) return null;
  return evidenceSources.find(e =>
    e.field === field && e.value && value &&
    e.value.toLowerCase().includes(value.toLowerCase())
  ) || null;
}

/**
 * 渲染单个证据徽章
 * @param {Object} evidence - 证据对象
 * @returns {string} HTML 字符串
 */
function renderEvidenceBadge(evidence) {
  if (!evidence) return '';
  const isVerified = evidence.confidence === 'verified';
  const icon = isVerified ? '✓' : '∼';
  const cls = isVerified ? 'ev-verified' : 'ev-inferred';
  const sourceMap = {
    'dependency_file': '依赖文件',
    'file_tree': '文件树',
    'source_code': '源码',
    'commit_history': '提交历史',
    'release_notes': '发布记录',
    'github_stats': 'GitHub统计',
    'llm_inference': 'AI推断',
    'readme': 'README',
  };
  const sourceLabel = sourceMap[evidence.source_type] || evidence.source_type || '';
  return `<span class="ev-badge ${cls}" title="${escapeHtml(evidence.source_detail || '')}">${icon} ${sourceLabel}</span>`;
}

/**
 * 渲染证据摘要面板
 * @param {Array} evidenceSources - 证据来源数组
 * @returns {string} HTML 字符串
 */
function renderEvidenceSummary(evidenceSources) {
  if (!Array.isArray(evidenceSources) || evidenceSources.length === 0) return '';
  const verified = evidenceSources.filter(e => e.confidence === 'verified').length;
  const inferred = evidenceSources.filter(e => e.confidence === 'inferred').length;
  const total = evidenceSources.length;
  const coverage = total > 0 ? Math.round(verified / total * 100) : 0;
  const coverageColor = coverage >= 70 ? 'var(--green)' : coverage >= 40 ? 'var(--orange)' : 'var(--red)';
  return `<div class="evidence-summary">
    <span class="ev-summary-label">证据链</span>
    <span class="ev-coverage" style="color:${coverageColor}">${coverage}% 已验证</span>
    <span class="ev-count">${verified} 已验证</span>
    <span class="ev-count ev-inferred-count">${inferred} 推断</span>
    <span class="ev-total">共 ${total} 项</span>
  </div>`;
}

// ════════════════════════════════════════
// 核心渲染：项目分析卡片
// ════════════════════════════════════════

/**
 * 渲染单个项目分析卡片
 * @param {Object} proj - 项目分析数据
 * @param {number} idx - 当前项目索引
 * @param {number} total - 项目总数
 * @param {number} epNum - 期数编号
 * @param {Object} [options] - 渲染选项
 * @param {boolean} [options.showQA=true] - 是否渲染 Q&A 交互面板
 * @returns {string} HTML 字符串
 */
export function renderProjectCard(proj, idx, total, epNum, options = {}) {
  proj = proj || {};  // null 安全防护
  const { showQA = true } = options;
  const title = escapeHtml(proj.repo_name || proj.title || '未命名项目');
  const summary = escapeHtml(proj.summary || '');
  const evidenceSummaryHtml = renderEvidenceSummary(proj.evidence_sources);

  // 技术栈标签
  const techStack = Array.isArray(proj.tech_stack) ? proj.tech_stack : [];
  const evidenceSources = Array.isArray(proj.evidence_sources) ? proj.evidence_sources : [];
  const techTagsHtml = techStack.length > 0
    ? `<div class="tech-tags">${techStack.map(t => {
        const color = pickTagColor(String(t));
        const ev = findEvidence(evidenceSources, 'tech_stack', String(t));
        const evBadge = renderEvidenceBadge(ev);
        return `<span class="tech-tag" style="background:${color}">${escapeHtml(t)}${evBadge}</span>`;
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
       <div class="module-grid">${keyModules.map(m => {
         const ev = findEvidence(evidenceSources, 'key_modules', m.name || '');
         const evBadge = renderEvidenceBadge(ev);
         return `<div class="module-item">
           <div class="module-name"><span class="mn-dot"></span>${escapeHtml(m.name || '')}${evBadge}</div>
           <div class="module-desc">${escapeHtml(m.description || m.desc || '')}</div>
         </div>`;
       }).join('')}</div>`
    : '';

  // 快速上手
  const quickStartHtml = proj.quick_start
    ? `<div class="section-label"><span class="sl-icon">🚀</span>快速上手</div><div class="code-block">${escapeHtml(proj.quick_start)}</div>`
    : '';

  // 技术亮点（元素可为字符串或 {point, value} 字典）
  const highlights = Array.isArray(proj.highlights) ? proj.highlights : [];
  const highlightsHtml = highlights.length > 0
    ? `<div class="section-label"><span class="sl-icon">✨</span>技术亮点</div>
       <ul class="insight-list">${highlights.map(h => renderInsightItem(normalizeHighlight(h), escapeHtml)).join('')}</ul>`
    : '';

  // 应用场景（元素可为字符串或 {who, scenario, solve} 字典）
  const useCases = Array.isArray(proj.use_cases) ? proj.use_cases : [];
  const useCasesHtml = useCases.length > 0
    ? `<div class="section-label"><span class="sl-icon">🎯</span>应用场景</div>
       <ul class="insight-list use-cases">${useCases.map(u => renderInsightItem(normalizeUseCase(u), escapeHtml)).join('')}</ul>`
    : '';

  // 同类对比
  const comparisonHtml = proj.comparison
    ? `<div class="section-label"><span class="sl-icon">⚖️</span>同类对比</div><div class="proj-text">${escapeHtml(proj.comparison)}</div>`
    : '';

  // 代码洞察
  const codeInsightsHtml = proj.code_insights
    ? `<div class="section-label"><span class="sl-icon">🔬</span>代码洞察</div><div class="proj-text">${escapeHtml(proj.code_insights)}</div>`
    : '';

  // 代码级分析指标
  const codeMetricsHtml = renderCodeMetrics(proj.code_metrics);

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

  // Q&A 交互面板（可选，仅分析页启用）
  const qaHtml = showQA ? renderQASection(proj, epNum) : '';

  return `
    <div class="proj-card">
      <div class="proj-head">
        <div class="proj-icon">📦</div>
        <div class="proj-title">${title}</div>
        ${reviewBadgeHtml}
      </div>
      ${summary ? `<div class="proj-summary">${summary}</div>` : ''}
      ${evidenceSummaryHtml}
      ${techTagsHtml ? `<div class="section-label"><span class="sl-icon">🛠️</span>技术栈</div>${techTagsHtml}` : ''}
      ${healthPanelHtml}
      ${commitNarrativeHtml}
      ${archHtml}
      ${mermaidHtml}
      ${modulesHtml}${quickStartHtml}${highlightsHtml}${useCasesHtml}${comparisonHtml}${codeInsightsHtml}
      ${codeMetricsHtml}
      ${dependenciesHtml}
      ${qaHtml}
    </div>
    ${divider}
  `;
}

// ════════════════════════════════════════
// 代码级分析指标渲染
// ════════════════════════════════════════

/**
 * 渲染代码级分析指标面板
 * @param {Object} metrics - 代码指标数据
 * @returns {string} HTML 字符串
 */
function renderCodeMetrics(metrics) {
  if (!metrics || typeof metrics !== 'object' || Object.keys(metrics).length === 0) {
    return '';
  }

  const arch = metrics.architecture_pattern || 'unknown';
  const archConf = metrics.architecture_confidence || 0;
  const archSignals = Array.isArray(metrics.architecture_signals) ? metrics.architecture_signals : [];
  const totalLoc = metrics.total_loc || 0;
  const fileCount = metrics.file_count || 0;
  const avgFileLoc = metrics.avg_file_loc || 0;
  const complexity = metrics.complexity_score || 0;
  const quality = metrics.quality_score || 0;
  const maintainability = metrics.maintainability_index || 0;
  const testLevel = metrics.test_coverage_level || 'unknown';
  const docRatio = metrics.documentation_ratio || 0;
  const smells = Array.isArray(metrics.code_smells) ? metrics.code_smells : [];
  const locByLang = metrics.loc_by_language || {};
  const largestFiles = Array.isArray(metrics.largest_files) ? metrics.largest_files : [];

  // 语言分布条
  const langEntries = Object.entries(locByLang).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const langBarsHtml = langEntries.length > 0
    ? `<div class="cm-lang-bars">${langEntries.map(([lang, loc]) => {
        const pct = totalLoc > 0 ? (loc / totalLoc * 100).toFixed(1) : 0;
        return `<div class="cm-lang-row">
          <span class="cm-lang-name">${escapeHtml(lang)}</span>
          <div class="cm-lang-bar-wrap"><div class="cm-lang-bar" style="width:${pct}%"></div></div>
          <span class="cm-lang-loc">${loc}</span>
        </div>`;
      }).join('')}</div>`
    : '';

  // 代码异味
  const smellsHtml = smells.length > 0
    ? `<div class="cm-smells">${smells.map(s => `<span class="cm-smell">⚠ ${escapeHtml(s)}</span>`).join('')}</div>`
    : '';

  // 最大文件
  const largestHtml = largestFiles.length > 0
    ? `<div class="cm-largest-files">${largestFiles.map(f =>
        `<div class="cm-file-row"><span class="cm-file-path">${escapeHtml(f.path)}</span><span class="cm-file-loc">${f.loc} 行</span></div>`
      ).join('')}</div>`
    : '';

  // 测试覆盖级别颜色
  const testLevelColors = { '高': 'cm-test-high', '中': 'cm-test-mid', '低': 'cm-test-low', '无': 'cm-test-none', 'unknown': 'cm-test-none' };
  const testLevelClass = testLevelColors[testLevel] || 'cm-test-none';

  // 架构信号
  const archSignalsHtml = archSignals.length > 0
    ? `<div class="cm-arch-signals">${archSignals.map(s => `<span class="cm-arch-signal">${escapeHtml(s)}</span>`).join('')}</div>`
    : '';

  return `
    <div class="section-label"><span class="sl-icon">📊</span>代码级分析</div>
    <div class="code-metrics-panel">
      <div class="cm-grid">
        <div class="cm-cell">
          <div class="cm-cell-label">架构模式</div>
          <div class="cm-cell-value cm-arch">${escapeHtml(arch)} <span class="cm-conf">(${(archConf * 100).toFixed(0)}%)</span></div>
          ${archSignalsHtml}
        </div>
        <div class="cm-cell">
          <div class="cm-cell-label">代码规模</div>
          <div class="cm-cell-value">${totalLoc} 行 / ${fileCount} 文件</div>
          <div class="cm-cell-sub">平均 ${avgFileLoc} 行/文件</div>
        </div>
        <div class="cm-cell">
          <div class="cm-cell-label">复杂度</div>
          <div class="cm-score-bar">
            <div class="cm-score-fill cm-complexity" style="width:${complexity * 10}%"></div>
          </div>
          <div class="cm-cell-value">${complexity}/10</div>
        </div>
        <div class="cm-cell">
          <div class="cm-cell-label">质量评分</div>
          <div class="cm-score-bar">
            <div class="cm-score-fill cm-quality" style="width:${quality}%"></div>
          </div>
          <div class="cm-cell-value">${quality}/100</div>
        </div>
        <div class="cm-cell">
          <div class="cm-cell-label">可维护性</div>
          <div class="cm-score-bar">
            <div class="cm-score-fill cm-maintainability" style="width:${maintainability}%"></div>
          </div>
          <div class="cm-cell-value">${maintainability}/100</div>
        </div>
        <div class="cm-cell">
          <div class="cm-cell-label">测试覆盖</div>
          <div class="cm-cell-value ${testLevelClass}">${escapeHtml(testLevel)}</div>
          <div class="cm-cell-sub">文档比 ${(docRatio * 100).toFixed(0)}%</div>
        </div>
      </div>
      ${langBarsHtml}
      ${smellsHtml}
      ${largestHtml}
    </div>
  `;
}

// ════════════════════════════════════════
// Q&A 交互面板
// ════════════════════════════════════════

/**
 * 渲染 Q&A 交互面板（借鉴 NotebookLM 交互模式）
 * @param {Object} proj - 项目分析数据
 * @param {number} epNum - 期数编号
 * @returns {string} HTML 字符串
 */
function renderQASection(proj, epNum) {
  const repoName = escapeHtml(proj.repo_name || '');
  const epNumStr = String(epNum || '');
  return `
    <div class="section-label"><span class="sl-icon">💬</span>互动问答</div>
    <div class="qa-panel" data-repo="${repoName}" data-ep="${epNumStr}">
      <div class="qa-input-row">
        <input type="text" class="qa-input" placeholder="针对这个项目提问...（如：它的架构有什么亮点？）" aria-label="提问输入框" />
        <button class="qa-submit-btn" aria-label="提交问题">提问</button>
      </div>
      <div class="qa-answer"></div>
    </div>
  `;
}

// ════════════════════════════════════════
// 增强可视化：质量评分 / 健康面板 / 依赖 / 对比
// ════════════════════════════════════════

/**
 * 质量评分徽章（0-10，标题旁）
 * @param {number|string} score - 质量评分
 * @returns {string} HTML 字符串
 */
function renderReviewBadge(score) {
  const n = typeof score === 'number' ? score : parseFloat(score);
  if (!n || isNaN(n) || n <= 0) return '';
  const cls = n >= 7 ? 'review-good' : (n >= 4 ? 'review-mid' : 'review-low');
  return `<span class="review-badge ${cls}">质量评分: ${n.toFixed(1)}/10</span>`;
}

/**
 * 健康等级 → CSS 类映射
 * @param {string} grade - 健康等级（A+/A/B/C/D/F）
 * @returns {string} CSS 类名
 */
function gradeClass(grade) {
  const g = String(grade == null ? '' : grade).toUpperCase().trim();
  const map = {
    'A+': 'grade-ap', 'A': 'grade-a', 'B': 'grade-b',
    'C': 'grade-c', 'D': 'grade-d', 'F': 'grade-f',
  };
  return map[g] || 'grade-d';
}

/**
 * 健康度面板渲染
 * @param {Object} hd - 健康度数据
 * @returns {string} HTML 字符串
 */
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

/**
 * 依赖清单渲染
 * @param {Array} deps - 依赖列表（字符串或对象）
 * @returns {string} HTML 字符串
 */
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

/**
 * 跨项目对比（响应级 comparison 对象）
 * @param {Object} cmp - 对比数据
 * @returns {string} HTML 字符串
 */
export function renderComparisonSection(cmp) {
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

// ════════════════════════════════════════
// 容器包装 — 供 episodes.js 内联展开使用
// ════════════════════════════════════════

/**
 * 渲染完整分析容器（含标题栏 + 项目卡片列表）
 * 供 episodes.js 的 toggleAnalysis 内联展开使用
 * @param {Object} analysisData - API 返回的分析数据
 * @param {number} epNum - 期数编号
 * @returns {string} HTML 字符串
 */
export function renderAnalysisContainer(analysisData, epNum) {
  analysisData = analysisData || {};  // null 安全防护
  const analyses = analysisData.analyses || [];
  if (analyses.length === 0) {
    return '<div class="log-empty">暂无分析数据</div>';
  }

  const cards = analyses.map((proj, idx) =>
    renderProjectCard(proj, idx, analyses.length, epNum, { showQA: false })
  ).join('');

  return `
    <div class="analysis-header">📊 项目深度分析 · 共 ${analyses.length} 个项目</div>
    ${cards}
  `;
}
