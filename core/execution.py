"""
深度研究智能体的执行后端（Execution backends）。

本地模式（local）保留当前行为。SSH 模式保持控制器状态在本地，而把文件操作、
shell 命令、训练、日志尾随、PID 检查与 GPU 检查都跑在一台远程主机上。
"""

from __future__ import annotations

import json
import logging
import os
import base64
import shutil
import shlex
import subprocess
import textwrap
import time
from pathlib import Path, PurePosixPath
from typing import Optional

logger = logging.getLogger("autodl.execution")


# 仓库阅读类工具（list_tree / grep_files）跳过的目录，使智能体看到源码而非
# VCS 元数据与构建缓存。
WALK_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".ipynb_checkpoints",
}
# grep_files 跳过大于此体积的文件（很可能是数据/二进制而非源码）。
GREP_MAX_FILE_BYTES = 2_000_000


# --- Slurm 存活状态分类（供 SlurmExecutionBackend 使用）---
# 我们把任务的 `sacct` 状态映射到三个桶。参考：`man sacct` 的 JOB STATE CODES。
# PENDING/RUNNING 等归入“运行中”；COMPLETED 为“已完成”；其余为“失败”。
# 故意不包含 PREEMPTED：在 requeue 策略下被抢占的任务会回到 PENDING，因此我们
# 让它落入“unknown”（有界宽限），而非过早回收。
_SLURM_RUNNING_STATES = {
    "PENDING", "RUNNING", "REQUEUED", "RESIZING", "SUSPENDED",
    "CONFIGURING", "COMPLETING",
}
_SLURM_OK_STATES = {"COMPLETED"}
_SLURM_FAIL_STATES = {
    "FAILED", "TIMEOUT", "CANCELLED", "NODE_FAIL", "OUT_OF_MEMORY",
    "BOOT_FAIL", "DEADLINE", "REVOKED", "SPECIAL_EXIT",
}


def _parse_slurm_time_seconds(spec: str) -> int:
    """把 Slurm 的 ``--time`` 规格解析成秒数。

    接受文档形式：``minutes``、``minutes:seconds``、``hours:minutes:seconds``、
    ``days-hours``、``days-hours:minutes``、``days-hours:minutes:seconds``。
    无法解析时返回一个大哨兵值，使挂钟存活上限不会误触发（连续 unknown 的宽限
    仍会约束循环）。
    """
    s = str(spec or "").strip()
    if not s:
        return 10 ** 9
    try:
        days = 0
        if "-" in s:
            d, s = s.split("-", 1)
            days = int(d)
        parts = s.split(":") if s else []
        if days:
            # days-hours[:minutes[:seconds]]
            hours = int(parts[0]) if len(parts) >= 1 else 0
            minutes = int(parts[1]) if len(parts) >= 2 else 0
            seconds = int(parts[2]) if len(parts) >= 3 else 0
        elif len(parts) == 1:
            hours, minutes, seconds = 0, int(parts[0]), 0          # 裸分钟
        elif len(parts) == 2:
            hours, minutes, seconds = 0, int(parts[0]), int(parts[1])  # minutes:seconds
        else:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    except (ValueError, TypeError, IndexError):
        return 10 ** 9


