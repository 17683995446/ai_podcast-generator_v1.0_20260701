// ════════════════════════════════════════
// 代码语法高亮工具 — 基于 highlight.js
// 动态加载 CDN，按需高亮页面中的代码块
// ════════════════════════════════════════

import { copyToClipboard } from './clipboard.js';

const HLJS_CDN_CORE = 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/highlight.min.js';

// 常用语言（按需加载，减小体积）
const HLJS_LANGUAGES = {
  bash: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/bash.min.js',
  python: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/python.min.js',
  javascript: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/javascript.min.js',
  typescript: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/typescript.min.js',
  go: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/go.min.js',
  rust: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/rust.min.js',
  json: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/json.min.js',
  yaml: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/yaml.min.js',
  shell: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/shell.min.js',
  dockerfile: 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/languages/dockerfile.min.js',
};

// highlight.js 主题 CSS（暗色主题，匹配 dashboard 深色模式）
const HLJS_THEME_CSS = 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/atom-one-dark.min.css';
const HLJS_THEME_LIGHT_CSS = 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11/build/styles/atom-one-light.min.css';

let _hljsLoaded = false;
let _hljsLoading = null;

// ── 动态加载 highlight.js 核心 + 常用语言 ──
export async function ensureHighlight() {
  if (_hljsLoaded && window.hljs) return true;
  if (_hljsLoading) return _hljsLoading;

  _hljsLoading = (async () => {
    // 1. 加载主题 CSS
    injectThemeCSS();

    // 2. 加载 highlight.js 核心
    await loadScript(HLJS_CDN_CORE);
    if (!window.hljs) {
      console.warn('[highlight] highlight.js 核心加载失败');
      return false;
    }

    // 3. 注册常用语言
    for (const [name, url] of Object.entries(HLJS_LANGUAGES)) {
      try {
        await loadScript(url);
        // highlight.js 11+ 自动注册通过 script 加载的语言
      } catch (e) {
        console.warn(`[highlight] 语言 ${name} 加载失败:`, e);
      }
    }

    _hljsLoaded = true;
    return true;
  })();

  return _hljsLoading;
}

// ── 注入主题 CSS（支持深色/浅色切换） ──
function injectThemeCSS() {
  if (document.getElementById('hljs-theme-dark')) return;

  // 暗色主题（默认）
  const darkLink = document.createElement('link');
  darkLink.id = 'hljs-theme-dark';
  darkLink.rel = 'stylesheet';
  darkLink.href = HLJS_THEME_CSS;
  darkLink.media = '(prefers-color-scheme: dark), (max-width: 0px)'; // 默认不启用，通过 JS 控制
  document.head.appendChild(darkLink);

  // 浅色主题
  const lightLink = document.createElement('link');
  lightLink.id = 'hljs-theme-light';
  lightLink.rel = 'stylesheet';
  lightLink.href = HLJS_THEME_LIGHT_CSS;
  lightLink.media = '(max-width: 0px)';
  document.head.appendChild(lightLink);

  // 根据当前主题启用对应 CSS
  updateTheme();
}

// ── 根据当前主题切换 highlight.js CSS ──
function updateTheme() {
  const isDark = document.body.classList.contains('dark-mode') ||
    !document.body.classList.contains('light-mode');
  const darkLink = document.getElementById('hljs-theme-dark');
  const lightLink = document.getElementById('hljs-theme-light');
  if (darkLink && lightLink) {
    darkLink.media = isDark ? 'all' : '(max-width: 0px)';
    lightLink.media = !isDark ? 'all' : '(max-width: 0px)';
  }
}

