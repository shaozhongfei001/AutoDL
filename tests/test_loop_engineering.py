"""
M2 machine-judgment tests (SDD 05 Loop Engineering).

Covers the machine-authoritative KEEP/DISCARD/INCOMPARABLE verdict loop that
runs BEFORE the LLM reflection:
  * verdict correctness (improve -> KEEP, worse -> DISCARD, missing -> INCOMPARABLE)
  * contract_status gating (a crashed/timed-out run is never KEEP)
  * verdict persisted to the append-only ledger
  * graceful degradation when VCS infra is absent (never crashes the loop)
  * legacy fallback when no experiment contract is configured
"""

import tempfile
import unittest
from pathlib import Path

from core.experiment_contract import gate_verdict_by_contract_status
from core.loop import ResearchLoop


def _make_loop(tmp, primary="validation_accuracy", direction="maximize",
               min_effect_size=0.005, loop_engineering=True):
    project_dir = Path(tmp)
    (project_dir / "PROJECT_BRIEF.md").write_text("Train a classifier to acc > 0.8")
    config = {
        "project": {"workspace": "workspace"},
        "agent": {"max_cycles": 1, "cooldown_interval": 0},
        "obsidian": {"enabled": False},
        "ledger": {"enabled": True, "metric_key": primary, "metric_direction": "higher_better"},
        "stagnation": {"enabled": True, "threshold_cycles": 2},
        "journal": {"enabled": True},
        "safety": {"enabled": True, "fail_threshold": 3},
        "gates": {"enabled": True, "threshold": 0.8, "direction": "higher_better"},
        "experiment": {
            "evaluation": {
                "primary_metric": {"name": primary, "direction": direction},
                "minimum_effect_size": min_effect_size,
            },
            "loop_engineering": {"enabled": loop_engineering},
        },
    }
    return ResearchLoop(config=config, project_dir=str(project_dir))


class GateVerdictByContractStatusTests(unittest.TestCase):
    """Pure function tests for the contract_status gate."""

    def test_clean_status_passthrough_keep(self):
        v = gate_verdict_by_contract_status({"verdict": "KEEP", "delta": 0.02}, "SUCCESS")
        self.assertEqual(v["verdict"], "KEEP")

    def test_empty_status_is_clean_legacy(self):
        v = gate_verdict_by_contract_status({"verdict": "KEEP", "delta": 0.02}, "")
        self.assertEqual(v["verdict"], "KEEP")

    def test_crash_never_keep(self):
        v = gate_verdict_by_contract_status({"verdict": "KEEP", "delta": 0.02}, "CRASH")
        self.assertEqual(v["verdict"], "DISCARD")

    def test_timeout_never_keep(self):
        v = gate_verdict_by_contract_status({"verdict": "KEEP", "delta": 0.02}, "TIMEOUT")
        self.assertEqual(v["verdict"], "DISCARD")

    def test_budget_exceeded_never_keep(self):
        v = gate_verdict_by_contract_status({"verdict": "KEEP", "delta": 0.02}, "BUDGET_EXCEEDED")
        self.assertEqual(v["verdict"], "DISCARD")

    def test_incomparable_passthrough_any_status(self):
        v = gate_verdict_by_contract_status({"verdict": "INCOMPARABLE", "delta": None}, "CRASH")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_status_key_added(self):
        v = gate_verdict_by_contract_status({"verdict": "DISCARD", "delta": -0.1}, "SUCCESS")
        self.assertEqual(v["contract_status"], "SUCCESS")


class MachineJudgeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def _seed_champion(self, loop, value=0.90):
        loop.ledger.record(
            cycle=0, hypothesis="champion baseline", status="launched",
            metrics={"validation_accuracy": value}, ts=0.0,
        )

    def test_keep_when_candidate_better(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 11,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "KEEP")

    def test_discard_when_candidate_worse(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 12,
            "final_metrics": {"validation_accuracy": 0.85},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "DISCARD")

    def test_incomparable_when_metric_missing(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 13,
            "final_metrics": {"other_metric": 1.0},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "INCOMPARABLE")

    def test_crash_gates_keep_to_discard(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 14,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",  # legacy status is "completed"
            "contract_status": "CRASH",
        })
        self.assertEqual(machine["verdict"], "DISCARD")

    def test_verdict_written_to_ledger(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        loop._machine_judge({
            "experiment_launched": True,
            "pid": 15,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        verdict_entries = [e for e in loop.ledger.all() if e.get("action", "").startswith("verdict")]
        self.assertEqual(len(verdict_entries), 1)
        self.assertEqual(verdict_entries[0]["verdict"], "KEEP")

    def test_verdict_written_to_state(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        loop._machine_judge({
            "experiment_launched": True,
            "pid": 16,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        state = loop._load_state()
        self.assertEqual(state.get("verdict"), "KEEP")
        self.assertEqual(state.get("last_verdict", {}).get("verdict"), "KEEP")

    def test_archives_manifest_without_vcs_no_crash(self):
        # No VCS controller configured -> ledger-manifest archive, still returns
        # a verdict and never raises.
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 17,
            "log_file": "",
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "KEEP")
        # a manifest artifact should have been persisted under the workspace
        artifacts = list((loop.workspace / "artifacts").glob("*"))
        self.assertGreater(len(artifacts), 0)

    def test_legacy_path_when_m2_disabled(self):
        # No primary metric in the experiment contract -> M2 disabled -> None.
        loop = _make_loop(self.tempdir.name, primary="", loop_engineering=False)
        self.assertFalse(loop._machine_judge_enabled)
        self.assertIsNone(loop._machine_judge({
            "experiment_launched": True,
            "final_metrics": {"validation_accuracy": 0.95},
        }))

    def test_no_experiment_launched_returns_none(self):
        loop = _make_loop(self.tempdir.name)
        self.assertTrue(loop._machine_judge_enabled)
        self.assertIsNone(loop._machine_judge({"experiment_launched": False}))

    def test_machine_judge_is_authoritative_in_reflect(self):
        # The reflect result's decision must carry the machine verdict and the
        # LLM cannot override it. We stub dispatch_leader to return an LLM
        # opinion that contradicts the machine verdict.
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 18,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "KEEP")

        # Stub the LLM so no real API call is made. It returns a contradictory
        # opinion ("DISCARD") that the machine KEEP must override.
        loop.dispatcher.dispatch_leader = lambda task, context=None: {
            "milestone": "candidate looked worse",
            "decision": "DISCARD",
        }
        reflect = loop._reflect({}, machine_judgment=machine)
        self.assertTrue(reflect.get("decision", "").startswith("[machine:KEEP]"), reflect.get("decision"))
        # LLM narrative is preserved as an explanation, never the decision.
        self.assertEqual(reflect.get("narrative"), "candidate looked worse")


class VerdictHistoryEnrichmentTests(unittest.TestCase):
    """M5/M6 integration: verdict history is rebuilt from the ledger into THINK
    context so the leader can dedup hypotheses and resume from the last verdict."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def _seed_champion(loop, value=0.90):
        loop.ledger.record(
            cycle=0, hypothesis="champion baseline", status="launched",
            metrics={"validation_accuracy": value}, ts=0.0,
        )

    def test_enrich_context_rebuilds_verdict_history_from_ledger(self):
        loop = _make_loop(self.tempdir.name)
        self._seed_champion(loop, 0.90)
        machine = loop._machine_judge({
            "experiment_launched": True,
            "pid": 19,
            "final_metrics": {"validation_accuracy": 0.95},
            "experiment_status": "completed",
        })
        self.assertEqual(machine["verdict"], "KEEP")

        context = {}
        loop._enrich_context(context)
        self.assertIn("last_verdict", context)
        self.assertEqual(context["last_verdict"]["verdict"], "KEEP")
        self.assertIn("verdict_history", context)
        self.assertEqual(len(context["verdict_history"]), 1)
        # KEEP candidate is surfaced so M5 can avoid re-proposing it.
        self.assertIn("promoted_candidates", context)
        self.assertEqual(len(context["promoted_candidates"]), 1)

    def test_no_context_fields_when_no_verdicts(self):
        # No verdict recorded yet -> context stays quiet (nothing to dedup).
        loop = _make_loop(self.tempdir.name)
        context = {}
        loop._enrich_context(context)
        self.assertNotIn("last_verdict", context)
        self.assertNotIn("verdict_history", context)
        self.assertNotIn("promoted_candidates", context)


class ConvergenceTests(unittest.TestCase):
    """P2: M5 convergence — hypothesis de-dup + no-progress escalation."""

    def _make_dedup_loop(self, tmp, dedup_enabled=True):
        project_dir = Path(tmp)
        (project_dir / "PROJECT_BRIEF.md").write_text("Train a classifier")
        config = {
            "project": {"workspace": "workspace"},
            "agent": {"max_cycles": 2, "cooldown_interval": 0},
            "obsidian": {"enabled": False},
            "ledger": {"enabled": True},
            "stagnation": {"enabled": False},
            "journal": {"enabled": True},
            "safety": {"enabled": True},
            "gates": {"enabled": False},
            "experiment": {
                "evaluation": {"primary_metric": {"name": "validation_accuracy", "direction": "maximize"}},
                "loop_engineering": {
                    "enabled": True,
                    "dedup": {
                        "enabled": dedup_enabled,
                        "repeated_hypothesis_limit": 1,
                    },
                },
            },
        }
        return ResearchLoop(config=config, project_dir=str(project_dir))

    def test_dedup_blocks_repeated_hypothesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp)
            r1 = loop._apply_hypothesis_dedup({"action": "experiment", "hypothesis": "Try more conv layers"})
            self.assertNotEqual(r1.get("action"), "wait")
            r2 = loop._apply_hypothesis_dedup({"action": "experiment", "hypothesis": "Try more conv layers"})
            self.assertEqual(r2.get("action"), "wait")
            self.assertTrue(r2.get("hypothesis_dedup_blocked"))

    def test_dedup_disabled_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp, dedup_enabled=False)
            r = loop._apply_hypothesis_dedup({"action": "experiment", "hypothesis": "same"})
            self.assertNotEqual(r.get("action"), "wait")

    def test_dedup_no_hypothesis_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp)
            r = loop._apply_hypothesis_dedup({"action": "report"})
            self.assertEqual(r.get("action"), "report")

    def test_no_progress_escalation_in_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp)
            loop._no_progress_streak = 5  # >= widen_threshold(3) -> widen
            think = {"action": "experiment", "task": "same plan", "hypothesis": "h"}
            loop._last_no_progress_signature = loop._plan_signature(think)
            out = loop._apply_no_progress_fallback(think, None)
            self.assertEqual(out.get("action"), "wait")
            self.assertEqual(out.get("no_progress_escalation"), "widen")
            self.assertTrue(out.get("no_progress_advice"))

    def test_no_progress_escalation_terminate(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp)
            loop._no_progress_streak = 10  # >= terminate_threshold(10)
            think = {"action": "experiment", "task": "same plan", "hypothesis": "h"}
            loop._last_no_progress_signature = loop._plan_signature(think)
            out = loop._apply_no_progress_fallback(think, None)
            self.assertEqual(out.get("no_progress_escalation"), "terminate")

    def test_escalate_no_progress_levels(self):
        from core.safety import escalate_no_progress
        self.assertEqual(escalate_no_progress(1)["level"], "normal")
        self.assertEqual(escalate_no_progress(4)["level"], "widen")
        self.assertEqual(escalate_no_progress(8)["level"], "lower_target")
        self.assertEqual(escalate_no_progress(12)["level"], "terminate")


class ResumeDedupStateTests(unittest.TestCase):
    """P5: on restart, attempted-hypothesis state resumes from the ledger."""

    def _make_dedup_loop(self, tmp, ledger_entries=None, dedup_enabled=True):
        from core.ledger import ExperimentLedger
        project_dir = Path(tmp)
        (project_dir / "PROJECT_BRIEF.md").write_text("Train a classifier")
        ws = project_dir / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        config = {
            "project": {"workspace": "workspace"},
            "agent": {"max_cycles": 2, "cooldown_interval": 0},
            "obsidian": {"enabled": False},
            "ledger": {"enabled": True},
            "stagnation": {"enabled": False},
            "journal": {"enabled": False},
            "safety": {"enabled": False},
            "gates": {"enabled": False},
            "experiment": {
                "evaluation": {"primary_metric": {"name": "validation_accuracy", "direction": "maximize"}},
                "loop_engineering": {
                    "enabled": True,
                    "dedup": {"enabled": dedup_enabled, "repeated_hypothesis_limit": 1},
                },
            },
        }
        if ledger_entries is not None:
            ledger = ExperimentLedger(ws)
            for e in ledger_entries:
                ledger.record(**e)
        return ResearchLoop(config=config, project_dir=str(project_dir))

    def test_resume_loads_promoted_candidates_into_attempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [
                {"cycle": 0, "action": "verdict:e1", "verdict": "KEEP", "candidate_sha": "abc123",
                 "promotion_status": "PROMOTED", "metrics": {"validation_accuracy": 0.9}},
            ]
            loop = self._make_dedup_loop(tmp, ledger_entries=entries)
            # promoted candidate SHA is normalized into attempted hypotheses
            self.assertGreater(len(loop._attempted_hypotheses), 0)

    def test_resume_with_empty_ledger_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            loop = self._make_dedup_loop(tmp)  # empty ledger
            self.assertEqual(loop._attempted_hypotheses, set())

    def test_resume_with_dedup_disabled_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [
                {"cycle": 0, "action": "verdict:e1", "verdict": "KEEP", "candidate_sha": "abc123"},
            ]
            loop = self._make_dedup_loop(tmp, ledger_entries=entries, dedup_enabled=False)
            self.assertEqual(loop._attempted_hypotheses, set())

    def test_corrupt_state_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            ws = project_dir / "workspace"
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "state.json").write_text("{corrupt json")
            # constructing the loop must not crash despite corrupt state
            loop = self._make_dedup_loop(tmp)
            self.assertIsNotNone(loop)


if __name__ == "__main__":
    unittest.main()
