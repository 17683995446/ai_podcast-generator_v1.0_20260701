// ════════════════════════════
// Markdown 渲染工具（基于 marked）
// CDN 动态加载，失败时回退到简易 regex 格式化
// 替换原有的手写 **bold** / *italic* / \n → <br> 正则替换
// ════════════════════════════

const MARKED_CDN = 'https://cdn.jsdelivr.net/npm/marked@12/marked.min.js';

let _markedReady = null;

/**
 * 动态加载 marked CDN
 * @returns {Promise<typeof marked>}
 */
async function ensureMarked() {
  if (window.marked) return window.marked;
  if (_markedReady) return _markedReady;

  _markedReady = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = MARKED_CDN;
    script.onload = () => {
      // 配置 marked
      marked.setOptions({
        breaks: true,       // 换行符 → <br>
        gfm: true,          // GitHub Flavored Markdown
        headerIds: false,   // 不添加 header id
        mangle: false,      // 不转义 header 文本
      });
      resolve(marked);
    };
    script.onerror = () => reject(new Error('marked CDN 加载失败'));
    document.head.appendChild(script);
  });

  return _markedReady;
}

/**
 * 将 Markdown 文本渲染为 HTML
 * 支持：标题、粗体、斜体、代码块、行内代码、列表、链接、引用、表格、分隔线
 *
 * @param {string} markdown - Markdown 格式文本
 * @returns {Promise<string>} HTML 字符串
 */
export async function renderMarkdown(markdown) {
  if (!markdown) return '';

  try {
    const markedLib = await ensureMarked();
    return markedLib.parse(markdown);
  } catch (e) {
    console.warn('[marked] 加载失败，回退到简易格式化:', e);
    return _fallbackRender(markdown);
  }
}

/**
 * 简易 Markdown 回退渲染（当 marked CDN 加载失败时使用）
 * 保留原有的正则替换逻辑，确保基本格式可用
 */
function _fallbackRender(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/```[\s\S]*?```/g, (match) => {
      const code = match.replace(/```\w*\n?/, '').replace(/```$/, '');
      return `<pre><code>${code}</code></pre>`;
    })
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
}
