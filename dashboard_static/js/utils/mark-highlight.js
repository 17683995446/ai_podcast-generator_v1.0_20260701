// ════════════════════════════════════════
// mark-highlight.js — 关键词高亮（基于 mark.js）
// 通过 CDN 动态加载 mark.js，加载成功后使用其高亮功能
// 加载失败时回退到正则替换（与原手写实现一致）
// 替换 search-panel.js 中手写的 highlightKeyword 函数
// ════════════════════════════════════════

const MARKJS_CDN = 'https://cdn.jsdelivr.net/npm/mark.js@8.11.1/dist/mark.min.js';

let _Mark = null;
let _loading = null;

/**
 * 动态加载 mark.js CDN
 * @returns {Promise<Function|null>} Mark 构造函数，加载失败返回 null
 */
async function ensureMark() {
  if (_Mark) return _Mark;
  if (_loading) return _loading;

  _loading = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = MARKJS_CDN;
    script.onload = () => {
      _Mark = window.Mark || null;
      resolve(_Mark);
    };
    script.onerror = () => {
      console.warn('[mark.js] CDN 加载失败，使用正则回退');
      resolve(null);
    };
    document.head.appendChild(script);
  });

  return _loading;
}

// 预加载（非阻塞）
ensureMark();

/**
 * 在已转义的 HTML 文本中高亮关键词
 * mark.js 加载成功后，在后处理阶段使用 mark.js 高亮（支持分词、diacritics）
 * mark.js 未加载时回退到正则替换（与原手写实现一致）
 *
 * 注意：由于 search-panel.js 在拼装 HTML 字符串时调用此函数，
 * 这里采用同步正则回退 + 异步 mark.js 后处理的双模式策略。
 *
 * @param {string} escapedText - 已转义的 HTML 文本
 * @param {string} query - 搜索关键词
 * @returns {string} 带 <mark> 标签的 HTML
 */
export function highlightKeyword(escapedText, query) {
  if (!query) return escapedText;

  // 同步回退：正则替换（与原手写实现一致）
  const escapedQuery = escapeHtmlLocal(query);
  const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return escapedText.replace(regex, '<mark class="search-highlight">$1</mark>');
}

/**
 * 异步高亮：使用 mark.js 对 DOM 容器内的搜索结果进行高亮
 * 在搜索结果渲染到 DOM 后调用此函数进行后处理
 * mark.js 支持分词匹配、diacritics、精确/部分匹配等高级功能
 *
 * @param {HTMLElement} container - 搜索结果容器
 * @param {string} query - 搜索关键词
 * @param {Object} [options] - mark.js 选项
 */
export async function highlightInContainer(container, query, options = {}) {
  if (!container || !query) return;

  const Mark = await ensureMark();
  if (!Mark) return;

  try {
    const markInstance = new Mark(container);
    markInstance.mark(query, {
      separateWordSearch: false,
      accuracy: 'partially',
      className: 'search-highlight',
      ...options,
    });
  } catch (e) {
    console.warn('[mark.js] 高亮执行失败:', e);
  }
}

/**
 * 清除容器中的所有高亮标记
 * @param {HTMLElement} container - 搜索结果容器
 */
export async function unmarkContainer(container) {
  if (!container) return;
  const Mark = await ensureMark();
  if (!Mark) return;

  try {
    const markInstance = new Mark(container);
    markInstance.unmark();
  } catch (e) {
    console.warn('[mark.js] 清除高亮失败:', e);
  }
}

/**
 * 简易 HTML 转义（与 utils.js 的 escapeHtml 一致，避免循环依赖）
 */
function escapeHtmlLocal(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
