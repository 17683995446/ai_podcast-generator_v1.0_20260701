// ════════════════════════════════════════
// 持久化音频播放器 — 悬浮在页面底部
// 跨页面导航持续播放，不被 DOM 切换影响
// ════════════════════════════════════════

let audioEl = null;
let playerEl = null;
let currentEp = null;

function formatTime(sec) {
  if (!sec || isNaN(sec)) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function updatePlayButtonInList() {
  if (!currentEp) return;
  const btn = document.querySelector(`.ep-play-btn[data-ep="${currentEp.epNum}"]`);
  if (!btn) return;
  if (audioEl.paused) {
    btn.classList.remove('playing');
    btn.textContent = '▶ 播放';
  } else {
    btn.classList.add('playing');
    btn.textContent = '⏸ 暂停';
  }
}

function ensurePlayer() {
  if (playerEl) return;

  // 创建播放器 DOM
  playerEl = document.createElement('div');
  playerEl.className = 'player-bar';
  playerEl.innerHTML = `
    <div class="player-info">
      <div class="player-ep-badge"></div>
      <div class="player-title-text">未播放</div>
    </div>
    <div class="player-center">
      <button class="player-btn player-play-btn" title="播放/暂停">▶</button>
      <div class="player-progress-wrap">
        <span class="player-time player-current">0:00</span>
        <div class="player-seek-bar">
          <div class="player-seek-fill"></div>
          <input type="range" class="player-seek-input" min="0" max="100" value="0" step="0.1">
        </div>
        <span class="player-time player-total">0:00</span>
      </div>
    </div>
    <div class="player-right">
      <button class="player-btn player-mute-btn" title="静音">🔊</button>
      <input type="range" class="player-vol-input" min="0" max="100" value="100">
      <button class="player-btn player-close-btn" title="关闭">✕</button>
    </div>
  `;
  document.body.appendChild(playerEl);

  // 创建独立 Audio 对象（不在 container 内，不会被 SPA 切换销毁）
  audioEl = new Audio();
  audioEl.volume = 1.0;

  // ── Audio 事件绑定 ──
  audioEl.addEventListener('timeupdate', () => {
    if (!audioEl.duration) return;
    const pct = (audioEl.currentTime / audioEl.duration) * 100;
    playerEl.querySelector('.player-seek-input').value = pct;
    playerEl.querySelector('.player-seek-fill').style.width = pct + '%';
    playerEl.querySelector('.player-current').textContent = formatTime(audioEl.currentTime);
  });

  audioEl.addEventListener('loadedmetadata', () => {
    playerEl.querySelector('.player-total').textContent = formatTime(audioEl.duration);
  });

  audioEl.addEventListener('play', () => {
    playerEl.querySelector('.player-play-btn').textContent = '⏸';
    playerEl.classList.add('playing');
    updatePlayButtonInList();
  });

  audioEl.addEventListener('pause', () => {
    playerEl.querySelector('.player-play-btn').textContent = '▶';
    playerEl.classList.remove('playing');
    updatePlayButtonInList();
  });

  audioEl.addEventListener('ended', () => {
    playerEl.querySelector('.player-play-btn').textContent = '▶';
    playerEl.classList.remove('playing');
    updatePlayButtonInList();
  });

  // ── 播放器按钮事件 ──
  playerEl.querySelector('.player-play-btn').addEventListener('click', () => {
    if (audioEl.paused) {
      audioEl.play().catch(e => console.warn('播放失败:', e));
    } else {
      audioEl.pause();
    }
  });

  // 进度条拖动
  const seekInput = playerEl.querySelector('.player-seek-input');
  seekInput.addEventListener('input', () => {
    if (audioEl.duration) {
      audioEl.currentTime = (seekInput.value / 100) * audioEl.duration;
    }
  });

  // 音量控制
  const volInput = playerEl.querySelector('.player-vol-input');
  volInput.addEventListener('input', () => {
    audioEl.volume = volInput.value / 100;
    const muteBtn = playerEl.querySelector('.player-mute-btn');
    muteBtn.textContent = audioEl.volume === 0 ? '🔇' : '🔊';
  });

  // 静音按钮
  playerEl.querySelector('.player-mute-btn').addEventListener('click', () => {
    audioEl.muted = !audioEl.muted;
    playerEl.querySelector('.player-mute-btn').textContent = audioEl.muted ? '🔇' : '🔊';
  });

  // 关闭按钮
  playerEl.querySelector('.player-close-btn').addEventListener('click', () => {
    audioEl.pause();
    audioEl.currentTime = 0;
    playerEl.classList.remove('visible');
    currentEp = null;
    document.querySelectorAll('.ep-play-btn.playing').forEach(btn => {
      btn.classList.remove('playing');
      btn.textContent = '▶ 播放';
    });
  });
}

// ════════════════════════════════════════
// 播放节目（外部调用接口）
// ════════════════════════════════════════
export function playEpisode(url, title, epNum) {
  ensurePlayer();

  // 同一节目：切换播放/暂停
  if (currentEp && currentEp.url === url) {
    if (audioEl.paused) {
      audioEl.play().catch(e => console.warn('播放失败:', e));
    } else {
      audioEl.pause();
    }
    return;
  }

  // 新节目：加载并播放
  currentEp = { url, title, epNum };
  audioEl.src = url;
  audioEl.play().catch(e => console.warn('播放失败:', e));

  // 显示播放器
  playerEl.classList.add('visible');

  // 更新播放器信息
  playerEl.querySelector('.player-ep-badge').textContent = 'EP' + String(epNum).padStart(3, '0');
  playerEl.querySelector('.player-title-text').textContent = title;

  // 清除旧的高亮，设置新的高亮
  document.querySelectorAll('.ep-play-btn.playing').forEach(btn => {
    btn.classList.remove('playing');
    btn.textContent = '▶ 播放';
  });
  const btn = document.querySelector(`.ep-play-btn[data-ep="${epNum}"]`);
  if (btn) {
    btn.classList.add('playing');
    btn.textContent = '⏸ 暂停';
  }
}

// 获取当前播放的节目编号（供页面模块同步 UI）
export function getCurrentPlaying() {
  if (!currentEp || audioEl.paused) return null;
  return currentEp.epNum;
}

export function initPlayer() {
  ensurePlayer();
}