# 远程助手脚本：被 base64 编码后通过 ssh 在远程主机上 exec 执行。它提供与本地
# 后端一致的 JSON-over-stdin 工具传输（read_file / write_file / run_command /
# launch_command / gpu_status / submit_slurm 等），并复用同一套路径穿越防护。
REMOTE_HELPER = textwrap.dedent(
    """
    import json
    import os
    import pathlib
    import shlex
    import subprocess
    import sys


    def normalize_rel(raw):
        if raw is None or not str(raw).strip():
            raise ValueError("Path cannot be empty")
        rel = pathlib.PurePosixPath(str(raw))
        if rel.is_absolute():
            raise ValueError("Path must be relative to workspace")
        if any(part == ".." for part in rel.parts):
            raise ValueError(f"Path escapes workspace: {raw}")
        parts = [part for part in rel.parts if part not in ("", ".")]
        return pathlib.Path(*parts)


    def resolve_path(root, raw):
        rel = normalize_rel(raw)
        resolved = (root / rel).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {raw}") from exc
        return resolved


    WALK_SKIP_DIRS = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", ".idea", ".ipynb_checkpoints",
    }
    GREP_MAX_FILE_BYTES = 2000000


    def walk_tree(root, max_depth, max_entries):
        # 受深度限制、跳过噪声目录的递归目录树列举
        max_depth = max(1, int(max_depth))
        max_entries = max(1, int(max_entries))
        entries = []

        def walk(current, depth):
            if depth > max_depth or len(entries) >= max_entries:
                return
            try:
                children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
            except OSError:
                return
            for child in children:
                if len(entries) >= max_entries:
                    return
                if child.name in WALK_SKIP_DIRS:
                    continue
                if child.is_symlink():
                    continue
                rel = child.relative_to(root).as_posix()
                if child.is_dir():
                    entries.append(rel + "/")
                    walk(child, depth + 1)
                else:
                    entries.append(rel)

        walk(root, 1)
        return entries


    def grep_tree(root, base, pattern, max_results, ignore_case):
        # 在 root 下扫描文本文件中的 pattern，返回 file/line/text 命中列表
        import re
        if not pattern:
            raise ValueError("Search pattern cannot be empty")
        max_results = max(1, int(max_results))
        flags = re.IGNORECASE if ignore_case else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError("Invalid search pattern: " + str(exc))
        targets = []
        if root.is_file():
            targets = [root]
        else:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d not in WALK_SKIP_DIRS)
                for name in sorted(filenames):
                    targets.append(pathlib.Path(dirpath) / name)
        hits = []
        for file_path in targets:
            if len(hits) >= max_results:
                break
            try:
                if file_path.is_symlink():
                    continue
                if file_path.stat().st_size > GREP_MAX_FILE_BYTES:
                    continue
                with open(file_path, "r", errors="strict") as handle:
                    for lineno, line in enumerate(handle, start=1):
                        if regex.search(line):
                            hits.append({
                                "file": file_path.relative_to(base).as_posix(),
                                "line": lineno,
                                "text": line.rstrip("\\n")[:300],
                            })
                            if len(hits) >= max_results:
                                break
            except (UnicodeDecodeError, OSError, ValueError):
                continue
        return hits


    def gpu_status():
        # 通过 nvidia-smi 查询 GPU 利用率与显存
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                gpus = []
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpus.append(
                            {
                                "utilization": f"{parts[0]}%",
                                "memory": f"{parts[1]}MB/{parts[2]}MB",
                            }
                        )
                return {"gpus": gpus, "utilization": gpus[0]["utilization"] if gpus else "N/A"}
        except Exception:
            pass
        return {"utilization": "N/A"}


    def main():
        # 入口：从 stdin 读取 JSON 指令，执行对应 action，输出 JSON 结果
        payload = json.load(sys.stdin)
        root = pathlib.Path(payload["remote_workspace"]).expanduser().resolve(strict=False)
        action = payload["action"]
        result = None

        if action == "validate":
            root.mkdir(parents=True, exist_ok=True)
            result = {"status": "ok"}
        elif action == "read_file":
            path = resolve_path(root, payload["path"])
            if not path.exists():
                raise FileNotFoundError(f"File not found: {payload['path']}")
            result = {"content": path.read_text()}
        elif action == "read_file_range":
            path = resolve_path(root, payload["path"])
            if not path.exists():
                raise FileNotFoundError(f"File not found: {payload['path']}")
            lines = path.read_text().splitlines()
            start = max(1, int(payload.get("start_line", 1)))
            end_raw = payload.get("end_line")
            end = len(lines) if end_raw is None else min(len(lines), int(end_raw))
            if end < start:
                result = {"content": ""}
            else:
                selected = lines[start - 1:end]
                result = {"content": "\\n".join(str(start + i) + "\\t" + t for i, t in enumerate(selected))}
        elif action == "list_tree":
            raw = payload.get("path", ".")
            base = root if raw in ("", ".") else resolve_path(root, raw)
            if not base.is_dir():
                raise NotADirectoryError("Not a directory: " + str(raw))
            result = {"entries": walk_tree(base, payload.get("max_depth", 3), payload.get("max_entries", 300))}
        elif action == "grep_files":
            raw = payload.get("path", ".")
            base = root if raw in ("", ".") else resolve_path(root, raw)
            result = {"hits": grep_tree(base, root, payload["pattern"], payload.get("max_results", 50), payload.get("ignore_case", False))}
        elif action == "write_file":
            path = resolve_path(root, payload["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            content = payload["content"]
            path.write_text(content)
            result = {"status": "written", "path": payload["path"], "bytes": len(content)}
        elif action == "list_files":
            raw = payload.get("path", ".")
            if raw in ("", "."):
                path = root
            else:
                path = resolve_path(root, raw)
            if not path.is_dir():
                raise NotADirectoryError(f"Not a directory: {raw}")
            result = {"files": sorted(p.name for p in path.iterdir())[:100]}
        elif action == "run_command":
            try:
                proc = subprocess.run(
                    payload["argv"],
                    capture_output=True,
                    text=True,
                    timeout=int(payload.get("timeout_seconds", 120)),
                    cwd=str(root),
                    env={**os.environ, **(payload.get("env") or {})},
                    check=False,
                )
                result = {
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-500:],
                    "returncode": proc.returncode,
                }
            except subprocess.TimeoutExpired:
                result = {"error": f"Command timed out after {int(payload.get('timeout_seconds', 120))}s"}
        elif action == "launch_command":
            # 启动一个 detached 子进程，把输出写入日志文件，返回 PID
            log_file = payload["log_file"]
            log_path = resolve_path(root, log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as handle:
                proc = subprocess.Popen(
                    payload["argv"],
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, **(payload.get("env") or {})},
                    start_new_session=True,
                    cwd=str(root),
                )
            result = {"pid": proc.pid, "log_file": log_file, "status": "launched"}
        elif action == "is_process_alive":
            try:
                os.kill(int(payload["pid"]), 0)
                result = {"alive": True}
            except OSError:
                result = {"alive": False}
        elif action == "tail_file":
            path = resolve_path(root, payload["path"])
            if not path.exists():
                result = {"lines": []}
            else:
                lines = path.read_text().splitlines()
                result = {"lines": lines[-int(payload.get('lines', 50)) :]}
        elif action == "get_gpu_status":
            result = gpu_status()
        elif action == "submit_slurm":
            # 在这里（Python 中、shell=False）构造 sbatch 脚本——绝不从调用方传入
            # 的 argv 拼出任何远程 shell 字符串，因此不存在注入面。然后调用
            # `sbatch --parsable`，然后退出：登录节点上不留任何持久进程（即
            # v7 “提交即退出”不变量）。Slurm 负责强制 --time。
            argv = payload["argv"]
            if not isinstance(argv, list) or not argv:
                raise ValueError("submit_slurm requires a non-empty argv list")
            log_file = payload["log_file"]
            log_path = resolve_path(root, log_file)        # 复用路径穿越防护
            log_path.parent.mkdir(parents=True, exist_ok=True)
            root.mkdir(parents=True, exist_ok=True)
            # Slurm 通过 --gres 分配 GPU；继承的 CUDA_VISIBLE_DEVICES / GPU 会把
            # 每个任务都钉到错误的物理设备，因此剥除它们。
            env = {
                k: v for k, v in (payload.get("env") or {}).items()
                if k not in ("CUDA_VISIBLE_DEVICES", "GPU")
            }
            job_name = str(payload.get("job_name") or "ar_job")
            # #SBATCH 指令行由 Slurm 按空白分词（尊重双引号），而非经过 shell——
            # 因此含空格的路径必须双引号包裹。剥离任何内嵌双引号以保持引号无歧义
            # （路径实际从不含双引号）。
            def _q(value):
                return chr(34) + str(value).replace(chr(34), "") + chr(34)
            lines = ["#!/bin/bash"]
            lines.append("#SBATCH --job-name=" + _q(job_name))
            lines.append("#SBATCH --partition=" + str(payload["partition"]))
            lines.append("#SBATCH --chdir=" + _q(str(root)))
            # --output 是相对路径；Slurm 相对 --chdir 解析它，与 tail_file(log_file)
            # 在工作区根下解析的方式一致。
            lines.append("#SBATCH --output=" + _q(log_file))
            lines.append("#SBATCH --time=" + str(payload["time"]))
            raw_gres = payload.get("raw_gres") or ""
            gres = payload.get("gres")
            if raw_gres:
                lines.append("#SBATCH --gres=" + str(raw_gres))
            elif isinstance(gres, int) and gres >= 1:
                lines.append("#SBATCH --gres=gpu:" + str(gres))
            if payload.get("qos"):
                lines.append("#SBATCH --qos=" + str(payload["qos"]))
            if payload.get("account"):
                lines.append("#SBATCH --account=" + str(payload["account"]))
            for extra in (payload.get("extra_sbatch") or []):
                lines.append("#SBATCH " + str(extra))
            setup = payload.get("setup") or ""
            if setup:
                lines.append(str(setup))
            for k, v in env.items():
                lines.append("export " + str(k) + "=" + shlex.quote(str(v)))
            lines.append(" ".join(shlex.quote(str(a)) for a in argv))
            script = chr(10).join(lines) + chr(10)
            script_path = root / (".sbatch_" + job_name)
            script_path.write_text(script)
            try:
                proc = subprocess.run(
                    ["sbatch", "--parsable", str(script_path)],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(root), check=False,
                )
            except FileNotFoundError as exc:
                raise RuntimeError("sbatch not found on remote host: " + str(exc))
            if proc.returncode != 0:
                raise RuntimeError(
                    "sbatch failed: " + (proc.stderr or proc.stdout).strip()[:400]
                )
            token = ""
            if proc.stdout.strip():
                token = proc.stdout.strip().splitlines()[0].split(";")[0].strip()
            if not token.isdigit():
                raise RuntimeError(
                    "sbatch did not return a job id: " + proc.stdout.strip()[:200]
                )
            result = {
                "slurm_job_id": int(token),
                "log_file": log_file,
                "script_path": str(script_path),
            }
        else:
            raise ValueError(f"Unknown action: {action}")

        json.dump({"ok": True, "result": result}, sys.stdout)


    if __name__ == "__main__":
        try:
            main()
        except Exception as exc:
            json.dump(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                },
                sys.stdout,
            )
    """
).strip()

