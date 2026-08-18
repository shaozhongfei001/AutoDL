"""
稳定性加固（stability-hardening）通过项 A+B+D+E 的测试：

  A. loguru 框架日志桥 + 结构化 ``RESULT {...}`` 指标提取
     （训练子进程把最终指标作为最后一行标准输出打印出来）。
  B. launch_experiment 参数鲁棒性：去除 ``cd`` 前缀、拒绝 shell 运算符、
     并自动补全 log_file。
  D. 会话级错误升级：ToolRegistry 对失败计数，一旦某工具持续失败，
     就注入一个 ``escalation`` 提示（以 ``<escalation>`` 块形式暴露）。
  E. 空指标诊断：一个完成但无指标可提取的运行，应得到结构化的
     ``metrics_diagnosis``，而不是一个静默的空字典。
"""

import tempfile
import unittest
from pathlib import Path

from core.execution import LocalExecutionBackend
from core.monitor import ExperimentMonitor
from core.tools import ToolRegistry


class ResultContractMetricTests(unittest.TestCase):
    """A：结构化 RESULT 指标提取。"""

    def test_result_line_beats_regex(self):
        # 当日志里存在 RESULT 结构行时，它应优先于正则抽取的 loss/accuracy。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = [
            "epoch 10/10 | loss: 1.2 | accuracy: 0.85",
            'RESULT {"validation_accuracy": 0.982, "test_accuracy": 0.979}',
        ]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.982)
        self.assertEqual(m["test_accuracy"], 0.979)
        # 结构化契约应覆盖掉正则抽取的 accuracy/loss。
        self.assertNotIn("accuracy", m)
        self.assertNotIn("loss", m)

    def test_last_result_wins(self):
        # 多条 RESULT 时以后出现者为准。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = [
            'RESULT {"validation_accuracy": 0.90}',
            'RESULT {"validation_accuracy": 0.92}',
        ]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.92)

    def test_invalid_result_ignored_and_regex_fallback(self):
        # RESULT 内容不是合法 JSON 时跳过，退回到正则提取。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = ["RESULT {not json", "validation_accuracy=0.77"]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["validation_accuracy"], 0.77)

    def test_regex_fallback_still_works_without_result(self):
        # 无 RESULT 行时，正则回退仍能提取 loss / acc。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        lines = ["epoch 5/20 | loss: 0.3 | acc: 0.94"]
        m = mon._extract_metrics(lines)
        self.assertEqual(m["accuracy"], "0.94")
        self.assertIn("epoch", m)


class EmptyMetricDiagnosisTests(unittest.TestCase):
    """E：完成但无任何指标时的结构化诊断。"""

    def test_missing_result_line(self):
        # 既没有 RESULT 也没有可正则解析的指标 -> result_missing。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        # 没有 RESULT 也没有可正则解析的指标 -> result_missing。
        d = mon._diagnose_empty_metrics(["training finished", "saving model..."])
        self.assertEqual(d["reason"], "result_missing")
        self.assertIn("RESULT", d["hint"])

    def test_parseable_regex_log_gives_no_diagnosis(self):
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        # 没有 RESULT 但可被正则解析（loss/epoch）仍视为真实指标，无需诊断。
        d = mon._diagnose_empty_metrics(["epoch 1/1 | loss 1.0"])
        self.assertEqual(d, {})

    def test_result_with_no_numeric(self):
        # 有 RESULT 但其内不含任何数值 -> result_no_numeric。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        d = mon._diagnose_empty_metrics(['RESULT {"note": "done"}'])
        self.assertEqual(d["reason"], "result_no_numeric")

    def test_log_unavailable(self):
        # 空日志（无任何内容）-> log_unavailable。
        mon = ExperimentMonitor(backend=LocalExecutionBackend("."))
        d = mon._diagnose_empty_metrics([])
        self.assertEqual(d["reason"], "log_unavailable")


class LaunchExperimentRobustnessTests(unittest.TestCase):
    """B：命令清洗（sanitize）+ log_file 自动补全。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = LocalExecutionBackend(Path(self.tmp.name))
        self.registry = ToolRegistry(self.backend, config={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_strips_leading_cd(self):
        # 去除命令首部的 `cd workspace && ` 前缀。
        argv = self.registry._sanitize_experiment_command(
            "cd workspace && python train.py --lr 0.1"
        )
        self.assertEqual(argv, ["python", "train.py", "--lr", "0.1"])

    def test_strips_cd_semicolon(self):
        # 使用分号分隔的 `cd /tmp;` 同样应被剥离。
        argv = self.registry._sanitize_experiment_command(
            "cd /tmp; python train.py"
        )
        self.assertEqual(argv, ["python", "train.py"])

    def test_rejects_shell_operator(self):
        # 命令中出现 shell 运算符时直接拒绝。
        with self.assertRaises(ValueError):
            self.registry._sanitize_experiment_command(
                "python train.py && echo done"
            )

    def test_rejects_bare_cd(self):
        # 一个孤立的 `cd workspace` 也被拒绝。
        with self.assertRaises(ValueError):
            self.registry._sanitize_experiment_command("cd workspace")

    def test_log_file_auto_completed(self):
        # 未指定日志时自动补全为 logs/exp_* 路径，并附带实验预算。
        out = self.registry._exec_launch_experiment("python train.py --epochs 1")
        import json
        payload = json.loads(out)
        self.assertTrue(payload["log_file"].startswith("logs/exp_"))
        self.assertIn("experiment_budget", payload)


class ErrorEscalationTests(unittest.TestCase):
    """D：会话级错误计数 + 升级提示。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = LocalExecutionBackend(Path(self.tmp.name))
        self.registry = ToolRegistry(self.backend, config={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_shell_escalation_after_two_failures(self):
        # 同一工具连续失败数次后，输出中应出现升级提示，建议改用 launch_experiment。
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
        # 一次成功调用应重置失败计数。
        for _ in range(2):
            self.registry.execute_tool("run_shell", {"command": "cd x && ls"})
        # 一次成功的调用重置了失败连击。
        self.registry.execute_tool("run_shell", {"command": "pwd"})
        out = self.registry.execute_tool("run_shell", {"command": "pwd"})
        import json
        self.assertNotIn("escalation", json.loads(out))

    def test_loguru_bridge_imports(self):
        # loguru 桥接应可被导入并配置。
        from core.logging_setup import configure_logging, _HAS_LOGURU
        configure_logging(level="INFO")
        self.assertTrue(_HAS_LOGURU)


if __name__ == "__main__":
    unittest.main()