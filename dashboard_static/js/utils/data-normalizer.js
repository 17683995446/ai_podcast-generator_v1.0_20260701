// ════════════════════════════════════════
// data-normalizer.js — 字典/字符串混排数据归一化
// 兼容：纯字符串、JS 对象、Python repr dict 字符串（如 {'point': '...', 'value': '...'}）
//
// 提取自 episodes.js 和 analysis.js 中重复的 ~200 行代码
// 采用 analysis.js 中更健壮的实现版本（含 startsWith/endsWith 检查、正则兜底等）
// ════════════════════════════════════════

/**
 * 从对象中按候选键取第一个非空字符串值
 * @param {Object} obj - 数据对象
 * @param {string[]} keys - 候选键名列表
 * @returns {string} 第一个非空值，无匹配时返回空字符串
 */
export function pickField(obj, keys) {
  if (!obj || typeof obj !== 'object') return '';
  for (const k of keys) {
    const v = obj[k];
    if (v != null && v !== '') return String(v);
  }
  return '';
}

/**
 * 尝试把字符串解析为对象（兼容 JSON / Python repr dict）
 * @param {string} s - 输入字符串
 * @returns {Object|null} 解析成功返回对象，失败返回 null
 */
export function tryParseDict(s) {
  if (typeof s !== 'string') return null;
  const t = s.trim();
  // [object Object] 或非 dict 形式无法解析
  if (t === '[object Object]' || !t.startsWith('{') || !t.endsWith('}')) return null;

  // 1) 直接 JSON 解析（已是合法 JSON 时）
  try {
    const o = JSON.parse(t);
    if (o && typeof o === 'object' && !Array.isArray(o)) return o;
  } catch (e) { /* fallthrough */ }

  // 2) Python repr → JSON：暂存转义单引号 → 替换常量 → 单引号定界转双引号 → 还原撇号
  const j = t
    .replace(/\\'/g, '\x01')
    .replace(/\bTrue\b/g, 'true')
    .replace(/\bFalse\b/g, 'false')
    .replace(/\bNone\b/g, 'null')
    .replace(/'/g, '"')
    .replace(/\x01/g, "'");
  try {
    const o = JSON.parse(j);
    if (o && typeof o === 'object' && !Array.isArray(o)) return o;
  } catch (e) { /* fallthrough */ }

  return null;
}

/**
 * 正则兜底：从 Python repr 字符串中抽取指定键的字符串值
 * @param {string} str - Python repr 字符串
 * @param {string} key - 要抽取的键名
 * @returns {string} 抽取到的值，无匹配时返回空字符串
 */
export function extractPyField(str, key) {
  const re = new RegExp(`['"]${key}['"]\\s*:\\s*(['"])((?:[^\\\\]|\\\\.)*?)\\1`);
  const m = str.match(re);
  if (!m) return '';
  return m[2]
    .replace(/\\(['"])/g, '$1')
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\\\/g, '\\');
}

/**
 * 技术亮点条目归一化 → { title, desc }（title 可空）
 * 兼容：JS 对象、JSON 字符串、Python repr dict 字符串、纯字符串
 * @param {*} h - 原始数据
 * @returns {{title:string,desc:string}|null} 归一化后的对象
 */
export function normalizeHighlight(h) {
  if (h == null) return null;
  if (typeof h === 'object' && !Array.isArray(h)) {
    const title = pickField(h, ['point', 'title', 'name', 'highlight']);
    const desc = pickField(h, ['value', 'desc', 'description', 'detail', 'text']);
    return (title || desc) ? { title, desc } : null;
  }
  if (typeof h === 'string') {
    const parsed = tryParseDict(h);
    if (parsed) {
      const title = pickField(parsed, ['point', 'title', 'name', 'highlight']);
      const desc = pickField(parsed, ['value', 'desc', 'description', 'detail', 'text']);
      if (title || desc) return { title, desc };
    }
    // 正则兜底（针对未成功 JSON 化的 Python repr）
    if (h.trim().startsWith('{')) {
      const title = extractPyField(h, 'point') || extractPyField(h, 'title') || extractPyField(h, 'name');
      const desc = extractPyField(h, 'value') || extractPyField(h, 'desc') || extractPyField(h, 'description');
      if (title || desc) return { title, desc };
    }
    // 纯字符串：保持向后兼容
    return { title: '', desc: h };
  }
  return null;
}

/**
 * 应用场景条目归一化 → { title, desc }（title 可空）
 * 兼容：JS 对象、JSON 字符串、Python repr dict 字符串、纯字符串
 * @param {*} u - 原始数据
 * @returns {{title:string,desc:string}|null} 归一化后的对象
 */
export function normalizeUseCase(u) {
  if (u == null) return null;
  const buildFrom = (o) => {
    const title = pickField(o, ['who', 'target', 'audience', 'user']);
    const scenario = pickField(o, ['scenario', 'scene', 'context', 'situation']);
    const solve = pickField(o, ['solve', 'solution', 'benefit', 'value']);
    if (title || scenario || solve) {
      const desc = [scenario, solve].filter(Boolean).join('；');
      return { title, desc };
    }
    return null;
  };
  if (typeof u === 'object' && !Array.isArray(u)) {
    return buildFrom(u);
  }
  if (typeof u === 'string') {
    const parsed = tryParseDict(u);
    if (parsed) {
      const r = buildFrom(parsed);
      if (r) return r;
    }
    // 正则兜底
    if (u.trim().startsWith('{')) {
      const title = extractPyField(u, 'who') || extractPyField(u, 'target') || extractPyField(u, 'audience');
      const scenario = extractPyField(u, 'scenario') || extractPyField(u, 'scene') || extractPyField(u, 'context');
      const solve = extractPyField(u, 'solve') || extractPyField(u, 'solution') || extractPyField(u, 'benefit');
      if (title || scenario || solve) {
        const desc = [scenario, solve].filter(Boolean).join('；');
        return { title, desc };
      }
    }
    // 纯字符串：保持向后兼容
    return { title: '', desc: u };
  }
  return null;
}

/**
 * 渲染单条 insight 列表项：<li><strong>标题</strong>：描述</li>
 * @param {{title:string,desc:string}|null} item - 归一化后的条目
 * @param {Function} [escapeFn] - HTML 转义函数（默认不转义，调用方应传入 escapeHtml）
 * @returns {string} HTML 字符串
 */
export function renderInsightItem(item, escapeFn = (s) => s) {
  if (!item) return '';
  const { title, desc } = item;
  if (title && desc) {
    return `<li><strong>${escapeFn(title)}</strong>：${escapeFn(desc)}</li>`;
  }
  if (title) {
    return `<li><strong>${escapeFn(title)}</strong></li>`;
  }
  return `<li>${escapeFn(desc)}</li>`;
}
