import json
import random
import tempfile
import unittest
from pathlib import Path

from core.resilience import (
    Checkpoint,
    classify_recoverable,
    compute_backoff,
    next_retry_delay,
    recover_verdict_history,
    recoverable_candidates,
    summarize_recovery,
)


class ClassifyRecoverableTests(unittest.TestCase):
    """对 classify_recoverable / recoverable_candidates / summarize_recovery 恢复分类逻辑的测试。"""

    def test_terminal_status_not_recoverable(self):
        # 已达终态（成功/失败/判决完成）的记录不可恢复。
        for status in ("completed", "success", "failed", "verdict_keep", "verdict_discard"):
            entry = {"status": status, "action": "experiment", "pid": 123, "log_file": "x.log"}
            self.assertFalse(classify_recoverable(entry)["recoverable"])

    def test_no_experiment_not_recoverable(self):
        # 从未真正启动实验的记录（wait / 空记录）不可恢复。
        for entry in (
            {"status": "wait", "action": "wait"},
            {"status": "no_experiment", "action": "no_experiment"},
            {},
        ):
            self.assertFalse(classify_recoverable(entry)["recoverable"])

    def test_inflight_with_pid_recoverable(self):
        # 运行中（running）且带有 pid 的记录可恢复，原因应包含 unfinished。
        entry = {"cycle": 3, "status": "running", "action": "experiment",
                 "pid": 99, "log_file": "run3.log"}
        verdict = classify_recoverable(entry)
        self.assertTrue(verdict["recoverable"])
        self.assertIn("unfinished", verdict["reason"])

    def test_launched_with_log_recoverable(self):
        # 已启动（launched）且带日志的记录可恢复。
        entry = {"cycle": 4, "status": "launched", "action": "experiment", "log_file": "run4.log"}
        self.assertTrue(classify_recoverable(entry)["recoverable"])

    def test_crash_verdict_recoverable(self):
        # 崩溃导致的判决记录可恢复，原因应提到 crash。
        entry = {"cycle": 5, "status": "verdict_crash", "action": "verdict:x",
                 "pid": 5, "log_file": "run5.log"}
        verdict = classify_recoverable(entry)
        self.assertTrue(verdict["recoverable"])
        self.assertIn("crash", verdict["reason"])

    def test_recoverable_candidates_filters(self):
        # 从混合状态中只筛选出可恢复项（running），并附加恢复元信息。
        entries = [
            {"cycle": 1, "status": "completed", "action": "experiment"},
            {"cycle": 2, "status": "running", "action": "experiment", "pid": 1, "log_file": "a.log"},
            {"cycle": 3, "status": "wait", "action": "wait"},
        ]
        rec = recoverable_candidates(entries)
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["cycle"], 2)
        self.assertTrue(rec[0]["_recovery"]["recoverable"])

    def test_summarize_recovery(self):
        # 汇总应能统计出可续跑周期、终态数与不适用项数。
        entries = [
            {"cycle": 1, "status": "completed", "action": "experiment"},
            {"cycle": 2, "status": "running", "action": "experiment", "pid": 1, "log_file": "a.log"},
            {"cycle": 3, "status": "wait", "action": "wait"},
        ]
        summary = summarize_recovery(entries)
        self.assertEqual(summary["total_entries"], 3)
        self.assertEqual(summary["resumable_cycles"], [2])
        self.assertEqual(summary["terminal_count"], 1)
        self.assertEqual(summary["not_applicable_count"], 1)


class RecoverVerdictHistoryTests(unittest.TestCase):
    """对 recover_verdict_history 判决历史恢复逻辑的测试。"""

    def test_filters_verdict_entries_and_last(self):
        # 仅保留判决类记录，并能找到最近一条以及所有已晋升的候选。
        entries = [
            {"cycle": 1, "action": "verdict:a1", "verdict": "DISCARD",
             "candidate_sha": "sha-1"},
            {"cycle": 2, "action": "verdict:b2", "verdict": "KEEP",
             "candidate_sha": "sha-2", "promotion_status": "KEEP_PROMOTED"},
            {"cycle": 3, "action": "experiment", "status": "running"},
        ]
        out = recover_verdict_history(entries)
        self.assertEqual(len(out["verdicts"]), 2)
        self.assertEqual(out["last_verdict"]["candidate_sha"], "sha-2")
        self.assertEqual(out["promoted_candidates"], ["sha-2"])

    def test_no_verdicts(self):
        # 无任何判决记录时返回空列表与 None。
        out = recover_verdict_history([{"cycle": 1, "action": "wait"}])
        self.assertEqual(out["verdicts"], [])
        self.assertIsNone(out["last_verdict"])
        self.assertEqual(out["promoted_candidates"], [])

    def test_keep_only_promoted(self):
        # 只有 KEEP（且晋升）的候选才被计入 promoted_candidates。
        entries = [
            {"action": "verdict:x", "verdict": "KEEP", "candidate_sha": "sx"},
            {"action": "verdict:y", "verdict": "DISCARD", "candidate_sha": "sy"},
            {"action": "verdict:z", "verdict": "INCOMPARABLE", "candidate_sha": "sz"},
        ]
        self.assertEqual(recover_verdict_history(entries)["promoted_candidates"], ["sx"])


