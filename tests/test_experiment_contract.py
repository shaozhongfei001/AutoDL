import json
import tempfile
import unittest
from pathlib import Path

from core.experiment_contract import (
    ProtectedWritePolicy,
    are_comparable,
    classify_run_outcome,
    comparability_fingerprint,
    compute_fingerprint,
    resolve_budget,
    validate_experiment_config,
)
from core.execution import LocalExecutionBackend
from core.monitor import ExperimentMonitor
from core.tools import ToolRegistry


class ValidateExperimentConfigTests(unittest.TestCase):
    """对实验配置校验函数 validate_experiment_config 的测试。"""

    def test_empty_config_is_valid_legacy(self):
        # 空配置（旧式写法）应在不产出任何错误的前提下被接受。
        self.assertEqual(validate_experiment_config({}), [])

    def test_valid_budget_passes(self):
        # 配置含预算模式、主指标与可比性声明时为合法配置，不应报错。
        cfg = {
            "budget": {"mode": "active_wall_clock_seconds", "limit": 300, "hard_wall_clock_limit": 420},
            "evaluation": {"primary_metric": {"name": "validation_accuracy", "direction": "maximize"}},
            "comparability": {"requires_exact_cohort": True},
        }
        self.assertEqual(validate_experiment_config(cfg), [])

    def test_bad_mode_reported(self):
        # 非法预算模式应被记录为配置错误。
        cfg = {"budget": {"mode": "nonsense", "limit": 1}}
        errs = validate_experiment_config(cfg)
        self.assertTrue(any("budget.mode" in e for e in errs))

    def test_negative_limit_reported(self):
        # 负数预算上限同样是配置错误。
        cfg = {"budget": {"limit": -5}}
        errs = validate_experiment_config(cfg)
        self.assertTrue(any("budget.limit" in e for e in errs))


class BudgetTests(unittest.TestCase):
    """对预算解析（resolve_budget）与运行结果归类（classify_run_outcome）的测试。"""

    def test_resolve_budget_legacy_not_enforced(self):
        # 旧式配置（无 budget 段）解析后不被强制执行。
        b = resolve_budget({})
        self.assertFalse(b["enforced"])

    def test_resolve_budget_enforced_when_limit(self):
        b = resolve_budget({"budget": {"limit": 300}})
        self.assertTrue(b["enforced"])
        self.assertEqual(b["limit"], 300.0)

    def test_classify_no_budget_success(self):
        self.assertEqual(classify_run_outcome(50.0, {"enforced": False}, "completed"), "SUCCESS")

    def test_classify_crash(self):
        # 运行崩溃归类为 CRASH。
        self.assertEqual(classify_run_outcome(50.0, {"enforced": False}, "crash"), "CRASH")

    def test_classify_budget_exceeded(self):
        # 超过软预算限制但未触发硬上限 -> BUDGET_EXCEEDED。
        b = {"enforced": True, "limit": 300, "hard_wall_clock_limit": 420}
        self.assertEqual(classify_run_outcome(350.0, b, "completed"), "BUDGET_EXCEEDED")

    def test_classify_timeout_hard_cap(self):
        # 超出硬性墙上时钟上限 -> TIMEOUT。
        b = {"enforced": True, "limit": 300, "hard_wall_clock_limit": 420}
        self.assertEqual(classify_run_outcome(500.0, b, "completed"), "TIMEOUT")

    def test_classify_success_within_budget(self):
        # 在预算限制内正常完成 -> SUCCESS。
        b = {"enforced": True, "limit": 300, "hard_wall_clock_limit": 420}
        self.assertEqual(classify_run_outcome(200.0, b, "completed"), "SUCCESS")


class FingerprintTests(unittest.TestCase):
    """对可比性指纹（comparability_fingerprint / are_comparable / compute_fingerprint）的测试。"""

    def test_fingerprint_is_deterministic(self):
        # 指纹计算与键的书写顺序无关（确定性）。
        self.assertEqual(compute_fingerprint({"a": 1, "b": "x"}), compute_fingerprint({"b": "x", "a": 1}))

    def test_are_comparable_same_fingerprint(self):
        cfg = {
            "experiment": {
                "budget": {"mode": "active_wall_clock_seconds", "limit": 300},
                "comparability": {"hardware_cohort_id": "COHORT-X", "requires_exact_cohort": True},
            }
        }
        fp1 = comparability_fingerprint(cfg, data_fingerprint="d", evaluator_fingerprint="e")
        fp2 = comparability_fingerprint(cfg, data_fingerprint="d", evaluator_fingerprint="e")
        self.assertTrue(are_comparable(fp1, fp2))

    def test_are_not_comparable_different_cohort(self):
        # 不同硬件队列（cohort）的指纹应判定为不可比较。
        cfg1 = {"experiment": {"comparability": {"hardware_cohort_id": "A", "requires_exact_cohort": True}}}
        cfg2 = {"experiment": {"comparability": {"hardware_cohort_id": "B", "requires_exact_cohort": True}}}
        fp1 = comparability_fingerprint(cfg1)
        fp2 = comparability_fingerprint(cfg2)
        self.assertFalse(are_comparable(fp1, fp2))

    def test_legacy_empty_is_comparable(self):
        # 旧式（空）配置视为可比较。
        self.assertTrue(are_comparable({}, {}))


