"""
执行后端（Execution Backend）单元测试。

覆盖三种后端：本地（Local）、SSH 远程、Slurm 调度，以及公共工厂函数
build_execution_backend 与两类依赖后端的组件：监控器（ExperimentMonitor）
与进度仪表盘导出器（SnapshotExporter）。核心验证点包括：

  - 工厂函数能根据不同配置构建出正确的后端类型；
  - 内嵌的 REMOTE_HELPER 脚本具备符号链接逃逸防护（安全约束）；
  - Slurm 任务的提交、存活判定、终态与取消流程符合预期，且状态映射
    PENDING/RUNNING/COMPLETED/TIMEOUT 等与调度器语义一致；
  - 监控器与仪表盘统一经由后端抽象读取进程/日志/GPU 状态，而非直接操作本地进程。
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.execution import (
    LocalExecutionBackend,
    REMOTE_HELPER,
    SSHExecutionBackend,
    SlurmExecutionBackend,
    build_execution_backend,
    _parse_slurm_time_seconds,
    _SLURM_RUNNING_STATES,
    _SLURM_OK_STATES,
    _SLURM_FAIL_STATES,
)
from core.monitor import ExperimentMonitor
from core.snapshots import SnapshotExporter
from core.memory import MemoryManager


class _Completed:
    """模拟 subprocess.CompletedProcess 的最小辅助类，便于伪造子进程执行结果。"""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeBackend:
    """内存中的假后端（Fake）：记录每次方法调用，并按预置序列返回结果。"""

    def __init__(self, alive=None, tail=None, gpu=None, final=None):
        self.alive = list(alive or [])   # 依次弹出的存活判定结果
        self.tail = list(tail or [])     # 依次返回的日志尾部内容
        self.gpu = gpu or {"utilization": "N/A"}
        self.final = final or {"state": "unknown", "success": None}
        self.calls = []                  # 记录所有方法调用（含参数），供断言使用

    def validate(self):
        self.calls.append(("validate",))

    def read_file(self, path):
        self.calls.append(("read_file", path))
        return ""

    def write_file(self, path, content):
        self.calls.append(("write_file", path, content))
        return {"status": "written", "path": path, "bytes": len(content)}

    def list_files(self, path="."):
        self.calls.append(("list_files", path))
        return []

    def run_command(self, argv, timeout=120, env=None):
        self.calls.append(("run_command", argv, timeout, env))
        return {"stdout": "", "stderr": "", "returncode": 0}

    def launch_command(self, argv, log_file, env=None):
        self.calls.append(("launch_command", argv, log_file, env))
        return {"pid": 123, "log_file": log_file, "status": "launched"}

    def is_process_alive(self, pid):
        self.calls.append(("is_process_alive", pid))
        if self.alive:
            return self.alive.pop(0)   # 从序列头部弹出下一次要返回的存活结果
        return False

    def tail_file(self, path, lines=50):
        self.calls.append(("tail_file", path, lines))
        if self.tail:
            return self.tail.pop(0)    # 从序列头部弹出下一次要返回的日志内容
        return []

    def get_gpu_status(self):
        self.calls.append(("get_gpu_status",))
        return self.gpu

    def final_status(self, pid):
        self.calls.append(("final_status", pid))
        return self.final


class BuildExecutionBackendTests(unittest.TestCase):
    """验证 build_execution_backend 工厂函数的分支选择逻辑。"""

    def test_build_local_backend_by_default(self):
        # 未指定 execution.mode 时，默认应构建本地后端。
        backend = build_execution_backend(config={}, controller_workspace=Path("/tmp/workspace"))
        self.assertIsInstance(backend, LocalExecutionBackend)

    def test_build_ssh_backend(self):
        # 指定 mode=ssh 时，应构建 SSH 后端并透传主机与远端工作区配置。
        backend = build_execution_backend(
            config={
                "execution": {
                    "mode": "ssh",
                    "ssh_host": "user@example.com",
                    "remote_workspace": "/remote/ws",
                }
            },
            controller_workspace=Path("/tmp/workspace"),
        )
        self.assertIsInstance(backend, SSHExecutionBackend)
        self.assertEqual(backend.ssh_host, "user@example.com")
        self.assertEqual(backend.remote_workspace, "/remote/ws")

    def test_unknown_mode_raises(self):
        # 传入未知的 mode 时，应抛出 ValueError。
        with self.assertRaises(ValueError):
            build_execution_backend(
                config={"execution": {"mode": "bogus"}},
                controller_workspace=Path("/tmp/workspace"),
            )


class SSHExecutionBackendTests(unittest.TestCase):
    """验证 SSH 后端以及其内嵌的 REMOTE_HELPER 脚本行为。"""

    def test_remote_helper_rejects_symlink_escape(self):
        # 安全基线：即使工作区内存在指向外部的符号链接，helper 也绝不允许借此
        # 把文件写到工作区之外（路径穿越防护）。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            os.symlink(outside, root / "escape")   # 在工作区内创建一个指向外部的软链

            payload = {
                "action": "write_file",
                "remote_workspace": str(root),
                "path": "escape/pwned.txt",
                "content": "x",
            }
            proc = subprocess.run(
                ["python3", "-c", REMOTE_HELPER],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(proc.returncode, 0)
            body = json.loads(proc.stdout)
            self.assertFalse(body["ok"])
            self.assertIn("escapes workspace", body["error"])
            self.assertFalse((outside / "pwned.txt").exists())   # 外部目标绝不能被写入

    def _run_helper(self, payload):
        # 以子进程方式调用内嵌 helper 的公共入口，返回 helper 输出的 JSON 对象。
        proc = subprocess.run(
            ["python3", "-c", REMOTE_HELPER],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_remote_helper_grep_tree_and_range(self):
        # 验证 helper 的目录列举、grep 检索与按行范围读取三大基础能力。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            (root / "pkg").mkdir(parents=True)
            (root / "pkg" / "m.py").write_text("def main():\n    return 1\n")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.py").write_text("def main(): pass\n")

            tree = self._run_helper(
                {"action": "list_tree", "remote_workspace": str(root), "path": "."}
            )
            self.assertTrue(tree["ok"])
            self.assertIn("pkg/", tree["result"]["entries"])
            self.assertIn("pkg/m.py", tree["result"]["entries"])
            self.assertNotIn("__pycache__/", tree["result"]["entries"])   # 应忽略缓存目录

            grep = self._run_helper(
                {"action": "grep_files", "remote_workspace": str(root), "pattern": "def main"}
            )
            self.assertTrue(grep["ok"])
            files = {h["file"] for h in grep["result"]["hits"]}
            self.assertEqual(files, {"pkg/m.py"})
            self.assertEqual(grep["result"]["hits"][0]["line"], 1)   # 命中所在行号

            ranged = self._run_helper(
                {
                    "action": "read_file_range",
                    "remote_workspace": str(root),
                    "path": "pkg/m.py",
                    "start_line": 2,
                    "end_line": 2,
                }
            )
            self.assertTrue(ranged["ok"])
            self.assertEqual(ranged["result"]["content"], "2\t    return 1")   # 带行号前缀

    def test_remote_helper_walk_and_grep_skip_symlinks(self):
        # 安全基线：目录遍历与 grep 检索都必须跳过符号链接，防止泄露外部敏感文件。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            outside = Path(tmp) / "outside"
            (outside / "sub").mkdir(parents=True)
            (outside / "creds.txt").write_text("TOPSECRET token\n")   # 外部敏感文件
            os.symlink(outside, root / "leakdir")                     # 指向外部目录的软链
            os.symlink(outside / "creds.txt", root / "leak.txt")      # 指向外部文件的软链

            tree = self._run_helper({"action": "list_tree", "remote_workspace": str(root), "path": "."})
            self.assertTrue(tree["ok"])
            self.assertNotIn("leakdir/", tree["result"]["entries"])   # 不应遍历到软链目录
            self.assertNotIn("leak.txt", tree["result"]["entries"])   # 不应列出软链文件

            grep = self._run_helper(
                {"action": "grep_files", "remote_workspace": str(root), "pattern": "TOPSECRET"}
            )
            self.assertTrue(grep["ok"])
            self.assertEqual(grep["result"]["hits"], [])              # 不应检索到外部机密

    @patch("core.execution.shutil.which", return_value="/usr/bin/ssh")
    @patch("core.execution.subprocess.run")
    def test_validate_invokes_remote_helper(self, run_mock, _which_mock):
        # 验证 validate 发出的 ssh 命令形态：ssh + 通过 -c 内嵌的 python helper。
        run_mock.return_value = _Completed(stdout=json.dumps({"ok": True, "result": {"status": "ok"}}))
        backend = SSHExecutionBackend(
            ssh_host="user@example.com",
            remote_workspace="/remote/ws",
            remote_python="python3",
            ssh_args=["-p", "2222"],
        )

        backend.validate()

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][:4], ["ssh", "-p", "2222", "user@example.com"])
        self.assertIn("python3 -c", args[0][4])
        self.assertNotIn("import json", args[0][4])   # helper 源码不展开到命令行
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload["action"], "validate")
        self.assertEqual(payload["remote_workspace"], "/remote/ws")
        self.assertIn("timeout", kwargs)
        self.assertFalse(kwargs["check"])

    @patch("core.execution.subprocess.run")
    def test_run_command_uses_json_stdin_and_no_shell(self, run_mock):
        # 远程执行命令：参数经 base64 传给 helper，且不使用 shell，规避注入风险。
        run_mock.return_value = _Completed(
            stdout=json.dumps({"ok": True, "result": {"stdout": "hi", "stderr": "", "returncode": 0}})
        )
        backend = SSHExecutionBackend("user@example.com", "/remote/ws")

        result = backend.run_command(["python", "train.py"], timeout=42, env={"CUDA_VISIBLE_DEVICES": "0"})

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "ssh")
        self.assertIn("base64", args[0][-1])   # argv 经 base64 传递
        self.assertNotIn("shell", kwargs)      # 必须是 shell=False
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload["action"], "run_command")
        self.assertEqual(payload["argv"], ["python", "train.py"])
        self.assertEqual(payload["timeout_seconds"], 42)
        self.assertEqual(payload["env"]["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(result["stdout"], "hi")

    @patch("core.execution.subprocess.run")
    def test_remote_file_not_found_maps_to_python_exception(self, run_mock):
        # 远端读不到文件时，helper 报告 FileNotFoundError，后端把它映射为本地异常。
        run_mock.return_value = _Completed(
            stdout=json.dumps({"ok": False, "error_type": "FileNotFoundError", "error": "File not found: x.txt"})
        )
        backend = SSHExecutionBackend("user@example.com", "/remote/ws")

        with self.assertRaises(FileNotFoundError):
            backend.read_file("x.txt")


class MonitorAndObsidianBackendTests(unittest.TestCase):
    """验证监控器与进度快照导出器如何通过后端抽象协作。"""

    def test_monitor_uses_backend_for_pid_log_and_gpu(self):
        # 监控器应通过后端的 is_process_alive / tail_file / get_gpu_status 工作，
        # 而不是直接访问本地进程，从而兼容本地、SSH、Slurm 三种后端。
        backend = FakeBackend(
            alive=[True, False],
            tail=[["epoch 1"], ["epoch 1", "epoch 2 accuracy: 0.9"]],
            gpu={"utilization": "88%"},
        )
        monitor = ExperimentMonitor(poll_interval=0, backend=backend)
        monitor._active_experiments[123] = {"start_time": time.time(), "status": "running"}

        with patch("core.monitor.time.sleep", return_value=None):
            result = monitor.wait_for_completion(pid=123, log_file="logs/exp.log", notify=False)

        self.assertEqual(result["status"], "completed")
        self.assertIn("epoch 2", result["log_tail"])
        self.assertIn(("get_gpu_status",), backend.calls)
        self.assertIn(("tail_file", "logs/exp.log", 5), backend.calls)
        self.assertIn(("tail_file", "logs/exp.log", 50), backend.calls)

    def test_monitor_reports_failed_from_backend_final_status(self):
        # 后端报告失败终态时，监控器必须返回状态 "failed"，而不能静默当作 "completed"。
        backend = FakeBackend(
            alive=[True, False],
            tail=[["epoch 1"], ["epoch 1", "Traceback: boom"]],
            final={"state": "FAILED", "success": False},
        )
        monitor = ExperimentMonitor(poll_interval=0, backend=backend)
        monitor._active_experiments[7] = {"start_time": time.time(), "status": "running"}

        with patch("core.monitor.time.sleep", return_value=None):
            result = monitor.wait_for_completion(pid=7, log_file="logs/exp.log", notify=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["terminal_state"], "FAILED")
        self.assertFalse(result["success"])
        self.assertIn(("final_status", 7), backend.calls)

    def test_obsidian_dashboard_reads_remote_status_via_backend(self):
        # Obsidian 仪表盘应经由后端读取远端运行状态（活存 + 日志尾部），渲染报表。
        backend = FakeBackend(alive=[True], tail=[["remote epoch 7"]])
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "PROJECT_BRIEF.md").write_text("Train model")
            workspace = project_dir / "workspace"
            workspace.mkdir()
            (workspace / "state.json").write_text(
                json.dumps(
                    {
                        "status": "running",
                        "pid": 321,
                        "log_file": "logs/exp.log",
                        "started_at": time.time(),
                    }
                )
            )
            memory = MemoryManager(project_dir=project_dir)
            exporter = SnapshotExporter(
                config={"obsidian": {"enabled": True}},
                project_dir=project_dir,
                backend=backend,
            )

            result = exporter.refresh_dashboard(memory=memory, cycle_count=2)
            dashboard = Path(result["path"]).read_text()

        self.assertIn("TRAINING (PID 321", dashboard)
        self.assertIn("remote epoch 7", dashboard)
        self.assertIn(("is_process_alive", 321), backend.calls)
        self.assertIn(("tail_file", "logs/exp.log", 8), backend.calls)

    def test_obsidian_status_surfaces_failure(self):
        # 失败的运行绝不能渲染成 IDLE，必须明确展示失败态。
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "PROJECT_BRIEF.md").write_text("Train model")
            (project_dir / "workspace").mkdir()
            exporter = SnapshotExporter(
                config={"obsidian": {"enabled": True}},
                project_dir=project_dir,
                backend=FakeBackend(),
            )
        self.assertEqual(
            exporter._format_status({"status": "failed", "terminal_state": "TIMEOUT"}),
            "FAILED (TIMEOUT)",
        )
        self.assertEqual(exporter._format_status({"status": "failed"}), "FAILED")
        self.assertEqual(exporter._format_status({"status": "no_pid"}), "FAILED (no PID)")
        self.assertEqual(exporter._format_status({"status": "completed"}), "COMPLETED")


class SlurmExecutionBackendTests(unittest.TestCase):
    """验证 Slurm 调度后端：构建、校验、提交、存活判定、终态与取消流程。"""

    LOGIN = "user@login-node"   # 统一使用的登录节点主机名

    def _backend(self, **kw):
        # 构造一个带默认配置的 Slurm 后端，允许 kw 覆盖关键参数（分区、时长、GPU 数等）。
        defaults = dict(
            ssh_host=self.LOGIN,
            remote_workspace="/nfs/ws",
            slurm_partition="gpu",
            slurm_time="24:00:00",
            slurm_gpus_per_job=1,
        )
        defaults.update(kw)
        return SlurmExecutionBackend(**defaults)

    # --- 工厂构建 + 校验 ---

    def test_factory_builds_slurm_backend(self):
        # 工厂函数能根据 mode=slurm 正确构建 Slurm 后端并透传调度参数。
        backend = build_execution_backend(
            config={
                "execution": {
                    "mode": "slurm",
                    "ssh_host": self.LOGIN,
                    "remote_workspace": "/nfs/ws",
                    "slurm_partition": "gpu-h200",
                    "slurm_time": "12:00:00",
                    "slurm_gpus_per_job": 2,
                    "ssh_args": ["-p", "2222"],
                }
            },
            controller_workspace=Path("/tmp/workspace"),
        )
        self.assertIsInstance(backend, SlurmExecutionBackend)
        self.assertEqual(backend.slurm_partition, "gpu-h200")
        self.assertEqual(backend.slurm_time, "12:00:00")
        self.assertEqual(backend.slurm_gpus_per_job, 2)
        self.assertEqual(backend.ssh_args, ["-p", "2222"])

    def test_unknown_mode_message_lists_slurm(self):
        # 未知 mode 的报错信息中应列出所有受支持取值（含 slurm）。
        with self.assertRaisesRegex(ValueError, "local, ssh, slurm"):
            build_execution_backend(
                config={"execution": {"mode": "bogus"}},
                controller_workspace=Path("/tmp/workspace"),
            )

    def test_validate_requires_partition_and_time(self):
        # 缺少分区或时长时应提前抛错，且不发起任何 ssh 往返。
        with self.assertRaisesRegex(ValueError, "slurm_partition is required"):
            self._backend(slurm_partition="").validate()
        with self.assertRaisesRegex(ValueError, "slurm_time is required"):
            self._backend(slurm_time="").validate()

    # --- 提交（提交后即返回作业号）---

    @patch("core.execution.subprocess.run")
    def test_launch_submits_and_parses_job_id(self, run_mock):
        # 任务提交应解析出 Slurm 作业号，并保持在设置好的环境变量中传递。
        run_mock.return_value = _Completed(
            stdout=json.dumps(
                {"ok": True, "result": {"slurm_job_id": 12345, "log_file": "logs/exp.log"}}
            )
        )
        backend = self._backend(slurm_gpus_per_job=2)

        result = backend.launch_command(
            ["python", "train.py"],
            "logs/exp.log",
            env={"CUDA_VISIBLE_DEVICES": "3", "FOO": "bar"},
        )

        self.assertEqual(result["pid"], 12345)
        self.assertEqual(result["slurm_job_id"], 12345)
        self.assertEqual(result["status"], "submitted")

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "ssh")            # 传输层是 ssh，不使用本地 shell
        self.assertNotIn("shell", kwargs)
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload["action"], "submit_slurm")
        self.assertEqual(payload["argv"], ["python", "train.py"])
        self.assertEqual(payload["partition"], "gpu")
        self.assertEqual(payload["gres"], 2)
        self.assertEqual(payload["env"]["FOO"], "bar")  # CUDA 掩码交给远端 helper 处理

    @patch("core.execution.subprocess.run")
    def test_launch_failure_raises(self, run_mock):
        # 提交失败（如分区非法）应抛出 RuntimeError。
        run_mock.return_value = _Completed(
            stdout=json.dumps(
                {"ok": False, "error_type": "RuntimeError",
                 "error": "sbatch: error: invalid partition specified"}
            )
        )
        with self.assertRaises(RuntimeError):
            self._backend().launch_command(["python", "t.py"], "logs/exp.log")

    # --- 存活判定：sacct 状态映射 + 防悬挂边界 ---

    def _alive_with_state(self, sacct_stdout):
        # 给定一条 sacct 状态输出，返回 is_process_alive 的判定结果，供状态映射测试复用。
        backend = self._backend()
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout=sacct_stdout)):
            return backend.is_process_alive(12345)

    def test_is_alive_state_map(self):
        # 用状态映射表本身逐项驱动枚举的状态：凡是被从相应分组里误删的状态
        #（例如把 COMPLETING 从运行组移走）都会在这里触发回归报警。
        for state in _SLURM_RUNNING_STATES:
            self.assertTrue(self._alive_with_state(state + "\n"), state)
        for state in _SLURM_OK_STATES:
            self.assertFalse(self._alive_with_state(state + "\n"), state)
        for state in _SLURM_FAIL_STATES:
            self.assertFalse(self._alive_with_state(state + "\n"), state)
        # 归一化边界 + 一个非失败的不确定状态。
        self.assertFalse(self._alive_with_state("CANCELLED+\n"))          # 去除 '+' 后缀
        self.assertFalse(self._alive_with_state("CANCELLED by 1001\n"))   # 去除 ' by <uid>' 后缀
        # PREEMPTED 不属于失败态 -> 判为不确定 -> 在首个宽限探测中保持存活
        self.assertTrue(self._alive_with_state("PREEMPTED\n"))

    def test_is_alive_sacct_nonzero_rc_is_unknown_grace(self):
        # sacct 非零退出（瞬时记账错误）-> 判为不确定而不是死亡：在有限的宽限窗口内保持存活。
        backend = self._backend(slurm_unknown_grace_polls=2)
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="", returncode=1)):
            self.assertEqual([backend.is_process_alive(555) for _ in range(3)], [True, True, False])

    def test_is_alive_ssh_failure_is_unknown_grace(self):
        # ssh 超时 -> 判为不确定，而不是死亡。
        backend = self._backend(slurm_unknown_grace_polls=2)
        with patch.object(backend, "_ssh_shell",
                          side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=15)):
            self.assertEqual([backend.is_process_alive(556) for _ in range(3)], [True, True, False])

    def test_is_alive_pending_never_reaped_by_wallclock(self):
        # sacct 仍上报 PENDING 的任务，即使远远超出 --time + buffer 也不得被回收
        #（排队等待时长不受 --time 上限约束）。
        backend = self._backend(slurm_time="00:01:00", slurm_time_buffer=0)  # 60 秒上限
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="PENDING\n")):
            with patch("core.execution.time.time", side_effect=[1000.0, 1000.0 + 100000]):
                self.assertTrue(backend.is_process_alive(99))   # 首次探测
                self.assertTrue(backend.is_process_alive(99))   # 10 万秒后仍在 PENDING

    def test_is_alive_unknown_is_bounded(self):
        """回归防护：已消失或不可达的任务绝不能永久悬挂。"""
        backend = self._backend(slurm_unknown_grace_polls=3)
        # sacct 与 squeue 每次探测都为空 -> 每次都判为 'unknown'。
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="")):
            results = [backend.is_process_alive(777) for _ in range(4)]
        self.assertEqual(results, [True, True, True, False])

    @patch("core.execution.time.time")
    def test_is_alive_wallclock_cap(self, time_mock):
        backend = self._backend(slurm_time="00:01:00", slurm_time_buffer=0)  # 60 秒上限
        time_mock.side_effect = [1000.0, 1000.0 + 120]  # 首次播种；第二次已超上限
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="")):
            self.assertTrue(backend.is_process_alive(42))   # 未超上限且未知 -> 宽限存活
            self.assertFalse(backend.is_process_alive(42))  # 超出 --time+buffer -> 回收

    @patch("core.execution.subprocess.run")
    def test_liveness_reuses_host_and_args(self, run_mock):
        run_mock.return_value = _Completed(stdout="RUNNING\n")
        backend = self._backend(ssh_args=["-p", "2222"])

        self.assertTrue(backend.is_process_alive(12345))

        args, _ = run_mock.call_args
        self.assertEqual(args[0][:4], ["ssh", "-p", "2222", self.LOGIN])
        self.assertIn("sacct -j 12345", args[0][4])
        self.assertIn("State%30", args[0][4])              # 显式列宽，避免状态被截断

    def test_final_status_reflects_terminal_state(self):
        # 终态查询应根据最终观察到的状态给出成功与否的正确语义。
        backend = self._backend()
        # COMPLETED 作业 -> success 为 True
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="COMPLETED\n")):
            self.assertFalse(backend.is_process_alive(1))   # 记录下终态
        self.assertEqual(backend.final_status(1), {"state": "COMPLETED", "success": True})
        # TIMEOUT 作业 -> success 为 False（不可静默当作 "completed"）
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="TIMEOUT\n")):
            self.assertFalse(backend.is_process_alive(2))
        self.assertEqual(backend.final_status(2), {"state": "TIMEOUT", "success": False})
        # 从未观察到达到终态的任务 -> 判为不确定
        self.assertEqual(backend.final_status(999), {"state": "unknown", "success": None})

    def test_get_gpu_status_parses_queue(self):
        backend = self._backend()
        with patch.object(backend, "_ssh_shell", return_value=_Completed(stdout="   2 PENDING\n   1 RUNNING\n")):
            status = backend.get_gpu_status()
        self.assertEqual(status["utilization"], "slurm")
        self.assertEqual(status["pending"], 2)
        self.assertEqual(status["running"], 1)

    def test_cancel_calls_scancel(self):
        # 取消任务应调用 scancel。
        backend = self._backend()
        with patch.object(backend, "_ssh_shell", return_value=_Completed(returncode=0)) as shell:
            self.assertTrue(backend.cancel(12345))
        shell.assert_called_once()
        self.assertIn("scancel 12345", shell.call_args[0][0])
        # scancel 非零退出 -> False（不能无条件返回 True）
        with patch.object(backend, "_ssh_shell", return_value=_Completed(returncode=1)):
            self.assertFalse(backend.cancel(12345))
        # 传输层失败应被吞掉 -> False，且绝不向上抛异常
        with patch.object(backend, "_ssh_shell",
                          side_effect=subprocess.TimeoutExpired(cmd="scancel", timeout=8)):
            self.assertFalse(backend.cancel(12345))

    def test_parse_slurm_time_seconds(self):
        # 校验 Slurm 时长字符串到秒数（或其哨兵值）的解析逻辑。
        self.assertEqual(_parse_slurm_time_seconds("60"), 3600)            # 裸写的分钟
        self.assertEqual(_parse_slurm_time_seconds("01:30"), 90)           # 分:秒
        self.assertEqual(_parse_slurm_time_seconds("12:00:00"), 43200)     # 时:分:秒
        self.assertEqual(_parse_slurm_time_seconds("2-00:00:00"), 172800)  # 天-时:分:秒
        self.assertEqual(_parse_slurm_time_seconds("1-12"), 129600)        # 天-小时
        self.assertEqual(_parse_slurm_time_seconds("garbage"), 10 ** 9)    # 非法输入返回哨兵值


class SlurmRemoteHelperTests(unittest.TestCase):
    """把内嵌的 REMOTE_HELPER 当作子进程来运行（此处没有真实的 sbatch，因此提交会在脚本写
    完之后才失败——我们转而断言脚本内容本身）。"""

    def _run_helper(self, payload):
        # 以子进程执行 helper，返回其 JSON 输出结果。
        proc = subprocess.run(
            ["python3", "-c", REMOTE_HELPER],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_submit_slurm_builds_safe_script(self):
        # 提交生成的 sbatch 脚本必须安全且符合规范。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ws"
            root.mkdir()
            self._run_helper(
                {
                    "action": "submit_slurm",
                    "remote_workspace": str(root),
                    "argv": ["python", "t.py", "--x", "a b"],
                    "log_file": "logs/exp.log",
                    "env": {"CUDA_VISIBLE_DEVICES": "3", "FOO": "b a r"},
                    "partition": "gpu",
                    "time": "01:00:00",
                    "gres": 2,
                    "raw_gres": "",
                    "qos": "",
                    "account": "",
                    "job_name": "ar_exp",
                    "setup": "module load cuda/12.4",
                    "extra_sbatch": ["--nodes=1"],
                }
            )
            # 输出日志的父目录必须提前创建好（Slurm 不会自动创建）。
            self.assertTrue((root / "logs").is_dir())
            script = (root / ".sbatch_ar_exp").read_text()

        self.assertIn("#SBATCH --partition=gpu", script)
        self.assertIn("#SBATCH --time=01:00:00", script)
        self.assertIn('#SBATCH --output="logs/exp.log"', script)   # 加引号（含空格也安全）
        self.assertIn("#SBATCH --gres=gpu:2", script)
        self.assertIn("#SBATCH --nodes=1", script)
        self.assertIn("module load cuda/12.4", script)
        # 环境变量被安全引用；易注入的参数加引号；GPU 掩码被剥离。
        self.assertIn("export FOO='b a r'", script)
        self.assertIn("'a b'", script)
        self.assertNotIn("CUDA_VISIBLE_DEVICES", script)
        # 不得出现常驻登录节点的构造（2026-05-29 MIL 不变量）。
        for forbidden in ("tmux", "srun", "--wait", "squeue", "while "):
            self.assertNotIn(forbidden, script)

    def _run_helper_with_path(self, payload, extra_path):
        env = {**os.environ, "PATH": extra_path + os.pathsep + os.environ["PATH"]}
        proc = subprocess.run(
            ["python3", "-c", REMOTE_HELPER],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    @staticmethod
    def _fake_sbatch(bindir, body_line):
        fake = bindir / "sbatch"
        fake.write_text("#!/bin/bash\n" + body_line + "\n")
        fake.chmod(0o755)

    def _submit_payload(self, root, job_name):
        return {
            "action": "submit_slurm", "remote_workspace": str(root),
            "argv": ["python", "t.py"], "log_file": "out.log", "env": {},
            "partition": "gpu", "time": "01:00:00", "gres": 1,
            "raw_gres": "", "job_name": job_name,
        }

    def test_submit_slurm_parses_federated_job_id(self):
        # sbatch --parsable can emit the federated "<id>;<cluster>" form.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ws"; root.mkdir()
            binp = Path(tmp) / "bin"; binp.mkdir()
            self._fake_sbatch(binp, "printf '12345;cluster0\\n'")
            body = self._run_helper_with_path(self._submit_payload(root, "ar_fed"), str(binp))
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["result"]["slurm_job_id"], 12345)

    def test_submit_slurm_rejects_non_numeric_output(self):
        # 非 --parsable 的输出行（例如 "Submitted batch job 99"）必须被拒绝，
        # 不能被误解析成一个伪造的作业号。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ws"; root.mkdir()
            binp = Path(tmp) / "bin"; binp.mkdir()
            self._fake_sbatch(binp, "printf 'Submitted batch job 99\\n'")
            body = self._run_helper_with_path(self._submit_payload(root, "ar_bad"), str(binp))
        self.assertFalse(body["ok"])
        self.assertIn("did not return a job id", body["error"])

    def test_submit_slurm_raw_gres_overrides(self):
        # 使用原始 raw_gres（如 gpu:a100:4）时应覆盖普通的 gres 计数写进脚本。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ws"
            root.mkdir()
            self._run_helper(
                {
                    "action": "submit_slurm",
                    "remote_workspace": str(root),
                    "argv": ["python", "t.py"],
                    "log_file": "out.log",
                    "env": {},
                    "partition": "gpu",
                    "time": "01:00:00",
                    "gres": 1,
                    "raw_gres": "gpu:a100:4",
                    "job_name": "ar_raw",
                }
            )
            script = (root / ".sbatch_ar_raw").read_text()
        self.assertIn("#SBATCH --gres=gpu:a100:4", script)
        self.assertNotIn("--gres=gpu:1", script)


if __name__ == "__main__":
    unittest.main()
