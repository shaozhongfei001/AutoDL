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

import json
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
        # In-run early stopping (train-level): parse per-epoch validation
        # metrics from the live log and terminate the run early when the model
        # has stopped improving (plateau), so GPU time is not wasted. Disabled
        # by default (legacy behavior). Config lives under the budget block:
        #   budget.early_stop.{enabled, patience, improvement_tol, min_epochs, metric}
        es = (self.budget or {}).get("early_stop") or {}
        self.early_stop_enabled = bool(es.get("enabled", False))
        self.early_stop_patience = int(es.get("patience", 3))
        self.early_stop_tol = float(es.get("improvement_tol", 1e-4))
        self.early_stop_min_epochs = int(es.get("min_epochs", 5))
        self.early_stop_metric = str(es.get("metric", "validation_accuracy"))
        self._early_stopped = False

    def _extract_epoch_metrics(self, log_lines: list[str], metric: str) -> list[float]:
        """Extract the per-epoch value sequence of ``metric`` from the live log.

        Handles both the structured ``RESULT {...}`` per-epoch snapshot and the
        legacy ``key=value`` / ``epoch N ... metric=...`` text forms. Returns a
        chronological list of floats (earliest first). Empty when none found.
        """
        import re
        values: list[float] = []
        # Structured RESULT snapshots may carry the metric per epoch.
        for line in log_lines:
            m = re.search(r"RESULT\s+(\{.*\})", line)
            if not m:
                continue
            try:
                payload = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict) and metric in payload:
                try:
                    values.append(float(payload[metric]))
                except (TypeError, ValueError):
                    pass
        if values:
            return values
        # Legacy regex: `metric=0.98`, `metric: 0.98`, `metric 0.98`.
        pattern = re.compile(
            r"(?:{metric}\s*[:=]\s*([0-9.]+))|(?:^.*\b{metric}\b[^\d]*([0-9.]+))".format(
                metric=re.escape(metric)
            ),
            re.IGNORECASE,
        )
        for line in log_lines:
            m = pattern.search(line)
            if m:
                val = m.group(1) or m.group(2)
                try:
                    values.append(float(val))
                except (TypeError, ValueError):
                    pass
        return values

    def _check_in_run_early_stop(self, pid: int, log_lines: list[str]) -> bool:
        """In-run early stopping: if validation has plateaued for ``patience``
        consecutive epochs (beyond a tolerance), terminate the run to save GPU.

        Returns True when the run was early-stopped. Never fires before
        ``min_epochs`` observations (so the early volatile phase is respected)
        and only considers the metric named by ``early_stop_metric``.
        """
        if not self.early_stop_enabled:
            return False
        seq = self._extract_epoch_metrics(log_lines, self.early_stop_metric)
        if len(seq) < self.early_stop_min_epochs:
            return False
        best = max(seq)
        # Plateau: the most recent `patience` epochs have all stayed within the
        # tolerance of the running best (no further improvement for patience
        # consecutive epochs), counting the current (last) epoch too.
        sustained = 0
        for v in reversed(seq):
            if v >= best - self.early_stop_tol:
                sustained += 1
            else:
                break
        if sustained >= self.early_stop_patience:
            logger.warning(
                f"PID={pid} in-run early stop: '{self.early_stop_metric}' plateaued "
                f"for {sustained} epochs (best={best:.4f}); terminating to save GPU"
            )
            self._terminate(pid)
            return True
        return False

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

            # In-run early stopping (train-level): terminate early when the
            # per-epoch validation metric has plateaued, so GPU is not wasted
            # on epochs that cannot improve. Reads the live log tail (no LLM).
            if self.early_stop_enabled:
                try:
                    if self._check_in_run_early_stop(pid, self._safe_tail_file(log_file, lines=200)):
                        self._early_stopped = True
                        break
                except Exception as exc:  # pragma: no cover - advisory, never crash
                    logger.warning(f"in-run early-stop check failed: {exc}")

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
        # E: empty-metric diagnosis. A *completed* run that produced no metric is
        # itself a signal worth surfacing (it drove the INCOMPARABLE flood), so
        # attach a compact diagnosis for the loop to feed back to the code agent.
        metrics_diagnosis = {}
        if not metrics and status == "completed":
            try:
                metrics_diagnosis = self._diagnose_empty_metrics(log_tail)
            except Exception as exc:  # pragma: no cover - diagnostic must never crash
                logger.warning(f"metrics diagnosis failed: {exc}")
        # In-run early stop marks the run as a completed, budget-friendly run
        # (not a crash): the model reached a plateau and training was cut short.
        # The contract status stays SUCCESS (it IS a clean run — just shorter),
        # so the promotion gate still allows a genuinely better early-stopped
        # model to be kept; the `early_stopped` flag records the fact.
        early_stopped = bool(self._early_stopped)

        result = {
            "pid": pid,
            "status": status,
            "contract_status": contract_status,
            "success": success,
            "terminal_state": final.get("state", "unknown"),
            "elapsed_hours": elapsed / 3600,
            "active_train_seconds": active_seconds,
            "budget_enforced": bool(self.budget.get("enforced")),
            "early_stopped": early_stopped,
            "log_tail": "\n".join(log_tail),
            "metrics": metrics,
            "metrics_diagnosis": metrics_diagnosis,
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

        Priority order (most reliable first):
          1. ``RESULT {...}`` — a single-line JSON emitted at the end of a
             training script (A: structured metric contract). This is the
             authoritative, whitespace-safe protocol and is preferred over
             ad-hoc text regexes. A training script simply prints
             ``RESULT {"validation_accuracy": 0.982, "test_accuracy": 0.979}``.
          2. Split-aware ``key=value`` lines (validation_* / test_* / train_*).
          3. Generic patterns (backwards-compatible): loss / accuracy / FGD /
             FID / epoch / step.

        Split responsibility: ``validation_*`` values are kept for per-round
        selection; ``test_*`` values are tagged so downstream code can treat
        them as independent-acceptance-only (never fed back to selection).
        """
        import re

        metrics = {}
        # 1. Structured RESULT contract — take the LAST valid one so the final
        #    epoch's snapshot wins, and it overrides any regex-extracted values.
        for line in log_lines:
            m = re.search(r"RESULT\s+(\{.*\})", line)
            if not m:
                continue
            try:
                payload = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                cleaned = {k: v for k, v in payload.items() if isinstance(v, (int, float))}
                if cleaned:
                    metrics = cleaned  # structured contract replaces regex output
        if metrics:
            return metrics

        # 2/3. Regex fallback (legacy / non-RESULT training scripts).
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

    def _diagnose_empty_metrics(self, log_lines: list[str]) -> dict:
        """E: Structured diagnosis when a *completed* run yields no metrics.

        Instead of silently returning an empty dict (which produced the
        INCOMPARABLE-"no candidate metrics" flood), classify WHY extraction
        failed so the loop can hand the code agent actionable feedback:
          - (none)            metrics ARE extractable -> return {} (no diagnosis).
          - result_missing:   no ``RESULT {...}`` line at all AND no regex
                              metric — the training script does not emit the
                              structured contract.
          - log_unavailable:  tail returned nothing (log path mismatch).
          - result_no_numeric:RESULT line present but had no numeric values
                              (all strings/None).

        Returns a compact dict merged into the experiment result under
        ``metrics_diagnosis`` (advisory only; never used for verdict decisions).
        """
        import re

        if not log_lines:
            return {"reason": "log_unavailable", "tail_empty": True,
                    "hint": "Log path mismatch or empty file; launch_experiment log_file "
                            "must match the file the monitor tails."}

        # If the log already parses to metrics, there is nothing to diagnose.
        if self._extract_metrics(log_lines):
            return {}

        has_result = any(re.search(r"RESULT\s+\{", line) for line in log_lines)
        if not has_result:
            return {"reason": "result_missing", "lines": len(log_lines),
                    "hint": "Training script never printed a structured 'RESULT {...}' "
                            "line; add one (e.g. print('RESULT ' + json.dumps(metrics))) "
                            "or rely on regex-parseable 'accuracy=...' text."}

        # RESULT present but contained no numeric values (all strings/None).
        return {"reason": "result_no_numeric", "lines": len(log_lines),
                "hint": "RESULT line existed but had no numeric values; emit floats "
                        "(e.g. validation_accuracy as 0.98, not '98%')."}

    def _notify_completion(self, result: dict):
        """Send notification when experiment finishes (success or failure)."""
        outcome = result.get("status", "completed").upper()
        logger.info(
            f"EXPERIMENT {outcome} | PID={result['pid']} | "
            f"Time={result['elapsed_hours']:.1f}h | "
            f"State={result.get('terminal_state', '?')} | "
            f"Metrics={result.get('metrics', {})}"
        )
