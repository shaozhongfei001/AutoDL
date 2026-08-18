import json
import os
import tempfile
import unittest
from pathlib import Path

from core.execution import LocalExecutionBackend
from core.tools import ToolRegistry


class RepoReadingToolTests(unittest.TestCase):
    """对仓库读取类工具（search_code / list_tree / read_file）的测试，含安全边界。"""

    def setUp(self):
        # 构造一个带源码与 README 的临时工作区，并放置 __pycache__ 干扰项。
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name) / "workspace"
        self.workspace.mkdir()
        (self.workspace / "src").mkdir()
        (self.workspace / "src" / "train.py").write_text(
            "import torch\n"
            "def main():\n"
            "    lr = 1e-3\n"
            "    return lr\n"
        )
        (self.workspace / "README.md").write_text("# Demo\nuses learning rate\n")
        (self.workspace / "__pycache__").mkdir()
        (self.workspace / "__pycache__" / "junk.txt").write_text("def main(): pass\n")
        self.registry = ToolRegistry(LocalExecutionBackend(self.workspace))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_search_code_finds_match_with_file_and_line(self):
        # search_code 能定位命中文件与行号。
        result = json.loads(self.registry.execute_tool("search_code", {"pattern": r"def main"}))
        self.assertEqual(result["count"], 1)
        hit = result["matches"][0]
        self.assertEqual(hit["file"], "src/train.py")
        self.assertEqual(hit["line"], 2)

    def test_search_code_skips_pycache(self):
        # 缓存目录 __pycache__ 应被搜索忽略。
        result = json.loads(self.registry.execute_tool("search_code", {"pattern": r"def main"}))
        files = {m["file"] for m in result["matches"]}
        self.assertNotIn("__pycache__/junk.txt", files)

    def test_search_code_ignore_case(self):
        # 开启 ignore_case 后应能命中大小写不同的内容。
        result = json.loads(
            self.registry.execute_tool("search_code", {"pattern": "LEARNING", "ignore_case": True})
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matches"][0]["file"], "README.md")

    def test_search_code_invalid_regex_returns_error(self):
        # 非法正则应返回错误而非抛异常。
        result = json.loads(self.registry.execute_tool("search_code", {"pattern": "("}))
        self.assertIn("error", result)
        self.assertIn("Invalid search pattern", result["error"])

    def test_search_code_rejects_path_traversal(self):
        # 路径穿越（../）必须被拒绝，保护工作区边界安全。
        result = json.loads(
            self.registry.execute_tool("search_code", {"pattern": "x", "path": "../"})
        )
        self.assertIn("error", result)
        self.assertIn("escapes workspace", result["error"])

    def test_list_tree_is_recursive_and_marks_dirs(self):
        # list_tree 递归列出目录并标记子目录，且忽略 __pycache__。
        result = json.loads(self.registry.execute_tool("list_tree", {}))
        tree = result["tree"]
        self.assertIn("src/", tree)
        self.assertIn("src/train.py", tree)
        self.assertNotIn("__pycache__/", tree)

    def test_list_tree_depth_limit(self):
        # max_depth 限制遍历层级。
        result = json.loads(self.registry.execute_tool("list_tree", {"max_depth": 1}))
        tree = result["tree"]
        self.assertIn("src/", tree)
        self.assertNotIn("src/train.py", tree)

    def test_read_file_range_returns_numbered_slice(self):
        # read_file 按 start_line/end_line 返回带行号的片段。
        out = self.registry.execute_tool("read_file", {"path": "src/train.py", "start_line": 2, "end_line": 3})
        self.assertIn("2\tdef main():", out)
        self.assertIn("3\t    lr = 1e-3", out)
        self.assertNotIn("import torch", out)

    def test_read_file_without_range_unchanged(self):
        # 不带范围的 read_file 应原样返回整个文件内容。
        out = self.registry.execute_tool("read_file", {"path": "README.md"})
        self.assertEqual(out, "# Demo\nuses learning rate\n")

    def test_list_tree_rejects_path_traversal(self):
        # list_tree 同样拒绝路径穿越。
        result = json.loads(self.registry.execute_tool("list_tree", {"path": ".."}))
        self.assertIn("error", result)
        self.assertIn("escapes workspace", result["error"])

    def test_list_tree_does_not_follow_symlink_outside_workspace(self):
        # 安全基线：list_tree 不得跟随指向工作区外的符号链接，防止泄露外部目录。
        outside = Path(self.tempdir.name) / "outside"
        (outside / "sub").mkdir(parents=True)
        (outside / "sub" / "secret.txt").write_text("TOPSECRET\n")
        os.symlink(outside, self.workspace / "leak")

        result = json.loads(self.registry.execute_tool("list_tree", {}))
        tree = result["tree"]
        self.assertNotIn("leak/", tree)
        self.assertFalse(any(entry.startswith("leak/") for entry in tree))

    def test_search_code_does_not_read_symlinked_external_file(self):
        # 安全基线：search_code 不得读取指向外部的符号链接文件，防止泄密。
        outside = Path(self.tempdir.name) / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "creds.txt").write_text("TOPSECRET token\n")
        os.symlink(outside / "creds.txt", self.workspace / "leak.txt")

        result = json.loads(self.registry.execute_tool("search_code", {"pattern": "TOPSECRET"}))
        files = {m["file"] for m in result["matches"]}
        self.assertNotIn("leak.txt", files)
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
