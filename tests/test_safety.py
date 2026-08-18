import unittest

from core.safety import (
    check_hypothesis_dedup,
    escalate_no_progress,
    is_hypothesis_duplicate,
    normalize_hypothesis,
    prune_timestamps,
    scan_violations,
    seconds_until_allowed,
)


class ScanViolationsTests(unittest.TestCase):
    """对安全违规扫描（scan_violations）的测试：连续无进展与状态陈旧两类。"""

    def test_high_fail_count_flagged(self):
        # 连续失败超过阈值 -> 标记「consecutive no-progress」违规。
        viols = scan_violations({}, fail_count=3, now=1000.0, fail_threshold=3)
        self.assertEqual(len(viols), 1)
        self.assertIn("consecutive no-progress", viols[0])

    def test_below_threshold_not_flagged(self):
        # 失败数低于阈值不应被标记。
        self.assertEqual(scan_violations({}, fail_count=2, now=1000.0, fail_threshold=3), [])

    def test_stale_running_state_flagged(self):
        state = {"status": "running", "updated_at": 0.0}
        now = 7 * 3600  # 7 小时后
        viols = scan_violations(state, fail_count=0, now=now, stale_state_hours=6)
        self.assertEqual(len(viols), 1)
        self.assertIn("running", viols[0])

    def test_fresh_running_state_not_flagged(self):
        state = {"status": "running", "updated_at": 1000.0}
        viols = scan_violations(state, fail_count=0, now=1000.0 + 60, stale_state_hours=6)
        self.assertEqual(viols, [])

    def test_completed_state_not_flagged_for_staleness(self):
        state = {"status": "completed", "updated_at": 0.0}
        viols = scan_violations(state, fail_count=0, now=99 * 3600, stale_state_hours=6)
        self.assertEqual(viols, [])

    def test_non_dict_state_does_not_raise(self):
        for bad in ([1, 2, 3], "running", 42):
            self.assertEqual(scan_violations(bad, fail_count=0, now=1000.0), [])


class RateLimitTests(unittest.TestCase):
    """对限流（seconds_until_allowed / prune_timestamps）的测试。"""

    def test_disabled_returns_zero(self):
        # max_per_hour=0 表示限流关闭，应立即放行（等待 0 秒）。
        self.assertEqual(seconds_until_allowed([1, 2, 3], now=100, max_per_hour=0), 0.0)

    def test_under_budget_returns_zero(self):
        ts = [100.0, 200.0]
        self.assertEqual(seconds_until_allowed(ts, now=300.0, max_per_hour=6), 0.0)

    def test_over_budget_waits_until_oldest_rolls_off(self):
        # 6 次调用都发生在上一个小时内，最旧的一次在 now-3000s -> 需等待 600s。
        now = 10000.0
        ts = [now - 3000, now - 2500, now - 2000, now - 1500, now - 1000, now - 500]
        wait = seconds_until_allowed(ts, now=now, max_per_hour=6, window=3600)
        self.assertAlmostEqual(wait, 600.0)

    def test_over_budget_with_excess_waits_enough_to_get_under_cap(self):
        now = 10000.0
        # 窗口内共 8 次起始、上限 6：必须等到计数降到 6 以下才能放行。
        ts = [now - 3500, now - 3400, now - 3300, now - 1000, now - 800, now - 600, now - 400, now - 200]
        wait = seconds_until_allowed(ts, now=now, max_per_hour=6, window=3600)
        # 等待 `wait` 后重新计算窗口内计数，它必须小于 6。
        future = now + wait
        remaining = [t for t in ts if (future - t) < 3600]
        self.assertLess(len(remaining), 6)

    def test_old_timestamps_do_not_count(self):
        now = 10000.0
        ts = [now - 5000, now - 4000]  # 两者都早于 1 小时窗口
        self.assertEqual(seconds_until_allowed(ts, now=now, max_per_hour=1, window=3600), 0.0)

    def test_prune_timestamps(self):
        now = 10000.0
        ts = [now - 5000, now - 100, now - 50]
        self.assertEqual(prune_timestamps(ts, now=now, window=3600), [now - 100, now - 50])


