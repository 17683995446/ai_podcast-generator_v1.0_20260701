// ════════════════════════════════════════
// 持久化音频播放器 — 基于 Howler.js
// 悬浮在页面底部，跨页面导航持续播放
// Howler.js 提供：Web Audio API 优先、HTML5 回退、淡入淡出、跨浏览器兼容
// ════════════════════════════════════════

let howl = null;        // Howl 实例
let playerEl = null;    // 播放器 DOM 元素
let currentEp = null;   // 当前播放的节目信息 { url, title, epNum }
let isPlaying = false;  // 播放状态（Howler 无 paused 属性，需手动跟踪）
let howlerReady = null; // Howler.js 加载 Promise（避免重复加载）
let isLoading = false;  // 加载/切换中标志（防止 playEpisode 重入）
let playRequestId = 0;  // 代际计数器（使过期的异步回调失效）
let playPending = false;// play() 已调用但 play 事件尚未触发（防止双重播放）
let globalRafId = null; // 全局 rAF ID（卸载 Howl 时取消进度轮询）

// ── Howler.js 动态加载 ──
const HOWLER_CDN = 'https://cdn.jsdelivr.net/npm/howler@2.2.4/dist/howler.min.js';

async function ensureHowler() {
  if (window.Howl) return true;
  if (howlerReady) return howlerReady;

  howlerReady = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = HOWLER_CDN;
    script.onload = () => resolve(true);
    script.onerror = () => {
      console.warn('[player] Howler.js CDN 加载失败，回退到 HTML5 Audio');
      howlerReady = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return howlerReady;
}

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
  if (isPlaying) {
    btn.classList.add('playing');
    btn.textContent = '⏸ 暂停';
  } else {
    btn.classList.remove('playing');
    btn.textContent = '▶ 播放';
  }
}

function ensurePlayer() {
  if (playerEl) return;

  // 创建播放器 DOM
  playerEl = document.createElement('div');
  playerEl.className = 'player-bar';
  playerEl.setAttribute('role', 'region');
  playerEl.setAttribute('aria-label', '音频播放器');
  playerEl.innerHTML = `
    <div class="player-info">
      <div class="player-ep-badge"></div>
      <div class="player-title-text" aria-live="polite">未播放</div>
    </div>
    <div class="player-center">
      <button class="player-btn player-play-btn" title="播放/暂停" aria-label="播放或暂停">▶</button>
      <div class="player-progress-wrap">
        <span class="player-time player-current">0:00</span>
        <div class="player-seek-bar">
          <div class="player-seek-fill"></div>
          <input type="range" class="player-seek-input" min="0" max="100" value="0" step="0.1" aria-label="播放进度">
        </div>
        <span class="player-time player-total">0:00</span>
      </div>
    </div>
    <div class="player-right">
      <button class="player-btn player-mute-btn" title="静音" aria-label="静音切换">🔊</button>
      <input type="range" class="player-vol-input" min="0" max="100" value="100" aria-label="音量">
      <button class="player-btn player-close-btn" title="关闭" aria-label="关闭播放器">✕</button>
    </div>
  `;
  document.body.appendChild(playerEl);

  // ── 播放器按钮事件（防抖：playPending 期间忽略点击） ──
  playerEl.querySelector('.player-play-btn').addEventListener('click', () => {
    if (!howl || playPending || isLoading) return;
    if (isPlaying) {
      howl.pause();
    } else {
      playPending = true;
      howl.play();
    }
  });

  // 进度条拖动
  const seekInput = playerEl.querySelector('.player-seek-input');
  seekInput.addEventListener('input', () => {
    if (howl && howl.duration()) {
      howl.seek((seekInput.value / 100) * howl.duration());
    }
  });

  // 音量控制
  const volInput = playerEl.querySelector('.player-vol-input');
  volInput.addEventListener('input', () => {
    const vol = volInput.value / 100;
    if (howl) howl.volume(vol);
    const muteBtn = playerEl.querySelector('.player-mute-btn');
    muteBtn.textContent = vol === 0 ? '🔇' : '🔊';
  });

  // 静音按钮
  playerEl.querySelector('.player-mute-btn').addEventListener('click', () => {
    if (!howl) return;
    const muted = !howl.mute();
    howl.mute(muted);
    playerEl.querySelector('.player-mute-btn').textContent = muted ? '🔇' : '🔊';
  });

  // 关闭按钮
  playerEl.querySelector('.player-close-btn').addEventListener('click', () => {
    if (globalRafId) {
      cancelAnimationFrame(globalRafId);
      globalRafId = null;
    }
    if (howl) {
      howl.stop();
      howl.unload();
      howl = null;
    }
    isPlaying = false;
    isLoading = false;
    playPending = false;
    playRequestId++;
    playerEl.classList.remove('visible');
    playerEl.classList.remove('playing');
    currentEp = null;
    // 重置播放器 UI 信息
    playerEl.querySelector('.player-ep-badge').textContent = '';
    playerEl.querySelector('.player-title-text').textContent = '未播放';
    playerEl.querySelector('.player-play-btn').textContent = '▶';
    playerEl.querySelector('.player-current').textContent = '0:00';
    playerEl.querySelector('.player-total').textContent = '0:00';
    playerEl.querySelector('.player-seek-input').value = 0;
    playerEl.querySelector('.player-seek-fill').style.width = '0%';
    playerEl.querySelector('.player-vol-input').value = 100;
    playerEl.querySelector('.player-mute-btn').textContent = '🔊';
    // 清除节目列表中的播放状态
    document.querySelectorAll('.ep-play-btn.playing').forEach(btn => {
      btn.classList.remove('playing');
      btn.textContent = '▶ 播放';
    });
    // 清除节目卡片的 now-playing 标记
    document.querySelectorAll('.episode-item.now-playing').forEach(item => {
      item.classList.remove('now-playing');
    });
  });
}

