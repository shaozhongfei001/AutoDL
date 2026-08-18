"""
工具层安全测试：对 ToolRegistry 的各类工具做路径穿越、shell 注入、
破坏性 git 操作等安全边界验证。
"""

import json
import tempfile
import unittest
from pathlib import Path

from core.execution import LocalExecutionBackend
from core.tools import ToolRegistry


class RecordingBackend:
    """记录每次后端调用并返回占位结果的假后端，用于断言请求被拦截。"""

    def __init__(self):
        self.calls = []

    def read_file(self, path):
        self.calls.append(("read_file", path))
        return ""

    def write_file(self, path, content):
        self.calls.append(("write_file", path, content))
        return {"status": "written"}

    def list_files(self, path="."):
        self.calls.append(("list_files", path))
        return []

    def run_command(self, argv, timeout=120, env=None):
        self.calls.append(("run_command", argv, timeout, env))
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def launch_command(self, argv, log_file, env=None):
        self.calls.append(("launch_command", argv, log_file, env))
        return {"pid": 1, "log_file": log_file, "status": "launched"}


class ToolRegistrySecurityTests(unittest.TestCase):
    """对 ToolRegistry 各工具的安全边界测试。"""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tempdir.name) / "workspace"
        self.workspace.mkdir()
        self.registry = ToolRegistry(LocalExecutionBackend(self.workspace))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_write_file_rejects_path_traversal(self):
        # 写入路径穿越（../）必须被拒绝，且外部文件绝不能被创建。
        result = json.loads(
            self.registry.execute_tool("write_file", {"path": "../escape.txt", "content": "owned"})
        )
        self.assertIn("error", result)
        self.assertIn("escapes workspace", result["error"])
        self.assertFalse((self.workspace.parent / "escape.txt").exists())

    def test_read_file_rejects_absolute_path(self):
        # 读取绝对路径应被拒绝，且请求不应落到后端执行。
        backend = RecordingBackend()
        registry = ToolRegistry(backend)
        result = json.loads(registry.execute_tool("read_file", {"path": "/etc/hosts"}))
        self.assertIn("error", result)
        self.assertIn("relative to workspace", result["error"])
        self.assertEqual(backend.calls, [])   # 后端不应收到任何调用

    def test_list_files_rejects_parent_escape(self):
        # 列目录时禁止越过工作区（..）向上逃逸。
        result = json.loads(self.registry.execute_tool("list_files", {"path": ".."}))
        self.assertIn("error", result)
        self.assertIn("escapes workspace", result["error"])

    def test_run_shell_rejects_shell_operator_injection_payload(self):
        # D0：shell 运算符（; && | > ...）被直接拒绝，使注入载荷永远到不了 shell；
        # 命令返回显式错误，且任何后续命令都不被执行。
        result = json.loads(
            self.registry.execute_tool("run_shell", {"command": "echo hello; touch injected.txt"})
        )
        self.assertIn("error", result)
        self.assertIn("not allowed", result["error"])
        self.assertFalse((self.workspace / "injected.txt").exists())

    def test_run_shell_rejects_cd_prefix(self):
        # D0：`cd ... && ...` 是经典的失败形态；命令以工作区为 cwd，
        # 因此不需要 cd，其出现即被拒绝。
        result = json.loads(
            self.registry.execute_tool(
                "run_shell", {"command": "cd /tmp && echo hi"}
            )
        )
        self.assertIn("error", result)
        self.assertFalse((self.workspace / "injected.txt").exists())

    def test_run_shell_blocks_destructive_git(self):
        # 破坏性 git 操作（reset --hard）必须被拦截。
        result = json.loads(
            self.registry.execute_tool("run_shell", {"command": "git reset --hard"})
        )
        self.assertIn("error", result)
        self.assertIn("destructive git", result["error"])

    def test_run_shell_allows_readonly_git(self):
        # 只读 git 操作（git status）应被允许执行。
        result = json.loads(
            self.registry.execute_tool("run_shell", {"command": "git status"})
        )
        self.assertIn("returncode", result)

    def test_run_shell_blocks_dangerous_binaries(self):
        # 危险可执行文件（如 rm -rf）必须被拦截。
        result = json.loads(self.registry.execute_tool("run_shell", {"command": "rm -rf tmp"}))
        self.assertIn("error", result)
        self.assertIn("Blocked executable", result["error"])

    def test_launch_experiment_rejects_log_path_traversal(self):
        # 启动实验时，日志路径同样禁止穿越工作区。
        result = json.loads(
            self.registry.execute_tool(
                "launch_experiment",
                {
                    "command": 'python3 -c "print(\'hi\')"',
                    "log_file": "../outside.log",
                },
            )
        )
        self.assertIn("error", result)
        self.assertIn("escapes workspace", result["error"])


if __name__ == "__main__":
    unittest.main()