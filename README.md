# GitHub 前沿观察 · 自动播客生成工具

> 自动获取 GitHub 前沿研究项目，用云端大模型转化为中文音频播客。站在巨人的肩膀上，零 GPU、低成本、可定时运行。

## ✨ 特性

- **全自动流水线**：项目发现 → README 抓取 → 脚本生成 → 语音合成 → 音频后期 → RSS 发布
- **云端优先**：无需本地 GPU，全部调用云端 API
- **极低成本**：单期 5 分钟播客约 ¥0.5-1（DeepSeek + 阿里云 CosyVoice）
- **多 Speaker 对话**：自动生成主持人 + 嘉宾的双人播客脚本与音频
- **Apple Podcasts 兼容**：生成标准播客 RSS feed，可直接提交到小宇宙/Apple Podcasts
- **GitHub Actions 定时**：每日自动生成新一期，零服务器成本
- **Dry-run 测试**：无 API Key 也可跑通完整流程

## 🏗️ 架构

```
GitHub Trending ──► README 抓取 ──► DeepSeek 脚本 ──► CosyVoice TTS ──► 音频后期 ──► RSS Feed
   (RSSHub)         (Jina Reader)    (云端 LLM)       (阿里云百炼)     (Pydub+LUFS)   (Apple兼容)
```

| 阶段 | 使用的开源/云服务 | 成本 |
|------|------------------|------|
| 项目发现 | RSSHub + huchenme/github-trending-api | 免费 |
| README 抓取 | Jina Reader（r.jina.ai） | 免费 |
| 脚本生成 | DeepSeek V4-Flash（OpenAI 兼容） | ¥0.04/期 |
| TTS 合成 | 阿里云百炼 CosyVoice v3-flash | ¥0.5/期 |
| 音频后期 | Pydub + pyloudnorm（-16 LUFS） | 免费 |
| 定时运行 | GitHub Actions | 免费（2000 分钟/月） |

## 🚀 快速开始

### 1. 安装

```bash
git clone <your-repo-url>
cd github-podcast-tool
pip install -r requirements.txt

# 系统需安装 FFmpeg（音频处理依赖）
# Ubuntu: sudo apt install ffmpeg
# macOS: brew install ffmpeg
```

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入以下密钥：
#   DEEPSEEK_API_KEY  - https://platform.deepseek.com （新用户 $5 免费）
#   DASHSCOPE_API_KEY - https://bailian.console.aliyun.com （新用户赠送额度）
#   GITHUB_TOKEN      - https://github.com/settings/tokens （可选，提升限流）
```

### 3. 先试跑（无需 API Key）

```bash
python main.py run --dry-run
```

这会使用内置样例数据走完整流程，生成一段静音占位音频 + RSS feed，验证安装无误。

### 4. 正式生成

```bash
python main.py run
```

输出：
- `output/episodes/episode_001.mp3` — 播客音频
- `output/feed.xml` — 播客 RSS feed
- `output/scripts/script_*.json` — 播客脚本

### 5. 其他命令

```bash
python main.py discover          # 仅发现并查看当前 GitHub 热门项目
python main.py list              # 查看已发布的节目历史
```

## ⚙️ 配置说明

编辑 `config.yaml` 自定义：

```yaml
discovery:
  trending_since: "daily"        # daily / weekly / monthly
  language: "python"             # 按语言过滤（留空则全部）
  max_projects: 3                # 每期讨论项目数
  min_stars: 100                 # 最低 Star 数
  keywords: ["ai", "llm"]        # 关键词白名单

tts:
  model: "cosyvoice-v3-flash"    # 或 cosyvoice-v3-plus（质量更高）
  voice_mapping:
    host: "longxiaocheng"        # 主持人音色（男声沉稳）
    guest: "longwan"             # 嘉宾音色（女声知性）

llm:
  model: "deepseek-chat"         # DeepSeek V4-Flash
  # 切换其他模型只需改 base_url：
  #   智谱 GLM-4.7-Flash（免费）: https://open.bigmodel.cn/api/paas/v4
  #   硅基流动: https://api.siliconflow.cn/v1