class CheckpointTests(unittest.TestCase):
    """对检查点（Checkpoint）保存、断点续跑与损坏容错逻辑的测试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_no_checkpoint_means_start_from_one(self):
        # 无检查点时，续跑周期从 1 开始。
        cp = Checkpoint(self.workspace)
        point = cp.resume_point()
        self.assertFalse(point["has_checkpoint"])
        self.assertEqual(point["next_cycle"], 1)

    def test_save_and_resume(self):
        # 保存后能正确算出 next_cycle = last_cycle + 1，并读回上次状态。
        cp = Checkpoint(self.workspace)
        cp.save(last_cycle=7, last_state={"status": "running", "pid": 42})
        point = cp.resume_point()
        self.assertTrue(point["has_checkpoint"])
        self.assertEqual(point["last_cycle"], 7)
        self.assertEqual(point["next_cycle"], 8)
        self.assertEqual(point["last_state"]["pid"], 42)

    def test_save_is_atomic_and_readable(self):
        cp = Checkpoint(self.workspace)
        cp.save(last_cycle=3, last_state={"metric": 0.9})
        raw = json.loads(cp.path.read_text())
        self.assertEqual(raw["last_cycle"], 3)
        # 不应残留临时文件
        self.assertFalse(cp.path.with_suffix(".json.tmp").exists())

    def test_save_accumulates_fields(self):
        # 多次 save 应叠加字段，而不是互相覆盖丢失。
        cp = Checkpoint(self.workspace)
        cp.save(last_cycle=1)
        cp.save(last_state={"a": 1})
        data = cp.load()
        self.assertEqual(data["last_cycle"], 1)
        self.assertEqual(data["last_state"]["a"], 1)

    def test_corrupt_file_treated_as_no_checkpoint(self):
        # 损坏的检查点文件应被当作「无检查点」处理（安全回退而非崩溃）。
        cp = Checkpoint(self.workspace)
        cp.path.write_text("{ not json")
        point = cp.resume_point()
        self.assertFalse(point["has_checkpoint"])
        self.assertEqual(point["next_cycle"], 1)


class BackoffTests(unittest.TestCase):
    """对指数退避（compute_backoff / next_retry_delay）逻辑的测试。"""

    def test_exponential_growth(self):
        # 尝试次数越多次，等待时间呈指数增长。
        d0 = compute_backoff(0, base_seconds=30, max_seconds=3600, jitter=0)
        d1 = compute_backoff(1, base_seconds=30, max_seconds=3600, jitter=0)
        d2 = compute_backoff(2, base_seconds=30, max_seconds=3600, jitter=0)
        self.assertEqual(d0, 30.0)
        self.assertEqual(d1, 60.0)
        self.assertEqual(d2, 120.0)

    def test_capped_at_max(self):
        # 等待时间有上限（max_seconds），避免无限增长。
        d = compute_backoff(100, base_seconds=30, max_seconds=600, jitter=0)
        self.assertEqual(d, 600.0)

    def test_jitter_within_bounds(self):
        # 抖动（jitter）必须被限制在 ±10% 的允许区间内。
        rng = random.Random(1234)
        for attempt in range(10):
            d = compute_backoff(attempt, base_seconds=30, max_seconds=3600,
                                jitter=0.1, rng=rng)
            raw = 30.0 * (2 ** attempt)
            capped = min(3600.0, raw)
            self.assertGreaterEqual(d, capped * 0.9 - 1e-9)
            self.assertLessEqual(d, capped * 1.1 + 1e-9)

    def test_jitter_zero_is_deterministic(self):
        a = compute_backoff(3, base_seconds=30, max_seconds=3600, jitter=0)
        b = compute_backoff(3, base_seconds=30, max_seconds=3600, jitter=0)
        self.assertEqual(a, b)

    def test_next_retry_delay_steps(self):
        d0 = next_retry_delay(0, max_seconds=3600)
        d1 = next_retry_delay(d0, max_seconds=3600)
        d2 = next_retry_delay(d1, max_seconds=3600)
        self.assertEqual(d0, 2.0)
        self.assertEqual(d1, 4.0)
        self.assertEqual(d2, 8.0)

    def test_next_retry_delay_capped(self):
        d = next_retry_delay(10000, max_seconds=600)
        self.assertEqual(d, 600.0)


if __name__ == "__main__":
    unittest.main()
