"""阶段 3 测试：生成过程透明化 — PipelineReporter + 进度解析 + 集成。

测试覆盖：
  1. StageEvent / CheckpointData 数据类序列化
  2. PipelineReporter 生命周期（start/finish/fail/skip/checkpoint/report）
  3. _parse_progress_from_log 日志解析
  4. TaskManager.get_status() 返回 pipeline_progress
  5. 端到端集成：mock 流水线 + 进度事件 + 报告生成
"""
import json
import threading
import time

import pytest

from src.pipeline_reporter import (
    PipelineReporter,
    StageEvent,
    CheckpointData,
    _format_duration,
)


# ════════════════════════════════════════
# 1. StageEvent 数据类
# ════════════════════════════════════════
class TestStageEvent:
    """StageEvent 序列化与默认值。"""

    def test_to_dict_contains_all_fields(self):
        """to_dict 应包含所有字段。"""
        ev = StageEvent(
            stage="discovery", stage_label="项目发现",
            status="done", summary="发现 3 个项目",
        )
        d = ev.to_dict()
        assert d["stage"] == "discovery"
        assert d["stage_label"] == "项目发现"
        assert d["status"] == "done"
        assert d["summary"] == "发现 3 个项目"
        assert d["error"] == ""
        assert d["details"] == {}
        assert d["duration_ms"] == 0

    def test_default_status_is_pending(self):
        """新建 StageEvent 默认状态应为 pending。"""
        ev = StageEvent(stage="crawl")
        assert ev.status == "pending"


class TestCheckpointData:
    """CheckpointData 序列化与默认值。"""

    def test_to_dict_contains_all_fields(self):
        """to_dict 应包含所有字段。"""
        cp = CheckpointData(
            episode_number=5,
            repos_found=["a/b", "c/d"],
            evidence_count=14,
            script_segments=20,
            audio_duration_seconds=300.0,
        )
        d = cp.to_dict()
        assert d["episode_number"] == 5
        assert d["repos_found"] == ["a/b", "c/d"]
        assert d["evidence_count"] == 14
        assert d["script_segments"] == 20
        assert d["audio_duration_seconds"] == 300.0

    def test_defaults_are_empty(self):
        """新建 CheckpointData 所有列表/字典默认为空。"""
        cp = CheckpointData()
        assert cp.repos_found == []
        assert cp.validation_scores == {}
        assert cp.evidence_count == 0