// ── 创建 Howl 实例并绑定事件 ──
function createHowl(url) {
  const newHowl = new Howl({
    src: [url],
    html5: true,       // 使用 HTML5 Audio（流式加载，适合长音频）
    volume: 1.0,
    format: ['mp3'],
  });

  // ── Howl 事件绑定（替代 Audio addEventListener） ──
  newHowl.on('load', () => {
    if (playerEl) {
      playerEl.querySelector('.player-total').textContent = formatTime(newHowl.duration());
    }
  });

  newHowl.on('play', () => {
    playPending = false;
    isLoading = false;
    isPlaying = true;
    if (playerEl) {
      playerEl.querySelector('.player-play-btn').textContent = '⏸';
      playerEl.classList.add('playing');
    }
    updatePlayButtonInList();
  });

  newHowl.on('pause', () => {
    isPlaying = false;
    if (playerEl) {
      playerEl.querySelector('.player-play-btn').textContent = '▶';
      playerEl.classList.remove('playing');
    }
    updatePlayButtonInList();
  });

  newHowl.on('end', () => {
    isPlaying = false;
    if (playerEl) {
      playerEl.querySelector('.player-play-btn').textContent = '▶';
      playerEl.classList.remove('playing');
      // 重置进度条
      playerEl.querySelector('.player-seek-input').value = 0;
      playerEl.querySelector('.player-seek-fill').style.width = '0%';
      playerEl.querySelector('.player-current').textContent = '0:00';
    }
    updatePlayButtonInList();
  });

  newHowl.on('loaderror', (id, err) => {
    console.warn('[player] 音频加载失败:', err);
    playPending = false;
    isLoading = false;
    isPlaying = false;
    if (playerEl) {
      playerEl.querySelector('.player-play-btn').textContent = '▶';
      playerEl.classList.remove('playing');
    }
    updatePlayButtonInList();
  });

  newHowl.on('playerror', (id, err) => {
    console.warn('[player] 播放失败:', err);
    playPending = false;
    isLoading = false;
    isPlaying = false;
    if (playerEl) {
      playerEl.querySelector('.player-play-btn').textContent = '▶';
      playerEl.classList.remove('playing');
    }
    updatePlayButtonInList();
  });

  // ── 进度更新（Howler 无 timeupdate 事件，用 requestAnimationFrame 轮询） ──
  function updateProgress() {
    if (!isPlaying || !newHowl || !playerEl) {
      globalRafId = null;
      return;
    }
    const duration = newHowl.duration();
    if (duration) {
      const current = newHowl.seek();
      const pct = (current / duration) * 100;
      playerEl.querySelector('.player-seek-input').value = pct;
      playerEl.querySelector('.player-seek-fill').style.width = pct + '%';
      playerEl.querySelector('.player-current').textContent = formatTime(current);
    }
    globalRafId = requestAnimationFrame(updateProgress);
  }

  // 播放时启动进度轮询，暂停时停止
  newHowl.on('play', () => {
    if (!globalRafId) updateProgress();
  });
  newHowl.on('pause', () => {
    if (globalRafId) {
      cancelAnimationFrame(globalRafId);
      globalRafId = null;
    }
  });
  newHowl.on('end', () => {
    if (globalRafId) {
      cancelAnimationFrame(globalRafId);
      globalRafId = null;
    }
  });

  return newHowl;
}

