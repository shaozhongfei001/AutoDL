import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from core.experiment_contract import decide_verdict
from core.git_vcs import GitExperimentVcs, VcsError, head_sha
from core.ledger import ExperimentLedger


def git_init(repo: Path, author=True):
    repo.mkdir(parents=True, exist_ok=True)
    env = {}
    if author:
        env = {
            "GIT_AUTHOR_NAME": "shaozhongfei001",
            "GIT_AUTHOR_EMAIL": "shaozhongfei@163.com",
            "GIT_COMMITTER_NAME": "shaozhongfei001",
            "GIT_COMMITTER_EMAIL": "shaozhongfei@163.com",
        }
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "shaozhongfei@163.com"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "shaozhongfei001"], check=True, env=env)
    return env


class DecideVerdictTests(unittest.TestCase):
    def test_keep_when_better(self):
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "KEEP")

    def test_discard_when_worse(self):
        v = decide_verdict(
            {"validation_accuracy": 0.97}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_discard_when_better_but_below_effect(self):
        # improved 0.004 but min_effect_size is 0.005 -> noise guard -> DISCARD
        v = decide_verdict(
            {"validation_accuracy": 0.984}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_incomparable_when_metric_missing(self):
        v = decide_verdict(
            {"other": 1}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize",
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_minimize_direction(self):
        v = decide_verdict(
            {"validation_loss": 0.03}, {"validation_loss": 0.05},
            "validation_loss", "minimize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "KEEP")

    # --- P1 robustness guards ---
    def test_invalid_direction_incomparable(self):
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "bogus")
        self.assertEqual(v["verdict"], "INCOMPARABLE")
        self.assertIn("direction", v["reason"])

    def test_empty_primary_metric_incomparable(self):
        v = decide_verdict({"x": 1}, {"x": 1}, "", "maximize")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_negative_effect_size_incomparable(self):
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size=-0.1)
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_non_numeric_effect_size_incomparable(self):
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size="not-a-number")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_numeric_string_effect_size_ok(self):
        # coerce numeric strings instead of throwing
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size="0.001")
        self.assertEqual(v["verdict"], "KEEP")

    def test_metrics_none_safe(self):
        v = decide_verdict(None, {"validation_accuracy": 0.98}, "validation_accuracy")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_metric_value_boolean_no_exception(self):
        # booleans are not numeric for our purposes -> INCOMPARABLE, not throw
        v = decide_verdict({"validation_accuracy": True}, {"validation_accuracy": 0.98},
                           "validation_accuracy")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_gate_verdict_non_dict_safe(self):
        from core.experiment_contract import gate_verdict_by_contract_status
        v = gate_verdict_by_contract_status(None, "CRASH")
        self.assertEqual(v["verdict"], "INCOMPARABLE")
        self.assertEqual(v["contract_status"], "CRASH")

    def test_gate_blocks_keep_on_crash(self):
        from core.experiment_contract import gate_verdict_by_contract_status
        raw = {"verdict": "KEEP", "delta": 0.01}
        g = gate_verdict_by_contract_status(raw, "CRASH")
        self.assertEqual(g["verdict"], "DISCARD")

    def test_gate_passes_keep_on_success(self):
        from core.experiment_contract import gate_verdict_by_contract_status
        raw = {"verdict": "KEEP", "delta": 0.01}
        g = gate_verdict_by_contract_status(raw, "SUCCESS")
        self.assertEqual(g["verdict"], "KEEP")

    # --- P3 statistical rigor: multi-seed aggregation + noise calibration ---
    def test_multi_seed_candidate_mean(self):
        # candidate ran 3 seeds -> mean used; beats champion -> KEEP
        v = decide_verdict(
            {"validation_accuracy": [0.98, 0.985, 0.99]}, {"validation_accuracy": 0.97},
            "validation_accuracy", "maximize", minimum_effect_size=0.001,
        )
        self.assertEqual(v["verdict"], "KEEP")
        self.assertAlmostEqual(v["delta"], 0.015, places=3)  # mean=0.985 - 0.97

    def test_multi_seed_champion_mean(self):
        v = decide_verdict(
            {"validation_accuracy": 0.97}, {"validation_accuracy": [0.985, 0.99, 0.995]},
            "validation_accuracy", "maximize", minimum_effect_size=0.001,
        )
        self.assertEqual(v["verdict"], "DISCARD")  # cand 0.97 < champion mean 0.99

    def test_empty_seed_list_incomparable(self):
        v = decide_verdict(
            {"validation_accuracy": []}, {"validation_accuracy": 0.98},
            "validation_accuracy",
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_noise_std_raises_effective_bar(self):
        # improvement 0.008 but noise_std 0.005 -> effective bar = 2*0.005=0.01
        # delta 0.008 < 0.01 -> DISCARD despite positive improvement
        v = decide_verdict(
            {"validation_accuracy": 0.988}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.0, noise_std=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")
        self.assertIn("improved but below", v["reason"])

    def test_noise_std_below_effect_size_no_change(self):
        # configured effect 0.02 dominates noise_std 0.005 (0.01) -> bar stays 0.02
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.02, noise_std=0.005,
        )
        # delta 0.01 < 0.02 -> DISCARD (configured bar wins)
        self.assertEqual(v["verdict"], "DISCARD")

    def test_noise_std_above_effect_size_blocks(self):
        # configured effect 0.001, noise_std 0.005 -> effective 0.01; delta 0.005 -> DISCARD
        v = decide_verdict(
            {"validation_accuracy": 0.985}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.001, noise_std=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_noise_std_negative_incomparable(self):
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", noise_std=-0.1,
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")


class GitExperimentVcsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.env = git_init(self.repo)
        (self.repo / "baseline.txt").write_text("base")
        self._commit("baseline")
        self.vcs = GitExperimentVcs(self.repo, champion_ref="champion/test", candidate_ref_prefix="exp/test")

    def tearDown(self):
        self.tmp.cleanup()

    def _commit(self, msg):
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", msg], check=True, env=self.env)
        return head_sha(self.repo)

    def test_champion_ref_created_from_main(self):
        champ = head_sha(self.repo, "champion/test")
        self.assertEqual(champ, head_sha(self.repo, "main"))

    def test_promote_fast_forward(self):
        base = head_sha(self.repo, "champion/test")
        (self.repo / "cand.txt").write_text("cand")
        cand_sha = self._commit("candidate")

        res = self.vcs.promote_to_champion(cand_sha, base)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "PROMOTED")
        self.assertEqual(head_sha(self.repo, "champion/test"), cand_sha)

    def test_promote_stale_candidate_rejected(self):
        base = head_sha(self.repo, "champion/test")
        # champion moves forward independently
        (self.repo / "adv.txt").write_text("adv")
        new_champ = self._commit("advance champion")
        self.vcs.promote_to_champion(new_champ, base)

        # stale candidate built on old base -> rejected
        (self.repo / "stale.txt").write_text("stale")
        stale_sha = self._commit("stale candidate")
        res = self.vcs.promote_to_champion(stale_sha, base)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "STALE_CANDIDATE")

    def test_candidate_worktree_is_isolated(self):
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("c1", base, parent)
        self.assertTrue(wt.exists())
        # writing in the worktree does not touch the main working tree
        (wt / "cand.txt").write_text("x")
        self.assertFalse((self.repo / "cand.txt").exists())

    def test_artifact_manifest_contains_sha(self):
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("c2", base, parent)
        (wt / "cand.py").write_text("print('hi')")
        cand_sha = self.vcs.commit_candidate(wt, "candidate c2")
        log = wt / "exp.log"
        log.write_text("validation_accuracy=0.99")
        manifest = self.vcs.build_artifact_manifest("c2", wt, {"validation_accuracy": 0.99}, log_file=log)
        self.assertEqual(manifest["candidate_sha"], cand_sha)
        self.assertEqual(manifest["metrics"]["validation_accuracy"], 0.99)
        self.assertTrue(any(f["role"] == "log" for f in manifest["files"]))
        self.assertTrue(manifest["manifest_sha256"])

    def test_promote_non_fast_forward_rejected(self):
        base = head_sha(self.repo, "champion/test")
        # Build a divergent candidate that does NOT contain ``base`` in its
        # history (an orphan commit) while the champion still points at ``base``
        # so the optimistic-lock check passes but the fast-forward check fails.
        tree = subprocess.run(
            ["git", "-C", str(self.repo), "write-tree"],
            capture_output=True, text=True, check=True, env=self.env,
        ).stdout.strip()
        orphan_sha = subprocess.run(
            ["git", "-C", str(self.repo), "commit-tree", tree, "-m", "orphan candidate"],
            capture_output=True, text=True, check=True, env=self.env,
        ).stdout.strip()

        res = self.vcs.promote_to_champion(orphan_sha, base)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "NOT_FAST_FORWARD")
        # the protected champion must never have moved
        self.assertEqual(head_sha(self.repo, "champion/test"), base)

    def test_artifact_manifest_sha256_is_self_consistent(self):
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("m1", base, parent)
        (wt / "model.py").write_text("def f(): return 1")
        self.vcs.commit_candidate(wt, "model m1")
        log = wt / "run.log"
        log.write_text("acc=0.99")
        manifest = self.vcs.build_artifact_manifest("m1", wt, {"acc": 0.99}, log_file=log)

        # manifest_sha256 must equal a deterministic hash of the whole body.
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        expected = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.assertEqual(manifest["manifest_sha256"], expected)
        # every file entry carries a full 64-hex SHA-256
        for f in manifest["files"]:
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")

    def test_artifact_manifest_tolerates_external_log(self):
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("m2", base, parent)
        (wt / "model.py").write_text("def f(): return 2")
        self.vcs.commit_candidate(wt, "model m2")
        # a log written outside the worktree (e.g. central artifacts dir) must
        # not crash the manifest build
        external = Path(self.tmp.name) / "central" / "m2.log"
        external.parent.mkdir(parents=True, exist_ok=True)
        external.write_text("acc=0.9")
        manifest = self.vcs.build_artifact_manifest("m2", wt, {"acc": 0.9}, log_file=external)
        self.assertTrue(any(f["role"] == "log" for f in manifest["files"]))
        self.assertTrue(manifest["manifest_sha256"])

    def test_candidate_worktree_resume_is_idempotent(self):
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt1 = self.vcs.create_candidate_worktree("r1", base, parent)
        (wt1 / "cand.py").write_text("x")
        # calling create again must return the same already-registered worktree
        wt2 = self.vcs.create_candidate_worktree("r1", base, parent)
        self.assertEqual(wt1, wt2)
        self.assertTrue((wt2 / "cand.py").exists())


