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
    def test_terminal_status_not_recoverable(self):
        for status in ("completed", "success", "failed", "verdict_keep", "verdict_discard"):
            entry = {"status": status, "action": "experiment", "pid": 123, "log_file": "x.log"}
            self.assertFalse(classify_recoverable(entry)["recoverable"])

    def test_no_experiment_not_recoverable(self):
        for entry in (
            {"status": "wait", "action": "wait"},
            {"status": "no_experiment", "action": "no_experiment"},
            {},
        ):
            self.assertFalse(classify_recoverable(entry)["recoverable"])

    def test_inflight_with_pid_recoverable(self):
        entry = {"cycle": 3, "status": "running", "action": "experiment",
                 "pid": 99, "log_file": "run3.log"}
        verdict = classify_recoverable(entry)
        self.assertTrue(verdict["recoverable"])
        self.assertIn("unfinished", verdict["reason"])

    def test_launched_with_log_recoverable(self):
        entry = {"cycle": 4, "status": "launched", "action": "experiment", "log_file": "run4.log"}
        self.assertTrue(classify_recoverable(entry)["recoverable"])

    def test_crash_verdict_recoverable(self):
        entry = {"cycle": 5, "status": "verdict_crash", "action": "verdict:x",
                 "pid": 5, "log_file": "run5.log"}
        verdict = classify_recoverable(entry)
        self.assertTrue(verdict["recoverable"])
        self.assertIn("crash", verdict["reason"])

    def test_recoverable_candidates_filters(self):
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
    def test_filters_verdict_entries_and_last(self):
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
        out = recover_verdict_history([{"cycle": 1, "action": "wait"}])
        self.assertEqual(out["verdicts"], [])
        self.assertIsNone(out["last_verdict"])
        self.assertEqual(out["promoted_candidates"], [])

    def test_keep_only_promoted(self):
        entries = [
            {"action": "verdict:x", "verdict": "KEEP", "candidate_sha": "sx"},
            {"action": "verdict:y", "verdict": "DISCARD", "candidate_sha": "sy"},
            {"action": "verdict:z", "verdict": "INCOMPARABLE", "candidate_sha": "sz"},
        ]
        self.assertEqual(recover_verdict_history(entries)["promoted_candidates"], ["sx"])


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_no_checkpoint_means_start_from_one(self):
        cp = Checkpoint(self.workspace)
        point = cp.resume_point()
        self.assertFalse(point["has_checkpoint"])
        self.assertEqual(point["next_cycle"], 1)

    def test_save_and_resume(self):
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
        # no leftover temp file
        self.assertFalse(cp.path.with_suffix(".json.tmp").exists())

    def test_save_accumulates_fields(self):
        cp = Checkpoint(self.workspace)
        cp.save(last_cycle=1)
        cp.save(last_state={"a": 1})
        data = cp.load()
        self.assertEqual(data["last_cycle"], 1)
        self.assertEqual(data["last_state"]["a"], 1)

    def test_corrupt_file_treated_as_no_checkpoint(self):
        cp = Checkpoint(self.workspace)
        cp.path.write_text("{ not json")
        point = cp.resume_point()
        self.assertFalse(point["has_checkpoint"])
        self.assertEqual(point["next_cycle"], 1)


class BackoffTests(unittest.TestCase):
    def test_exponential_growth(self):
        d0 = compute_backoff(0, base_seconds=30, max_seconds=3600, jitter=0)
        d1 = compute_backoff(1, base_seconds=30, max_seconds=3600, jitter=0)
        d2 = compute_backoff(2, base_seconds=30, max_seconds=3600, jitter=0)
        self.assertEqual(d0, 30.0)
        self.assertEqual(d1, 60.0)
        self.assertEqual(d2, 120.0)

    def test_capped_at_max(self):
        d = compute_backoff(100, base_seconds=30, max_seconds=600, jitter=0)
        self.assertEqual(d, 600.0)

    def test_jitter_within_bounds(self):
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
