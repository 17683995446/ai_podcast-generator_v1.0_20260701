// ════════════════════════════════════════
// stats.js — 统计卡片组件
// ════════════════════════════════════════
import { api } from '../api.js';
import { updateStatusBadge } from '../utils.js';

// 缓存上一次统计数据用于趋势对比
let _lastStats = null;

export async function loadStats() {
  try {
    const s = await api.getStats();

    // 趋势对比
    const trends = {
      episodes: _computeTrend(s.episodes, _lastStats?.episodes),
      duration: _computeTrend(s.total_duration_min, _lastStats?.total_duration_min),
      chars: _computeTrend(s.total_chars, _lastStats?.total_chars),
      size: _computeTrend(s.total_size_mb, _lastStats?.total_size_mb),
    };

    document.getElementById('statEpisodes').textContent = s.episodes;
    _setStatValue('statDuration', s.total_duration_min);
    document.getElementById('statChars').textContent = s.total_chars.toLocaleString();
    _setStatValue('statSize', s.total_size_mb);

    // 更新趋势指示器（如果 DOM 中存在）
    _updateTrend('statEpisodesTrend', trends.episodes);
    _updateTrend('statDurationTrend', trends.duration);
    _updateTrend('statCharsTrend', trends.chars);
    _updateTrend('statSizeTrend', trends.size);

    updateStatusBadge(s.task_running);

    _lastStats = { ...s };
  } catch (e) {
    const fallback = (id) => { const el = document.getElementById(id); if (el) el.textContent = '-'; };
    ['statEpisodes', 'statDuration', 'statChars', 'statSize'].forEach(fallback);
    console.error('loadStats 失败:', e);
  }
}

function _computeTrend(current, previous) {
  if (previous === undefined || previous === null) return { dir: 'neutral', text: '—' };
  const diff = current - previous;
  if (diff === 0) return { dir: 'neutral', text: '稳定' };
  if (diff > 0) return { dir: 'up', text: `↑ +${_formatNum(diff)}` };
  return { dir: 'down', text: `↓ ${_formatNum(diff)}` };
}

function _formatNum(n) {
  if (typeof n === 'number') {
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
    if (Number.isInteger(n)) return String(n);
    return n.toFixed(1);
  }
  return String(n);
}

function _updateTrend(elId, trend) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `stat-trend ${trend.dir}`;
  el.textContent = trend.text;
}

// 设置统计值，保留 .stat-unit 子元素
function _setStatValue(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  const unit = el.querySelector('.stat-unit');
  el.textContent = value;
  if (unit) el.appendChild(unit);
}
