"""
早期停止（Early-Stop）机制的测试用例，覆盖「循环层」与「训练/进程运行层」两级停止。

两类停止分别解决不同问题：
  1. 运行内（in-run，由监控器 monitor 负责）：逐个轮次解析训练日志中的验证集指标，
     一旦指标出现停滞（plateau）就提前终止训练子进程，从而节省 GPU 计算资源。
  2. 循环层（loop-level）：主动检测「搜索是否已饱和 / 领导者是否已停止进步」，
     让无人值守的 Agent 循环能够自行收敛，而不会无限空转直到被人工强制终止。
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
    """针对 _extract_epoch_metrics 与 _check_in_run_early_stop 两个方法的单元测试。"""

    def _mon(self, **es):
        # 构造一个开启早期停止的监控器配置；**es 允许测试用例覆盖默认参数
        #（如 patience、min_epochs、metric 等）。
        cfg = {"early_stop": {"enabled": True, "patience": 2,
                              "improvement_tol": 1e-4, "min_epochs": 3,
                              "metric": "validation_accuracy", **es}}
        return ExperimentMonitor(backend=LocalExecutionBackend("."), budget=cfg)

    def test_extract_from_legacy_lines(self):
        # 从形如 key=value 的旧式日志行中，逐行提取验证集准确率指标。
        mon = self._mon()
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.90",
                 "validation_accuracy=0.90"]
        self.assertEqual(mon._extract_epoch_metrics(lines, "validation_accuracy"),
                         [0.80, 0.90, 0.90])

    def test_extract_from_result_snapshots(self):
        # 从 RESULT JSON 快照行中提取指标，同样应得到按顺序排列的指标列表。
        mon = self._mon()
        lines = [
            'RESULT {"validation_accuracy": 0.80}',
            'RESULT {"validation_accuracy": 0.90}',
        ]
        self.assertEqual(mon._extract_epoch_metrics(lines, "validation_accuracy"),
                         [0.80, 0.90])

    def test_no_early_stop_before_min_epochs(self):
        # 尚未达到最低轮数 min_epochs 之前，即使指标连续不变也绝不可提前停止。
        mon = self._mon(min_epochs=5)
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.80"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_early_stop_on_plateau(self):
        # 指标先升到最优（0.80 -> 0.90），随后连续 2 轮停在 0.90 不再进步，应触发停止。
        mon = self._mon(patience=2, min_epochs=3)
        # 0.80 -> 0.90（当前最优），然后在 0.90 上停滞了 2 轮。
        lines = ["validation_accuracy=0.80", "validation_accuracy=0.90",
                 "validation_accuracy=0.90"]
        self.assertTrue(mon._check_in_run_early_stop(999, lines))

    def test_no_early_stop_while_improving(self):
        # 指标仍在持续进步（0.70 -> 0.80 -> 0.90），此时不应触发停止。
        mon = self._mon(patience=2, min_epochs=3)
        lines = ["validation_accuracy=0.70", "validation_accuracy=0.80",
                 "validation_accuracy=0.90"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_disabled_is_noop(self):
        # 当早期停止被显式禁用（enabled=False）时，该逻辑应完全不生效（no-op）。
        mon = self._mon(enabled=False)
        lines = ["validation_accuracy=0.90", "validation_accuracy=0.90"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))

    def test_lower_better_loss_plateau(self):
        # loss 先下降后持平 -> 应在持平的尾部触发早期停止（方向为越小越好）。
        mon = self._mon(direction="lower_better", metric="validation_loss",
                        patience=2, min_epochs=3)
        lines = ["validation_loss=1.20", "validation_loss=0.80",
                 "validation_loss=0.80"]
        self.assertTrue(mon._check_in_run_early_stop(999, lines))

    def test_lower_better_still_dropping_no_stop(self):
        # loss 处于「越小越好」方向且仍在持续下降时，不应触发早期停止。
        mon = self._mon(direction="lower_better", metric="validation_loss",
                        patience=2, min_epochs=3)
        lines = ["validation_loss=1.50", "validation_loss=0.80",
                 "validation_loss=0.40"]
        self.assertFalse(mon._check_in_run_early_stop(999, lines))


class InRunEarlyStopEndToEndTests(unittest.TestCase):
    """端到端测试：真实的训练子进程在指标停滞后会早早被提前终止。"""

    def test_monitor_terminates_plateaued_run(self):
        # 脚本先打印出一段上升的验证指标，随后进入漫长的停滞区；自带运行内早期停止
        # 的监控器应当在它自然跑完之前就将其终止，以节省时间与 GPU。
        tmp = Path(tempfile.mkdtemp())
        backend = LocalExecutionBackend(tmp)
        # 该脚本先打印上升的验证指标，再陷入长期停滞；开启运行内早期停止的监控器
        # 应当远远早于它自然结束就先把它杀掉。
        (tmp / "train_plateau.py").write_text(
            "import time\n"
            "print('validation_accuracy=0.80')\n"
            "time.sleep(0.3)\n"
            "print('validation_accuracy=0.90')\n"
            "time.sleep(0.3)\n"
            "for _ in range(30):\n"      # 停滞 30 轮，大约 9 秒
            "    print('validation_accuracy=0.90')\n"
            "    time.sleep(0.3)\n"
            "print('finished normally')\n"
        )
        # 预算配置：启用基于墙上时钟的主动限制，并打开运行内早期停止。
        es = {"mode": "active_wall_clock_seconds", "limit": 60,
              "hard_wall_clock_limit": 60, "enforced": True,
              "early_stop": {"enabled": True, "patience": 2,
                             "improvement_tol": 1e-4, "min_epochs": 3,
                             "metric": "validation_accuracy"}}
        mon = ExperimentMonitor(backend=backend, poll_interval=0.1, budget=es)
        reg = ToolRegistry(backend, config={})
        # 启动训练子进程，并取得它的 pid 与日志文件路径。
        payload = json.loads(reg._exec_launch_experiment(
            "python train_plateau.py"))
        started = time.time()
        res = mon.wait_for_completion(payload["pid"], payload["log_file"],
                                      notify=False)
        elapsed = time.time() - started
        self.assertTrue(res["early_stopped"],
                        f"expected early_stopped, got {res}")
        # 30*0.3 = 9 秒的停滞区应当被压缩到约 1~2 秒。
        self.assertLess(elapsed, 6.0,
                        f"early stop was too slow: {elapsed:.1f}s")
        self.assertEqual(res["contract_status"], "SUCCESS")
        # 即便被提前终止，指标仍应被成功提取（取停滞区的最终准确率）。
        self.assertAlmostEqual(res["metrics"].get("validation_accuracy"), 0.90,
                               places=1)


class LoopLevelEarlyStopTests(unittest.TestCase):
    """针对 _early_stop_reason 触发条件的测试（领导者停滞 + 搜索饱和）。"""

    def _make_loop(self, **es):
        # 构建一个开启循环工程配置的 ResearchLoop 实例；**es 用于覆盖早期停止相关参数。
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
        # 连续多轮都没有真正发起实验（领导者停滞），应触发早期停止。
        loop = self._make_loop(max_consecutive_no_experiment=3)
        # 连续 3 轮都没有发起实验。
        think = {"action": "report"}
        for _ in range(2):
            self.assertEqual(loop._early_stop_reason(think, {}), "")
        reason = loop._early_stop_reason(think, {})
        self.assertIn("early-stop", reason)
        self.assertIn("no experiment", reason)

    def test_experiment_resets_stagnation(self):
        # 一旦真正发起一次实验，之前累积的停滞计数就应当被重置归零。
        loop = self._make_loop(max_consecutive_no_experiment=3)
        think = {"action": "report"}
        loop._early_stop_reason(think, {})
        loop._early_stop_reason(think, {})
        # 发起一次真实实验会重置计数器。
        loop._early_stop_reason({"action": "experiment"}, {"experiment_launched": True})
        self.assertEqual(loop._early_stop_reason(think, {}), "")

    def test_saturation_trigger(self):
        # 多轮判决的增量都落在噪声带内（搜索陷入停滞），应判定为「搜索已饱和」。
        loop = self._make_loop(saturation_rounds=3, plateau_band=2.0)
        # 强制让一个冠军（champion）存在。
        loop._recent_verdicts = [
            {"verdict": "DISCARD", "delta": 0.001, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": -0.0005, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.0002, "noise_std": 0.0018},
        ]
        # 通过打补丁（monkey-patch）让 champion 存在，从而 has_champion 为真。
        loop._resolve_champion_metrics = lambda: {"validation_accuracy": 0.99}
        reason = loop._early_stop_reason({"action": "experiment"}, {})
        self.assertIn("saturated", reason)

    def test_no_saturation_if_improving(self):
        # 各轮增量的幅度明显超出噪声带（仍在显著进步），不应判定为饱和。
        loop = self._make_loop(saturation_rounds=3, plateau_band=2.0)
        loop._recent_verdicts = [
            {"verdict": "DISCARD", "delta": 0.05, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.02, "noise_std": 0.0018},
            {"verdict": "DISCARD", "delta": 0.01, "noise_std": 0.0018},
        ]
        loop._resolve_champion_metrics = lambda: {"validation_accuracy": 0.99}
        # 增量明显超出噪声带 -> 并非停滞 -> 应继续搜索而不是停止。
        self.assertEqual(loop._early_stop_reason({"action": "experiment"}, {}), "")

    def test_disabled_is_noop(self):
        # 早期停止被显式禁用时，该逻辑完全不生效。
        loop = self._make_loop(enabled=False)
        self.assertEqual(loop._early_stop_reason({"action": "report"}, {}), "")


if __name__ == "__main__":
    unittest.main()