class LedgerVerdictTests(unittest.TestCase):
    def test_record_verdict_appends_versioning_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ExperimentLedger(Path(tmp))
            entry = ledger.record_verdict(
                cycle=3, experiment_id="e9",
                metrics={"validation_accuracy": 0.99},
                verdict="KEEP",
                champion_before_sha="aaa",
                candidate_sha="bbb",
                champion_after_sha="bbb",
                promotion_status="PROMOTED",
                artifact_manifest_uri="artifacts/STUDY-001/e9/manifest.json",
                reason="delta 0.01 >= min_effect_size",
            )
            self.assertEqual(entry["verdict"], "KEEP")
            self.assertEqual(entry["promotion_status"], "PROMOTED")
            self.assertEqual(entry["candidate_sha"], "bbb")
            # re-read from disk to confirm append-only persistence
            reloaded = ledger.all()
            self.assertEqual(len(reloaded), 1)
            self.assertEqual(reloaded[0]["artifact_manifest_uri"], "artifacts/STUDY-001/e9/manifest.json")

    def test_record_verdict_is_append_only_and_accumulates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = ExperimentLedger(Path(tmp))
            ledger.record_verdict(
                cycle=1, experiment_id="e1", metrics={"acc": 0.9}, verdict="KEEP",
                champion_before_sha="aaa", candidate_sha="bbb", champion_after_sha="bbb",
                promotion_status="PROMOTED",
                artifact_manifest_uri="artifacts/S/e1/manifest.json",
                reason="delta 0.01",
            )
            ledger.record_verdict(
                cycle=2, experiment_id="e2", metrics={"acc": 0.8}, verdict="DISCARD",
                champion_before_sha="bbb", candidate_sha="ccc", champion_after_sha="bbb",
                promotion_status="NOT_PROMOTED",
                artifact_manifest_uri="artifacts/S/e2/manifest.json",
                reason="delta -0.01",
            )
            entries = ledger.all()
            # append-only: both events survive; nothing is rewritten in place
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["cycle"], 1)
            self.assertEqual(entries[0]["promotion_status"], "PROMOTED")
            self.assertEqual(entries[1]["verdict"], "DISCARD")
            self.assertEqual(entries[1]["champion_after_sha"], "bbb")
            self.assertEqual(entries[1]["artifact_manifest_uri"], "artifacts/S/e2/manifest.json")
            # the on-disk representation stays one JSON object per line
            lines = [ln for ln in ledger.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2)
            self.assertIsNotNone(json.loads(lines[1]))


if __name__ == "__main__":
    unittest.main()
