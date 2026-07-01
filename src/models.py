"""数据模型定义。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class GitHubRepo:
    """从 GitHub Trending / RSS 发现的仓库。"""

    name: str                       # owner/repo
    url: str                        # 仓库地址
    description: str = ""
    stars: int = 0
    language: str = ""
    topics: list[str] = field(default_factory=list)
    readme_markdown: str = ""       # 抓取后的 README 内容
    trending_rank: int = 0          # 在 trending 中的排名

    @property
    def short_name(self) -> str:
        """仅仓库名（不含 owner）。"""
        return self.name.split("/")[-1]


@dataclass
class PodcastHost:
    """播客主持人/嘉宾。"""

    name: str
    persona: str                    # 角色设定
    voice_key: str = "host"         # 映射到 config.tts.voice_mapping


@dataclass
class PodcastSegment:
    """播客单段对话。"""

    speaker: str                    # 主持人名字
    text: str                       # 台词
    emotion: str = "neutral"        # 情感标签：excited/neutral/curious/happy/sad
    voice_key: str = "host"         # TTS 音色映射键
    start_time: float = 0.0         # 该段在最终音频中的起始时间（秒）
    end_time: float = 0.0           # 该段在最终音频中的结束时间（秒）
    chapter_title: str = ""         # 该段所属章节标题


@dataclass
class PodcastScript:
    """LLM 生成的完整播客脚本（JSON Schema 对应）。"""

    title: str
    description: str
    hosts: list[PodcastHost]
    segments: list[PodcastSegment]
    repo_names: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    outline: dict = field(default_factory=dict)            # 生成的大纲（sections列表）
    repo_urls: list[str] = field(default_factory=list)     # 仓库URL列表
    style: str = "casual"                                  # 生成时使用的风格
    target_minutes: int = 8                                # 目标时长
    critic_score: float = 0.0           # 脚本评审分数（1-10）
    critic_feedback: str = ""           # 评审反馈

    def total_chars(self) -> int:
        """脚本总字符数（用于成本估算）。"""
        return sum(len(s.text) for s in self.segments)

    def estimate_minutes(self, chars_per_minute: int = 350) -> float:
        """估算音频时长（分钟）。中文播客约 350 字/分钟。"""
        return round(self.total_chars() / chars_per_minute, 1)


@dataclass
class RepoHealth:
    """仓库健康度指标（借鉴 GitHub Intelligence / GitDiffs 的活跃度分析）。"""
    repo_name: str
    commit_count_30d: int = 0           # 近30天提交数
    contributor_count: int = 0          # 贡献者数量
    release_count: int = 0              # Release 总数
    open_issues: int = 0                # 未解决 Issue
    closed_issues: int = 0              # 已解决 Issue
    issue_close_rate: float = 0.0       # Issue 关闭率
    last_commit_date: str = ""          # 最近提交日期
    last_release_date: str = ""         # 最近发布日期
    top_contributors: list[dict] = field(default_factory=list)  # [{"name","commits"}]
    commit_activity_trend: str = ""     # 活跃趋势描述

    @property
    def health_score(self) -> float:
        """计算健康度评分（0-100）。"""
        score = 0.0
        # 提交活跃度（30分）
        if self.commit_count_30d >= 100:
            score += 30
        elif self.commit_count_30d >= 30:
            score += 20
        elif self.commit_count_30d >= 10:
            score += 10
        # 贡献者多样性（20分）
        if self.contributor_count >= 50:
            score += 20
        elif self.contributor_count >= 10:
            score += 15
        elif self.contributor_count >= 3:
            score += 8
        # Issue 处理效率（20分）
        total_issues = self.open_issues + self.closed_issues
        if total_issues > 0:
            score += min(20, self.issue_close_rate * 20)
        # 发布节奏（15分）
        if self.release_count >= 10:
            score += 15
        elif self.release_count >= 3:
            score += 10
        elif self.release_count >= 1:
            score += 5
        # 社区规模（15分，由外部的 stars 补充）
        return round(score, 1)

    @property
    def health_grade(self) -> str:
        """健康度等级。"""
        s = self.health_score
        if s >= 80:
            return "A+"
        elif s >= 65:
            return "A"
        elif s >= 50:
            return "B"
        elif s >= 35:
            return "C"
        elif s >= 20:
            return "D"
        return "F"

    def to_dict(self) -> dict:
        return {
            "repo_name": self.repo_name,
            "commit_count_30d": self.commit_count_30d,
            "contributor_count": self.contributor_count,
            "release_count": self.release_count,
            "open_issues": self.open_issues,
            "closed_issues": self.closed_issues,
            "issue_close_rate": round(self.issue_close_rate, 2),
            "last_commit_date": self.last_commit_date,
            "last_release_date": self.last_release_date,
            "top_contributors": self.top_contributors,
            "commit_activity_trend": self.commit_activity_trend,
            "health_score": self.health_score,
            "health_grade": self.health_grade,
        }


@dataclass
class DependencyInfo:
    """依赖解析结果（借鉴 readme-ai 的真实依赖解析）。"""
    file_name: str = ""                 # 依赖文件名
    manager: str = ""                   # 包管理器：pip / npm / cargo / go / maven
    dependencies: list[dict] = field(default_factory=list)  # [{"name","version"}]
    dev_dependencies: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "manager": self.manager,
            "dependencies": self.dependencies,
            "dev_dependencies": self.dev_dependencies,
        }


@dataclass
class ProjectAnalysis:
    """单个 GitHub 项目的深度分析结果（类似 zread.ai 的项目解读）。"""
    repo_name: str
    summary: str = ""                    # 一句话概述
    tech_stack: list[str] = field(default_factory=list)   # 技术栈
    architecture: str = ""               # 架构设计描述
    key_modules: list[dict] = field(default_factory=list)  # [{"name","description"}]
    quick_start: str = ""                # 快速上手指南
    highlights: list[str] = field(default_factory=list)   # 技术亮点
    use_cases: list[str] = field(default_factory=list)    # 应用场景
    comparison: str = ""                 # 同类项目对比
    code_insights: str = ""              # 代码洞察
    # 新增字段（借鉴 zread.ai / DeepRepo / readme-ai）
    mermaid_diagram: str = ""            # Mermaid 架构图代码
    dependencies: list[dict] = field(default_factory=list)  # 真实依赖列表
    commit_narrative: str = ""           # Commit 演进叙事
    review_score: float = 0.0            # 评审回路评分
    review_passed: bool = True           # 评审是否通过

    def to_dict(self) -> dict:
        """序列化为可存储的 dict。"""
        return {
            "repo_name": self.repo_name,
            "summary": self.summary,
            "tech_stack": self.tech_stack,
            "architecture": self.architecture,
            "key_modules": self.key_modules,
            "quick_start": self.quick_start,
            "highlights": self.highlights,
            "use_cases": self.use_cases,
            "comparison": self.comparison,
            "code_insights": self.code_insights,
            "mermaid_diagram": self.mermaid_diagram,
            "dependencies": self.dependencies,
            "commit_narrative": self.commit_narrative,
            "review_score": self.review_score,
            "review_passed": self.review_passed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectAnalysis":
        """从 dict 反序列化。"""
        return cls(
            repo_name=data.get("repo_name", ""),
            summary=data.get("summary", ""),
            tech_stack=data.get("tech_stack", []),
            architecture=data.get("architecture", ""),
            key_modules=data.get("key_modules", []),
            quick_start=data.get("quick_start", ""),
            highlights=data.get("highlights", []),
            use_cases=data.get("use_cases", []),
            comparison=data.get("comparison", ""),
            code_insights=data.get("code_insights", ""),
            mermaid_diagram=data.get("mermaid_diagram", ""),
            dependencies=data.get("dependencies", []),
            commit_narrative=data.get("commit_narrative", ""),
            review_score=data.get("review_score", 0.0),
            review_passed=data.get("review_passed", True),
        )


@dataclass
class ProjectComparison:
    """跨项目对比矩阵（借鉴 zread.ai 多仓库对比 + RepoTale 知识图谱）。"""
    repos: list[str] = field(default_factory=list)
    tech_overlap: list[dict] = field(default_factory=list)  # 重叠技术栈
    positioning_diff: str = ""          # 定位差异
    activity_ranking: list[dict] = field(default_factory=list)  # 活跃度排名
    verdict: str = ""                   # 综合评判

    def to_dict(self) -> dict:
        return {
            "repos": self.repos,
            "tech_overlap": self.tech_overlap,
            "positioning_diff": self.positioning_diff,
            "activity_ranking": self.activity_ranking,
            "verdict": self.verdict,
        }


@dataclass
class Chapter:
    """播客章节（用于 RSS chapters 和前端显示）。"""
    title: str
    start_time: float          # 起始时间（秒）
    end_time: float = 0.0      # 结束时间（秒）
    description: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "start_time": round(self.start_time, 1),
                "end_time": round(self.end_time, 1), "description": self.description}


@dataclass
class ShowNotes:
    """节目笔记（借鉴 Transcribr/LumiClip 的自动 show notes 生成）。"""
    title: str = ""                      # 节目标题（兼容 show_notes_generator）
    summary: str = ""                    # 一句话摘要
    key_takeaways: list[str] = field(default_factory=list)  # 3-5个关键要点
    project_links: list[dict] = field(default_factory=list)  # [{"name","url","stars","description"}]
    mentioned_tech: list[str] = field(default_factory=list)  # 提到的技术名词
    timestamps: list[dict] = field(default_factory=list)  # [{"time","title","description"}]
    social_quotes: list[str] = field(default_factory=list)  # 3条可分享金句

    def to_dict(self) -> dict:
        return {"title": self.title, "summary": self.summary, "key_takeaways": self.key_takeaways,
                "project_links": self.project_links, "mentioned_tech": self.mentioned_tech,
                "timestamps": self.timestamps, "social_quotes": self.social_quotes}

    def to_markdown(self) -> str:
        """生成 Markdown 格式的 show notes（用于 RSS content:encoded）。"""
        parts = [f"## 摘要\n{self.summary}"]
        if self.key_takeaways:
            parts.append("## 关键要点")
            for t in self.key_takeaways:
                parts.append(f"- {t}")
        if self.project_links:
            parts.append("## 项目链接")
            for p in self.project_links:
                parts.append(f"- [{p['name']}]({p['url']}) - ⭐{p.get('stars', 0)} {p.get('description', '')}")
        if self.timestamps:
            parts.append("## 时间戳")
            for ts in self.timestamps:
                mins = int(ts['time'] // 60)
                secs = int(ts['time'] % 60)
                parts.append(f"- {mins:02d}:{secs:02d} {ts['title']}")
        if self.mentioned_tech:
            parts.append("## 提到的技术")
            parts.append(", ".join(self.mentioned_tech))
        if self.social_quotes:
            parts.append("## 金句")
            for q in self.social_quotes:
                parts.append(f'> "{q}"')
        return "\n\n".join(parts)


@dataclass
class Episode:
    """一期完整播客节目。"""

    script: PodcastScript
    audio_path: str = ""            # 最终音频文件路径
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    episode_number: int = 1
    published_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    )
    chapters: list[Chapter] = field(default_factory=list)           # 章节列表（Podcasting 2.0）
    show_notes: ShowNotes = field(default_factory=ShowNotes)        # 自动节目笔记
    transcript_path: str = ""                                       # SRT/WebVTT 字幕文件路径
    status: str = "published"                                       # draft/published/failed
