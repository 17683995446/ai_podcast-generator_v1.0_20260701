"""交互式问答 API（借鉴 NotebookLM 交互模式）。"""
from __future__ import annotations
from flask import Blueprint, jsonify, request
from ..config import PROJECT_ROOT
from ..utils import json_error, json_ok

qa_bp = Blueprint("qa", __name__)

@qa_bp.route("/ask", methods=["POST"])
def ask():
    """回答用户关于项目的问题。
    
    请求体: {"question": "问题", "episode_number": 15, "repo_name": "owner/repo"}
    """
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    episode_number = data.get("episode_number")
    repo_name = data.get("repo_name", "")
    
    # 输入验证
    if len(question) > 1000:
        return json_error("问题过长（最大 1000 字符）", 400)
    if not isinstance(episode_number, (int, str)):
        return json_error("episode_number 必须是数字", 400)

    if not question:
        return json_error("请输入问题", 400)
    if not episode_number:
        return json_error("缺少节目编号", 400)
    
    from src.config_loader import load_config
    from src.qa_engine import QAEngine
    
    config = load_config(str(PROJECT_ROOT / "config.yaml"))
    engine = QAEngine(config)
    answer = engine.ask_by_episode(question, int(episode_number), repo_name)
    
    return jsonify({"answer": answer, "question": question})

@qa_bp.route("/ask-by-repo", methods=["POST"])
def ask_by_repo():
    """直接对任意 repo URL 提问（先分析再回答）。
    
    请求体: {"question": "问题", "repo_url": "https://github.com/owner/repo"}
    """
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    repo_url = data.get("repo_url", "").strip()
    
    if not question or not repo_url:
        return json_error("请提供问题和仓库 URL", 400)
    
    from src.config_loader import load_config
    from src.discovery import RepoDiscovery
    from src.crawler import ReadmeCrawler
    from src.deep_extractor import DeepExtractor
    from src.project_analyzer import ProjectAnalyzer
    from src.qa_engine import QAEngine
    
    config = load_config(str(PROJECT_ROOT / "config.yaml"))
    
    # Quick analysis
    discovery = RepoDiscovery(config)
    repos = discovery.discover_by_repo_urls([repo_url])
    if not repos:
        return json_error(f"未找到项目：{repo_url}", 404)
    
    crawler = ReadmeCrawler(config)
    crawler.fetch_all(repos)
    
    extractor = DeepExtractor(config)
    for repo in repos:
        deep = extractor.extract(repo)
        if deep:
            repo.readme_markdown += f"\n\n{deep}"
    
    analyzer = ProjectAnalyzer(config)
    analyses = analyzer.analyze(repos)
    
    if not analyses:
        return json_error("分析失败", 500)
    
    engine = QAEngine(config)
    answer = engine.ask(question, analyses[0].to_dict(), repos[0].readme_markdown[:3000])
    
    return jsonify({"answer": answer, "question": question, "repo_name": repos[0].name})