# ════════════════════════════════════════
# 2. PipelineReporter 生命周期
# ════════════════════════════════════════
class TestReporterLifecycle:
    """PipelineReporter 阶段追踪。"""

    def test_start_pipeline_sets_timestamp(self, tmp_path):
        """start_pipeline 应记录开始时间。"""
        r = PipelineReporter(output_dir=tmp_path)
        assert r._started_at == 0.0
        r.start_pipeline(episode_number=3)
        assert r._started_at > 0
        assert r._checkpoint.episode_number == 3

    def test_start_stage_sets_running(self, tmp_path):
        """start_stage 应将阶段标记为 running。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_stage("discovery", "正在发现项目")
        ev = r._events["discovery"]
        assert ev.status == "running"
        assert ev.started_at > 0
        assert ev.summary == "正在发现项目"

    def test_finish_stage_sets_done_and_duration(self, tmp_path):
        """finish_stage 应标记完成并计算耗时。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_stage("crawl")
        time.sleep(0.01)  # 确保有耗时
        r.finish_stage("crawl", "已抓取 3 个 README", {"count": 3})
        ev = r._events["crawl"]
        assert ev.status == "done"
        assert ev.duration_ms > 0
        assert ev.summary == "已抓取 3 个 README"
        assert ev.details == {"count": 3}

    def test_fail_stage_sets_error(self, tmp_path):
        """fail_stage 应标记失败并记录错误。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_stage("tts")
        r.fail_stage("tts", "API timeout")
        ev = r._events["tts"]
        assert ev.status == "failed"
        assert ev.error == "API timeout"

    def test_skip_stage_sets_skipped(self, tmp_path):
        """skip_stage 应标记为跳过。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.skip_stage("compare", "单项目无需对比")
        ev = r._events["compare"]
        assert ev.status == "skipped"
        assert ev.summary == "单项目无需对比"

    def test_unknown_stage_ignored(self, tmp_path):
        """未知阶段名应被安全忽略。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_stage("unknown_stage")  # 不应抛异常
        r.finish_stage("unknown_stage")
        assert "unknown_stage" not in r._events


class TestReporterCheckpoint:
    """PipelineReporter 检查点持久化。"""

    def test_update_checkpoint_sets_fields(self, tmp_path):
        """update_checkpoint 应更新对应字段。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.update_checkpoint(
            repos_found=["a/b"],
            evidence_count=5,
            script_segments=10,
        )
        assert r._checkpoint.repos_found == ["a/b"]
        assert r._checkpoint.evidence_count == 5
        assert r._checkpoint.script_segments == 10

    def test_update_checkpoint_ignores_unknown_fields(self, tmp_path):
        """update_checkpoint 应忽略未知字段。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.update_checkpoint(unknown_field="value")
        assert not hasattr(r._checkpoint, "unknown_field")

    def test_save_checkpoint_writes_json(self, tmp_path):
        """save_checkpoint 应写入 JSON 文件。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline(episode_number=1)
        r.start_stage("discovery")
        r.finish_stage("discovery", "发现 3 个项目")
        r.update_checkpoint(repos_found=["a/b", "c/d"])

        path = r.save_checkpoint("test_checkpoint.json")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "checkpoint" in data
        assert "events" in data
        assert data["checkpoint"]["repos_found"] == ["a/b", "c/d"]
        assert data["events"]["discovery"]["status"] == "done"


class TestReporterReport:
    """PipelineReporter 报告生成。"""

    def test_finish_pipeline_returns_report(self, tmp_path):
        """finish_pipeline 应返回包含统计信息的报告。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline(episode_number=2)
        r.start_stage("discovery")
        r.finish_stage("discovery", "发现 2 个项目")
        r.start_stage("crawl")
        r.finish_stage("crawl")
        r.start_stage("tts")
        r.fail_stage("tts", "API error")
        r.skip_stage("compare")
        time.sleep(0.01)  # 确保有总耗时

        report = r.finish_pipeline()
        assert report["episode_number"] == 2
        assert report["stages_completed"] == 2
        assert report["stages_failed"] == 1
        assert report["stages_skipped"] == 1
        assert report["total_duration_ms"] > 0
        assert "stages" in report
        assert "checkpoint" in report

    def test_get_progress_snapshot(self, tmp_path):
        """get_progress 应返回进度快照。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline()
        r.start_stage("discovery")
        r.finish_stage("discovery", "完成")
        r.start_stage("crawl", "进行中")

        progress = r.get_progress()
        assert progress["total_stages"] == 9
        assert progress["completed_stages"] == 1
        assert progress["progress_percent"] == round(1 / 9 * 100)
        assert progress["current_stage"] == "crawl"
        assert "discovery" in progress["stages"]
        assert progress["stages"]["discovery"]["status"] == "done"

    def test_get_progress_no_current_when_all_done(self, tmp_path):
        """所有阶段完成时 current_stage 应为 None。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline()
        for stage_id, _ in PipelineReporter.STAGES:
            r.start_stage(stage_id)
            r.finish_stage(stage_id)

        progress = r.get_progress()
        assert progress["current_stage"] is None
        assert progress["completed_stages"] == 9
        assert progress["progress_percent"] == 100

    def test_generate_report_includes_all_metrics(self, tmp_path):
        """generate_report 应包含所有制作指标。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline(episode_number=7)
        r.update_checkpoint(
            repos_found=["a/b", "c/d"],
            evidence_count=10,
            validation_scores={"a/b": 0.85, "c/d": 0.72},
            script_segments=15,
            script_review_score=8.0,
            audio_segments=15,
            audio_duration_seconds=600.0,
        )
        r.finish_pipeline()

        report = r.generate_report()
        assert report["episode_number"] == 7
        assert report["repos_processed"] == 2
        assert report["evidence_count"] == 10
        assert report["avg_validation_score"] == round((0.85 + 0.72) / 2, 2)
        assert report["script_segments"] == 15
        assert report["script_review_score"] == 8.0
        assert report["audio_segments"] == 15
        assert report["audio_duration_seconds"] == 600.0
        assert "audio_duration_human" in report
        assert "total_duration_human" in report


