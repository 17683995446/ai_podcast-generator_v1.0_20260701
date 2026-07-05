// ════════════════════════════════════════
// config-panel.js — 配置面板组件
// ════════════════════════════════════════
import { api } from '../api.js';
import { escapeHtml } from '../utils.js';

export async function loadConfig() {
  const panel = document.getElementById('configPanel');
  if (!panel) return;
  try {
    const data = await api.getConfig();
    const cfg = data.config || {};
    const env = data.env || {};

    // 安全访问嵌套配置，避免 undefined 解构异常
    const llm = cfg.llm || {};
    const tts = cfg.tts || {};
    const discovery = cfg.discovery || {};
    const voiceMapping = tts.voice_mapping || {};

    let html = '';
    // LLM
    html += `<div class="config-block"><h4>🤖 LLM</h4>`;
    html += row('模型', llm.model);
    html += row('Base URL', llm.base_url);
    html += row('thinking', llm.enable_thinking);
    html += `</div>`;
    // TTS
    html += `<div class="config-block"><h4>🔊 TTS</h4>`;
    html += row('Provider', tts.provider);
    html += row('模型', tts.model);
    html += row('主持人音色', voiceMapping.host);
    html += row('嘉宾音色', voiceMapping.guest);
    html += `</div>`;
    // Discovery
    html += `<div class="config-block"><h4>🔍 发现</h4>`;
    html += row('每期项目数', discovery.max_projects);
    html += row('最低 Star', discovery.min_stars);
    html += row('周期', discovery.trending_since);
    html += `</div>`;
    // API Keys
    html += `<div class="config-block"><h4>🔑 API Keys (.env)</h4>`;
    for (const [k, v] of Object.entries(env)) {
      html += row(k, v);
    }
    html += `</div>`;

    panel.innerHTML = html;
  } catch (e) {
    panel.innerHTML = '<div class="log-empty">配置加载失败</div>';
    console.error('loadConfig 失败:', e);
  }
}

// 配置行（内部函数）— 值为 null/undefined 时显示占位符
function row(k, v) {
  const display = (v === null || v === undefined) ? '—' : String(v);
  return `<div class="config-row"><span class="config-key">${escapeHtml(k)}</span><span class="config-val">${escapeHtml(display)}</span></div>`;
}
