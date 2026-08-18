import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.loop import ResearchLoop


class ResearchLoopFallbackTests(unittest.TestCase):
    """ResearchLoop 的「无进展回退（fallback）」机制测试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.project_dir = Path(self.tempdir.name)
        (self.project_dir / "PROJECT_BRIEF.md").write_text("Test brief")
        self.loop = ResearchLoop(
            config={
                "project": {"workspace": "workspace"},
                "agent": {
                    "max_cycles": 1,
                    "cooldown_interval": 0,
                    "no_progress_fallback_threshold": 2,
                },
                "obsidian": {"enabled": False},
            },
            project_dir=str(self.project_dir),
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_run_resets_leader_history_each_cycle(self):
        # 每个 run 周期开始前都应重置领导者的历史，避免跨周期残留干扰。
        self.loop.dispatcher.reset_leader_history = Mock()
        self.loop._think = lambda directive=None: {"action": "wait", "reason": "idle"}
        self.loop._smart_cooldown = lambda: None

        self.loop.run()

        self.loop.dispatcher.reset_leader_history.assert_called_once()

    def test_repeated_no_progress_plan_triggers_wait_fallback(self):
        # 连续多次「计划发起实验但并未真正启动」时，应触发「等待」回退，避免空转重试。
        plan = {
            "action": "experiment",
            "agent": "code",
            "task": "Retry the same broken command",
            "hypothesis": "It might work this time",
        }
        execute_result = {"experiment_launched": False}   # 并未真正启动实验
        reflect_result = {}

        self.loop._record_cycle_outcome(plan, execute_result, reflect_result)
        self.loop._record_cycle_outcome(plan, execute_result, reflect_result)

        fallback = self.loop._apply_no_progress_fallback(plan, directive=None)

        self.assertEqual(fallback["action"], "wait")
        self.assertIn("Fallback triggered", fallback["reason"])


if __name__ == "__main__":
    unittest.main()
