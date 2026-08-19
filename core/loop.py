"""
AutoResearcher 核心循环

驱动实验 7×24 小时自主运行的 THINK → EXECUTE → REFLECT 周期。
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
# 进度快照导出（progress snapshot）为可选功能：为消除对核心循环的静态依赖
# （B 解耦），此处不在顶层硬 import，而在 _refresh_snapshots 中按需惰性导入；
# 若导入失败（例如未安装 yaml 等），则以 self.obsidian=None 禁用导出。
# note: 模块已从 core/obsidian.py 重命名为 core/snapshots.py；保留 obsidian 模块
# 名作为兼容回退入口，优先使用新名字 snapshots。
try:  # pragma: no cover - 依环境
    from . import snapshots as _obsidian_mod  # noqa: F401
except Exception:  # pragma: no cover - 依赖缺失守卫
    try:
        from . import obsidian as _obsidian_mod  # noqa: F401
    except Exception:
        _obsidian_mod = None

from .tools import ToolRegistry
from .ledger import ExperimentLedger, detect_stagnation, check_phase_gate
from .journal import ResearchJournal
from . import safety

logger = logging.getLogger("autodl")


class ResearchLoop:
    """自主研究主循环。

    实现 THINK → EXECUTE → REFLECT 周期：
    - THINK（思考）：分析状态、形成假设、规划实验
    - EXECUTE（执行）：派发 code 智能体实现并运行实验
    - REFLECT（反思）：评估结果、更新记忆、决定下一步动作
    """

    def __init__(self, config: dict, project_dir: str):
        self.config = config
        self.project_dir = Path(project_dir).resolve()
        # 工作区目录（controller 与实验数据的根）
        self.workspace = self.project_dir / config.get("project", {}).get("workspace", "workspace")
        self.workspace.mkdir(exist_ok=True)
        self.state_path = self.workspace / "state.json"
        # 构造执行后端（local/ssh/slurm）并校验可达性
        self.execution_backend = build_execution_backend(config=config, controller_workspace=self.workspace)
        self.execution_backend.validate()

        # 核心组件：记忆管理器（两层）
        self.memory = MemoryManager(
            project_dir=self.project_dir,
            brief_max=config.get("memory", {}).get("brief_max_chars", 3000),
            log_max=config.get("memory", {}).get("log_max_chars", 2000),
            milestone_max=config.get("memory", {}).get("milestone_max_chars", 1200),
            max_recent=config.get("memory", {}).get("max_recent_entries", 15),
        )
        # A 契约：把实验预算（若已配置）传入 monitor，使其能强制 hard_wall_clock_limit
        # 并对运行做分类。
        from .experiment_contract import resolve_budget
        self._budget_eff = resolve_budget(config.get("experiment", {}))
        self.monitor = ExperimentMonitor(
            poll_interval=config.get("monitor", {}).get("poll_interval", 900),
            zero_llm=config.get("monitor", {}).get("zero_llm", True),
            backend=self.execution_backend,
            budget=self._budget_eff,
        )
        agent_config = config.get("agent", {}) or {}
        # 智能体调度器（Leader-Worker 架构）
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
        # A 契约：校验 config schema；违规仅作建议性警告（绝不使周期崩溃），
        # 但尽早暴露给运维 / QA。
        if self._experiment_cfg:
            try:
                from .experiment_contract import validate_experiment_config
                violations = validate_experiment_config(self._experiment_cfg)
                for v in violations:
                    logger.warning(f"experiment contract schema violation: {v}")
            except Exception as exc:  # pragma: no cover - 守卫
                logger.warning(f"experiment contract validation failed: {exc}")
        # 进度导出（obsidian Dashboard / per-exp 快照）为可选功能：禁用或模块
        # 不可导入时置 None，绝不因导出功能阻塞核心循环（B+C 解耦）。
        obsidian_cfg = config.get("obsidian", {}) or {}
        obsidian_enabled = bool(obsidian_cfg.get("enabled", False))
        self.obsidian_records_dir = self.workspace / obsidian_cfg.get(
            "local_fallback_dir", "progress_tracking"
        )
        self.obsidian = None
        if obsidian_enabled and _obsidian_mod is not None:
            try:
                # 类已由 ObsidianExporter 重命名为 SnapshotExporter；保留旧名兼容回退。
                exporter_cls = getattr(
                    _obsidian_mod, "SnapshotExporter",
                    getattr(_obsidian_mod, "ObsidianExporter", None),
                )
                if exporter_cls is None:
                    self.obsidian = None
                else:
                    self.obsidian = exporter_cls(
                        config=config,
                        project_dir=self.project_dir,
                        backend=self.execution_backend,
                    )
            except Exception as exc:  # pragma: no cover - 守卫
                logger.warning(f"obsidian exporter init failed, disabled: {exc}")
                self.obsidian = None

        # v2 自主模块：持久实验账本 + 研究日志。全部为增量、建议性——
        # 它们丰富 THINK 上下文，但除非在 config 中显式启用，不改变控制流。
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

        # --- M2：机器裁决（Loop Engineering）配置 ---
        # 当实验契约声明了主指标且账本可用时启用。否则回退到旧的纯 LLM REFLECT 路径
        # （向后兼容）。
        self._le_cfg = self._experiment_cfg.get("loop_engineering", {}) or {}
        eval_cfg = self._experiment_cfg.get("evaluation", {}) or {}
        pm = eval_cfg.get("primary_metric", {}) or {}
        self._primary_metric = str(pm.get("name") or "").strip()
        self._primary_direction = str(pm.get("direction") or "maximize")
        try:
            self._min_effect_size = float(eval_cfg.get("minimum_effect_size", 0.0))
        except (TypeError, ValueError):
            self._min_effect_size = 0.0
        # 机器裁决只有在存在可比较的真实指标且账本可用时才是权威的，否则走旧路径。
        self._machine_judge_enabled = bool(
            self._primary_metric
            and self.ledger is not None
            and self._le_cfg.get("enabled", True)
        )
        # 可选 VCS 控制器（M3/M4）。加守卫，实现缺失/不完整时降级为仅账本归档，不崩溃。
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
            except Exception as exc:  # pragma: no cover - 可选基础设施
                logger.warning(f"VCS controller unavailable; archiving to ledger only: {exc}")
                self._vcs = None

        # 状态
        self.cycle_count = self._load_cycle_counter()
        self.max_cycles = agent_config.get("max_cycles", -1)
        self.cooldown = agent_config.get("cooldown_interval", 300)
        self.no_progress_fallback_threshold = agent_config.get("no_progress_fallback_threshold", 3)
        # 主动式防烧钱：每小时启动周期数的上限（0 = 禁用）
        self.max_cycles_per_hour = agent_config.get("max_cycles_per_hour", 0)
        self._cycle_times_path = self.workspace / ".cycle_times"
        self._running = True
        self._no_progress_streak = 0
        self._last_no_progress_signature = ""
        # M5 收敛：记录已尝试的假设，使循环拒绝重复
        self._dedup_enabled = bool(
            self._le_cfg.get("dedup", {}).get("enabled", False)
        )
        self._repeated_hypothesis_limit = int(
            self._le_cfg.get("dedup", {}).get("repeated_hypothesis_limit", 1)
        )
        self._attempted_hypotheses: set[str] = set()
        # I1 (P0)：无人值守收敛/终止。当 max_cycles<0 且机器循环持续拒绝候选时，
        # 在连续 N 轮无 KEEP 后收敛，而非无限循环。0 禁用该守卫（旧行为）。
        convergence = self._le_cfg.get("convergence", {})
        self._conv_max_no_improvement_rounds = int(convergence.get("max_no_improvement_rounds", 10))
        self._no_improvement_streak = 0
        self._convergence_reason = ""

        # 早停（活跃饱和检测）。不只等待 `max_no_improvement_rounds` 个 DISCARD 累积，
        # 而是从机器 verdict（候选反复落在冠军下方噪声带内的平台期）与 Leader 停滞
        # （连续多轮未发起实验）检测饱和。除非配置，否则禁用。
        es = self._le_cfg.get("early_stop", {})
        self._early_stop_enabled = bool(es.get("enabled", False))
        self._early_saturation_rounds = int(es.get("saturation_rounds", 3))
        self._early_plateau_band = float(es.get("plateau_band", 2.0))
        self._early_max_no_experiment = int(es.get("max_consecutive_no_experiment", 3))
        self._recent_verdicts: list[dict] = []   # 机器 verdict 的滚动窗口
        self._consecutive_no_experiment = 0

        # M6 自愈：重启时从账本的已晋级候选恢复去重状态，使已被接受的想法不被重新提出。
        # 尽力而为，绝不阻塞启动（旧空账本为 no-op）。
        if self.ledger is not None and self._dedup_enabled:
            try:
                from .resilience import recover_verdict_history
                from .safety import normalize_hypothesis
                vh = recover_verdict_history(self.ledger.all())
                for cand_sha in vh.get("promoted_candidates") or []:
                    if cand_sha:
                        self._attempted_hypotheses.add(normalize_hypothesis(cand_sha))
            except Exception as exc:  # pragma: no cover - 恢复绝不能崩溃
                logger.warning(f"M6 dedup-state resume failed (continuing): {exc}")

        # 优雅关闭：注册信号处理器
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def run(self):
        """主入口。运行 THINK → EXECUTE → REFLECT 循环。"""
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
                # 保持 Leader 上下文限定在单个周期内
                self.dispatcher.reset_leader_history()

                # 检查人工指令（HUMAN_DIRECTIVE.md）
                directive = self._consume_directive()
                self._update_state(
                    {
                        "cycle": self.cycle_count,
                        "status": "planning",
                        "updated_at": time.time(),
                        "last_directive": directive or "",
                    }
                )

                # THINK：分析与规划
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

                # EXECUTE：运行计划
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
                    # 监控实验（零 LLM 成本）
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

                # REFLECT：评估与更新。M2 在 LLM 反思**之前**运行机器裁决，使 verdict
                # 具有权威性；LLM 的叙述只是假设/解释，绝不能推翻机器的
                # KEEP/DISCARD/INCOMPARABLE 决策。
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

                # I1 (P0)：无人值守收敛。当没有硬性 max_cycles 上限时，若机器循环持续
                # 找不到真实改进（或 no-progress 升级达到 terminate），则记录可审计的
                # 原因并停止循环。
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

                    # 早停：活跃饱和 + Leader 停滞检测
                    if self._early_stop_enabled:
                        stop_reason = self._early_stop_reason(think_result, execute_result)
                        if stop_reason:
                            self._convergence_reason = stop_reason
                            logger.warning(stop_reason)
                            self.memory.log_decision(
                                f"Cycle {self.cycle_count}: {stop_reason}"
                            )
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
        """THINK 阶段：分析当前状态并规划下一个实验。"""
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
        """EXECUTE 阶段：实现并运行规划好的实验。"""
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
        """以零 LLM 调用监控运行中的实验。"""
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
        """M2 机器裁决循环：在 LLM 反思运行**之前**产生权威的 KEEP/DISCARD/
        INCOMPARABLE verdict。

        流程（所有失败都优雅降级，绝不使主循环崩溃）：
          1. 当 M2 禁用或未运行实验时跳过（返回 None）-> 保留旧的纯 LLM REFLECT 路径。
          2. 从 monitor 结果读取候选指标 + ``contract_status``。
          3. 若 VCS 控制器可用，则归档候选制品（build_artifact_manifest）——先归档后决策。
          4. 解析冠军指标（账本最佳，否则配置值）。
          5. 调用 ``decide_verdict`` 并用 ``contract_status`` 做闸门。
          6. 把 verdict 记入账本 + 写入记忆/状态。

        返回的 dict 是机器权威的；LLM 叙述无法覆盖。返回 None 则回退到旧反思路径。
        """
        if not self._machine_judge_enabled:
            return None
        if not execute_result.get("experiment_launched"):
            return None

        metrics = execute_result.get("final_metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        # 优先采用 monitor 的真实 contract_status（SUCCESS/BUDGET_EXCEEDED/TIMEOUT/CRASH）。
        # 旧路径只携带 `experiment_status`（"completed"/"failed"）：映射到 SUCCESS / CRASH，
        # 使闸门同样生效。
        contract_status = execute_result.get("contract_status")
        if not contract_status:
            legacy_status = (execute_result.get("experiment_status") or "").lower()
            contract_status = "CRASH" if legacy_status == "failed" else "SUCCESS"
        contract_status = str(contract_status).upper()

        # 候选未产出任何指标 -> INCOMPARABLE
        verdict = {"verdict": "INCOMPARABLE", "reason": "no candidate metrics", "delta": None}

        champion_metrics = self._resolve_champion_metrics()
        if metrics:
            try:
                from .experiment_contract import decide_verdict, gate_verdict_by_contract_status
                # P3：传入测量噪声，使有效门槛抬升至测量噪声之上
                #（effective = max(配置值, 2*noise_std)）。
                noise_std = self._le_cfg.get("noise_std", 0.0)
                raw = decide_verdict(
                    candidate_metrics=metrics,
                    champion_metrics=champion_metrics,
                    primary_metric=self._primary_metric,
                    direction=self._primary_direction,
                    minimum_effect_size=self._min_effect_size,
                    noise_std=noise_std,
                )
                # 按 contract_status 做硬闸门：崩溃/超时/预算耗尽的运行的指标即便好看，
                # 也绝不 KEEP。
                verdict = gate_verdict_by_contract_status(raw, contract_status)
            except Exception as exc:
                logger.warning(f"M2 decide_verdict failed; falling back to INCOMPARABLE: {exc}")
                verdict = {"verdict": "INCOMPARABLE", "reason": f"decide_verdict error: {exc}", "delta": None}

        # --- M4：先归档后决策（尽力而为，账本降级）---
        artifact_manifest_uri = ""
        candidate_sha = ""
        champion_before_sha = self._champion_sha()
        try:
            manifest_uri, candidate_sha = self._archive_candidate_artifacts(execute_result, verdict)
            artifact_manifest_uri = manifest_uri
        except Exception as exc:
            logger.warning(f"M2 artifact archive failed (continuing to ledger): {exc}")

        # --- 晋级副作用（M3，尽力而为）---
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

        # I1：跟踪连续无机器验证改进的轮数，使无人值守循环能收敛而非无限循环。
        if machine.get("verdict") == "KEEP":
            self._no_improvement_streak = 0
        else:
            self._no_improvement_streak += 1

        # 早停：把 verdict（含 delta + 噪声）记入滚动窗口供活跃饱和检测。
        # 无论结果如何，发起过的实验都会重置 Leader 停滞计数器。
        if self._early_stop_enabled:
            self._recent_verdicts.append({
                "verdict": machine.get("verdict"),
                "delta": machine.get("delta"),
                "noise_std": self._le_cfg.get("noise_std", 0.0),
                "cycle": self.cycle_count,
            })
            if len(self._recent_verdicts) > max(self._early_saturation_rounds * 2, 6):
                self._recent_verdicts = self._recent_verdicts[-6:]
            self._consecutive_no_experiment = 0

        # 把机器 verdict 写入持久记忆 + 状态（事实，而非叙述）。
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

    # --- M2 辅助方法 ----------------------------------------------------------

    def _resolve_champion_metrics(self) -> dict:
        """主指标当前已知最佳的冠军指标。

        优先用账本最佳；否则返回空 dict，使 decide_verdict 在未建立冠军前返回
        INCOMPARABLE。
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
        """当前冠军 SHA（供账本版本化，尽力而为）。"""
        if self._vcs is not None:
            try:
                from .git_vcs import head_sha
                return head_sha(self._vcs.repo, self._vcs.champion_ref)
            except Exception as exc:
                logger.warning(f"M2 champion sha unavailable: {exc}")
        return ""

    def _archive_candidate_artifacts(self, execute_result: dict, verdict: dict) -> tuple[str, str]:
        """把候选制品归档进不可变清单（M4）。

        返回 ``(manifest_uri, candidate_sha)``。当 VCS 控制器缺失或 worktree 不可用时，
        降级为账本清单（无 git）。
        """
        experiment_id = str(execute_result.get("pid") or self.cycle_count)
        log_path = None
        if execute_result.get("log_file"):
            lp = Path(execute_result["log_file"])
            if lp.exists():
                log_path = lp
        metrics = execute_result.get("final_metrics") or {}

        if self._vcs is not None:
            # 优先用隔离的候选 worktree；否则从 controller 工作区日志快照，
            # 使归档仍发生在决策之前。
            wt = None
            candidates_dir = self.workspace / "candidates"
            for candidate in (candidates_dir.iterdir() if candidates_dir.is_dir() else []):
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
                # 把 manifest JSON 持久化到工作区以便复现
                manifest_path = self.workspace / "artifacts" / experiment_id / "manifest.json"
                try:
                    manifest_path.parent.mkdir(parents=True, exist_ok=True)
                    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
                except OSError as exc:
                    logger.warning(f"M2 manifest persist failed: {exc}")
                return uri, candidate_sha

        # 账本清单降级：无 git 也归档事实（绝不阻塞决策）。
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
        """尽力而为的 M3 晋级（仅快进）。当 VCS 控制器缺失或父 SHA 过期时降级为 no-op。"""
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
        """把机器 verdict 持久化进只追加账本（M4）。"""
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
        """REFLECT 阶段：评估结果并更新记忆。

        当 ``machine_judgment`` 存在（M2 激活）时，它是权威决策。LLM 的反思被降级为
        假设/解释，仅作为叙述被记录——绝不能推翻机器 verdict。
        """
        logger.info("REFLECT phase starting...")

        context = {
            "brief": self.memory.get_brief(),
            "memory_log": self.memory.get_log(),
            "experiment_result": execute_result,
            "cycle": self.cycle_count,
        }
        self._enrich_context(context)
        # 把机器 verdict 作为不可覆盖的事实暴露给 Leader。
        if machine_judgment:
            context["machine_verdict"] = machine_judgment
            context["llm_narrative_can_override"] = False

        result = self.dispatcher.dispatch_leader(
            task="reflect",
            context=context,
        )

        # M2：机器 verdict 是权威的——把它并回反思决策中，使下游 state/账本反映现实
        # 而非 LLM 意见。
        if machine_judgment and machine_judgment.get("verdict"):
            mv = machine_judgment
            verdict = mv["verdict"]
            reason = mv.get("reason") or ""
            result["verdict"] = verdict
            result["promotion_status"] = mv.get("promotion_status", "")
            result["decision"] = f"[machine:{verdict}] {reason}".strip()
            # LLM 叙述仅作为解释保留。
            if result.get("decision"):
                result["narrative"] = result.get("milestone") or result.get("decision")

        # 基于反思更新记忆
        if result.get("milestone"):
            self.memory.log_milestone(result["milestone"])
        if result.get("decision"):
            self.memory.log_decision(result["decision"])

        return result

    def _refresh_obsidian(self, reflect_result: dict, directive: Optional[str]):
        """刷新进度导出：per-exp 快照（B+C）+ 全局 Dashboard 总览索引。

        本地快照（progress_tracking/）始终写入（不依赖 obsidian vault）；
        若已配置并启用 Obsidian vault，则额外刷新 Dashboard/Daily 到 vault。
        """
        # 1) 每实验一份独立快照（exp_{cycle}_{pid}.md），数据来自自有 ledger。
        if _obsidian_mod is not None and self.ledger is not None:
            try:
                entries = self.ledger.all()
                # 命名收敛（选项1）：把一个实验的多条记录（launch+verdict）聚合成
                # 一份快照，实现「一个实验一个文件」。
                for entry in _obsidian_mod.merge_entries_by_cycle(entries):
                    _obsidian_mod.write_experiment_snapshot(
                        self.obsidian_records_dir, entry
                    )
                # 2) 生成全局总览索引 Dashboard.md（仅作为索引，不覆写 vault 版）。
                index = _obsidian_mod.build_dashboard_index(self.obsidian_records_dir)
                index_path = self.obsidian_records_dir / "Dashboard.md"
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(index, encoding="utf-8")
            except Exception as exc:  # pragma: no cover - 导出失败不阻塞循环
                logger.warning(f"progress snapshot refresh failed: {exc}")
        # 3) 若启用 Obsidian vault，则额外刷新 Dashboard/Daily（保留原有能力）。
        if self.obsidian is not None and self.obsidian.is_enabled():
            try:
                self.obsidian.refresh_dashboard(memory=self.memory, cycle_count=self.cycle_count)
                self.obsidian.append_daily_entry(
                    memory=self.memory,
                    cycle_count=self.cycle_count,
                    event_type="cycle_complete",
                    reflection=reflect_result,
                    directive=directive,
                )
            except Exception as exc:  # pragma: no cover - 导出失败不阻塞循环
                logger.warning(f"obsidian dashboard refresh failed: {exc}")

    def _plan_signature(self, plan: dict) -> str:
        """为重复计划检测构建稳定签名。"""
        normalized = {
            "action": plan.get("action", ""),
            "agent": plan.get("agent", ""),
            "task": " ".join(plan.get("task", "").split())[:300],
            "hypothesis": " ".join(plan.get("hypothesis", "").split())[:200],
        }
        return json.dumps(normalized, sort_keys=True, ensure_ascii=True)

    def _apply_hypothesis_dedup(self, think_result: dict) -> dict:
        """M5 收敛：在执行前拒绝重复假设。

        若启用了假设去重，且 THINK 计划重复了已尝试的想法，则把去重建议注入上下文
        并记录 key——使循环收敛而非在同一实验上烧预算。禁用或无假设时为 no-op
        （保留旧行为）。
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
                # 注入建议使下一次 THINK 尝试不同想法。
                think_result = dict(think_result)
                think_result["hypothesis_dedup_blocked"] = True
                think_result["hypothesis_dedup_reason"] = reason
                # 返回 wait，让循环冷却，Leader 携带建议重新规划，而非执行重复实验。
                think_result["action"] = "wait"
                think_result["reason"] = reason
        except Exception as exc:  # pragma: no cover - 收敛绝不能崩溃
            logger.warning(f"M5 dedup check failed (continuing): {exc}")
        return think_result

    def _apply_no_progress_fallback(self, think_result: dict, directive: Optional[str]) -> dict:
        """若同一实验计划反复无进展，则退避。"""
        if directive or self.no_progress_fallback_threshold <= 0:
            return think_result

        if think_result.get("action") != "experiment":
            return think_result

        signature = self._plan_signature(think_result)
        if (
            self._no_progress_streak >= self.no_progress_fallback_threshold
            and signature == self._last_no_progress_signature
        ):
            # M5 升级：把 streak 翻译成具体的下一步动作。
            escalation = "normal"
            escalation_advice = ""
            try:
                from .safety import escalate_no_progress
                esc = escalate_no_progress(self._no_progress_streak)
                escalation = esc.get("level", "normal")
                escalation_advice = esc.get("advice", "")
            except Exception as exc:  # pragma: no cover - 仅建议性
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

    def _early_stop_reason(self, think_result: dict, execute_result: dict) -> str:
        """活跃早停检测（两个触发器），应在循环提前收敛时返回原因字符串，否则返回 ''。

        触发器 A —— Leader 停滞：Leader 连续 ``max_consecutive_no_experiment`` 轮未发起
        实验（report/wait/其他非实验动作，或发起但从未真正启动的实验）。这正好捕获了
        E2E 中观察到的故障：饱和的 Leader 不断输出报告而非实验，循环永远碰不到
        DISCARD 连击阈值，只能手动杀掉。

        触发器 B —— 饱和平台期：机器循环产出了 ``saturation_rounds`` 个连续 DISCARD
        verdict，且其 delta 全部落在冠军下方噪声带内（|delta| <= plateau_band*noise_std）。
        这意味着候选不断落在冠军周围的平台期、无法实质改进，继续搜索是浪费预算。
        需要存在一个非空冠军（一个真实的比较基准）。

        早停未启用或没有触发器触发时返回 ''（不停止）。
        """
        if not self._early_stop_enabled:
            return ""

        # --- 触发器 A：Leader 停滞（未真正发起实验）---
        experiment_launched = bool(
            (execute_result or {}).get("experiment_launched")
        )
        if experiment_launched:
            self._consecutive_no_experiment = 0
        else:
            self._consecutive_no_experiment += 1
        if self._early_max_no_experiment > 0 and \
                self._consecutive_no_experiment >= self._early_max_no_experiment:
            return (
                f"converged (early-stop): leader launched no experiment for "
                f"{self._consecutive_no_experiment} consecutive rounds "
                f"(limit {self._early_max_no_experiment}); no active exploration"
            )

        # --- 触发器 B：来自机器 verdict 的饱和平台期 ---
        if self._early_saturation_rounds <= 0:
            return ""
        recent = self._recent_verdicts[-self._early_saturation_rounds:]
        if len(recent) < self._early_saturation_rounds:
            return ""
        # 要求已建立真实冠军（避免在首个 INCOMPARABLE 运行、基线存在前就停止）。
        has_champion = bool(self._resolve_champion_metrics())
        if not has_champion:
            return ""
        all_discard = all(
            r.get("verdict") == "DISCARD" and isinstance(r.get("delta"), (int, float))
            for r in recent
        )
        if not all_discard:
            return ""
        # 所有 delta 都在冠军周围的噪声平台带内。
        within_band = all(
            abs(float(r["delta"])) <= self._early_plateau_band * float(r.get("noise_std") or 0.0)
            + 1e-12
            for r in recent
        )
        if within_band:
            return (
                f"converged (early-stop): {self._early_saturation_rounds} consecutive "
                f"machine DISCARD verdicts with deltas within the noise plateau "
                f"(band {self._early_plateau_band}*noise_std); champion appears saturated"
            )
        return ""

    def _record_cycle_outcome(self, think_result: dict, execute_result: dict, reflect_result: dict):
        """跟踪重复周期是否产生了真实进展。"""
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
        """向 Leader 上下文字典追加建议性的 v2 信号（账本 / 停滞 / 日志 / 违规 /
        闸门）。所有键都是可选的，只在对应功能启用且有内容可报告时才添加。"""
        if self.ledger is not None:
            try:
                summary = self.ledger.summary(self._ledger_cfg.get("recent_in_context", 5))
                if summary:
                    context["recent_experiments"] = summary
            except Exception as exc:  # 绝不因构建上下文而中断周期
                logger.warning(f"ledger summary failed: {exc}")

            # M2/M5/M6：从账本重建机器 verdict 历史，使 Leader 能避免重新提出已判定
            # 的假设（去重）并从最后 verdict 恢复。纯函数；账本是唯一事实来源，即便
            # state.json 损坏/缺失也是如此。
            try:
                from .resilience import recover_verdict_history
                vh = recover_verdict_history(self.ledger.all())
                if vh.get("last_verdict"):
                    context["last_verdict"] = vh["last_verdict"]
                if vh.get("verdicts"):
                    context["verdict_history"] = vh["verdicts"]
                if vh.get("promoted_candidates"):
                    context["promoted_candidates"] = vh["promoted_candidates"]
            except Exception as exc:  # 绝不因构建上下文而中断周期
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
            except Exception as exc:  # 绝不因建议性信号而中断周期
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

        # E：暴露结构化的空指标诊断，使 REFLECT 阶段的 Leader 能把可执行的修复
        # （输出 RESULT 行 / 修正日志路径）交给下一个 code 智能体，而非静默重复失败运行。
        try:
            er = context.get("experiment_result") or {}
            if isinstance(er, dict) and not (er.get("final_metrics") or {}):
                diag = er.get("metrics_diagnosis") or {}
                if isinstance(diag, dict) and diag.get("reason"):
                    context["metrics_feedback"] = (
                        "Last run produced NO metrics. Diagnosis: "
                        f"{diag.get('reason')}. Hint: {diag.get('hint', '')}"
                    )
        except Exception as exc:  # pragma: no cover - 仅建议性
            logger.warning(f"metrics feedback failed: {exc}")

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
        """把本轮结果追加进实验账本；当反思产出里程碑时捕获一条持久洞察。"""
        if self.ledger is None:
            return
        metrics = execute_result.get("final_metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        if execute_result.get("experiment_launched"):
            # 优先采用 monitor 的真实结果（completed / failed），而非泛化的 "launched"，
            # 使账本反映实际发生的事。
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
        except OSError as exc:  # pragma: no cover - 磁盘故障路径
            logger.warning(f"failed to persist cycle times: {exc}")

    def _throttle_if_needed(self):
        """主动式防烧钱：睡眠以控制循环绝不超出 max_cycles_per_hour。禁用时为 no-op
        （且不写状态）。"""
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
        """以短间隔轮询，而非固定长等待。"""
        logger.info(f"Smart cooldown: polling every {self.cooldown}s")
        elapsed = 0
        while elapsed < self.cooldown and self._running:
            time.sleep(min(60, self.cooldown - elapsed))
            elapsed += 60

            # 检查是否有实验刚结束
            if self.monitor.has_completed_experiments():
                logger.info("Experiment completed during cooldown. Waking up.")
                return

    def _cooldown_after_error(self):
        """出错后退避，防止烧钱循环。"""
        backoff = min(self.cooldown * 2, 1800)  # 最长 30 分钟
        logger.warning(f"Error backoff: waiting {backoff}s")
        time.sleep(backoff)

    def _consume_directive(self) -> Optional[str]:
        """若 HUMAN_DIRECTIVE.md 存在则读取并消费（消费后归档）。"""
        directive_path = self.workspace / "HUMAN_DIRECTIVE.md"
        if directive_path.exists():
            content = directive_path.read_text().strip()
            if content:
                # 归档指令
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

    # 加载配置
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

    # 配置日志。A：框架自身的日志流路由经过稳定、线程安全的 loguru 框架
    # （见 core.logging_setup）。下面的标准库 basicConfig 保留为优雅降级与文件处理器；
    # 当可用时 configure_logging 把 "autodl" 日志树桥接到 loguru，否则为 no-op。
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path(args.project) / "autodl.log"),
        ],
    )
    try:
        from .logging_setup import configure_logging
        configure_logging(
            level=str(config.get("logging", {}).get("level", "INFO")),
            serialize=bool(config.get("logging", {}).get("serialize", False)),
        )
    except Exception as exc:  # pragma: no cover - 日志绝不能阻塞启动
        logging.getLogger("autodl").warning(f"loguru setup failed; using stdlib logging: {exc}")

    # 运行
    loop = ResearchLoop(config=config, project_dir=args.project)
    loop.run()


if __name__ == "__main__":
    main()
