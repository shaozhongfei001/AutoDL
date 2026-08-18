"""
V2 循环集成测试：主循环（ResearchLoop）中的上下文丰富、停滞信号、
相位门禁、终止记录与节流逻辑。
"""

import tempfile
import unittest
from pathlib import Path

from core.loop import ResearchLoop


def _make_loop(tmp, **overrides):
    # 便捷构造一个测试用的 ResearchLoop；可用 **overrides 覆盖任意配置段。
    project_dir = Path(tmp)
    (project_dir / "PROJECT_BRIEF.md").write_text("Train a classifier to acc > 0.8")
    config = {
        "project": {"workspace": "workspace"},
        "agent": {"max_cycles": 1, "cooldown_interval": 0},
        "obsidian": {"enabled": False},
        "ledger": {"enabled": True, "metric_key": "acc", "metric_direction": "higher_better"},
        "stagnation": {"enabled": True, "threshold_cycles": 2},
        "journal": {"enabled": True},
        "safety": {"enabled": True, "fail_threshold": 3},
        "gates": {"enabled": True, "threshold": 0.8, "direction": "higher_better"},
    }
    for k, v in overrides.items():
        config[k] = v
    return ResearchLoop(config=config, project_dir=str(project_dir))


class V2ContextEnrichmentTests(unittest.TestCase):
    """对 _enrich_context 上下文丰富逻辑的测试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.loop = _make_loop(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_enrich_context_populates_all_signals(self):
        # 丰富的上下文应包含最近实验、停滞信号、相位门禁以及死路/洞察记录。
        for i, acc in enumerate([0.70, 0.71, 0.71, 0.71]):
            self.loop.ledger.record(cycle=i, hypothesis=f"exp {i}", status="launched",
                                    metrics={"acc": acc}, ts=float(i))
        self.loop.journal.append_dead_end("SGD without warmup diverges")
        self.loop.journal.append_insight("cosine schedule helps late training")

        context = {}
        self.loop._enrich_context(context)

        self.assertIn("recent_experiments", context)
        self.assertIn("progress_signal", context)
        self.assertIn("STAGNATING", context["progress_signal"])
        self.assertIn("phase_gate", context)
        self.assertIn("NOT met", context["phase_gate"])  # 最优 acc 0.71 < 0.8
        self.assertIn("dead_ends", context)
        self.assertIn("SGD without warmup", context["dead_ends"])
        self.assertIn("insights", context)

    def test_violation_surfaces_on_repeated_no_progress(self):
        # 连续无进展达到一定次数后，上下文中应出现活动违规信息。
        self.loop._no_progress_streak = 3
        context = {}
        self.loop._enrich_context(context)
        self.assertIn("active_violations", context)

    def test_rendered_prompt_includes_sections(self):
        # 生成给领导者的提示词应包含「Recent Experiments」与「Phase Gate」等章节。
        self.loop.ledger.record(cycle=1, hypothesis="baseline", status="launched",
                                metrics={"acc": 0.9}, ts=1.0)
        context = {"brief": "b", "memory_log": "m", "cycle": 1}
        self.loop._enrich_context(context)
        text = self.loop.dispatcher._format_leader_input("think", context)
        self.assertIn("## Recent Experiments", text)
        self.assertIn("## Phase Gate", text)
        self.assertIn("MET", text)  # 最优 acc 0.9 >= 0.8

    def test_record_to_ledger_from_cycle_results(self):
        # 单轮结果应被正确写入账本，并把里程碑沉淀为持久化的洞察。
        think = {"action": "experiment", "hypothesis": "try dropout"}
        execute = {"experiment_launched": True, "pid": 42, "log_file": "logs/a.log",
                   "final_metrics": {"acc": 0.77}}
        reflect = {"milestone": "best acc so far 0.77"}
        self.loop._record_to_ledger(think, execute, reflect)

        entries = self.loop.ledger.all()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["metrics"]["acc"], 0.77)
        self.assertEqual(entries[0]["pid"], 42)
        # 里程碑被捕获为一条可持久化的洞察
        self.assertIn("best acc so far", self.loop.journal.insights_tail(2000))

    def test_record_to_ledger_marks_failed_with_terminal_state(self):
        # 失败的实验应记录为 "failed"（而不是 "launched"），并在结论前加上
        # sacct 的终态标记。
        think = {"action": "experiment", "hypothesis": "lr=10"}
        execute = {"experiment_launched": True, "experiment_status": "failed",
                   "terminal_state": "TIMEOUT", "pid": 9, "log_file": "logs/a.log",
                   "final_metrics": {}}
        reflect = {"decision": "retry with lower lr"}
        self.loop._record_to_ledger(think, execute, reflect)

        entry = self.loop.ledger.all()[0]
        self.assertEqual(entry["status"], "failed")
        self.assertTrue(entry["conclusion"].startswith("[TIMEOUT] "))


class V2ThrottleTests(unittest.TestCase):
    """对节流（max_cycles_per_hour）逻辑的测试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_throttle_disabled_is_noop_and_writes_nothing(self):
        # 节流关闭时什么都不做，也不写计时文件。
        loop = _make_loop(self.tempdir.name)  # max_cycles_per_hour 默认是 0
        loop._throttle_if_needed()
        self.assertFalse(loop._cycle_times_path.exists())

    def test_throttle_enabled_records_cycle_time_when_under_budget(self):
        # 预算未超时不休眠，但应记录一次周期时间戳。
        loop = _make_loop(self.tempdir.name, agent={"max_cycles": 1, "max_cycles_per_hour": 6})
        loop._throttle_if_needed()  # 未超预算 -> 不休眠，但记录一条时间戳
        self.assertTrue(loop._cycle_times_path.exists())
        self.assertEqual(len(loop._load_cycle_times()), 1)


if __name__ == "__main__":
    unittest.main()