class HypothesisDedupTests(unittest.TestCase):
    """对假设去重（normalize / is_hypothesis_duplicate / check_hypothesis_dedup）的测试。"""

    def test_normalize_hypothesis_stable(self):
        # 归一化应忽略大小写、多余空白与标点，保证等价输入得到一致结果。
        self.assertEqual(
            normalize_hypothesis("  Try LR 1e-3,  batch 32! "),
            normalize_hypothesis("try lr 1e-3 batch 32"),
        )

    def test_empty_hypothesis_normalizes_to_empty(self):
        self.assertEqual(normalize_hypothesis(None), "")
        self.assertEqual(normalize_hypothesis("  "), "")

    def test_novel_hypothesis_allowed(self):
        verdict = check_hypothesis_dedup("try lr 1e-3", [], repeated_hypothesis_limit=1)
        self.assertTrue(verdict["allowed"])
        self.assertEqual(verdict["reason"], "")

    def test_repeated_hypothesis_rejected(self):
        attempted = ["try lr 1e-3", "different thing"]
        verdict = check_hypothesis_dedup("Try LR 1e-3 !", attempted,
                                         repeated_hypothesis_limit=1)
        self.assertFalse(verdict["allowed"])
        self.assertIn("duplicate", verdict["reason"])

    def test_limit_of_two_allows_first_repeat(self):
        attempted = ["try lr 1e-3"]
        verdict = check_hypothesis_dedup("try lr 1e-3", attempted,
                                         repeated_hypothesis_limit=2)
        self.assertTrue(verdict["allowed"])

    def test_disabled_dedup_always_allows(self):
        verdict = check_hypothesis_dedup("x", ["x"], repeated_hypothesis_limit=0)
        self.assertTrue(verdict["allowed"])

    def test_is_duplicate_matches_set_input(self):
        self.assertTrue(is_hypothesis_duplicate("b", {"a", "b"}, repeated_hypothesis_limit=1))
        self.assertFalse(is_hypothesis_duplicate("c", {"a", "b"}, repeated_hypothesis_limit=1))


class NoProgressEscalationTests(unittest.TestCase):
    """无进展升级（escalate_no_progress）分级处置逻辑测试。"""

    def test_normal_below_threshold(self):
        # 连续无进展轮数低于阈值 -> 处于 normal（正常）级别。
        self.assertEqual(escalate_no_progress(0)["level"], "normal")
        self.assertEqual(escalate_no_progress(2, widen_threshold=3)["level"], "normal")

    def test_widen_at_low_streak(self):
        # 中等连续轮数 -> 升级为「扩大搜索空间」。
        decision = escalate_no_progress(4, widen_threshold=3,
                                        lower_target_threshold=6, terminate_threshold=10)
        self.assertEqual(decision["level"], "widen")
        self.assertIn("widen", decision["advice"].lower())

    def test_lower_target_at_mid_streak(self):
        # 更高连续轮数 -> 升级为「降低目标」。
        decision = escalate_no_progress(7, widen_threshold=3,
                                        lower_target_threshold=6, terminate_threshold=10)
        self.assertEqual(decision["level"], "lower_target")

    def test_terminate_at_high_streak(self):
        # 极高连续轮数 -> 强烈建议终止。
        decision = escalate_no_progress(11, widen_threshold=3,
                                        lower_target_threshold=6, terminate_threshold=10)
        self.assertEqual(decision["level"], "terminate")
        self.assertIn("terminat", decision["advice"].lower())

    def test_custom_thresholds(self):
        self.assertEqual(escalate_no_progress(2, widen_threshold=5)["level"], "normal")
        self.assertEqual(escalate_no_progress(5, widen_threshold=5)["level"], "widen")


if __name__ == "__main__":
    unittest.main()