class TestReporterThreadSafety:
    """PipelineReporter 线程安全。"""

    def test_concurrent_stage_updates(self, tmp_path):
        """多线程同时更新不同阶段不应出错。"""
        r = PipelineReporter(output_dir=tmp_path)
        r.start_pipeline()
        errors = []

        def worker(stage_id):
            try:
                r.start_stage(stage_id)
                time.sleep(0.001)
                r.finish_stage(stage_id, f"完成 {stage_id}")
            except Exception as e:
                errors.append(str(e))

        threads = []
        for stage_id, _ in PipelineReporter.STAGES:
            t = threading.Thread(target=worker, args=(stage_id,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        progress = r.get_progress()
        assert progress["completed_stages"] == 9


# ════════════════════════════════════════
# 3. _format_duration 辅助函数
# ════════════════════════════════════════
class TestFormatDuration:
    """_format_duration 时长格式化。"""

    def test_zero_ms(self):
        assert _format_duration(0) == "0s"

    def test_seconds(self):
        assert _format_duration(45000) == "45s"

    def test_minutes(self):
        assert _format_duration(125000) == "2m5s"

    def test_hours(self):
        assert _format_duration(3725000) == "1h2m"


# ════════════════════════════════════════
# 4. _parse_progress_from_log 日志解析
# ════════════════════════════════════════
class TestParseProgressFromLog:
    """task_manager._parse_progress_from_log 日志解析。"""

    def test_parses_single_progress_event(self):
        """应正确解析单个进度事件。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = [
            "[1/6] 发现 GitHub 前沿项目",
            '::PROGRESS::{"stage":"discovery","status":"done","label":"项目发现","summary":"发现 3 个项目"}',
        ]
        result = _parse_progress_from_log(log)
        assert result is not None
        assert "discovery" in result["stages"]
        assert result["stages"]["discovery"]["status"] == "done"
        assert result["stages"]["discovery"]["summary"] == "发现 3 个项目"
        assert result["completed_stages"] == 1

    def test_parses_multiple_events(self):
        """应正确解析多个阶段事件。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = [
            '::PROGRESS::{"stage":"discovery","status":"done","label":"项目发现","summary":"发现 3 个项目"}',
            '::PROGRESS::{"stage":"crawl","status":"done","label":"README抓取","summary":"已抓取 3 个 README"}',
            '::PROGRESS::{"stage":"deep_extract","status":"running","label":"深度提取","summary":"深度内容提取..."}',
        ]
        result = _parse_progress_from_log(log)
        assert result is not None
        assert result["completed_stages"] == 2
        assert result["current_stage"] == "deep_extract"
        assert result["progress_percent"] == round(2 / 9 * 100)

    def test_returns_none_for_empty_log(self):
        """空日志应返回 None。"""
        from dashboard.task_manager import _parse_progress_from_log

        assert _parse_progress_from_log([]) is None

    def test_returns_none_for_no_progress_lines(self):
        """无进度事件的日志应返回 None。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = ["普通日志行", "另一行日志"]
        assert _parse_progress_from_log(log) is None

    def test_handles_malformed_progress_line(self):
        """格式错误的进度行应被跳过。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = [
            "::PROGRESS::not valid json",
            '::PROGRESS::{"stage":"discovery","status":"done","label":"发现","summary":"OK"}',
        ]
        result = _parse_progress_from_log(log)
        assert result is not None
        assert "discovery" in result["stages"]

    def test_latest_status_overrides_earlier(self):
        """后出现的进度事件应覆盖同阶段的早期事件。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = [
            '::PROGRESS::{"stage":"discovery","status":"running","label":"发现","summary":"进行中"}',
            '::PROGRESS::{"stage":"discovery","status":"done","label":"发现","summary":"完成"}',
        ]
        result = _parse_progress_from_log(log)
        assert result["stages"]["discovery"]["status"] == "done"
        assert result["stages"]["discovery"]["summary"] == "完成"

    def test_all_done_no_current_stage(self):
        """所有阶段完成时 current_stage 应为 None。"""
        from dashboard.task_manager import _parse_progress_from_log

        log = [
            '::PROGRESS::{"stage":"discovery","status":"done","label":"发现","summary":"完成"}',
            '::PROGRESS::{"stage":"publish","status":"done","label":"发布","summary":"已发布"}',
        ]
        result = _parse_progress_from_log(log)
        assert result["current_stage"] is None
        assert result["completed_stages"] == 2


# ════════════════════════════════════════
# 5. TaskManager 集成
# ════════════════════════════════════════
class TestTaskManagerProgress:
    """TaskManager.get_status() 应包含 pipeline_progress。"""

    def test_status_includes_pipeline_progress_key(self):
        """get_status 返回应包含 pipeline_progress 键。"""
        from dashboard.task_manager import task_manager
        from dashboard.huey_app import reset_progress

        reset_progress()
        status = task_manager.get_status()
        assert "pipeline_progress" in status

    def test_status_pipeline_progress_null_when_no_events(self):
        """无进度事件时 pipeline_progress 应为 None。"""
        from dashboard.task_manager import task_manager
        from dashboard.huey_app import _progress, _progress_lock, reset_progress

        reset_progress()
        with _progress_lock:
            _progress["log"] = ["普通日志", "无进度事件"]
        status = task_manager.get_status()
        assert status["pipeline_progress"] is None

    def test_status_pipeline_progress_parsed_from_log(self):
        """日志中有进度事件时应解析出 pipeline_progress。"""
        from dashboard.task_manager import task_manager
        from dashboard.huey_app import _progress, _progress_lock, reset_progress

        reset_progress()
        with _progress_lock:
            _progress["log"] = [
                '::PROGRESS::{"stage":"discovery","status":"done","label":"发现","summary":"发现 2 个项目"}',
                '::PROGRESS::{"stage":"crawl","status":"running","label":"抓取","summary":"抓取中..."}',
            ]
        status = task_manager.get_status()
        pp = status["pipeline_progress"]
        assert pp is not None
        assert pp["current_stage"] == "crawl"
        assert pp["completed_stages"] == 1
        assert "discovery" in pp["stages"]


# ════════════════════════════════════════
# 6. 端到端集成：mock 流水线 + 报告器
# ════════════════════════════════════════
class TestEndToEndReporterIntegration:
    """模拟完整流水线，验证报告器全程追踪。"""

    def test_full_pipeline_reporter_tracks_all_stages(self, tmp_path):
        """模拟 9 阶段流水线，验证报告器追踪所有阶段。"""
        reporter = PipelineReporter(output_dir=tmp_path)
        reporter.start_pipeline(episode_number=1)

        # 模拟每个阶段的执行
        stage_summaries = {
            "discovery": "发现 3 个项目",
            "crawl": "已抓取 3 个 README",
            "deep_extract": "已提取 3 个项目，21 条证据",
            "analyze": "已分析 3 个项目",
            "compare": "对比完成：5 项技术重叠",
            "script": "脚本 18 段，4500 字",
            "tts": "已合成 18 段语音",
            "mix": "音频 360s，5 章节",
            "publish": "EP001 已发布",
        }

        for stage_id, stage_label in PipelineReporter.STAGES:
            reporter.start_stage(stage_id)
            time.sleep(0.001)
            reporter.finish_stage(stage_id, stage_summaries.get(stage_id, ""))

        reporter.update_checkpoint(
            episode_number=1,
            repos_found=["a/b", "c/d", "e/f"],
            evidence_count=21,
            script_segments=18,
            audio_duration_seconds=360.0,
        )

        # 验证进度快照
        progress = reporter.get_progress()
        assert progress["completed_stages"] == 9
        assert progress["progress_percent"] == 100
        assert progress["current_stage"] is None

        # 验证最终报告
        report = reporter.generate_report()
        assert report["episode_number"] == 1
        assert report["repos_processed"] == 3
        assert report["evidence_count"] == 21
        assert report["script_segments"] == 18
        assert report["audio_duration_seconds"] == 360.0

        # 验证检查点持久化
        checkpoint_path = reporter.save_checkpoint("final_checkpoint.json")
        assert checkpoint_path.exists()
        saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert saved["checkpoint"]["episode_number"] == 1
        assert len(saved["events"]) == 9

    def test_pipeline_with_failure_still_generates_report(self, tmp_path):
        """流水线中途失败也能生成报告。"""
        reporter = PipelineReporter(output_dir=tmp_path)
        reporter.start_pipeline(episode_number=2)

        # 前 3 阶段成功
        for stage_id in ["discovery", "crawl", "deep_extract"]:
            reporter.start_stage(stage_id)
            reporter.finish_stage(stage_id, "完成")

        # 第 4 阶段失败
        reporter.start_stage("analyze")
        reporter.fail_stage("analyze", "LLM API 超时")

        # 后续阶段跳过
        for stage_id in ["compare", "script", "tts", "mix", "publish"]:
            reporter.skip_stage(stage_id, "前置阶段失败")

        report = reporter.finish_pipeline()
        assert report["stages_completed"] == 3
        assert report["stages_failed"] == 1
        assert report["stages_skipped"] == 5

        progress = reporter.get_progress()
        assert progress["completed_stages"] == 3
        assert progress["current_stage"] is None  # 没有运行中的阶段

    def test_progress_events_simulate_stdout_output(self, tmp_path):
        """模拟 main.py 的 _emit_progress 输出，验证日志解析闭环。"""
        import sys
        from io import StringIO

        reporter = PipelineReporter(output_dir=tmp_path)
        reporter.start_pipeline(episode_number=3)

        # 捕获 stdout（模拟 Huey 捕获子进程输出）
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            # 模拟 _emit_progress 的输出
            for stage_id, label in PipelineReporter.STAGES[:3]:
                reporter.start_stage(stage_id)
                # 模拟 _emit_progress 输出
                data = {"stage": stage_id, "status": "running", "label": label, "summary": f"{label}进行中"}
                print(f"::PROGRESS::{json.dumps(data, ensure_ascii=False)}")

                reporter.finish_stage(stage_id, f"{label}完成")
                data = {"stage": stage_id, "status": "done", "label": label, "summary": f"{label}完成"}
                print(f"::PROGRESS::{json.dumps(data, ensure_ascii=False)}")
        finally:
            sys.stdout = old_stdout

        # 将捕获的输出解析为日志行（模拟 Huey 的 _progress["log"]）
        log_lines = captured.getvalue().strip().split("\n")

        # 验证日志解析
        from dashboard.task_manager import _parse_progress_from_log
        result = _parse_progress_from_log(log_lines)
        assert result is not None
        assert result["completed_stages"] == 3
        assert "discovery" in result["stages"]
        assert result["stages"]["discovery"]["status"] == "done"
