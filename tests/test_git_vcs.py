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


if __name__ == "__main__":
    unittest.main()
