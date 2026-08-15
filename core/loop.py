"""
AutoResearcher Core Loop

The autonomous THINK → EXECUTE → REFLECT cycle that drives experiments 24/7.
"""

import os
import sys
import time
import json
import signal
import argparse
import logging
from pathlib import Path
from typing import Optional

from .memory import MemoryManager
from .monitor import ExperimentMonitor
from .agents import AgentDispatcher
from .execution import build_execution_backend
from .obsidian import ObsidianExporter
from .tools import ToolRegistry
from .ledger import ExperimentLedger, detect_stagnation, check_phase_gate
from .journal import ResearchJournal
from . import safety

logger = logging.getLogger("autodl")


class ResearchLoop:
    """Main autonomous research loop.

    Implements the THINK → EXECUTE → REFLECT cycle:
    - THINK: Analyze state, form hypothesis, plan experiment
    - EXECUTE: Dispatch code agent to implement and run experiment
    - REFLECT: Evaluate results, update memory, decide next action
    """

    def __init__(self, config: dict, project_dir: str):
        self.config = config
        self.project_dir = Path(project_dir).resolve()
        self.workspace = self.project_dir / config.get("project", {}).get("workspace", "workspace")
        self.workspace.mkdir(exist_ok=True)
        self.state_path = self.workspace / "state.json"
        self.execution_backend = build_execution_backend(config=config, controller_workspace=self.workspace)
        self.execution_backend.validate()

        # Core components
        self.memory = MemoryManager(
            project_dir=self.project_dir,
            brief_max=config.get("memory", {}).get("brief_max_chars", 3000),
            log_max=config.get("memory", {}).get("log_max_chars", 2000),
            milestone_max=config.get("memory", {}).get("milestone_max_chars", 1200),
            max_recent=config.get("memory", {}).get("max_recent_entries", 15),
        )
        # A contract: carry the experiment budget (if configured) into the
        # monitor so it can enforce hard_wall_clock_limit and classify runs.
        from .experiment_contract import resolve_budget
        self._budget_eff = resolve_budget(config.get("experiment", {}))
        self.monitor = ExperimentMonitor(
            poll_interval=config.get("monitor", {}).get("poll_interval", 900),
            zero_llm=config.get("monitor", {}).get("zero_llm", True),
            backend=self.execution_backend,
            budget=self._budget_eff,
        )
        agent_config = config.get("agent", {}) or {}
        self.dispatcher = AgentDispatcher(
            model=agent_config.get("model", "claude-sonnet-4-6"),
            provider=agent_config.get("provider", "anthropic"),
            max_steps=agent_config.get("max_steps_per_cycle", 3),
            base_url=agent_config.get("base_url", ""),
            api_key_env=agent_config.get("api_key_env", ""),
            auth_token_env=agent_config.get("auth_token_env", ""),
        )
        self.tools = ToolRegistry(self.execution_backend, config=config)
        self._experiment_cfg = config.get("experiment", {}) or {}
        # A contract: validate config schema; violations are advisory warnings
        # (never crash a cycle) but surface early for operators/QA.
        if self._experiment_cfg:
            try:
                from .experiment_contract import validate_experiment_config
                violations = validate_experiment_config(self._experiment_cfg)
                for v in violations:
                    logger.warning(f"experiment contract schema violation: {v}")
            except Exception as exc:  # pragma: no cover - guard
                logger.warning(f"experiment contract validation failed: {exc}")
        self.obsidian = ObsidianExporter(
            config=config,
            project_dir=self.project_dir,
            backend=self.execution_backend,
        )

        # v2 autonomy modules: persistent experiment ledger + research journals.
        # All are additive and advisory — they enrich the THINK context but do
        # not change control flow unless explicitly enabled in config.
        self._ledger_cfg = config.get("ledger", {}) or {}
        self._stagnation_cfg = config.get("stagnation", {}) or {}
        self._journal_cfg = config.get("journal", {}) or {}
        self._safety_cfg = config.get("safety", {}) or {}
        self._gates_cfg = config.get("gates", {}) or {}
        self.ledger = (
            ExperimentLedger(self.workspace)
            if self._ledger_cfg.get("enabled", True)
            else None
        )
        self.journal = (
            ResearchJournal(self.workspace, max_chars=self._journal_cfg.get("max_chars", 4000))
            if self._journal_cfg.get("enabled", True)
            else None
        )

        # --- M2: machine-judgment (Loop Engineering) configuration ---
        # Enabled when an experiment contract declares a primary metric AND the
        # ledger is available. When disabled, the loop falls back to the legacy
        # LLM-only REFLECT path (backwards compatible).
        self._le_cfg = self._experiment_cfg.get("loop_engineering", {}) or {}
        eval_cfg = self._experiment_cfg.get("evaluation", {}) or {}
        pm = eval_cfg.get("primary_metric", {}) or {}
        self._primary_metric = str(pm.get("name") or "").strip()
        self._primary_direction = str(pm.get("direction") or "maximize")
        try:
            self._min_effect_size = float(eval_cfg.get("minimum_effect_size", 0.0))
        except (TypeError, ValueError):
            self._min_effect_size = 0.0
        # Machine judgment is authoritative only when there is a real metric to
        # compare and a ledger to record it into. Otherwise -> legacy path.
        self._machine_judge_enabled = bool(
            self._primary_metric
            and self.ledger is not None
            and self._le_cfg.get("enabled", True)
        )
        # Optional VCS controller (M3/M4). Guarded so a missing/partial vcs
        # implementation degrades to ledger-only archiving, never crashes.
        self._vcs = None
        if self._le_cfg.get("vcs", {}).get("enabled", False):
            try:
                from .git_vcs import GitExperimentVcs
                vcs_repo = Path(self._le_cfg["vcs"].get("repo", self.project_dir))
                self._vcs = GitExperimentVcs(
                    repo=vcs_repo,
                    champion_ref=self._le_cfg["vcs"].get("champion_ref", "champion/STUDY-001"),
                    candidate_ref_prefix=self._le_cfg["vcs"].get("candidate_ref_prefix", "experiment/STUDY-001"),
                )
            except Exception as exc:  # pragma: no cover - optional infra
                logger.warning(f"VCS controller unavailable; archiving to ledger only: {exc}")
                self._vcs = None

        # State
        self.cycle_count = self._load_cycle_counter()
        self.max_cycles = agent_config.get("max_cycles", -1)
        self.cooldown = agent_config.get("cooldown_interval", 300)
        self.no_progress_fallback_threshold = agent_config.get("no_progress_fallback_threshold", 3)
        # Proactive anti-burn: cap cycles started per rolling hour (0 = disabled).
        self.max_cycles_per_hour = agent_config.get("max_cycles_per_hour", 0)
        self._cycle_times_path = self.workspace / ".cycle_times"
        self._running = True
        self._no_progress_streak = 0
        self._last_no_progress_signature = ""
        # M5 convergence: track attempted hypotheses so the loop rejects repeats.
        # Config: experiment.loop_engineering.dedup.{enabled,repeated_hypothesis_limit}
        self._dedup_enabled = bool(
            self._le_cfg.get("dedup", {}).get("enabled", False)
        )
        self._repeated_hypothesis_limit = int(
            self._le_cfg.get("dedup", {}).get("repeated_hypothesis_limit", 1)
        )
        self._attempted_hypotheses: set[str] = set()
        # I1 (P0): unattended convergence/termination. When max_cycles<0 and the
        # machine loop keeps rejecting candidates, converge after N rounds with
        # no KEEP instead of looping forever. 0 disables the guard (legacy).
        convergence = self._le_cfg.get("convergence", {})
        self._conv_max_no_improvement_rounds = int(convergence.get("max_no_improvement_rounds", 10))
        self._no_improvement_streak = 0
        self._convergence_reason = ""

        # M6 self-healing: on restart, resume de-dup state from the ledger's
        # promoted candidates so already-accepted ideas are not re-proposed.
        # Best-effort; never blocks startup (legacy empty ledger is a no-op).
        if self.ledger is not None and self._dedup_enabled:
            try:
                from .resilience import recover_verdict_history
                from .safety import normalize_hypothesis
                vh = recover_verdict_history(self.ledger.all())
                for cand_sha in vh.get("promoted_candidates") or []:
                    if cand_sha:
                        self._attempted_hypotheses.add(normalize_hypothesis(cand_sha))
            except Exception as exc:  # pragma: no cover - recovery must not crash
                logger.warning(f"M6 dedup-state resume failed (continuing): {exc}")

        # Graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def run(self):
        """Main entry point. Runs the THINK → EXECUTE → REFLECT loop."""
        logger.info(f"AutoResearcher starting | project={self.project_dir} | cycle={self.cycle_count}")

        while self._running:
            if self.max_cycles > 0 and self.cycle_count >= self.max_cycles:
                logger.info(f"Reached max cycles ({self.max_cycles}). Stopping.")
                break

            self._throttle_if_needed()
            if not self._running:
                break

            self.cycle_count += 1
            self._save_cycle_counter()
            logger.info(f"=== Cycle {self.cycle_count} ===")

            try:
                # Keep leader context bounded to one cycle.
                self.dispatcher.reset_leader_history()

                # Check for human directive
                directive = self._consume_directive()
                self._update_state(
                    {
                        "cycle": self.cycle_count,
                        "status": "planning",
                        "updated_at": time.time(),
                        "last_directive": directive or "",
                    }
                )

                # THINK: Analyze and plan
                think_result = self._think(directive)
                think_result = self._apply_hypothesis_dedup(think_result)
                think_result = self._apply_no_progress_fallback(think_result, directive)

                if think_result.get("action") == "wait":
                    logger.info("THINK decided to wait. Entering cooldown.")
                    self._update_state(
                        {
                            "cycle": self.cycle_count,
                            "status": "waiting",
                            "updated_at": time.time(),
                            "suggested_next_step": think_result.get("reason", ""),
                        }
                    )
                    self._smart_cooldown()
                    continue

                # EXECUTE: Run the plan
                execute_result = self._execute(think_result)

                if execute_result.get("experiment_launched"):
                    self._update_state(
                        {
                            "cycle": self.cycle_count,
                            "status": "running",
                            "pid": execute_result.get("pid"),
                            "log_file": execute_result.get("log_file", ""),
                            "started_at": time.time(),
                            "updated_at": time.time(),
                        }
                    )
                    # Monitor experiment (zero LLM cost)
                    monitor_result = self._monitor_experiment(execute_result)
                    experiment_status = monitor_result.get("status", "completed")
                    execute_result["training_logs"] = monitor_result.get("log_tail", "")
                    execute_result["final_metrics"] = monitor_result.get("metrics", {})
                    execute_result["experiment_status"] = experiment_status
                    execute_result["terminal_state"] = monitor_result.get("terminal_state", "")
                    self._update_state(
                        {
                            "status": experiment_status,
                            "pid": execute_result.get("pid"),
                            "log_file": execute_result.get("log_file", ""),
                            "updated_at": time.time(),
                            "terminal_state": monitor_result.get("terminal_state", ""),
                            "last_training_logs": monitor_result.get("log_tail", ""),
                            "last_metrics": monitor_result.get("metrics", {}),
                            "elapsed_hours": monitor_result.get("elapsed_hours"),
                        }
                    )

                # REFLECT: Evaluate and update. M2 runs a machine judgment BEFORE
                # the LLM reflection so the verdict is authoritative; the LLM's
                # narrative is only a hypothesis/explanation and can never
                # override the machine's KEEP/DISCARD/INCOMPARABLE decision.
                machine_judgment = self._machine_judge(execute_result)
                reflect_result = self._reflect(execute_result, machine_judgment=machine_judgment)
                self._update_state(
                    {
                        "cycle": self.cycle_count,
                        "updated_at": time.time(),
                        "last_milestone": reflect_result.get("milestone", ""),
                        "last_decision": reflect_result.get("decision", ""),
                        "suggested_next_step": reflect_result.get("decision")
                        or reflect_result.get("reason")
                        or reflect_result.get("task", ""),
                        "last_error": "",
                    }
                )
                self._record_cycle_outcome(think_result, execute_result, reflect_result)
                self._record_to_ledger(think_result, execute_result, reflect_result)
                self._refresh_obsidian(reflect_result=reflect_result, directive=directive)

                # I1 (P0): unattended convergence. When running without a hard
                # max_cycles cap, converge if the machine loop keeps finding no
                # real improvement (or the no-progress escalation reaches
                # terminate). Records an auditable reason and stops the loop.
                if self.max_cycles < 0:
                    if self._conv_max_no_improvement_rounds > 0 and \
                            self._no_improvement_streak >= self._conv_max_no_improvement_rounds:
                        self._convergence_reason = (
                            f"converged: no machine-verified improvement (KEEP) for "
                            f"{self._no_improvement_streak} consecutive rounds "
                            f"(limit {self._conv_max_no_improvement_rounds})"
                        )
                        logger.warning(self._convergence_reason)
                        self.memory.log_decision(f"Cycle {self.cycle_count}: {self._convergence_reason}")
                        self._running = False
                        break
                    escalation = think_result.get("no_progress_escalation")
                    if escalation == "terminate":
                        self._convergence_reason = (
                            f"converged: no-progress escalation reached 'terminate'"
                        )
                        logger.warning(self._convergence_reason)
                        self.memory.log_decision(f"Cycle {self.cycle_count}: {self._convergence_reason}")
                        self._running = False
                        break

            except Exception as e:
                logger.error(f"Cycle {self.cycle_count} failed: {e}", exc_info=True)
                self.memory.log_decision(f"Cycle {self.cycle_count} error: {str(e)[:200]}")
                self._update_state(
                    {
                        "cycle": self.cycle_count,
                        "status": "error",
                        "updated_at": time.time(),
                        "last_error": str(e)[:500],
                    }
                )
                self._cooldown_after_error()

        logger.info("AutoResearcher stopped.")

    def _think(self, directive: Optional[str] = None) -> dict:
        """THINK phase: analyze current state and plan next experiment."""
        logger.info("THINK phase starting...")

        context = {
            "brief": self.memory.get_brief(),
            "memory_log": self.memory.get_log(),
            "cycle": self.cycle_count,
            "directive": directive,
        }
        self._enrich_context(context)

        result = self.dispatcher.dispatch_leader(
            task="think",
            context=context,
        )

        logger.info(f"THINK result: action={result.get('action', 'unknown')}")
        return result

    def _execute(self, plan: dict) -> dict:
        """EXECUTE phase: implement and run the planned experiment."""
        logger.info("EXECUTE phase starting...")

        agent_type = plan.get("agent", "code")
        task_description = plan.get("task", "")

        result = self.dispatcher.dispatch_worker(
            agent_type=agent_type,
            task=task_description,
            tool_registry=self.tools,
        )

        return result

    def _monitor_experiment(self, execute_result: dict) -> dict:
        """Monitor running experiment with ZERO LLM calls."""
        pid = execute_result.get("pid")
        log_file = execute_result.get("log_file")

        if not pid:
            return {"status": "no_pid"}

        logger.info(f"Monitoring experiment PID={pid}, log={log_file}")
        return self.monitor.wait_for_completion(
            pid=pid,
            log_file=log_file,
            notify=self.config.get("monitor", {}).get("notify_on_complete", True),
        )

    def _machine_judge(self, execute_result: dict) -> Optional[dict]:
        """M2 machine-judgment loop: produce an authoritative KEEP/DISCARD/
        INCOMPARABLE verdict BEFORE the LLM reflection runs.

        Flow (all failures degrade gracefully, never crash the main loop):
          1. Skip (return None) when M2 is disabled or no experiment was run
             -> the legacy LLM-only REFLECT path is preserved.
          2. Read candidate metrics + ``contract_status`` from the monitor result.
          3. Archive candidate artifacts (build_artifact_manifest) if a VCS
             controller is available — archive before decide.
          4. Resolve champion metrics (ledger best metric, else configured).
          5. Call ``decide_verdict`` and gate it by ``contract_status``.
          6. Record the verdict to the ledger + write it to memory/state.

        The returned dict is machine-authoritative; LLM narrative cannot override
        it. Returns None to fall back to legacy reflection.
        """
        if not self._machine_judge_enabled:
            return None
        if not execute_result.get("experiment_launched"):
            return None

        metrics = execute_result.get("final_metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        # Prefer the monitor's real contract_status (SUCCESS/BUDGET_EXCEEDED/
        # TIMEOUT/CRASH). Legacy paths carry only `experiment_status`
        # ("completed"/"failed"): map those to SUCCESS / CRASH so the gate works.
        contract_status = execute_result.get("contract_status")
        if not contract_status:
            legacy_status = (execute_result.get("experiment_status") or "").lower()
            contract_status = "CRASH" if legacy_status == "failed" else "SUCCESS"
        contract_status = str(contract_status).upper()

        # Nothing to compare if the candidate produced no metrics -> INCOMPARABLE.
        verdict = {"verdict": "INCOMPARABLE", "reason": "no candidate metrics", "delta": None}

        champion_metrics = self._resolve_champion_metrics()
        if metrics:
            try:
                from .experiment_contract import decide_verdict, gate_verdict_by_contract_status
                # P3: pass measured noise so the effective bar is raised above
                # measurement noise (effective = max(config, 2*noise_std)).
                noise_std = self._le_cfg.get("noise_std", 0.0)
                raw = decide_verdict(
                    candidate_metrics=metrics,
                    champion_metrics=champion_metrics,
                    primary_metric=self._primary_metric,
                    direction=self._primary_direction,
                    minimum_effect_size=self._min_effect_size,
                    noise_std=noise_std,
                )
                # Hard-gate by contract status: a crashed/timed-out/budget-killed
                # run is never KEEP even if metrics happen to look good.
                verdict = gate_verdict_by_contract_status(raw, contract_status)
            except Exception as exc:
                logger.warning(f"M2 decide_verdict failed; falling back to INCOMPARABLE: {exc}")
                verdict = {"verdict": "INCOMPARABLE", "reason": f"decide_verdict error: {exc}", "delta": None}

        # --- M4: archive before decide (best-effort, ledger fallback) ---
        artifact_manifest_uri = ""
        candidate_sha = ""
        champion_before_sha = self._champion_sha()
        try:
            manifest_uri, candidate_sha = self._archive_candidate_artifacts(execute_result, verdict)
            artifact_manifest_uri = manifest_uri
        except Exception as exc:
            logger.warning(f"M2 artifact archive failed (continuing to ledger): {exc}")

        # --- promotion side effect (M3, best-effort) ---
        promotion_status = ""
        if verdict.get("verdict") == "KEEP" and candidate_sha:
            promotion_status = self._try_promote(candidate_sha, champion_before_sha)

        machine = dict(verdict)
        machine["promotion_status"] = promotion_status
        machine["artifact_manifest_uri"] = artifact_manifest_uri
        machine["candidate_sha"] = candidate_sha
        machine["champion_before_sha"] = champion_before_sha
        machine["metrics"] = metrics
        machine["contract_status"] = contract_status
        machine["primary_metric"] = self._primary_metric

        self._record_verdict(machine)

        # I1: track consecutive rounds with no machine-verified improvement so the
        # unattended loop can converge instead of looping forever.
        if machine.get("verdict") == "KEEP":
            self._no_improvement_streak = 0
        else:
            self._no_improvement_streak += 1

        # Write machine verdict into durable memory + state (facts, not narrative).
        self.memory.log_decision(
            f"M2 verdict cycle={self.cycle_count}: {machine['verdict']} "
            f"(contract={contract_status}, {machine.get('reason', '')})"
        )
        state = self._load_state()
        state["verdict"] = machine.get("verdict")
        state["promotion_status"] = promotion_status
        state["last_verdict"] = machine
        state["no_improvement_streak"] = self._no_improvement_streak
        self.state_path.write_text(json.dumps(state, indent=2))

        logger.info(f"M2 machine verdict cycle={self.cycle_count}: {machine['verdict']} (contract={contract_status})")
        return machine

    # --- M2 helpers ----------------------------------------------------------

    def _resolve_champion_metrics(self) -> dict:
        """Best-known champion metrics for the primary metric.

        Prefers the ledger's best metric; otherwise returns an empty dict, which
        makes decide_verdict return INCOMPARABLE until a champion exists.
        """
        if self.ledger is not None and self._primary_metric:
            try:
                direction = "higher_better" if self._primary_direction == "maximize" else "lower_better"
                best = self.ledger.best_metric(self._primary_metric, direction=direction)
                if best is not None:
                    return {self._primary_metric: best}
            except Exception as exc:
                logger.warning(f"M2 champion metric resolve failed: {exc}")
        return {}

    def _champion_sha(self) -> str:
        """Current champion SHA for ledger versioning (best-effort)."""
        if self._vcs is not None:
            try:
                from .git_vcs import head_sha
                return head_sha(self._vcs.repo, self._vcs.champion_ref)
            except Exception as exc:
                logger.warning(f"M2 champion sha unavailable: {exc}")
        return ""

    def _archive_candidate_artifacts(self, execute_result: dict, verdict: dict) -> tuple[str, str]:
        """Archive candidate artifacts into an immutable manifest (M4).

        Returns ``(manifest_uri, candidate_sha)``. Falls back to a ledger-manifest
        (no git) when the VCS controller is absent or the worktree is unavailable.
        """
        experiment_id = str(execute_result.get("pid") or self.cycle_count)
        log_path = None
        if execute_result.get("log_file"):
            lp = Path(execute_result["log_file"])
            if lp.exists():
                log_path = lp
        metrics = execute_result.get("final_metrics") or {}

        if self._vcs is not None:
            # Prefer the isolated candidate worktree; otherwise snapshot from the
            # controller workspace log so archiving still happens before decide.
            wt = None
            for candidate in (self.workspace / "candidates").iterdir() if (self.workspace / "candidates").is_dir() else []:
                if candidate.is_dir() and candidate.name.endswith(experiment_id):
                    wt = candidate
                    break
            if wt is not None:
                manifest = self._vcs.build_artifact_manifest(
                    experiment_id=experiment_id,
                    worktree=wt,
                    metrics=metrics,
                    log_file=log_path,
                )
                candidate_sha = manifest.get("candidate_sha", "")
                uri = f"artifacts/{experiment_id}/manifest.json"
                # persist the manifest JSON under the workspace for reproducibility
                manifest_path = self.workspace / "artifacts" / experiment_id / "manifest.json"
                try:
                    import json as _json
                    manifest_path.parent.mkdir(parents=True, exist_ok=True)
                    manifest_path.write_text(_json.dumps(manifest, indent=2, default=str))
                except OSError as exc:
                    logger.warning(f"M2 manifest persist failed: {exc}")
                return uri, candidate_sha

        # Ledger-manifest fallback: archive facts without git (never blocks decide).
        try:
            manifest = {
                "experiment_id": experiment_id,
                "metrics": metrics,
                "verdict": verdict.get("verdict"),
                "contract_status": verdict.get("contract_status"),
                "log_file": str(log_path) if log_path else "",
            }
            manifest_path = self.workspace / "artifacts" / experiment_id / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
            return f"artifacts/{experiment_id}/manifest.json", ""
        except OSError as exc:
            logger.warning(f"M2 ledger-manifest archive failed: {exc}")
            return "", ""

    def _try_promote(self, candidate_sha: str, expected_parent_sha: str) -> str:
        """Best-effort M3 promotion (fast-forward only). Degrades to a no-op when
        the VCS controller is absent or the parent is stale."""
        if self._vcs is None:
            return "PROMOTION_SKIPPED_NO_VCS"
        try:
            result = self._vcs.promote_to_champion(candidate_sha, expected_parent_sha)
            if result.get("ok"):
                return "PROMOTED"
            return f"PROMOTION_DEFERRED:{result.get('reason', 'UNKNOWN')}"
        except Exception as exc:
            logger.warning(f"M2 promotion skipped: {exc}")
            return "PROMOTION_SKIPPED"

    def _record_verdict(self, machine: dict):
        """Persist the machine verdict to the append-only ledger (M4)."""
        if self.ledger is None:
            return
        try:
            self.ledger.record_verdict(
                cycle=self.cycle_count,
                experiment_id=str(machine.get("candidate_sha") or self.cycle_count),
                metrics=machine.get("metrics") or {},
                verdict=machine.get("verdict", ""),
                champion_before_sha=machine.get("champion_before_sha", ""),
                candidate_sha=machine.get("candidate_sha", ""),
                promotion_status=machine.get("promotion_status", ""),
                artifact_manifest_uri=machine.get("artifact_manifest_uri", ""),
                reason=machine.get("reason", ""),
            )
        except Exception as exc:
            logger.warning(f"M2 verdict ledger record failed: {exc}")

    def _reflect(self, execute_result: dict, machine_judgment: Optional[dict] = None) -> dict:
        """REFLECT phase: evaluate results and update memory.

        When ``machine_judgment`` is present (M2 active), it is the authoritative
        decision. The LLM's reflection is reduced to a hypothesis/explanation and
        is only recorded as narrative — it can never override the machine verdict.
        """
        logger.info("REFLECT phase starting...")

        context = {
            "brief": self.memory.get_brief(),
            "memory_log": self.memory.get_log(),
            "experiment_result": execute_result,
            "cycle": self.cycle_count,
        }
        self._enrich_context(context)
        # Surface the machine verdict to the leader as non-overridable facts.
        if machine_judgment:
            context["machine_verdict"] = machine_judgment
            context["llm_narrative_can_override"] = False

        result = self.dispatcher.dispatch_leader(
            task="reflect",
            context=context,
        )

        # M2: the machine verdict is authoritative — fold it into the reflected
        # decision so downstream state/ledger reflect reality, not LLM opinion.
        if machine_judgment and machine_judgment.get("verdict"):
            mv = machine_judgment
            verdict = mv["verdict"]
            reason = mv.get("reason") or ""
            result["verdict"] = verdict
            result["promotion_status"] = mv.get("promotion_status", "")
            result["decision"] = f"[machine:{verdict}] {reason}".strip()
            # LLM narrative is kept as an explanation only.
            if result.get("decision"):
                result["narrative"] = result.get("milestone") or result.get("decision")

        # Update memory based on reflection
        if result.get("milestone"):
            self.memory.log_milestone(result["milestone"])
        if result.get("decision"):
            self.memory.log_decision(result["decision"])

        return result

    def _refresh_obsidian(self, reflect_result: dict, directive: Optional[str]):
        if not self.obsidian.is_enabled():
            return
        self.obsidian.refresh_dashboard(memory=self.memory, cycle_count=self.cycle_count)
        self.obsidian.append_daily_entry(
            memory=self.memory,
            cycle_count=self.cycle_count,
            event_type="cycle_complete",
            reflection=reflect_result,
            directive=directive,
        )

    def _plan_signature(self, plan: dict) -> str:
        """Build a stable signature for repeated-plan detection."""
        normalized = {
            "action": plan.get("action", ""),
            "agent": plan.get("agent", ""),
            "task": " ".join(plan.get("task", "").split())[:300],
            "hypothesis": " ".join(plan.get("hypothesis", "").split())[:200],
        }
        return json.dumps(normalized, sort_keys=True, ensure_ascii=True)

    def _apply_hypothesis_dedup(self, think_result: dict) -> dict:
        """M5 convergence: reject repeated hypotheses before they are executed.

        If hypothesis de-duplication is enabled and the THINK plan repeats an
        already-attempted idea, inject a duplicate advisory into the context and
        record the key — so the loop converges instead of burning budget on the
        same experiment. When disabled or no hypothesis is present, this is a
        no-op (legacy behavior preserved).
        """
        if not self._dedup_enabled:
            return think_result
        hypothesis = think_result.get("hypothesis") or think_result.get("task") or ""
        if not hypothesis:
            return think_result
        try:
            from .safety import check_hypothesis_dedup
            decision = check_hypothesis_dedup(
                hypothesis, self._attempted_hypotheses, self._repeated_hypothesis_limit
            )
            self._attempted_hypotheses.add(decision["key"])
            if not decision["allowed"]:
                reason = decision["reason"] or "duplicate hypothesis"
                logger.warning(f"M5 dedup blocked: {reason}")
                self.memory.log_decision(f"Cycle {self.cycle_count}: {reason}")
                # Inject the advisory so the next THINK tries a different idea.
                think_result = dict(think_result)
                think_result["hypothesis_dedup_blocked"] = True
                think_result["hypothesis_dedup_reason"] = reason
                # Return wait so the loop cools down and the leader re-plans with
                # the advisory in context rather than executing a repeat.
                think_result["action"] = "wait"
                think_result["reason"] = reason
        except Exception as exc:  # pragma: no cover - convergence must not crash
            logger.warning(f"M5 dedup check failed (continuing): {exc}")
        return think_result

    def _apply_no_progress_fallback(self, think_result: dict, directive: Optional[str]) -> dict:
        """Back off if the same experiment plan keeps repeating without progress."""
        if directive or self.no_progress_fallback_threshold <= 0:
            return think_result

        if think_result.get("action") != "experiment":
            return think_result

        signature = self._plan_signature(think_result)
        if (
            self._no_progress_streak >= self.no_progress_fallback_threshold
            and signature == self._last_no_progress_signature
        ):
            # M5 escalation: translate the streak into a concrete next action.
            escalation = "normal"
            escalation_advice = ""
            try:
                from .safety import escalate_no_progress
                esc = escalate_no_progress(self._no_progress_streak)
                escalation = esc.get("level", "normal")
                escalation_advice = esc.get("advice", "")
            except Exception as exc:  # pragma: no cover - advisory only
                logger.warning(f"M5 escalation failed (continuing with default): {exc}")

            reason = (
                f"Fallback triggered after {self._no_progress_streak} no-progress cycles on the same plan. "
                "Backing off to avoid empty loops until new signal arrives."
            )
            logger.warning(reason)
            self.memory.log_decision(reason)
            if self.journal is not None:
                task_text = " ".join(think_result.get("task", "").split())[:160]
                self.journal.append_dead_end(
                    f"Cycle {self.cycle_count}: repeated with no progress — {task_text}"
                )
            return {
                "action": "wait",
                "reason": reason,
                "decision": reason,
                "no_progress_escalation": escalation,
                "no_progress_advice": escalation_advice,
            }

        return think_result

    def _record_cycle_outcome(self, think_result: dict, execute_result: dict, reflect_result: dict):
        """Track whether repeated cycles are producing real progress."""
        if think_result.get("action") != "experiment":
            if think_result.get("action") != "wait":
                self._no_progress_streak = 0
                self._last_no_progress_signature = ""
            return

        signature = self._plan_signature(think_result)
        made_progress = bool(
            execute_result.get("experiment_launched")
            or execute_result.get("final_metrics")
            or reflect_result.get("milestone")
        )

        if made_progress:
            self._no_progress_streak = 0
            self._last_no_progress_signature = ""
            return

        if signature == self._last_no_progress_signature:
            self._no_progress_streak += 1
        else:
            self._last_no_progress_signature = signature
            self._no_progress_streak = 1

    def _enrich_context(self, context: dict):
        """Add advisory v2 signals (ledger / stagnation / journals / violations /
        gate) to a leader context dict. All keys are optional and only added when
        the corresponding feature is enabled and has something to report."""
        if self.ledger is not None:
            try:
                summary = self.ledger.summary(self._ledger_cfg.get("recent_in_context", 5))
                if summary:
                    context["recent_experiments"] = summary
            except Exception as exc:  # never let context-building break a cycle
                logger.warning(f"ledger summary failed: {exc}")

            # M2/M5/M6: rebuild the machine-verdict history from the ledger so the
            # leader can avoid re-proposing hypotheses already judged (dedup) and
            # resume from the last verdict. Pure; ledger is the single source of
            # truth even if state.json is corrupt/missing.
            try:
                from .resilience import recover_verdict_history
                vh = recover_verdict_history(self.ledger.all())
                if vh.get("last_verdict"):
                    context["last_verdict"] = vh["last_verdict"]
                if vh.get("verdicts"):
                    context["verdict_history"] = vh["verdicts"]
                if vh.get("promoted_candidates"):
                    context["promoted_candidates"] = vh["promoted_candidates"]
            except Exception as exc:  # never let context-building break a cycle
                logger.warning(f"verdict history rebuild failed: {exc}")

            metric_key = self._ledger_cfg.get("metric_key", "")
            direction = self._ledger_cfg.get("metric_direction", "higher_better")

            if metric_key and self._stagnation_cfg.get("enabled", True):
                try:
                    verdict = detect_stagnation(
                        self.ledger.all(),
                        metric_key,
                        direction=direction,
                        threshold_cycles=self._stagnation_cfg.get("threshold_cycles", 3),
                        min_delta=self._stagnation_cfg.get("min_delta", 0.0),
                    )
                    context["progress_signal"] = self._format_stagnation(verdict)
                except Exception as exc:
                    logger.warning(f"stagnation detection failed: {exc}")

            if metric_key and self._gates_cfg.get("enabled", False):
                try:
                    gate = check_phase_gate(
                        self.ledger.all(),
                        metric_key,
                        threshold=self._gates_cfg.get("threshold", 0.0),
                        direction=self._gates_cfg.get("direction", direction),
                    )
                    context["phase_gate"] = self._format_gate(gate)
                except Exception as exc:
                    logger.warning(f"phase gate check failed: {exc}")

        if self.journal is not None:
            try:
                tail_chars = int(self._journal_cfg.get("tail_in_context", 1500))
                dead_ends = self.journal.dead_ends_tail(tail_chars)
                if "- [" in dead_ends:
                    context["dead_ends"] = dead_ends.strip()
                insights = self.journal.insights_tail(tail_chars)
                if "- [" in insights:
                    context["insights"] = insights.strip()
            except Exception as exc:  # never let an advisory signal break a cycle
                logger.warning(f"journal tail failed: {exc}")

        if self._safety_cfg.get("enabled", True):
            try:
                violations = safety.scan_violations(
                    self._load_state(),
                    self._no_progress_streak,
                    time.time(),
                    fail_threshold=self._safety_cfg.get("fail_threshold", 3),
                    stale_state_hours=self._safety_cfg.get("stale_state_hours", 6),
                )
                if violations:
                    context["active_violations"] = "\n".join(f"- {v}" for v in violations)
            except Exception as exc:
                logger.warning(f"violation scan failed: {exc}")

    @staticmethod
    def _format_stagnation(verdict: dict) -> str:
        if verdict.get("reason"):
            return f"{verdict['reason']} (metric={verdict.get('metric_key', '')})"
        flag = "STAGNATING" if verdict.get("stagnating") else "improving"
        return (
            f"{flag}: best {verdict.get('metric_key')}={verdict.get('best')}, "
            f"{verdict.get('cycles_since_improvement')} cycle(s) since last improvement "
            f"over {verdict.get('n_points')} measured runs."
        )

    @staticmethod
    def _format_gate(gate: dict) -> str:
        if gate.get("gate_met"):
            return f"Phase gate MET (best metric={gate.get('best_metric')}). OK to pursue innovation."
        return f"Phase gate NOT met: {gate.get('blocker_reason', 'baseline quality not reached')}."

    def _record_to_ledger(self, think_result: dict, execute_result: dict, reflect_result: dict):
        """Append this cycle's outcome to the experiment ledger and capture a
        durable insight when the reflection produced a milestone."""
        if self.ledger is None:
            return
        metrics = execute_result.get("final_metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        if execute_result.get("experiment_launched"):
            # Prefer the monitor's real outcome (completed / failed) over a
            # generic "launched" so the ledger reflects what actually happened.
            status = execute_result.get("experiment_status") or "launched"
        else:
            status = think_result.get("action", "") or "no_experiment"
        terminal_state = execute_result.get("terminal_state", "")
        conclusion = reflect_result.get("milestone") or reflect_result.get("decision", "")
        if status == "failed" and terminal_state:
            conclusion = (f"[{terminal_state}] " + conclusion).strip()
        try:
            self.ledger.record(
                cycle=self.cycle_count,
                hypothesis=think_result.get("hypothesis") or think_result.get("task", ""),
                action=think_result.get("action", ""),
                status=status,
                metrics=metrics,
                pid=execute_result.get("pid"),
                log_file=execute_result.get("log_file", ""),
                conclusion=conclusion,
            )
        except Exception as exc:
            logger.warning(f"ledger record failed: {exc}")

        if self.journal is not None and reflect_result.get("milestone"):
            self.journal.append_insight(reflect_result["milestone"])

    def _load_cycle_times(self) -> list:
        if self._cycle_times_path.exists():
            try:
                data = json.loads(self._cycle_times_path.read_text())
                if isinstance(data, list):
                    return [float(t) for t in data]
            except (json.JSONDecodeError, ValueError, TypeError):
                return []
        return []

    def _save_cycle_times(self, timestamps: list):
        try:
            self._cycle_times_path.write_text(json.dumps(timestamps))
        except OSError as exc:  # pragma: no cover - disk failure path
            logger.warning(f"failed to persist cycle times: {exc}")

    def _throttle_if_needed(self):
        """Proactive anti-burn: sleep so the agent never exceeds
        max_cycles_per_hour. No-op (and no state writes) when disabled."""
        if not self.max_cycles_per_hour or self.max_cycles_per_hour <= 0:
            return
        now = time.time()
        timestamps = self._load_cycle_times()
        wait = safety.seconds_until_allowed(timestamps, now, self.max_cycles_per_hour)
        if wait > 0:
            logger.warning(
                f"Anti-burn: {self.max_cycles_per_hour} cycles/hour reached; "
                f"throttling for {int(wait)}s"
            )
            elapsed = 0.0
            while elapsed < wait and self._running:
                chunk = min(30.0, wait - elapsed)
                time.sleep(chunk)
                elapsed += chunk
            now = time.time()
        timestamps = safety.prune_timestamps(timestamps, now)
        timestamps.append(now)
        self._save_cycle_times(timestamps)

    def _smart_cooldown(self):
        """Poll at short intervals instead of fixed long wait."""
        logger.info(f"Smart cooldown: polling every {self.cooldown}s")
        elapsed = 0
        while elapsed < self.cooldown and self._running:
            time.sleep(min(60, self.cooldown - elapsed))
            elapsed += 60

            # Check if any experiment just finished
            if self.monitor.has_completed_experiments():
                logger.info("Experiment completed during cooldown. Waking up.")
                return

    def _cooldown_after_error(self):
        """Back off after an error to prevent burn loops."""
        backoff = min(self.cooldown * 2, 1800)  # Max 30 min
        logger.warning(f"Error backoff: waiting {backoff}s")
        time.sleep(backoff)

    def _consume_directive(self) -> Optional[str]:
        """Read and consume HUMAN_DIRECTIVE.md if present."""
        directive_path = self.workspace / "HUMAN_DIRECTIVE.md"
        if directive_path.exists():
            content = directive_path.read_text().strip()
            if content:
                # Archive the directive
                archive_dir = self.workspace / "directive_archive"
                archive_dir.mkdir(exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                directive_path.rename(archive_dir / f"directive_{timestamp}.md")
                logger.info(f"Consumed directive: {content[:100]}...")
                return content
        return None

    def _load_cycle_counter(self) -> int:
        counter_file = self.workspace / ".cycle_counter"
        if counter_file.exists():
            return int(counter_file.read_text().strip())
        return 0

    def _save_cycle_counter(self):
        counter_file = self.workspace / ".cycle_counter"
        counter_file.write_text(str(self.cycle_count))

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _update_state(self, updates: dict):
        state = self._load_state()
        state.update(updates)
        self.state_path.write_text(json.dumps(state, indent=2))

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}. Initiating graceful shutdown.")
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="AutoResearcher - Autonomous ML Experiment Agent")
    parser.add_argument("--project", type=str, required=True, help="Path to project directory")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config file path")
    parser.add_argument("--max-cycles", type=int, default=None, help="Override max cycles")
    parser.add_argument("--gpu", type=str, default=None, help="GPU device(s) to use")
    parser.add_argument("--check", action="store_true", help="Verify installation and exit")

    args = parser.parse_args()

    if args.check:
        print("AutoResearcher installation check:")
        print(f"  Python: {sys.version}")
        print(f"  Project: {args.project}")
        print("  Status: OK")
        return

    # Load config
    import yaml
    config_path = Path(args.project) / args.config
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        config = {}

    if args.max_cycles is not None:
        config.setdefault("agent", {})["max_cycles"] = args.max_cycles

    if args.gpu is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path(args.project) / "autodl.log"),
        ],
    )

    # Run
    loop = ResearchLoop(config=config, project_dir=args.project)
    loop.run()


if __name__ == "__main__":
    main()