REMOTE_HELPER_B64 = base64.b64encode(REMOTE_HELPER.encode("utf-8")).decode("ascii")
REMOTE_LAUNCHER = "import base64,sys;exec(base64.b64decode(sys.argv[1]).decode())"


def normalize_relative_path(path: str) -> str:
    """规范化一个工作区相对路径，并拒绝路径穿越。"""
    if path is None or not str(path).strip():
        raise ValueError("Path cannot be empty")

    pure = PurePosixPath(str(path))
    if pure.is_absolute():
        raise ValueError("Path must be relative to workspace")
    if any(part == ".." for part in pure.parts):
        raise ValueError(f"Path escapes workspace: {path}")

    normalized = str(pure)
    return "." if normalized in ("", ".") else normalized


def _resolve_under_root(root: Path, rel_path: str) -> Path:
    # 解析出 root 下的真实路径，并强制其仍位于 root 内
    parts = [part for part in PurePosixPath(rel_path).parts if part not in ("", ".")]
    resolved = (root / Path(*parts)).resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace: {rel_path}") from exc
    return resolved


def _walk_tree(root: Path, base: Path, max_depth: int, max_entries: int) -> list[str]:
    """相对 `base` 的受深度限制递归列举，跳过噪声目录。"""
    max_depth = max(1, int(max_depth))
    max_entries = max(1, int(max_entries))
    entries: list[str] = []

    def walk(current: Path, depth: int):
        if depth > max_depth or len(entries) >= max_entries:
            return
        try:
            children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
        except (PermissionError, OSError):
            return
        for child in children:
            if len(entries) >= max_entries:
                return
            if child.name in WALK_SKIP_DIRS:
                continue
            # 绝不跟随或列出符号链接：它们可指向工作区之外，从而破坏别处强制的沙箱。
            if child.is_symlink():
                continue
            rel = child.relative_to(base).as_posix()
            if child.is_dir():
                entries.append(rel + "/")
                walk(child, depth + 1)
            else:
                entries.append(rel)

    walk(root, 1)
    return entries


