"""配置默认值常量 — 集中管理所有硬编码值的默认值。

设计原则（第一性原理）：
  1. 单一来源：所有默认值定义在此文件，其他模块引用而非重复定义
  2. 命名规范：SECTION_KEY 形式，如 LLM_TEMPERATURE、TTS_SAMPLE_RATE
  3. 可发现性：通过常量名即可了解可配置项
  4. 向后兼容：不改变 YAML 结构，仅提供默认值引用
"""
from __future__ import annotations

# ════════════════════════════════════════
# LLM 配置默认值
# ════════════════════════════════════════
LLM_BASE_URL = "https://api.siliconflow.cn/v1"
LLM_MODEL = "Qwen/Qwen3.5-9B"
LLM_ENABLE_THINKING = False
LLM_TEMPERATURE = 0.8
LLM_TEMPERATURE_OUTLINE = 0.6       # 大纲生成
LLM_TEMPERATURE_ANALYSIS = 0.4      # 项目分析
LLM_TEMPERATURE_MERMAID = 0.3       # 架构图
LLM_TEMPERATURE_REVIEW = 0.2        # 评审
LLM_TEMPERATURE_SCRIPT = 0.8        # 脚本生成
LLM_MAX_TOKENS = 4000
LLM_MAX_TOKENS_LONGFORM = 8000      # 长内容模式
LLM_TIMEOUT = 120

# 免费模型判定子串
FREE_MODEL_KEYWORDS = ["9B", "4B", "7B", "Flash", "flash"]

# ════════════════════════════════════════
# TTS 配置默认值
# ════════════════════════════════════════
TTS_BASE_URL = "https://api.siliconflow.cn/v1"
TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
TTS_RESPONSE_FORMAT = "wav"
TTS_SAMPLE_RATE = 24000
TTS_PROVIDER = "siliconflow"
TTS_VOICE_MAPPING = {
    "host": "alex",
    "guest": "anna",
}

# ════════════════════════════════════════
# Discovery 配置默认值
# ════════════════════════════════════════
DISCOVERY_RSSHUB_BASE_URL = "https://rsshub.app"
DISCOVERY_TRENDING_SINCE = "daily"
DISCOVERY_TRENDING_API_URL = "https://ghapi.huchen.dev/repositories"
DISCOVERY_MAX_PROJECTS = 3
DISCOVERY_MIN_STARS = 100
DISCOVERY_EXCLUDE_KEYWORDS = ["awesome", "interview", "leetcode"]
DISCOVERY_USER_AGENT = "github-podcast-tool/0.1"
DISCOVERY_SEARCH_STARS_THRESHOLD = 500
DISCOVERY_SEARCH_STARS_FALLBACK = 200

# ════════════════════════════════════════
# Crawler 配置默认值
# ════════════════════════════════════════
CRAWLER_JINA_READER_URL = "https://r.jina.ai"
CRAWLER_MAX_README_CHARS = 8000
CRAWLER_TIMEOUT = 30

# ════════════════════════════════════════
# Audio 配置默认值
# ════════════════════════════════════════
AUDIO_SEGMENT_SILENCE_MS = 400
AUDIO_SENTENCE_SILENCE_MS = 150
AUDIO_TARGET_LUFS = -16.0
AUDIO_OUTPUT_FORMAT = "mp3"
AUDIO_OUTPUT_BITRATE = "192k"

# ════════════════════════════════════════
# Publish 配置默认值
# ════════════════════════════════════════
PUBLISH_COVER_ART = "assets/cover.png"
PUBLISH_CATEGORY = "Technology"
PUBLISH_LANGUAGE = "zh-cn"
PUBLISH_EXPLICIT = False

# ════════════════════════════════════════
# Output 路径默认值
# ════════════════════════════════════════
OUTPUT_EPISODES_DIR = "output/episodes"
OUTPUT_FEED_PATH = "output/feed.xml"
OUTPUT_SCRIPTS_DIR = "output/scripts"
OUTPUT_ANALYSES_DIR = "output/analyses"
OUTPUT_REPORTS_DIR = "output/reports"
OUTPUT_SEGMENTS_TMP_DIR = "output/segments_tmp"
OUTPUT_LOG_FILE = "output/podcast.log"

# ════════════════════════════════════════
# Podcast 元信息默认值
# ════════════════════════════════════════
PODCAST_TITLE = "GitHub 前沿观察"
PODCAST_AUTHOR = "Anonymous"
PODCAST_STYLE = "casual"
PODCAST_STYLES = ["casual", "technical", "debate", "interview"]

# ════════════════════════════════════════
# Pipeline 配置默认值
# ════════════════════════════════════════
PIPELINE_TOTAL_STAGES = 9
PIPELINE_SEGMENTED_THRESHOLD = 3      # 3+ 项目触发分段生成
PIPELINE_MAX_REVISIONS = 2            # 脚本审查最大重写次数
PIPELINE_LOG_TAIL_LINES = 50          # 任务日志保留行数
PIPELINE_LOG_MAX_LINES = 500          # 日志最大行数

# ════════════════════════════════════════
# Console 配置
# ════════════════════════════════════════
CONSOLE_WIDTH = 200

# ════════════════════════════════════════
# API Key 环境变量名
# ════════════════════════════════════════
ENV_LLM_API_KEY = "LLM_API_KEY"
ENV_TTS_API_KEY = "TTS_API_KEY"
ENV_SILICONFLOW_API_KEY = "SILICONFLOW_API_KEY"
ENV_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
ENV_DASHSCOPE_API_KEY = "DASHSCOPE_API_KEY"
ENV_GITHUB_TOKEN = "GITHUB_TOKEN"
ENV_PODCAST_TITLE = "PODCAST_TITLE"
ENV_PODCAST_AUTHOR = "PODCAST_AUTHOR"
ENV_PODCAST_EMAIL = "PODCAST_EMAIL"
ENV_PODCAST_SITE_URL = "PODCAST_SITE_URL"
ENV_PODCAST_MEDIA_BASE_URL = "PODCAST_MEDIA_BASE_URL"
ENV_LOG_LEVEL = "LOG_LEVEL"