// 监听主题切换
if (typeof window !== 'undefined') {
  // MutationObserver 监听 body class 变化（主题切换时触发）
  const observer = new MutationObserver(() => updateTheme());
  observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

// ── 高亮容器内所有代码块 ──
export async function highlightAll(container = document) {
  const loaded = await ensureHighlight();
  if (!loaded || !window.hljs) return;

  // 查找所有 .code-block 元素，转换为 <pre><code> 结构并高亮
  const codeBlocks = container.querySelectorAll('.code-block:not([data-hljs])');
  for (const block of codeBlocks) {
    highlightCodeBlock(block);
  }

  // 也高亮 <pre><code> 元素（P0安全修复：先转义HTML再高亮，防止XSS）
  const preCodes = container.querySelectorAll('pre code:not([data-hljs])');
  for (const code of preCodes) {
    try {
      // 安全措施：用 textContent 重新设置内容，确保所有HTML被转义
      const rawText = code.textContent || '';
      if (rawText.trim()) {
        code.textContent = rawText;  // textContent 自动转义HTML
        // 清除旧的 highlighted 标记，避免 highlight.js 重复高亮警告
        delete code.dataset.highlighted;
        window.hljs.highlightElement(code);
        code.setAttribute('data-hljs', '1');
      }
    } catch (e) {
      // 忽略高亮失败
    }
  }
}

// ── 高亮单个 .code-block 元素 ──
function highlightCodeBlock(block) {
  const rawText = block.textContent || '';
  if (!rawText.trim()) return;

  // 检测语言（简单的启发式）
  const lang = detectLanguage(rawText);

  // 转换为 <pre><code> 结构
  const pre = document.createElement('pre');
  pre.className = 'hljs-pre';
  const code = document.createElement('code');
  code.className = lang ? `language-${lang}` : '';
  code.textContent = rawText;

  // 保留原有的 $ 前缀效果（通过 CSS）
  if (block.classList.contains('code-block')) {
    pre.classList.add('terminal-style');
  }

  pre.appendChild(code);
  block.innerHTML = '';
  block.appendChild(pre);
  block.setAttribute('data-hljs', '1');

  // 应用高亮
  try {
    if (lang) {
      // 清除 dataset.highlighted 避免重复高亮警告
      delete code.dataset.highlighted;
      window.hljs.highlightElement(code);
    } else {
      // 自动检测：用 highlightAuto 返回的 HTML 设置 innerHTML（highlightAuto 输出已转义的 HTML）
      const result = window.hljs.highlightAuto(code.textContent);
      code.innerHTML = result.value;
      code.className = `language-${result.language || 'plaintext'} hljs`;
      code.setAttribute('data-hljs', '1');
    }
  } catch (e) {
    // 高亮失败，保持纯文本
  }

  // 添加复制按钮
  addCopyButton(block, rawText);
}

// ── 语言检测（启发式） ──
function detectLanguage(text) {
  const lower = text.toLowerCase().trim();

  // Shell / 终端命令
  if (/^(pip |npm |yarn |cargo |go |python |node |docker |git |make |brew |apt |brew )/.test(lower) ||
      /^(curl |wget |export |source |cd |mkdir |chmod |sudo )/.test(lower)) {
    return 'bash';
  }

  // Python
  if (/\b(def |class |import |from |print\(|if __name__|self\.|lambda )/.test(text)) {
    return 'python';
  }

  // JavaScript / TypeScript
  if (/\b(function |const |let |var |console\.log|require\(|module\.exports|=>)/.test(text)) {
    return 'javascript';
  }

  // JSON
  if (/^\s*[\[{]/.test(text) && /[:]\s*["\d\[{]/.test(text)) {
    return 'json';
  }

  // YAML
  if (/^\s*[\w-]+:\s/.test(text) && !/[{};]/.test(text)) {
    return 'yaml';
  }

  // Go
  if (/\b(func |package |import \("|fmt\.|err )/.test(text)) {
    return 'go';
  }

  // Rust
  if (/\b(fn |let mut |pub fn |impl |use std::|println!)/.test(text)) {
    return 'rust';
  }

  // 默认：让 highlight.js 自动检测
  return null;
}

// ── 复制到剪贴板（由 utils/clipboard.js 提供，基于 copy-to-clipboard 库） ──

// ── 复制按钮 ──
function addCopyButton(block, text) {
  const btn = document.createElement('button');
  btn.className = 'code-copy-btn';
  btn.textContent = '复制';
  btn.title = '复制代码';
  btn.addEventListener('click', async () => {
    const ok = await copyToClipboard(text);
    if (ok) {
      btn.textContent = '已复制 ✓';
    } else {
      btn.textContent = '复制失败';
    }
    setTimeout(() => { btn.textContent = '复制'; }, 1500);
  });
  block.style.position = 'relative';
  block.appendChild(btn);
}

// ── 辅助：加载 script ──
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load: ${src}`));
    document.head.appendChild(script);
  });
}