def _grep_tree(root: Path, base: Path, pattern: str, max_results: int, ignore_case: bool) -> list[dict]:
    """在 `root` 下扫描文本文件中的 `pattern`，返回 file/line/text 命中。"""
    import re as _re

    if not pattern:
        raise ValueError("Search pattern cannot be empty")
    max_results = max(1, int(max_results))
    flags = _re.IGNORECASE if ignore_case else 0
    try:
        regex = _re.compile(pattern, flags)
    except _re.error as exc:
        raise ValueError(f"Invalid search pattern: {exc}") from exc

    targets: list[Path] = []
    if root.is_file():
        targets = [root]
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in WALK_SKIP_DIRS)
            for name in sorted(filenames):
                targets.append(Path(dirpath) / name)

    hits: list[dict] = []
    for file_path in targets:
        if len(hits) >= max_results:
            break
        try:
            # os.walk 不向下进入符号链接目录，但符号链接*文件*仍会出现，否则会被
            # 打开——那可能读取到工作区外的文件。跳过任何符号链接目标。
            if file_path.is_symlink():
                continue
            if file_path.stat().st_size > GREP_MAX_FILE_BYTES:
                continue
            with open(file_path, "r", errors="strict") as handle:
                for lineno, line in enumerate(handle, start=1):
                    if regex.search(line):
                        hits.append(
                            {
                                "file": file_path.relative_to(base).as_posix(),
                                "line": lineno,
                                "text": line.rstrip("\n")[:300],
                            }
                        )
                        if len(hits) >= max_results:
                            break
        except (UnicodeDecodeError, PermissionError, OSError, ValueError):
            # 二进制文件、不可读、或逃逸出 base —— 静默跳过
            continue
    return hits


