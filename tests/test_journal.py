import tempfile
import unittest
from pathlib import Path

from core.journal import ResearchJournal


class ResearchJournalTests(unittest.TestCase):
    """研究日志（ResearchJournal）单元测试：追加、读取尾部、容错与滚动归档。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_append_and_tail(self):
        # 追加「死路 / 洞察」两类条目后，应能正确读取其带时间戳的尾部内容。
        journal = ResearchJournal(self.workspace)
        journal.append_dead_end("ResNet-50 overfits badly here", ts="2026-06-01 10:00")
        journal.append_insight("lr warmup stabilizes the first 500 steps", ts="2026-06-01 10:05")

        de = journal.dead_ends_tail(1500)
        ins = journal.insights_tail(1500)
        self.assertIn("ResNet-50 overfits", de)
        self.assertIn("- [2026-06-01 10:00]", de)
        self.assertIn("lr warmup stabilizes", ins)

    def test_empty_entries_ignored(self):
        # 空白内容不应被记入死路列表。
        journal = ResearchJournal(self.workspace)
        journal.append_dead_end("   ")
        self.assertNotIn("- [", journal.dead_ends_tail(1500))

    def test_tail_tolerates_string_max_chars(self):
        journal = ResearchJournal(self.workspace)
        journal.append_dead_end("something failed")
        # 来自 YAML 引号配置的 max_chars 会以字符串形式传入，tail 必须容忍而不抛异常。
        self.assertIn("something failed", journal.dead_ends.tail("1500"))

    def test_tail_on_unreadable_path_returns_empty(self):
        journal = ResearchJournal(self.workspace)
        # 把日志文件替换成目录，使 read_text 抛 IsADirectoryError，验证容错返回空串。
        path = self.workspace / "INSIGHTS.md"
        path.unlink()
        path.mkdir()
        self.assertEqual(journal.insights.tail(1500), "")

    def test_rotation_creates_backup_and_keeps_header(self):
        # 日志超长时滚动，旧内容应归档到 .bak，且活动文件仍保留表头与最近条目。
        journal = ResearchJournal(self.workspace, max_chars=200)
        for i in range(40):
            journal.append_dead_end(f"failed approach number {i} with a long description", ts="2026-06-01 10:00")

        dead_ends_path = self.workspace / "DEAD_ENDS.md"
        content = dead_ends_path.read_text()
        self.assertTrue(content.startswith("# Dead Ends"))
        backups = list(self.workspace.glob("DEAD_ENDS.*.bak"))
        self.assertTrue(backups, "rotation should have produced a .bak archive")
        # 最近的条目应存活在活动文件中。
        self.assertIn("number 39", content)


if __name__ == "__main__":
    unittest.main()