// ════════════════════════════════════════
// 播放节目（外部调用接口）
// 防护机制：
//   1. isLoading — playEpisode 执行期间拒绝重入
//   2. playRequestId — 代际计数器，await 后若已被后续调用超越则放弃
//   3. playPending — play() 已调用但 play 事件未触发时阻止再次 play()
// ════════════════════════════════════════
export async function playEpisode(url, title, epNum) {
  // 防护 1：加载/切换中时直接忽略（防止连续乱点）
  if (isLoading) return;

  ensurePlayer();

  // 确保 Howler.js 已加载
  const howlerLoaded = await ensureHowler();
  if (!howlerLoaded) {
    // Howler.js 加载失败，回退到 HTML5 Audio
    fallbackPlay(url, title, epNum);
    return;
  }

  // 防护 2：代际计数器 — await 期间若有新请求则放弃本次操作
  const myRequestId = ++playRequestId;

  // 同一节目：切换播放/暂停
  if (currentEp && currentEp.url === url && howl) {
    // playPending 期间不响应（防止双重播放）
    if (playPending) return;
    if (isPlaying) {
      howl.pause();
    } else {
      playPending = true;
      howl.play();
    }
    return;
  }

  // 新节目：设置加载锁
  isLoading = true;

  // 卸载旧的 Howl，清理 rAF
  if (globalRafId) {
    cancelAnimationFrame(globalRafId);
    globalRafId = null;
  }
  if (howl) {
    howl.stop();
    howl.unload();
    howl = null;
  }
  // 重置状态（stop 不一定触发 pause/end 事件）
  isPlaying = false;
  playPending = false;

  // 防护 2 检查：await 期间若有新请求则放弃
  if (myRequestId !== playRequestId) {
    isLoading = false;
    return;
  }

  currentEp = { url, title, epNum };
  howl = createHowl(url);
  playPending = true;
  howl.play();

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
  // 清除旧的 now-playing 标记
  document.querySelectorAll('.episode-item.now-playing').forEach(item => {
    item.classList.remove('now-playing');
  });
  const btn = document.querySelector(`.ep-play-btn[data-ep="${epNum}"]`);
  if (btn) {
    btn.classList.add('playing');
    btn.textContent = '⏸ 暂停';
  }
  // 添加 now-playing 标记到节目卡片
  const epItem = document.querySelector(`.episode-item[data-ep-num="${epNum}"]`);
  if (epItem) {
    epItem.classList.add('now-playing');
  }

  // isLoading 在 Howl 'play' 事件中清除（见 createHowl）
  // 安全兜底：3 秒后强制清除（防止 play 事件未触发导致死锁）
  setTimeout(() => {
    if (myRequestId === playRequestId) {
      isLoading = false;
      if (!isPlaying) playPending = false;
    }
  }, 3000);
}

// 获取当前播放的节目编号（供页面模块同步 UI）
export function getCurrentPlaying() {
  if (!currentEp || !isPlaying) return null;
  return currentEp.epNum;
}

export function initPlayer() {
  ensurePlayer();
  // 预加载 Howler.js（不阻塞，后台加载）
  ensureHowler();
}

// ════════════════════════════════════════
// 降级方案：Howler.js 加载失败时回退到原生 HTML5 Audio
// ════════════════════════════════════════
let fallbackAudio = null;