class ExecutionBackend:
    """执行后端抽象基类。"""

    def validate(self):
        raise NotImplementedError

    def read_file(self, path: str) -> str:
        raise NotImplementedError

    def read_file_range(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        raise NotImplementedError

    def write_file(self, path: str, content: str) -> dict:
        raise NotImplementedError

    def list_files(self, path: str = ".") -> list[str]:
        raise NotImplementedError

    def list_tree(self, path: str = ".", max_depth: int = 3, max_entries: int = 300) -> list[str]:
        raise NotImplementedError

    def grep_files(
        self,
        pattern: str,
        path: str = ".",
        max_results: int = 50,
        ignore_case: bool = False,
    ) -> list[dict]:
        raise NotImplementedError

    def run_command(self, argv: list[str], timeout: int = 120, env: Optional[dict] = None) -> dict:
        raise NotImplementedError

    def launch_command(self, argv: list[str], log_file: str, env: Optional[dict] = None) -> dict:
        raise NotImplementedError

    def is_process_alive(self, pid: int) -> bool:
        raise NotImplementedError

    def tail_file(self, path: str, lines: int = 50) -> list[str]:
        raise NotImplementedError

    def get_gpu_status(self) -> dict:
        raise NotImplementedError

    def final_status(self, pid: int) -> dict:
        """已完成任务的结果：``{"state": <str>, "success": <bool|None>}``。

        默认是不确定的（``success=None``）：只跟踪 OS pid 的后端在进程消失后无法
        恢复退出码，因此调用方继续把它当作“已完成”。Slurm 后端会用真实的
        ``sacct`` 终态覆盖此方法，使 FAILED / TIMEOUT / CANCELLED 不会被静默
        当作成功。
        """
        return {"state": "unknown", "success": None}


class LocalExecutionBackend(ExecutionBackend):
    """当前在本机上的行为。"""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    def validate(self):
        self.workspace.mkdir(parents=True, exist_ok=True)

    def read_file(self, path: str) -> str:
        file_path = _resolve_under_root(self.workspace, normalize_relative_path(path))
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return file_path.read_text()

    def read_file_range(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        file_path = _resolve_under_root(self.workspace, normalize_relative_path(path))
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        lines = file_path.read_text().splitlines()
        start = max(1, int(start_line))
        end = len(lines) if end_line is None else min(len(lines), int(end_line))
        if end < start:
            return ""
        selected = lines[start - 1 : end]
        return "\n".join(f"{start + i}\t{text}" for i, text in enumerate(selected))

    def write_file(self, path: str, content: str) -> dict:
        rel_path = normalize_relative_path(path)
        file_path = _resolve_under_root(self.workspace, rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return {"status": "written", "path": rel_path, "bytes": len(content)}

    def list_files(self, path: str = ".") -> list[str]:
        rel_path = normalize_relative_path(path)
        dir_path = self.workspace if rel_path == "." else _resolve_under_root(self.workspace, rel_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        return sorted([f.name for f in dir_path.iterdir()])[:100]

    def list_tree(self, path: str = ".", max_depth: int = 3, max_entries: int = 300) -> list[str]:
        rel_path = normalize_relative_path(path)
        root = self.workspace if rel_path == "." else _resolve_under_root(self.workspace, rel_path)
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        return _walk_tree(root, root, max_depth=max_depth, max_entries=max_entries)

    def grep_files(
        self,
        pattern: str,
        path: str = ".",
        max_results: int = 50,
        ignore_case: bool = False,
    ) -> list[dict]:
        rel_path = normalize_relative_path(path)
        root = self.workspace if rel_path == "." else _resolve_under_root(self.workspace, rel_path)
        return _grep_tree(root, self.workspace, pattern, max_results=max_results, ignore_case=ignore_case)

    def run_command(self, argv: list[str], timeout: int = 120, env: Optional[dict] = None) -> dict:
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.workspace),
                env={**os.environ, **(env or {})},
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s"}

        return {
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-500:],
            "returncode": result.returncode,
        }

    def launch_command(self, argv: list[str], log_file: str, env: Optional[dict] = None) -> dict:
        # 启动一个 detached 子进程，输出写入日志文件，返回 PID
        rel_path = normalize_relative_path(log_file)
        log_path = _resolve_under_root(self.workspace, rel_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        with open(log_path, "w") as handle:
            proc = subprocess.Popen(
                argv,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env={**os.environ, **(env or {})},
                start_new_session=True,
                cwd=str(self.workspace),
            )

        return {"pid": proc.pid, "log_file": rel_path, "status": "launched"}

    def is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def tail_file(self, path: str, lines: int = 50) -> list[str]:
        rel_path = normalize_relative_path(path)
        file_path = _resolve_under_root(self.workspace, rel_path)
        if not file_path.exists():
            return []
        return file_path.read_text().splitlines()[-lines:]

    def get_gpu_status(self) -> dict:
        # 通过 nvidia-smi 查询 GPU 状态
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().splitlines()
                gpus = []
                for line in lines:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpus.append(
                            {
                                "utilization": f"{parts[0]}%",
                                "memory": f"{parts[1]}MB/{parts[2]}MB",
                            }
                        )
                return {"gpus": gpus, "utilization": gpus[0]["utilization"] if gpus else "N/A"}
        except Exception:
            pass
        return {"utilization": "N/A"}


class SSHExecutionBackend(ExecutionBackend):
    """通过 SSH 在远程主机上运行对工具可见的工作区。"""

    def __init__(
        self,
        ssh_host: str,
        remote_workspace: str,
        remote_python: str = "python3",
        ssh_args: Optional[list[str]] = None,
    ):
        self.ssh_host = ssh_host
        self.remote_workspace = remote_workspace
        self.remote_python = remote_python or "python3"
        self.ssh_args = [str(arg) for arg in (ssh_args or [])]

    def validate(self):
        if not self.ssh_host:
            raise ValueError("execution.ssh_host is required when execution.mode=ssh")
        if not self.remote_workspace:
            raise ValueError("execution.remote_workspace is required when execution.mode=ssh")
        if shutil.which("ssh") is None:
            raise RuntimeError("ssh binary not found on PATH")
        self._invoke("validate", transport_timeout=30)

    def read_file(self, path: str) -> str:
        payload = self._invoke("read_file", path=normalize_relative_path(path))
        return payload["content"]

    def read_file_range(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        payload = self._invoke(
            "read_file_range",
            path=normalize_relative_path(path),
            start_line=int(start_line),
            end_line=None if end_line is None else int(end_line),
        )
        return payload["content"]

    def write_file(self, path: str, content: str) -> dict:
        return self._invoke("write_file", path=normalize_relative_path(path), content=content)

    def list_files(self, path: str = ".") -> list[str]:
        payload = self._invoke("list_files", path=normalize_relative_path(path))
        return payload["files"]

    def list_tree(self, path: str = ".", max_depth: int = 3, max_entries: int = 300) -> list[str]:
        payload = self._invoke(
            "list_tree",
            path=normalize_relative_path(path),
            max_depth=int(max_depth),
            max_entries=int(max_entries),
        )
        return payload["entries"]

    def grep_files(
        self,
        pattern: str,
        path: str = ".",
        max_results: int = 50,
        ignore_case: bool = False,
    ) -> list[dict]:
        payload = self._invoke(
            "grep_files",
            pattern=pattern,
            path=normalize_relative_path(path),
            max_results=int(max_results),
            ignore_case=bool(ignore_case),
            transport_timeout=60,
        )
        return payload["hits"]

    def run_command(self, argv: list[str], timeout: int = 120, env: Optional[dict] = None) -> dict:
        return self._invoke(
            "run_command",
            argv=argv,
            timeout_seconds=timeout,
            env=env or {},
            transport_timeout=timeout + 10,
        )

    def launch_command(self, argv: list[str], log_file: str, env: Optional[dict] = None) -> dict:
        return self._invoke(
            "launch_command",
            argv=argv,
            log_file=normalize_relative_path(log_file),
            env=env or {},
            transport_timeout=30,
        )

    def is_process_alive(self, pid: int) -> bool:
        payload = self._invoke("is_process_alive", pid=int(pid), transport_timeout=15)
        return bool(payload["alive"])

    def tail_file(self, path: str, lines: int = 50) -> list[str]:
        payload = self._invoke("tail_file", path=normalize_relative_path(path), lines=lines, transport_timeout=15)
        return payload["lines"]

    def get_gpu_status(self) -> dict:
        return self._invoke("get_gpu_status", transport_timeout=20)

    def _ssh_shell(self, remote_cmd: str, timeout: int = 15) -> subprocess.CompletedProcess:
        """运行一次临时远程 shell 命令，复用本后端的 host 与 ssh_args（单一事实
        来源——不存在分裂的传输）。供 Slurm 子类用于 `sacct` / `squeue` / `scancel`，
        那是唯一需要任意远程 shell 字符串的地方。每次调用只运行一个命令并立即返回；
        远程不启动任何持久进程。被插值进这些字符串的只有经过校验的整数（job id）
        或操作员控制的配置。
        """
        return subprocess.run(
            ["ssh", *self.ssh_args, self.ssh_host, remote_cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _invoke(self, action: str, transport_timeout: int = 60, **kwargs) -> dict:
        # 通过标准输入 JSON 把动作派发给远程助手脚本（同一套传输）
        payload = {
            "action": action,
            "remote_workspace": self.remote_workspace,
            **kwargs,
        }
        remote_command = (
            f"{shlex.quote(self.remote_python)} -c {shlex.quote(REMOTE_LAUNCHER)} "
            f"{shlex.quote(REMOTE_HELPER_B64)}"
        )
        command = ["ssh", *self.ssh_args, self.ssh_host, remote_command]
        try:
            result = subprocess.run(
                command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=transport_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"SSH backend action '{action}' timed out after {transport_timeout}s") from exc

        if result.returncode != 0:
            stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
            message = " | ".join(stderr_tail) if stderr_tail else "unknown ssh error"
            raise RuntimeError(f"SSH backend action '{action}' failed: {message}")

        try:
            payload = json.loads((result.stdout or "").strip() or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SSH backend action '{action}' returned invalid JSON") from exc

        if not payload.get("ok"):
            error = payload.get("error", "unknown remote error")
            error_type = payload.get("error_type", "RuntimeError")
            if error_type == "FileNotFoundError":
                raise FileNotFoundError(error)
            if error_type == "NotADirectoryError":
                raise NotADirectoryError(error)
            if error_type == "ValueError":
                raise ValueError(error)
            raise RuntimeError(error)

        return payload.get("result", {})


class SlurmExecutionBackend(SSHExecutionBackend):
    """通过登录节点在 Slurm 管理的集群上运行实验。

    登录节点与计算节点共享 NFS 工作区，因此文件操作 / 仓库阅读 / ``run_command``
    全部继承自 :class:`SSHExecutionBackend`（它们在同一个 JSON-over-stdin 助手传输
    上运行于登录节点）。调度器上只有三处不同：

      - **启动（launch）** —— 不启动进程，而是通过**一次**瞬时 ssh 调用提交一个
        ``sbatch`` 作业（``--parsable``），调用立即退出。整数型的 Slurm job id 被
        放入 ``pid`` 字段返回，从而现有的基于 PID 的 monitor / state.json 逻辑
        保持不变。不留下任何 ``srun --wait`` / ``tmux`` / 轮询循环（2026-05-29
        Tokyo-U MIL 事故：登录节点上的持久进程是不允许的）。
      - **存活（liveness）** —— 在集群可达时 ``sacct`` 是唯一权威；控制器瞬时轮询它。
        Slurm 强制 ``--time``（报告 ``TIMEOUT``），因此运行中的作业总会自行到达
        终态。
      - **GPU 状态** —— 登录节点没有可用的 ``nvidia-smi``；改用 ``squeue`` 上报
        分区的队列占用情况。

    两道安全阀位于 :meth:`is_process_alive` **内部**，使得即便集群不可达，monitor
    的无限 ``while is_process_alive(pid): sleep`` 循环也能被证明会终止。它们**仅**
    在 sacct 无法确认任务状态时适用——一个 sacct 仍报告为排队/运行中的任务永不被
    回收（长 PENDING 队列等待不受 ``--time`` 约束）：

      1. *有界 unknown 宽限* —— 在连续 ``slurm_unknown_grace_polls`` 次不确定探测
         （ssh 宕机 / sacct 已清理）后，任务被宣告死亡。
      2. *挂钟兜底* —— 若自首次轮询起 ``--time`` + ``slurm_time_buffer`` 已过去而
         任务仍无法确认，它会被宣告死亡（Slurm 届时本已为任何真正运行过的作业
         产生了终态）。
    """

    def __init__(
        self,
        ssh_host: str,
        remote_workspace: str,
        remote_python: str = "python3",
        ssh_args: Optional[list[str]] = None,
        slurm_partition: str = "",
        slurm_time: str = "",
        slurm_gpus_per_job: Optional[int] = None,
        slurm_gres: str = "",
        slurm_qos: str = "",
        slurm_account: str = "",
        slurm_setup: str = "",
        slurm_extra_sbatch: Optional[list[str]] = None,
        slurm_unknown_grace_polls: int = 4,
        slurm_time_buffer: int = 1800,
    ):
        super().__init__(ssh_host, remote_workspace, remote_python, ssh_args)
        self.slurm_partition = slurm_partition
        self.slurm_time = slurm_time
        self.slurm_gpus_per_job = slurm_gpus_per_job
        self.slurm_gres = slurm_gres
        self.slurm_qos = slurm_qos
        self.slurm_account = slurm_account
        self.slurm_setup = slurm_setup
        self.slurm_extra_sbatch = list(slurm_extra_sbatch or [])
        self.slurm_unknown_grace_polls = int(slurm_unknown_grace_polls)
        self.slurm_time_buffer = int(slurm_time_buffer)
        self._time_cap_seconds = _parse_slurm_time_seconds(slurm_time)
        # 每个作业的存活状态，以 Slurm job id 为键
        self._first_seen: dict[int, float] = {}
        self._unknown_count: dict[int, int] = {}
        self._last_terminal: dict[int, str] = {}

    def validate(self):
        if not self.ssh_host:
            raise ValueError("execution.ssh_host is required when execution.mode=slurm")
        if not self.remote_workspace:
            raise ValueError("execution.remote_workspace is required when execution.mode=slurm")
        if not self.slurm_partition:
            raise ValueError("execution.slurm_partition is required when execution.mode=slurm")
        if not self.slurm_time:
            raise ValueError("execution.slurm_time is required when execution.mode=slurm")
        if shutil.which("ssh") is None:
            raise RuntimeError("ssh binary not found on PATH")
        # 工作区可达 + 远程 python 可用（继承的助手传输）
        self._invoke("validate", transport_timeout=30)
        # 需要全部三种工具：`command -v a b c` 任一存在即成功，因此逐个检查
        probe = self._ssh_shell(
            "command -v sbatch >/dev/null 2>&1 "
            "&& command -v sacct >/dev/null 2>&1 "
            "&& command -v squeue >/dev/null 2>&1 && echo OK",
            timeout=15,
        )
        if probe.returncode != 0 or "OK" not in (probe.stdout or ""):
            raise RuntimeError(
                "Slurm tools (sbatch/sacct/squeue) not found on the login node; "
                "is execution.ssh_host a Slurm submit host?"
            )

    def launch_command(self, argv: list[str], log_file: str, env: Optional[dict] = None) -> dict:
        # 提交 sbatch 作业，返回 Slurm job id（放进 pid 字段）
        normalized_log = normalize_relative_path(log_file)
        job_name = "ar_" + (Path(normalized_log).stem or "job")
        payload = self._invoke(
            "submit_slurm",
            argv=list(argv),
            log_file=normalized_log,
            env=env or {},                       # 远程助手会剥除 CUDA_VISIBLE_DEVICES/GPU
            partition=self.slurm_partition,
            time=self.slurm_time,
            gres=self.slurm_gpus_per_job,
            raw_gres=self.slurm_gres,
            qos=self.slurm_qos,
            account=self.slurm_account,
            job_name=job_name,
            setup=self.slurm_setup,
            extra_sbatch=list(self.slurm_extra_sbatch),
            transport_timeout=90,
        )
        job_id = int(payload["slurm_job_id"])
        # `pid` 携带 Slurm job id，使现有的 monitor / state.json / obsidian 逻辑
        # （都以 `pid` 为键）无需改动即可工作。
        return {
            "pid": job_id,
            "slurm_job_id": job_id,
            "log_file": payload.get("log_file", normalized_log),
            "status": "submitted",
        }

    def _sacct_state(self, job_id: int) -> tuple[str, str]:
        """返回 Slurm 任务的 (桶, 原始状态)；桶 ∈ {running, completed, failed,
        unknown}。一次瞬时 sacct 查询，并对过新 / 已从记账清除的任务回退到 squeue。"""
        cmd = f"sacct -j {int(job_id)} --format=State%30 -X -n -P 2>/dev/null | head -1"
        try:
            r = self._ssh_shell(cmd, timeout=15)
        except (subprocess.TimeoutExpired, OSError):
            return "unknown", "ssh_failed"
        if r.returncode != 0:
            return "unknown", f"sacct_rc={r.returncode}"
        out = (r.stdout or "").strip()
        # split()[0] 丢弃后缀 " by <uid>"（如 "CANCELLED by 1001"）；.replace("+","")
        # 剥离 Slurm 追加的 "CANCELLED+" 后缀。
        raw = out.split()[0].replace("+", "").upper() if out else ""
        if not raw:
            sq = f"squeue -j {int(job_id)} -h -o '%T' 2>/dev/null | head -1"
            try:
                r2 = self._ssh_shell(sq, timeout=15)
                raw = (r2.stdout or "").strip().upper()
            except (subprocess.TimeoutExpired, OSError):
                raw = ""
            if not raw:
                return "unknown", "sacct_empty"
        if raw in _SLURM_RUNNING_STATES:
            return "running", raw
        if raw in _SLURM_OK_STATES:
            return "completed", raw
        if raw in _SLURM_FAIL_STATES:
            return "failed", raw
        return "unknown", raw

    def is_process_alive(self, pid: int) -> bool:
        """仅当 Slurm 任务处于“运行中”桶时才算存活。不确定的探测只在一个有界的
        连续轮数内保持任务存活；一旦超过 ``--time`` + 缓冲也仍无法确认，则强制回收。
        两道边界共同保证 monitor 的轮询循环总是会终止。"""
        job_id = int(pid)
        now = time.time()
        first = self._first_seen.setdefault(job_id, now)
        bucket, raw = self._sacct_state(job_id)
        if bucket == "running":
            # PENDING/RUNNING 等是权威的。长队列等待不受 --time 约束（--time 只统计
            # 运行期间），因此绝不回收一个 sacct 仍确认排队或运行的任务。
            self._unknown_count[job_id] = 0
            return True
        if bucket in ("completed", "failed"):
            self._last_terminal[job_id] = raw
            return False
        # 不确定（ssh/sacct 不可达，或任务已从 sacct 与 squeue 都清除）。两道边界
        # 使 monitor 轮询循环有限，同时绝不回收 sacct 确认存活的任务：
        #   - 挂钟兜底：Slurm 强制 --time，因此一旦 --time + 缓冲已过而我们仍无法
        #     确认任务，它几乎可以确定已经消失；
        #   - 连续 unknown 宽限：应付较短的中断。
        if now - first > self._time_cap_seconds + self.slurm_time_buffer:
            return False
        self._unknown_count[job_id] = self._unknown_count.get(job_id, 0) + 1
        return self._unknown_count[job_id] <= self.slurm_unknown_grace_polls

    def get_gpu_status(self) -> dict:
        """上报分区的队列占用情况（登录节点无可用的 nvidia-smi）。仅建议性——
        monitor 只是把 ``utilization`` 记入日志。"""
        cmd = (
            "squeue --me -p " + shlex.quote(self.slurm_partition)
            + " --states=PD,R -h -o '%T' 2>/dev/null | sort | uniq -c"
        )
        pending = running = 0
        try:
            r = self._ssh_shell(cmd, timeout=20)
        except (subprocess.TimeoutExpired, OSError):
            return {
                "utilization": "slurm", "partition": self.slurm_partition,
                "pending": 0, "running": 0, "note": "squeue unavailable",
            }
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].isdigit():
                    count, state = int(parts[0]), parts[1].upper()
                    if state.startswith("PEND") or state == "PD":
                        pending = count
                    elif state.startswith("R"):
                        running = count
        return {
            "utilization": "slurm", "partition": self.slurm_partition,
            "pending": pending, "running": running,
        }

    def cancel(self, pid: int) -> bool:
        """对 Slurm 任务尽力 ``scancel``。尚未接入任何调用方（孤立任务本会被
        ``--time`` 回收）；预留给未来的“关闭时 kill”路径。"""
        try:
            r = self._ssh_shell("scancel " + str(int(pid)), timeout=8)
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def last_terminal_state(self, pid: int) -> Optional[str]:
        """已完成任务的原始 sacct 状态（若被观测到，如 ``TIMEOUT``）。"""
        return self._last_terminal.get(int(pid))

    def final_status(self, pid: int) -> dict:
        """来自观测到的 ``sacct`` 终态的真实结果。

        ``success`` 仅对 ``COMPLETED`` 为 True；``FAILED`` / ``TIMEOUT`` /
        ``CANCELLED`` / ``OUT_OF_MEMORY`` / … 都报告为失败。若任务从未被观测到
        到达终态（例如集群不可达并被挂钟兜底回收），则结果不确定。
        """
        raw = self._last_terminal.get(int(pid))
        if raw is None:
            return {"state": "unknown", "success": None}
        return {"state": raw, "success": raw in _SLURM_OK_STATES}


def build_execution_backend(config: Optional[dict], controller_workspace: Path) -> ExecutionBackend:
    """依据项目配置构造执行后端。"""
    config = config or {}
    execution = config.get("execution", {}) or {}
    mode = execution.get("mode", "local")

    if mode == "ssh":
        return SSHExecutionBackend(
            ssh_host=execution.get("ssh_host", ""),
            remote_workspace=execution.get("remote_workspace", ""),
            remote_python=execution.get("remote_python", "python3"),
            ssh_args=execution.get("ssh_args", []) or [],
        )
    if mode == "slurm":
        return SlurmExecutionBackend(
            ssh_host=execution.get("ssh_host", ""),
            remote_workspace=execution.get("remote_workspace", ""),
            remote_python=execution.get("remote_python", "python3"),
            ssh_args=execution.get("ssh_args", []) or [],
            slurm_partition=execution.get("slurm_partition", ""),
            slurm_time=execution.get("slurm_time", ""),
            slurm_gpus_per_job=execution.get("slurm_gpus_per_job"),
            slurm_gres=execution.get("slurm_gres", ""),
            slurm_qos=execution.get("slurm_qos", ""),
            slurm_account=execution.get("slurm_account", ""),
            slurm_setup=execution.get("slurm_setup", ""),
            slurm_extra_sbatch=execution.get("slurm_extra_sbatch", []) or [],
            slurm_unknown_grace_polls=int(execution.get("slurm_unknown_grace_polls", 4)),
            slurm_time_buffer=int(execution.get("slurm_time_buffer", 1800)),
        )
    if mode != "local":
        raise ValueError(f"Unknown execution.mode '{mode}'. Supported: local, ssh, slurm")
    return LocalExecutionBackend(controller_workspace)
