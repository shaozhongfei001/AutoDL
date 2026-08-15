"""
AutoResearcher Experiment Monitor

The key innovation: ZERO LLM calls during experiment training.

While your model trains (hours/days), the monitor only does:
- Process alive check
- Log file tail read
- GPU utilization check

This means running AutoResearcher 24/7 costs the same as running it
only during the THINK and REFLECT phases.
"""

import logging
import shlex
import time
from typing import Optional

from .execution import ExecutionBackend, LocalExecutionBackend

logger = logging.getLogger("autodl.monitor")


class ExperimentMonitor:
    """Zero-LLM experiment monitoring.

    Design principle: During training, the agent is effectively "sleeping"
    at zero cost. It only wakes up (calls LLM) when training completes
    and results need analysis.
    """

    def __init__(
        self,
        poll_interval: int = 900,
        zero_llm: bool = True,
        backend: Optional[ExecutionBackend] = None,
        budget: Optional[dict] = None,
    ):
        self.poll_interval = poll_interval  # seconds between checks
        self.zero_llm = zero_llm
        self.backend = backend or LocalExecutionBackend(".")
        self._active_experiments: dict[int, dict] = {}
        # A contract: optional budget (mode/limit/hard_wall_clock_limit/enforced).
        # Legacy (no budget) keeps the old unbounded-wait behavior.
        self.budget = budget or {}

    def launch_experiment(self, command: str, log_file: str, gpu: Optional[str] = None) -> dict:
        """Launch an experiment via nohup and track its PID.

        Args:
            command: The training command to run
            log_file: Path to redirect stdout/stderr
            gpu: CUDA_VISIBLE_DEVICES value

        Returns:
            dict with pid, log_file, start_time
        """
        env = {}
        if gpu is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(gpu)

        experiment = self.backend.launch_command(
            argv=shlex.split(command),
            log_file=log_file,
            env=env,
        )
        experiment.update({
            "start_time": time.time(),
            "command": command,
            "status": "running",
        })
        self._active_experiments[experiment["pid"]] = experiment

        logger.info(f"Launched experiment: PID={experiment['pid']}, cmd={command[:80]}...")
        return experiment

    def wait_for_completion(self, pid: int, log_file: str, notify: bool = True) -> dict:
        """Wait for experiment to complete. ZERO LLM calls during wait.

        This is the core cost-saving mechanism. Instead of asking the LLM
        "is training done?", we just check if the process is alive.
        """
        logger.info(f"Monitoring PID={pid}, polling every {self.poll_interval}s")

        hard_limit = float(self.budget.get("hard_wall_clock_limit") or 0)
        started = self._active_experiments.get(pid, {}).get("start_time", time.time())

        while self._is_process_alive(pid):
            time.sleep(self.poll_interval)

            # Log current status (no LLM involved)
            gpu_info = self._safe_gpu_status()
            log_tail = self._safe_tail_file(log_file, lines=5)
            elapsed = time.time() - started

            # A contract: hard wall-clock backstop. If the process outlives the
            # configured hard limit, kill it so it cannot burn unbounded budget.
            # (The poll_interval bounds discovery latency but NOT the budget.)
            if hard_limit > 0 and elapsed >= hard_limit:
                logger.warning(
                    f"PID={pid} exceeded hard_wall_clock_limit={hard_limit:.0f}s; "
                    f"terminating to enforce experiment budget"
                )
                self._terminate(pid)
                break

            logger.info(
                f"PID={pid} alive | elapsed={elapsed/3600:.1f}h | "
                f"GPU={gpu_info.get('utilization', 'N/A')} | "
                f"last_log: {log_tail[-1] if log_tail else 'N/A'}"
            )

        # Experiment finished (or hard-killed) — ask the backend for the real
        # outcome. Slurm reports the sacct terminal state; pid-only backends
        # return unknown and we classify via the budget/elapsed instead.
        elapsed = time.time() - started
        log_tail = self._safe_tail_file(log_file, lines=50)

        final = self._safe_final_status(pid)
        success = final.get("success")

        # A contract: classify the run under the active budget (advisory when
        # budget absent -> SUCCESS/TIMEOUT; full status when enforced).
        from .experiment_contract import classify_run_outcome
        active_seconds = self._extract_active_train_seconds(log_tail)
        terminated = "crash" if success is False else "completed"
        contract_status = classify_run_outcome(
            active_seconds or elapsed, self.budget, terminated=terminated
        )
        # Backwards-compatible `status`: "completed"/"failed" as before. The new
        # `contract_status` (SUCCESS/BUDGET_EXCEEDED/TIMEOUT/CRASH) is additive
        # and only informative when a budget is configured.
        status = "failed" if success is False else "completed"

        if pid in self._active_experiments:
            self._active_experiments[pid]["status"] = status

        metrics = self._extract_metrics(log_tail)
        result = {
            "pid": pid,
            "status": status,
            "contract_status": contract_status,
            "success": success,
            "terminal_state": final.get("state", "unknown"),
            "elapsed_hours": elapsed / 3600,
            "active_train_seconds": active_seconds,
            "budget_enforced": bool(self.budget.get("enforced")),
            "log_tail": "\n".join(log_tail),
            "metrics": metrics,
        }

        logger.info(
            f"Experiment PID={pid} {status} after {result['elapsed_hours']:.1f}h "
            f"(state={result['terminal_state']}, contract={contract_status})"
        )

        if notify:
            self._notify_completion(result)

        return result

    def has_completed_experiments(self) -> bool:
        """Check if any tracked experiment has finished."""
        for pid, exp in list(self._active_experiments.items()):
            if exp["status"] == "running" and not self._is_process_alive(pid):
                exp["status"] = "completed"
                return True
        return False

    def _is_process_alive(self, pid: int) -> bool:
        """Check if process is still running (zero cost)."""
        return self.backend.is_process_alive(pid)

    def _terminate(self, pid: int) -> bool:
        """Best-effort terminate a run that exceeded its hard budget.

        For a local pid this is SIGTERM then a short grace before SIGKILL.
        Slurm backends override via ``cancel``; here we degrade gracefully to
        the backend's ``cancel`` if present, else nothing (the process is left
        for the OS / Slurm --time to reap).
        """
        cancel = getattr(self.backend, "cancel", None)
        if callable(cancel):
            try:
                return bool(cancel(pid))
            except Exception as exc:  # pragma: no cover
                logger.warning(f"cancel({pid}) failed: {exc}")
                return False
        try:
            import signal as _signal
            import os as _os
            _os.kill(pid, _signal.SIGTERM)
            return True
        except (OSError, TypeError):
            return False

    def _extract_active_train_seconds(self, log_lines: list[str]) -> Optional[float]:
        """Read ``active_train_seconds=...`` from the tail of the training log."""
        import re
        for line in reversed(log_lines):
            m = re.search(r"active_train_seconds=([0-9.]+)", line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    return None
        return None

    def _safe_gpu_status(self) -> dict:
        try:
            return self.backend.get_gpu_status()
        except Exception:
            return {"utilization": "N/A"}

    def _safe_final_status(self, pid: int) -> dict:
        try:
            return self.backend.final_status(pid) or {}
        except Exception:
            # Backend without final_status support -> treat as indeterminate.
            return {"state": "unknown", "success": None}

    def _safe_tail_file(self, filepath: str, lines: int = 50) -> list[str]:
        try:
            return self.backend.tail_file(filepath, lines=lines)
        except Exception:
            return []

    def _extract_metrics(self, log_lines: list[str]) -> dict:
        """Try to extract common metrics from training logs.

        Looks for patterns like:
        - loss: 0.123
        - accuracy: 95.2%
        - validation_accuracy=0.99 / test_accuracy=0.98 (split-aware)
        - FGD: 0.582
        - epoch 100/200

        Split responsibility: ``validation_*`` values are kept for per-round
        selection; ``test_*`` values are tagged so downstream code can treat
        them as independent-acceptance-only (never fed back to selection).
        """
        import re
        metrics = {}
        for line in reversed(log_lines):
            # Split-aware metrics first (validation vs test).
            for pattern, key in [
                (r"validation_accuracy=([0-9.]+)", "validation_accuracy"),
                (r"validation_loss=([0-9.]+)", "validation_loss"),
                (r"test_accuracy=([0-9.]+)", "test_accuracy"),
                (r"test_loss=([0-9.]+)", "test_loss"),
                (r"train_accuracy=([0-9.]+)", "train_accuracy"),
            ]:
                if key not in metrics:
                    match = re.search(pattern, line)
                    if match:
                        try:
                            metrics[key] = float(match.group(1))
                        except ValueError:
                            metrics[key] = match.group(1)
            # Generic patterns (backwards-compatible).
            for pattern, key in [
                (r"loss[:\s]+([0-9.]+)", "loss"),
                (r"acc(?:uracy)?[:\s]+([0-9.]+)", "accuracy"),
                (r"FGD[:\s]+([0-9.]+)", "FGD"),
                (r"FID[:\s]+([0-9.]+)", "FID"),
                (r"epoch[:\s]+(\d+)", "epoch"),
                (r"step[:\s]+(\d+)", "step"),
            ]:
                if key not in metrics:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        metrics[key] = match.group(1)
        return metrics

    def _notify_completion(self, result: dict):
        """Send notification when experiment finishes (success or failure)."""
        outcome = result.get("status", "completed").upper()
        logger.info(
            f"EXPERIMENT {outcome} | PID={result['pid']} | "
            f"Time={result['elapsed_hours']:.1f}h | "
            f"State={result.get('terminal_state', '?')} | "
            f"Metrics={result.get('metrics', {})}"
        )
