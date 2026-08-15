"""
Tests for the early-stop mechanism (loop-level + train/in-run level).

Two layers:
  1. In-run (monitor) early stop: parse per-epoch validation metrics from the
     live log and terminate a training subprocess once it plateaus, saving GPU.
  2. Loop-level early stop: active saturation / leader-stagnation detection so
     the unattended Agent loop converges on its own instead of cycling forever
     until a human kills the process.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path

from core.execution import LocalExecutionBackend
from core.monitor import ExperimentMonitor
from core.tools import ToolRegistry


class InRunEarlyStopMetricTests(unittest.TestCase):
    """_extract_epoch_metrics + _check_in_run_early_stop unit tests."""

    def _mon(self, **es):
        cfg = {"early_stop": {"enabled": True, "patience": 2,
                              "improvement_tol": 1e-4, "min_epochs": 3,
                              "metric": "validation_accuracy", **es}}
        return ExperimentMonitor(backend=LocalExecutionBackend("."), budget=cfg)

    def test_extract_from_legacy_lines(self):
        mon = self._mon()
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.90",
                 "validation_accuracy=0.90"]
        self.assertEqual(mon._extract_epoch_metrics(lines, "validation_accuracy"),
                         [0.80, 0.90, 0.90])

    def test_extract_from_result_snapshots(self):
        mon = self._mon()
        lines = [
            'RESULT {"validation_accuracy": 0.80}',
            'RESULT {"validation_accuracy": 0.90}',
        ]
        self.assertEqual(mon._extract_epoch_metrics(lines, "validation_accuracy"),
                         [0.80, 0.90])

    def test_no_early_stop_before_min_epochs(self):
        mon = self._mon(min_epochs=5)
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.80"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_early_stop_on_plateau(self):
        mon = self._mon(patience=2, min_epochs=3)
        # 0.80 -> 0.90 (best), then plateau at 0.90 for 2 epochs.
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.90",
                 "validation_accuracy=0.90"]
        self.assertTrue(mon._check_in_run_early_stop(999, lines))

    def test_no_early_stop_while_improving(self):
        mon = self._mon(patience=2, min_epochs=3)
        lines = ["validation_accuracy=0.70", "validation_accuracy=0.80",
                 "validation_accuracy=0.90"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_disabled_is_noop(self):
        mon = self._mon(enabled=False)
        lines = ["validation_accuracy=0.90", "validation_accuracy=0.90"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_lower_better_loss_plateau(self):
        # loss descending then flat -> early stop on the flat tail.
        mon = self._mon(direction="lower_better", metric="validation_loss",
                        patience=2, min_epochs=3)
        lines = ["validation_loss=1.20", "validation_loss=0.80",
                 "validation_loss=0.80"]
        self.assertTrue(mon._check_in_run_early_stop(999, lines))

    def test_lower_better_still_dropping_no_stop(self):
        mon = self._mon(direction="lower_better", metric="validation_loss",
                        patience=2, min_epochs=3)
        lines = ["validation_loss=1.50", "validation_loss=0.80",
                 "validation_loss=0.40"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))


class InRunEarlyStopEndToEndTests(unittest.TestCase):
    """A real training subprocess is early-terminated once it plateaus."""

    def test_monitor_terminates_plateaued_run(self):
        tmp = Path(tempfile.mkdtemp())
        backend = LocalExecutionBackend(tmp)
        # Script prints a rising val then a long plateau; a monitor with
        # in-run early stop should kill it long before it would finish.
        (tmp / "train_plateau.py").write_text(
            "import time\n"
            "print('validation_accuracy=0.80')\n"
            "time.sleep(0.3)\n"
            "print('validation_accuracy=0.90')\n"
            "time.sleep(0.3)\n"
            "for _ in range(30):\n"      # plateau for 30 epochs (~9s)
            "    print('validation_accuracy=0.90')\n"
            "    time.sleep(0.3)\n"
            "print('finished normally')\n"
        )
        es = {"mode": "active_wall_clock_seconds", "limit": 60,
              "hard_wall_clock_limit": 60, "enforced": True,
              "early_stop": {"enabled": True, "patience": 2,
                             "improvement_tol": 1e-4, "min_epochs": 3,
                             "metric": "validation_accuracy"}}
        mon = ExperimentMonitor(backend=backend, poll_interval=0.1, budget=es)
        reg = ToolRegistry(backend, config={})
        payload = json.loads(reg._exec_launch_experiment(
            "python train_plateau.py"))
        started = time.time()
        res = mon.wait_for_completion(payload["pid"], payload["log_file"],
                                      notify=False)
        elapsed = time.time() - started
        self.assertTrue(res["early_stopped"],
                        f"expected early_stopped, got {res}")
        # Plateau of 30*0.3=9s should be cut short to ~1-2s.
        self.assertLess(elapsed, 6.0,
                        f"early stop was too slow: {elapsed:.1f}s")
        self.assertEqual(res["contract_status"], "SUCCESS")
        # Metrics still extracted (final plateau accuracy).
        self.assertAlmostEqual(res["metrics"].get("validation_accuracy"), 0.90,
                               places=1)


class LoopLevelEarlyStopTests(unittest.TestCase):
    """_early_stop_reason triggers (leader stagnation + saturation)."""

    def _make_loop(self, **es):
        import tempfile as _t
        tmp = _t.mkdtemp()
        proj = Path(tmp)
        (proj / "PROJECT_BRIEF.md").write_text("Train a classifier")
        from core.loop import ResearchLoop
        cfg = {
            "project": {"workspace": "workspace"},
            "agent": {"max_cycles": -1, "cooldown_interval": 0},
            "obsidian": {"enabled": False},
            "ledger": {"enabled": True, "metric_key": "validation_accuracy"},
            "journal": {"enabled": True},
            "safety": {"enabled": False},
            "experiment": {"loop_engineering": {"enabled": True,
                                                "early_stop": {
                                                    "enabled": True,
                                                    "saturation_rounds": 3,
                                                    "plateau_band": 2.0,
                                                    "max_consecutive_no_experiment": 3,
                                                    **es}}},
        }
        loop = ResearchLoop(config=cfg, project_dir=str(proj))
        return loop

    def test_leader_stagnation_trigger(self):
        loop = self._make_loop(max_consecutive_no_experiment=3)
        # 3 rounds with no experiment launched.
        think = {"action": "report"}
        for _ in range(2):
            self.assertEqual(loop._early_stop_reason(think, {}), "")
        reason = loop._early_stop_reason(think, {})
        self.assertIn("early-stop", reason)
        self.assertIn("no experiment", reason)

    def test_experiment_resets_stagnation(self):
        loop = self._make_loop(max_consecutive_no_experiment=3)
        think = {"action": "report"}
        loop._early_stop_reason(think, {})
        loop._early_stop_reason(think, {})
        # A real experiment resets the counter.
        loop._early_stop_reason({"action": "experiment"}, {"experiment_launched": True})
        self.assertEqual(loop._early_stop_reason(think, {}), "")

    def test_saturation_trigger(self):
        loop = self._make_loop(saturation_rounds=3, plateau_band=2.0)
        # Force a champion to exist.
        loop._recent_verdicts = [
            {"verdict": "DISCARD", "delta": 0.001, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": -0.0005, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.0002, "noise_std": 0.0018},
        ]
        # Monkey-patch champion so has_champion is true.
        loop._resolve_champion_metrics = lambda: {"validation_accuracy": 0.99}
        reason = loop._early_stop_reason({"action": "experiment"}, {})
        self.assertIn("saturated", reason)

    def test_no_saturation_if_improving(self):
        loop = self._make_loop(saturation_rounds=3, plateau_band=2.0)
        loop._recent_verdicts = [
            {"verdict": "DISCARD", "delta": 0.05, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.02, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.01, "noise_std": 0.0018},
        ]
        loop._resolve_champion_metrics = lambda: {"validation_accuracy": 0.99}
        # Deltas far outside the noise band -> not a plateau -> keep searching.
        self.assertEqual(loop._early_stop_reason({"action": "experiment"}, {}), "")

    def test_disabled_is_noop(self):
        loop = self._make_loop(enabled=False)
        self.assertEqual(loop._early_stop_reason({"action": "report"}, {}), "")


if __name__ == "__main__":
    unittest.main()
