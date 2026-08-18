#!/usr/bin/env python3
"""逐秒控制台观察器，用于监控训练进程。

复用项目 ExecutionBackend 的零成本原语（is_process_alive、get_gpu_status、
tail_file），每秒轮询一次并向控制台打印一行状态。不做任何 LLM 调用——这与
core/monitor.py 的“廉价监控”哲学一致，只是更密集（1 秒而非默认的 poll_interval）。

用法：
    # 1) 启动一个写入日志文件的训练命令，然后观察它：
    python watch.py launch --cmd "python train_demo.py --steps 10" --log train.log

    # 2) 或者观察一个已在运行的 PID + 日志文件：
    python watch.py --pid <PID> --log <path/to/log>
"""
import argparse
import os
import shlex
import sys
import time
from pathlib import Path

# 把项目根目录加入 sys.path，使得从该目录运行时能正确解析 `core.*` 导入。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.execution import LocalExecutionBackend


def _fmt_gpu(gpu: dict) -> str:
    # 把 GPU 状态字典格式化成一行简短文本
    util = gpu.get("utilization")
    mem = gpu.get("memory_used") or gpu.get("memory_used_mb")
    name = gpu.get("name", "")
    if util is not None and str(util).lower() not in ("n/a", "none", ""):
        return f"GPU {name} util={util}% mem={mem}"
    return f"GPU {name} util=N/A"


def _print_status(pid: int, log_file: str, backend: LocalExecutionBackend, t0: float):
    # 打印一次状态行：存活、耗时、GPU、日志尾部
    alive = backend.is_process_alive(pid)
    elapsed = time.time() - t0
    gpu = _fmt_gpu(backend.get_gpu_status())
    tail = backend.tail_file(log_file, lines=3)
    last = tail[-1] if tail else "(no log yet)"
    state = "RUNNING" if alive else "EXITED "
    print(
        f"[{time.strftime('%H:%M:%S')}] pid={pid} {state} "
        f"elapsed={elapsed:6.1f}s | {gpu} | log: {last[:100]}",
        flush=True,
    )
    return alive


def watch_pid(pid: int, log_file: str, interval: float = 1.0):
    # 观察一个已存在的 PID，直到它退出
    backend = LocalExecutionBackend(".")
    t0 = time.time()
    print(f"Watching pid={pid} log={log_file} every {interval}s. Ctrl-C to stop.", flush=True)
    try:
        while backend.is_process_alive(pid):
            _print_status(pid, log_file, backend, t0)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped by user.", flush=True)
        return 130
    # 进程已退出——打印最后一次状态与日志尾部。
    _print_status(pid, log_file, backend, t0)
    print("Process exited. Last log tail:", flush=True)
    for line in backend.tail_file(log_file, lines=8):
        print("  " + line, flush=True)
    return 0


def launch_and_watch(cmd: str, log_file: str, interval: float = 1.0):
    # LocalExecutionBackend 的路径都相对其工作区（"." = 当前目录）。使用相对日志路径，
    # 使 launch（在 workspace 下解析）与 tail_file（同样的解析）指向同一文件。
    backend = LocalExecutionBackend(".")
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    exp = backend.launch_command(argv=shlex.split(cmd), log_file=log_file)
    pid = exp["pid"]
    print(f"Launched pid={pid}: {cmd}", flush=True)
    return watch_pid(pid, log_file, interval)


def main():
    parser = argparse.ArgumentParser(description="1-second console watcher")
    parser.add_argument("--pid", type=int, default=None, help="要观察的 PID")
    parser.add_argument("--log", type=str, default="train.log", help="日志文件路径")
    parser.add_argument("--interval", type=float, default=1.0, help="轮询间隔（秒）")
    parser.add_argument(
        "action", nargs="?", default="watch",
        choices=["watch", "launch"],
        help="“watch” 一个已有 pid，或 “launch” 一个命令后再观察",
    )
    parser.add_argument("--cmd", type=str, default=None, help="要启动的命令（配合 'launch'）")
    args = parser.parse_args()

    if args.action == "launch":
        if not args.cmd:
            print("--cmd is required with 'launch'", file=sys.stderr)
            return 2
        return launch_and_watch(args.cmd, args.log, args.interval)
    if not args.pid:
        print("--pid is required with 'watch' (or use 'launch')", file=sys.stderr)
        return 2
    return watch_pid(args.pid, args.log, args.interval)


if __name__ == "__main__":
    sys.exit(main())