function fallbackPlay(url, title, epNum) {
  if (!fallbackAudio) {
    fallbackAudio = new Audio();
    fallbackAudio.volume = 1.0;

    fallbackAudio.addEventListener('timeupdate', () => {
      if (!fallbackAudio.duration || !playerEl) return;
      const pct = (fallbackAudio.currentTime / fallbackAudio.duration) * 100;
      playerEl.querySelector('.player-seek-input').value = pct;
      playerEl.querySelector('.player-seek-fill').style.width = pct + '%';
      playerEl.querySelector('.player-current').textContent = formatTime(fallbackAudio.currentTime);
    });

    fallbackAudio.addEventListener('loadedmetadata', () => {
      if (playerEl) {
        playerEl.querySelector('.player-total').textContent = formatTime(fallbackAudio.duration);
      }
    });

    fallbackAudio.addEventListener('play', () => {
      playPending = false;
      isLoading = false;
      isPlaying = true;
      if (playerEl) {
        playerEl.querySelector('.player-play-btn').textContent = '⏸';
        playerEl.classList.add('playing');
      }
      updatePlayButtonInList();
    });

    fallbackAudio.addEventListener('pause', () => {
      isPlaying = false;
      if (playerEl) {
        playerEl.querySelector('.player-play-btn').textContent = '▶';
        playerEl.classList.remove('playing');
      }
      updatePlayButtonInList();
    });

    fallbackAudio.addEventListener('ended', () => {
      isPlaying = false;
      if (playerEl) {
        playerEl.querySelector('.player-play-btn').textContent = '▶';
        playerEl.classList.remove('playing');
      }
      updatePlayButtonInList();
    });

    // 绑定控制按钮到 fallback audio（防抖）
    playerEl.querySelector('.player-play-btn').addEventListener('click', () => {
      if (!fallbackAudio || playPending || isLoading) return;
      if (fallbackAudio.paused) {
        playPending = true;
        fallbackAudio.play().catch(e => { console.warn('播放失败:', e); playPending = false; });
      } else {
        fallbackAudio.pause();
      }
    });

    playerEl.querySelector('.player-seek-input').addEventListener('input', (e) => {
      if (fallbackAudio && fallbackAudio.duration) {
        fallbackAudio.currentTime = (e.target.value / 100) * fallbackAudio.duration;
      }
    });

    playerEl.querySelector('.player-vol-input').addEventListener('input', (e) => {
      if (fallbackAudio) fallbackAudio.volume = e.target.value / 100;
      const muteBtn = playerEl.querySelector('.player-mute-btn');
      muteBtn.textContent = e.target.value == 0 ? '🔇' : '🔊';
    });

    playerEl.querySelector('.player-mute-btn').addEventListener('click', () => {
      if (!fallbackAudio) return;
      fallbackAudio.muted = !fallbackAudio.muted;
      playerEl.querySelector('.player-mute-btn').textContent = fallbackAudio.muted ? '🔇' : '🔊';
    });

    playerEl.querySelector('.player-close-btn').addEventListener('click', () => {
      if (fallbackAudio) {
        fallbackAudio.pause();
        fallbackAudio.currentTime = 0;
      }
      isPlaying = false;
      isLoading = false;
      playPending = false;
      playRequestId++;
      playerEl.classList.remove('visible');
      playerEl.classList.remove('playing');
      currentEp = null;
      // 重置播放器 UI 信息
      playerEl.querySelector('.player-ep-badge').textContent = '';
      playerEl.querySelector('.player-title-text').textContent = '未播放';
      playerEl.querySelector('.player-play-btn').textContent = '▶';
      playerEl.querySelector('.player-current').textContent = '0:00';
      playerEl.querySelector('.player-total').textContent = '0:00';
      playerEl.querySelector('.player-seek-input').value = 0;
      playerEl.querySelector('.player-seek-fill').style.width = '0%';
      playerEl.querySelector('.player-vol-input').value = 100;
      playerEl.querySelector('.player-mute-btn').textContent = '🔊';
      // 清除节目列表中的播放状态
      document.querySelectorAll('.ep-play-btn.playing').forEach(btn => {
        btn.classList.remove('playing');
        btn.textContent = '▶ 播放';
      });
      // 清除节目卡片的 now-playing 标记
      document.querySelectorAll('.episode-item.now-playing').forEach(item => {
        item.classList.remove('now-playing');
      });
    });
  }

  // 同一节目：切换播放/暂停
  if (currentEp && currentEp.url === url) {
    if (playPending) return;
    if (fallbackAudio.paused) {
      playPending = true;
      fallbackAudio.play().catch(e => { console.warn('播放失败:', e); playPending = false; });
    } else {
      fallbackAudio.pause();
    }
    return;
  }

  // 新节目
  isLoading = true;
  if (fallbackAudio) {
    fallbackAudio.pause();
  }
  isPlaying = false;
  playPending = false;

  currentEp = { url, title, epNum };
  fallbackAudio.src = url;
  playPending = true;
  fallbackAudio.play().catch(e => { console.warn('播放失败:', e); playPending = false; isLoading = false; });

  playerEl.classList.add('visible');
  playerEl.querySelector('.player-ep-badge').textContent = 'EP' + String(epNum).padStart(3, '0');
  playerEl.querySelector('.player-title-text').textContent = title;

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
