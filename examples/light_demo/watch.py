#!/usr/bin/env python3
"""Second-by-second console watcher for a training process.

Reuses the project's ExecutionBackend zero-cost primitives (is_process_alive,
get_gpu_status, tail_file) to poll every 1 second and print a status line to
the console. No LLM calls — this is the same cheap monitoring philosophy as
core/monitor.py, just denser (1s instead of the default poll_interval).

Usage:
    # 1) Launch a training command that writes to a log file, then watch it:
    python watch.py launch --cmd "python train_demo.py --steps 10" --log train.log

    # 2) Or watch an already-running PID + log file:
    python watch.py --pid <PID> --log <path/to/log>
"""
import argparse
import os
import shlex
import sys
import time
from pathlib import Path

# Make the project root importable so `core.*` resolves when run from this dir.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.execution import LocalExecutionBackend


def _fmt_gpu(gpu: dict) -> str:
    util = gpu.get("utilization")
    mem = gpu.get("memory_used") or gpu.get("memory_used_mb")
    name = gpu.get("name", "")
    if util is not None and str(util).lower() not in ("n/a", "none", ""):
        return f"GPU {name} util={util}% mem={mem}"
    return f"GPU {name} util=N/A"


def _print_status(pid: int, log_file: str, backend: LocalExecutionBackend, t0: float):
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
    # Process exited — one final status with the log tail.
    _print_status(pid, log_file, backend, t0)
    print("Process exited. Last log tail:", flush=True)
    for line in backend.tail_file(log_file, lines=8):
        print("  " + line, flush=True)
    return 0


def launch_and_watch(cmd: str, log_file: str, interval: float = 1.0):
    # LocalExecutionBackend resolves paths relative to its workspace ("." = CWD).
    # Use a relative log path so launch (which resolves under workspace) and
    # tail_file (same resolution) agree on the same file.
    backend = LocalExecutionBackend(".")
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    exp = backend.launch_command(argv=shlex.split(cmd), log_file=log_file)
    pid = exp["pid"]
    print(f"Launched pid={pid}: {cmd}", flush=True)
    return watch_pid(pid, log_file, interval)


def main():
    parser = argparse.ArgumentParser(description="1-second console watcher")
    parser.add_argument("--pid", type=int, default=None, help="PID to watch")
    parser.add_argument("--log", type=str, default="train.log", help="log file path")
    parser.add_argument("--interval", type=float, default=1.0, help="poll interval (s)")
    parser.add_argument(
        "action", nargs="?", default="watch",
        choices=["watch", "launch"],
        help="'watch' an existing pid, or 'launch' a command then watch",
    )
    parser.add_argument("--cmd", type=str, default=None, help="command to launch (with 'launch')")
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