```

### CosyVoice 音色参考

完整列表见 [阿里云百炼音色列表](https://help.aliyun.com/zh/model-studio/multimodal-timbre-list)，常用：

| voice id | 名称 | 特点 |
|----------|------|------|
| `longxiaocheng` | 龙小成 | 男声，沉稳 |
| `longwan` | 龙婉 | 女声，知性 |
| `longxiaoxia` | 龙小夏 | 女声，活泼 |
| `longjielidou` | 龙杰力豆 | 男声，激情 |
| `longshu` | 龙叔 | 男声，成熟 |

## 🤖 GitHub Actions 自动化

项目已包含 `.github/workflows/daily_podcast.yml`，每日北京时间 09:00 自动生成。

配置步骤：
1. 将项目推送到 GitHub
2. 在仓库 Settings → Secrets 添加：
   - `DEEPSEEK_API_KEY`
   - `DASHSCOPE_API_KEY`
   - `PODCAST_MEDIA_BASE_URL`（音频文件的公开访问地址）
3. 也可在 Actions 页面手动触发（workflow_dispatch）

## 📁 项目结构

```
github-podcast-tool/
├── main.py                     # 主入口（CLI 编排）
├── config.yaml                 # 配置文件
├── .env.example                # 环境变量模板
├── requirements.txt
├── src/
│   ├── config_loader.py        # 配置加载
│   ├── models.py               # 数据模型
│   ├── discovery.py            # 项目发现（RSSHub + Trending API + Search）
│   ├── crawler.py              # README 抓取（Jina Reader + GitHub raw）
│   ├── llm_script.py           # LLM 脚本生成（DeepSeek）
│   ├── tts_synth.py            # TTS 合成（CosyVoice 多 speaker）
│   ├── audio_mixer.py          # 音频后期（拼接 + 响度归一）
│   └── rss_publisher.py        # RSS feed 生成
├── prompts/
│   └── podcast_system.txt      # 播客脚本系统提示词
├── .github/workflows/
│   └── daily_podcast.yml       # GitHub Actions 定时任务
├── tests/
│   └── test_dry_run.py         # 离线流程测试
└── output/                     # 输出目录
    ├── episodes/               # 音频文件
    ├── scripts/                # 脚本 JSON
    └── feed.xml                # RSS feed
```

## 💰 成本估算

| 项目 | 单期（5 分钟） | 月 30 期 |
|------|--------------|----------|
| DeepSeek LLM | ¥0.04 | ¥1.2 |
| CosyVoice TTS | ¥0.5 | ¥15 |
| GitHub Actions | 免费 | 免费 |
| **合计** | **≈ ¥0.5** | **≈ ¥16** |

> 零成本方案：智谱 GLM-4.7-Flash（永久免费）+ 腾讯云精品音色（800 万字符免费）

## 🔧 切换云服务

本项目设计为可插拔，切换 LLM 或 TTS 只需改配置：

### 切换 LLM

```yaml
llm:
  base_url: "https://open.bigmodel.cn/api/paas/v4"  # 智谱
  model: "glm-4.7-flash"                             # 永久免费
```

其他支持：硅基流动、Kimi、Qwen、OpenAI、Claude（均兼容 OpenAI SDK）。

### 切换 TTS

TTS 模块基于阿里云 dashscope SDK。如需切换到腾讯云/火山引擎，替换 `src/tts_synth.py` 中的 `_call_cosyvoice` 方法即可，接口保持一致。

## 📜 许可证

MIT

## 🙏 致谢

本项目站在以下开源/云服务的肩膀上：

- [RSSHub](https://github.com/DIYgod/RSSHub) — 万能 RSS 路由
- [huchenme/github-trending-api](https://github.com/huchenme/github-trending-api) — Trending API
- [Jina Reader](https://jina.ai/reader/) — 网页转 Markdown
- [DeepSeek](https://www.deepseek.com) — 高性价比 LLM
- [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) — 开源 TTS 大模型
- [Pydub](https://github.com/jiaaro/pydub) — 音频处理
- [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm) — 响度归一化
- [feedgen](https://github.com/lkiesow/python-feedgen) — RSS feed 生成