class ProtectedWritePolicyTests(unittest.TestCase):
    """对受保护写入策略（ProtectedWritePolicy）的测试：denylist、allowlist 与哈希门禁。"""

    def setUp(self):
        self.policy = ProtectedWritePolicy()

    def test_denylisted_dir_blocked(self):
        allowed, reason = self.policy.allows_write("data/foo.ubyte")
        self.assertFalse(allowed)
        self.assertIn("denylisted", reason)

    def test_denylisted_file_blocked(self):
        # 位于 denylist 的根级文件（如 config.yaml）也被禁止写入。
        allowed, reason = self.policy.allows_write("config.yaml")
        self.assertFalse(allowed)

    def test_contracts_blocked(self):
        # 契约层（contracts/）永久受保护，禁止被运行时写入。
        allowed, _ = self.policy.allows_write("contracts/studies/STUDY_CONTRACT.yaml")
        self.assertFalse(allowed)

    def test_ordinary_file_allowed_by_default(self):
        # 未列入任何黑名单 / 资质层级的普通文件默认允许写入。
        allowed, _ = self.policy.allows_write("note.txt")
        self.assertTrue(allowed)

    def test_train_py_allowed_by_default(self):
        # train.py 属于候选实验文件，默认允许写入（改造链路需要改它）。
        allowed, _ = self.policy.allows_write("train.py")
        self.assertTrue(allowed)

    def test_allowlist_narrows_writes(self):
        # 配置 allowlist 后，未在清单内的文件会被拒绝写入。
        p = ProtectedWritePolicy(allowlist=["train.py", "workspace/"])
        ok, _ = p.allows_write("train.py")
        self.assertTrue(ok)
        blocked, _ = p.allows_write("note.txt")
        self.assertFalse(blocked)

    def test_protected_hash_gate_detects_modification(self):
        # 哈希门禁：受保护文件被篡改后，assert_unchanged 应报告其路径。
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "data.txt").write_text("original")
            import hashlib
            expected = hashlib.sha256(b"original").hexdigest()
            p = ProtectedWritePolicy(protected_hashes={"data.txt": expected})
            self.assertEqual(p.assert_unchanged(ws), [])
            (ws / "data.txt").write_text("tampered")
            self.assertEqual(p.assert_unchanged(ws), ["protected file modified: data.txt"])


class MonitorBudgetIntegrationTests(unittest.TestCase):
    """监控器与预算交互的测试：从日志提取统计量供预算归类使用。"""

    def test_monitor_extracts_active_train_seconds(self):
        # 可从日志行中提取总的「主动训练秒数」统计量。
        backend = LocalExecutionBackend(".")
        monitor = ExperimentMonitor(poll_interval=0, backend=backend)
        lines = ["Epoch 1/3", "validation_accuracy=0.99", "test_accuracy=0.98", "active_train_seconds=14.35"]
        self.assertEqual(monitor._extract_active_train_seconds(lines), 14.35)

    def test_monitor_extracts_split_metrics(self):
        # 可同时提取 train / validation / test 三组切分的指标。
        backend = LocalExecutionBackend(".")
        monitor = ExperimentMonitor(poll_interval=0, backend=backend)
        m = monitor._extract_metrics(["validation_accuracy=0.99", "test_accuracy=0.98", "train_accuracy=0.99"])
        self.assertEqual(m["validation_accuracy"], 0.99)
        self.assertEqual(m["test_accuracy"], 0.98)
        self.assertEqual(m["train_accuracy"], 0.99)


class ToolRegistryD0Tests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name) / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_write_denylisted_data_blocked(self):
        registry = ToolRegistry(LocalExecutionBackend(self.workspace))
        result = json.loads(
            registry.execute_tool("write_file", {"path": "data/x.txt", "content": "x"})
        )
        self.assertIn("error", result)
        self.assertIn("protected write boundary", result["error"])

    def test_write_ordinary_file_allowed(self):
        registry = ToolRegistry(LocalExecutionBackend(self.workspace))
        result = json.loads(
            registry.execute_tool("write_file", {"path": "note.txt", "content": "hello"})
        )
        self.assertEqual(result["status"], "written")

    def test_run_shell_rejects_shell_operator(self):
        registry = ToolRegistry(LocalExecutionBackend(self.workspace))
        result = json.loads(
            registry.execute_tool("run_shell", {"command": "echo a && echo b"})
        )
        self.assertIn("error", result)

    def test_launch_experiment_attaches_budget_facts(self):
        cfg = {"experiment": {"budget": {"mode": "active_wall_clock_seconds", "limit": 300, "hard_wall_clock_limit": 420}}}
        registry = ToolRegistry(LocalExecutionBackend(self.workspace), config=cfg)
        result = json.loads(
            registry.execute_tool(
                "launch_experiment",
                {"command": "python train.py", "log_file": "exp.log"},
            )
        )
        self.assertEqual(result["experiment_budget"]["limit"], 300.0)
        self.assertTrue(result["experiment_budget"]["enforced"])


if __name__ == "__main__":
    unittest.main()
