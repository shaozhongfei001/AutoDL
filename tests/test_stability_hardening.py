"""
Tests for the stability-hardening pass A+B+D+E:

  A. loguru framework logging bridge + structured ``RESULT {...}`` metric
     extraction (the training subprocess prints it as its final stdout line).
  B. launch_experiment argument robustness: ``cd`` stripping, shell-operator
     rejection, and log_file auto-completion.
  D. session-level error escalation: ToolRegistry counts failures and injects
     an ``escalation`` hint (surfaced as an ``<escalation>`` block) once a tool
     keeps failing.
  E. empty-metric diagnosis: a completed run with no metric gets a structured
     ``metrics_diagnosis`` instead of a silent empty dict.
"""

import tempfile
import unittest
from pathlib import Path

from core.execution import LocalExecutionBackend
from core.monitor import ExperimentMonitor
from core.tools import ToolRegistry


class ResultContractMetricTests(unittest.TestCase):
    """A: structured RESULT metric extraction."""

    def test_result_line_beats_regex(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = [
            "epoch 10/10 | loss: 1.2 | accuracy: 0.85",
            'RESULT {"validation_accuracy": 0.982, "test_accuracy": 0.979}',
        ]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.982)
        self.assertEqual(m["test_accuracy"], 0.979)
        # The structured contract overrides the regex-scraped accuracy/loss.
        self.assertNotIn("accuracy", m)
        self.assertNotIn("loss", m)

    def test_last_result_wins(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = [
            'RESULT {"validation_accuracy": 0.90}',
            'RESULT {"validation_accuracy": 0.92}',
        ]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.92)

    def test_invalid_result_ignored_and_regex_fallback(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = ["RESULT {not json", "validation_accuracy=0.77"]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.77)

    def test_regex_fallback_still_works_without_result(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = ["epoch 5/20 | loss: 0.3 | acc: 0.94"]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["accuracy"], "0.94")
        self.assertIn("epoch", m)


class EmptyMetricDiagnosisTests(unittest.TestCase):
    """E: structured diagnosis when a completed run yields no metrics."""

    def test_missing_result_line(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        # No RESULT AND no regex-parseable metric -> result_missing.
        d = mon._diagnose_empty_metrics(["training finished", "saving model..."])
        self.assertEqual(d["reason"], "result_missing")
        self.assertIn("RESULT", d["hint"])

    def test_parseable_regex_log_gives_no_diagnosis(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        # Regex-parseable (loss/epoch) without RESULT is still real metrics.
        d = mon._diagnose_empty_metrics(["epoch 1/1 | loss 1.0"])
        self.assertEqual(d, {})

    def test_result_with_no_numeric(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        d = mon._diagnose_empty_metrics(['RESULT {"note": "done"}'])
        self.assertEqual(d["reason"], "result_no_numeric")

    def test_log_unavailable(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        d = mon._diagnose_empty_metrics([])
        self.assertEqual(d["reason"], "log_unavailable")


class LaunchExperimentRobustnessTests(unittest.TestCase):
    """B: sanitize + log_file auto-completion."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = LocalExecutionBackend(Path(self.tmp.name))
        self.registry = ToolRegistry(self.backend, config={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_strips_leading_cd(self):
        argv = self.registry._sanitize_experiment_command(
            "cd workspace && python train.py --lr 0.1"
        )
        self.assertEqual(argv, ["python", "train.py", "--lr", "0.1"])

    def test_strips_cd_semicolon(self):
        argv = self.registry._sanitize_experiment_command(
            "cd /tmp; python train.py"
        )
        self.assertEqual(argv, ["python", "train.py"])

    def test_rejects_shell_operator(self):
        with self.assertRaises(ValueError):
            self.registry._sanitize_experiment_command(
                "python train.py && echo done"
            )

    def test_rejects_bare_cd(self):
        with self.assertRaises(ValueError):
            self.registry._sanitize_experiment_command("cd workspace")

    def test_log_file_auto_completed(self):
        out = self.registry._exec_launch_experiment("python train.py --epochs 1")
        import json
        payload = json.loads(out)
        self.assertTrue(payload["log_file"].startswith("logs/exp_"))
        self.assertIn("experiment_budget", payload)


class ErrorEscalationTests(unittest.TestCase):
    """D: session-level error counting + escalation hints."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = LocalExecutionBackend(Path(self.tmp.name))
        self.registry = ToolRegistry(self.backend, config={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_shell_escalation_after_two_failures(self):
        for _ in range(2):
            out = self.registry.execute_tool("run_shell", {"command": "cd x && ls"})
            import json
            self.assertIn("error", json.loads(out))
        out = self.registry.execute_tool("run_shell", {"command": "cd x && ls"})
        import json
        payload = json.loads(out)
        self.assertIn("escalation", payload)
        self.assertIn("launch_experiment", payload["escalation"])

    def test_success_resets_escalation(self):
        for _ in range(2):
            self.registry.execute_tool("run_shell", {"command": "cd x && ls"})
        # A successful call resets the streak.
        self.registry.execute_tool("run_shell", {"command": "pwd"})
        out = self.registry.execute_tool("run_shell", {"command": "pwd"})
        import json
        self.assertNotIn("escalation", json.loads(out))

    def test_loguru_bridge_imports(self):
        from core.logging_setup import configure_logging, _HAS_LOGURU
        configure_logging(level="INFO")
        self.assertTrue(_HAS_LOGURU)


if __name__ == "__main__":
    unittest.main()
