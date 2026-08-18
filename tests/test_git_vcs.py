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
    """在临时目录初始化一个 git 仓库用于测试，可指定 author 以便做可控提交。"""
    repo.mkdir(parents=True, exist_ok=True)
    env = {}
    if author:
        # 为 git 操作提供固定的作者/提交者身份，保证测试可重复。
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
    """对 decide_verdict 判决逻辑的测试：KEEP/DISCARD/INCOMPARABLE 三种结论。"""

    def test_keep_when_better(self):
        # 候选比冠军更好且超过最小效应量 -> KEEP。
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "KEEP")

    def test_discard_when_worse(self):
        # 候选比冠军更差 -> DISCARD。
        v = decide_verdict(
            {"validation_accuracy": 0.97}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_discard_when_better_but_below_effect(self):
        # 提升 0.004 但最小效应量是 0.005 -> 噪声守卫触发 -> DISCARD。
        v = decide_verdict(
            {"validation_accuracy": 0.984}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_incomparable_when_metric_missing(self):
        # 候选缺失主指标 -> 无法比较 -> INCOMPARABLE。
        v = decide_verdict(
            {"other": 1}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize",
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_minimize_direction(self):
        # 越小越好的方向：loss 下降应判为 KEEP。
        v = decide_verdict(
            {"validation_loss": 0.03}, {"validation_loss": 0.05},
            "validation_loss", "minimize", minimum_effect_size=0.005,
        )
        self.assertEqual(v["verdict"], "KEEP")

    # --- P1 健壮性守卫 ---
    def test_invalid_direction_incomparable(self):
        # 非法方向 -> 无法比较，理由中应包含 direction 信息。
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "bogus")
        self.assertEqual(v["verdict"], "INCOMPARABLE")
        self.assertIn("direction", v["reason"])

    def test_empty_primary_metric_incomparable(self):
        # 主指标名为空 -> INCOMPARABLE。
        v = decide_verdict({"x": 1}, {"x": 1}, "", "maximize")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_negative_effect_size_incomparable(self):
        # 负的最小效应量 -> INCOMPARABLE。
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size=-0.1)
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_non_numeric_effect_size_incomparable(self):
        # 非数字字符串的效应量 -> INCOMPARABLE。
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size="not-a-number")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_numeric_string_effect_size_ok(self):
        # 数字形式的字符串应被强制转换，而不是抛异常。
        v = decide_verdict({"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
                           "validation_accuracy", "maximize", minimum_effect_size="0.001")
        self.assertEqual(v["verdict"], "KEEP")

    def test_metrics_none_safe(self):
        # 指标为 None 时应安全返回 INCOMPARABLE。
        v = decide_verdict(None, {"validation_accuracy": 0.98}, "validation_accuracy")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_metric_value_boolean_no_exception(self):
        # 对当前用途而言布尔值不是数值 -> 返回 INCOMPARABLE，而不是抛异常。
        v = decide_verdict({"validation_accuracy": True}, {"validation_accuracy": 0.98},
                           "validation_accuracy")
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_gate_verdict_non_dict_safe(self):
        # 非字典形式的原始判决也应安全返回 INCOMPARABLE 并保留 contract_status。
        from core.experiment_contract import gate_verdict_by_contract_status
        v = gate_verdict_by_contract_status(None, "CRASH")
        self.assertEqual(v["verdict"], "INCOMPARABLE")
        self.assertEqual(v["contract_status"], "CRASH")

    def test_gate_blocks_keep_on_crash(self):
        # 运行崩溃（CRASH）时必须把 KEEP 拦截为 DISCARD，防止把崩溃结果晋升。
        from core.experiment_contract import gate_verdict_by_contract_status
        raw = {"verdict": "KEEP", "delta": 0.01}
        g = gate_verdict_by_contract_status(raw, "CRASH")
        self.assertEqual(g["verdict"], "DISCARD")

    def test_gate_passes_keep_on_success(self):
        # 正常运行（SUCCESS）时保留原 KEEP 判决。
        from core.experiment_contract import gate_verdict_by_contract_status
        raw = {"verdict": "KEEP", "delta": 0.01}
        g = gate_verdict_by_contract_status(raw, "SUCCESS")
        self.assertEqual(g["verdict"], "KEEP")

    # --- P3 统计严谨性：多 seed 聚合 + 噪声标定 ---
    def test_multi_seed_candidate_mean(self):
        # 候选跑了 3 个 seed -> 取其均值；均值超过冠军 -> KEEP。
        v = decide_verdict(
            {"validation_accuracy": [0.98, 0.985, 0.99]}, {"validation_accuracy": 0.97},
            "validation_accuracy", "maximize", minimum_effect_size=0.001,
        )
        self.assertEqual(v["verdict"], "KEEP")
        self.assertAlmostEqual(v["delta"], 0.015, places=3)  # 均值 0.985 - 0.97

    def test_multi_seed_champion_mean(self):
        # 冠军用多 seed 均值（0.99）时，单点候选 0.97 应被判定为 DISCARD。
        v = decide_verdict(
            {"validation_accuracy": 0.97}, {"validation_accuracy": [0.985, 0.99, 0.995]},
            "validation_accuracy", "maximize", minimum_effect_size=0.001,
        )
        self.assertEqual(v["verdict"], "DISCARD")  # 候选 0.97 < 冠军均值 0.99

    def test_empty_seed_list_incomparable(self):
        # 空 seed 列表 -> 无法比较。
        v = decide_verdict(
            {"validation_accuracy": []}, {"validation_accuracy": 0.98},
            "validation_accuracy",
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")

    def test_noise_std_raises_effective_bar(self):
        # 提升 0.008 但 noise_std 为 0.005 -> 有效门槛 = 2*0.005 = 0.01
        # delta 0.008 < 0.01 -> 虽有正向提升仍为 DISCARD。
        v = decide_verdict(
            {"validation_accuracy": 0.988}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.0, noise_std=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")
        self.assertIn("improved but below", v["reason"])

    def test_noise_std_below_effect_size_no_change(self):
        # 配置效应 0.02 主导 noise_std 0.005（对应 0.01）-> 门槛仍是 0.02
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.02, noise_std=0.005,
        )
        # delta 0.01 < 0.02 -> DISCARD（以配置的门槛为准）
        self.assertEqual(v["verdict"], "DISCARD")

    def test_noise_std_above_effect_size_blocks(self):
        # 配置效应 0.001，noise_std 0.005 -> 有效门槛 0.01；delta 0.005 -> DISCARD。
        v = decide_verdict(
            {"validation_accuracy": 0.985}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", minimum_effect_size=0.001, noise_std=0.005,
        )
        self.assertEqual(v["verdict"], "DISCARD")

    def test_noise_std_negative_incomparable(self):
        # 负噪声标准差为非法 -> INCOMPARABLE。
        v = decide_verdict(
            {"validation_accuracy": 0.99}, {"validation_accuracy": 0.98},
            "validation_accuracy", "maximize", noise_std=-0.1,
        )
        self.assertEqual(v["verdict"], "INCOMPARABLE")


class GitExperimentVcsTests(unittest.TestCase):
    """对 GitExperimentVcs 的测试：champion 晋升、候选 worktree 隔离与制品清单。"""

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
        # 便捷提交：add -A 后再 commit，返回新提交的 SHA。
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", msg], check=True, env=self.env)
        return head_sha(self.repo)

    def test_champion_ref_created_from_main(self):
        # 初始化时 champion 引用应指向 main。
        champ = head_sha(self.repo, "champion/test")
        self.assertEqual(champ, head_sha(self.repo, "main"))

    def test_promote_fast_forward(self):
        # 候选基于当前 champion，可被快速前进晋升。
        base = head_sha(self.repo, "champion/test")
        (self.repo / "cand.txt").write_text("cand")
        cand_sha = self._commit("candidate")

        res = self.vcs.promote_to_champion(cand_sha, base)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "PROMOTED")
        self.assertEqual(head_sha(self.repo, "champion/test"), cand_sha)

    def test_promote_stale_candidate_rejected(self):
        base = head_sha(self.repo, "champion/test")
        # 冠军独立地向前推进
        (self.repo / "adv.txt").write_text("adv")
        new_champ = self._commit("advance champion")
        self.vcs.promote_to_champion(new_champ, base)

        # 基于旧 base 的过时候选 -> 应被拒绝
        (self.repo / "stale.txt").write_text("stale")
        stale_sha = self._commit("stale candidate")
        res = self.vcs.promote_to_champion(stale_sha, base)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "STALE_CANDIDATE")

    def test_candidate_worktree_is_isolated(self):
        # 候选 worktree 与主线工作树隔离：在 worktree 中写入不影响主线。
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("c1", base, parent)
        self.assertTrue(wt.exists())
        # 在 worktree 里写入不应触碰主线工作树
        (wt / "cand.txt").write_text("x")
        self.assertFalse((self.repo / "cand.txt").exists())

    def test_artifact_manifest_contains_sha(self):
        # 制品清单应包含候选 SHA 与指标，并附带日志文件条目与校验和。
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
        # 构造一个不含 ``base`` 的背离候选（孤儿提交）。此时冠军仍指向 ``base``，
        # 因此乐观锁检查通过，但快速前进（fast-forward）检查会失败。
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
        # 受保护的 champion 绝不能发生移动
        self.assertEqual(head_sha(self.repo, "champion/test"), base)

    def test_artifact_manifest_sha256_is_self_consistent(self):
        # 清单的 manifest_sha256 应等于整个主体（除自身字段外）的确定性哈希。
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("m1", base, parent)
        (wt / "model.py").write_text("def f(): return 1")
        self.vcs.commit_candidate(wt, "model m1")
        log = wt / "run.log"
        log.write_text("acc=0.99")
        manifest = self.vcs.build_artifact_manifest("m1", wt, {"acc": 0.99}, log_file=log)

        # manifest_sha256 必须等于对整个主体做的一次确定性哈希。
        body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        expected = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.assertEqual(manifest["manifest_sha256"], expected)
        # 每个文件条目都必须携带完整的 64 位十六进制 SHA-256
        for f in manifest["files"]:
            self.assertRegex(f["sha256"], r"^[0-9a-f]{64}$")

    def test_artifact_manifest_tolerates_external_log(self):
        # 位于 worktree 之外的日志（例如集中制品目录）不应让清单构建崩溃。
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt = self.vcs.create_candidate_worktree("m2", base, parent)
        (wt / "model.py").write_text("def f(): return 2")
        self.vcs.commit_candidate(wt, "model m2")
        # 写在 worktree 之外的日志（如集中制品目录）不得让清单构建崩溃。
        external = Path(self.tmp.name) / "central" / "m2.log"
        external.parent.mkdir(parents=True, exist_ok=True)
        external.write_text("acc=0.9")
        manifest = self.vcs.build_artifact_manifest("m2", wt, {"acc": 0.9}, log_file=external)
        self.assertTrue(any(f["role"] == "log" for f in manifest["files"]))
        self.assertTrue(manifest["manifest_sha256"])

    def test_candidate_worktree_resume_is_idempotent(self):
        # 对同一候选再次调用 create 应返回已注册的同一个 worktree（幂等）。
        parent = Path(self.tmp.name)
        base = head_sha(self.repo, "champion/test")
        wt1 = self.vcs.create_candidate_worktree("r1", base, parent)
        (wt1 / "cand.py").write_text("x")
        # 再次调用 create 必须返回同一个已注册的 worktree
        wt2 = self.vcs.create_candidate_worktree("r1", base, parent)
        self.assertEqual(wt1, wt2)
        self.assertTrue((wt2 / "cand.py").exists())


class LedgerVerdictTests(unittest.TestCase):
    """对实验账本（ExperimentLedger）记录判决时的版本字段与追加式持久化的测试。"""

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
            # 重新从磁盘读取以确认是追加式持久化
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
            # 追加式：两条记录都保留，不做任何原地改写
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["cycle"], 1)
            self.assertEqual(entries[0]["promotion_status"], "PROMOTED")
            self.assertEqual(entries[1]["verdict"], "DISCARD")
            self.assertEqual(entries[1]["champion_after_sha"], "bbb")
            self.assertEqual(entries[1]["artifact_manifest_uri"], "artifacts/S/e2/manifest.json")
            # 磁盘上仍保持每行一个 JSON 对象
            lines = [ln for ln in ledger.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), 2)
            self.assertIsNotNone(json.loads(lines[1]))


if __name__ == "__main__":
    unittest.main()
