"""
AutoResearcher 实验监控器

核心创新点：实验训练期间**零 LLM 调用**。

当模型训练（数小时/数天）时，监控器只做三件事：
- 进程存活检查
- 读取日志尾部
- GPU 利用率检查

这意味着让 AutoResearcher 7×24 小时运行的成本，与只在 THINK（思考）和
REFLECT（反思）阶段运行的成本完全相同。
"""

import json
import logging
import shlex
import time
from typing import Optional

from .execution import ExecutionBackend, LocalExecutionBackend

logger = logging.getLogger("autodl.monitor")


class ExperimentMonitor:
    """零 LLM 实验监控。

    设计原则：训练期间，智能体实质上是在“零成本睡眠”，只有当训练完成、
    需要分析结果时才被唤醒（发起 LLM 调用）。
    """

    def __init__(
        self,
        poll_interval: int = 900,
        zero_llm: bool = True,
        backend: Optional[ExecutionBackend] = None,
        budget: Optional[dict] = None,
    ):
        self.poll_interval = poll_interval  # 两次检查之间的秒数
        self.zero_llm = zero_llm
        self.backend = backend or LocalExecutionBackend(".")
        self._active_experiments: dict[int, dict] = {}
        # 契约：可选预算（mode/limit/hard_wall_clock_limit/enforced）。
        # 旧模式（无预算）保留原先的无限制等待行为。
        self.budget = budget or {}
        # 训练内早停（train 级）：从实时日志解析逐轮验证指标，当模型停止提升
        # （进入平台期）时提前终止运行，避免浪费 GPU 时间。默认关闭（旧行为）。
        # 配置位于 budget 块下：
        #   budget.early_stop.{enabled, patience, improvement_tol, min_epochs, metric}
        es = (self.budget or {}).get("early_stop") or {}
        self.early_stop_enabled = bool(es.get("enabled", False))
        self.early_stop_patience = int(es.get("patience", 3))
        self.early_stop_tol = float(es.get("improvement_tol", 1e-4))
        self.early_stop_min_epochs = int(es.get("min_epochs", 5))
        self.early_stop_metric = str(es.get("metric", "validation_accuracy"))
        # 早停指标的方向："higher_better"（准确率）或 "lower_better"（loss）。
        # 决定如何判断“提升”与“平台期”。默认 higher_better 保留旧行为。
        self.early_stop_direction = str(es.get("direction", "higher_better"))
        self._early_stopped = False

    def _extract_epoch_metrics(self, log_lines: list[str], metric: str) -> list[float]:
        """从实时日志提取 ``metric`` 的逐轮数值序列。

        同时兼容结构化的 ``RESULT {...}`` 逐轮快照与旧式 ``key=value`` /
        ``epoch N ... metric=...`` 文本形式。返回按时间排序的 float 列表
        （最早在前）；找不到时返回空列表。
        """
        import re
        values: list[float] = []
        # 结构化 RESULT 快照可能逐轮携带该指标
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
        # 旧式正则匹配：`metric=0.98`、`metric: 0.98`、`metric 0.98`
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
        """训练内早停：若验证指标在连续 ``patience`` 个 epoch 内进入平台期
        （改进幅度未超容差），则终止运行以节省 GPU。

        返回 True 表示已触发早停。在积累到 ``min_epochs`` 个观测之前绝不触发
        （以尊重早期波动阶段），且仅考虑 ``early_stop_metric`` 指定的指标。
        """
        if not self.early_stop_enabled:
            return False
        seq = self._extract_epoch_metrics(log_lines, self.early_stop_metric)
        if len(seq) < self.early_stop_min_epochs:
            return False
        lower_better = self.early_stop_direction == "lower_better"
        best = min(seq) if lower_better else max(seq)
        # 平台期：最近的 `patience` 个 epoch 相对运行最优值的改进都没超过容差。
        #   higher_better：值停留在 [best - tol, ...]（没出现新最优）
        #   lower_better： 值停留在 [..., best + tol]（loss 没再下降）
        sustained = 0
        for v in reversed(seq):
            if lower_better:
                plateau = v <= best + self.early_stop_tol
            else:
                plateau = v >= best - self.early_stop_tol
            if plateau:
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
        """通过 nohup 启动实验并跟踪其 PID。

        参数：
            command: 要运行的训练命令
            log_file: stdout/stderr 重定向路径
            gpu: CUDA_VISIBLE_DEVICES 的值

        返回：
            包含 pid、log_file、start_time 的字典
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
        """等待实验完成。等待期间**零 LLM 调用**。

        这是核心的省成本机制：与其问 LLM“训练结束了吗”，不如直接检查进程
        是否还活着。
        """
        logger.info(f"Monitoring PID={pid}, polling every {self.poll_interval}s")

        hard_limit = float(self.budget.get("hard_wall_clock_limit") or 0)
        started = self._active_experiments.get(pid, {}).get("start_time", time.time())

        while self._is_process_alive(pid):
            time.sleep(self.poll_interval)

            # 记录当前状态（不涉及 LLM）
            gpu_info = self._safe_gpu_status()
            log_tail = self._safe_tail_file(log_file, lines=5)
            elapsed = time.time() - started

            # 契约：硬挂钟兜底。若进程存活超过配置的硬上限，则杀掉它，避免
            # 无界烧钱。（poll_interval 约束的是发现延迟，而非预算本身。）
            if hard_limit > 0 and elapsed >= hard_limit:
                logger.warning(
                    f"PID={pid} exceeded hard_wall_clock_limit={hard_limit:.0f}s; "
                    f"terminating to enforce experiment budget"
                )
                self._terminate(pid)
                break

            # 训练内早停（train 级）：当逐轮验证指标进入平台期时提前终止，
            # 避免把 GPU 浪费在无法再提升的 epoch 上。读取实时日志尾部（无 LLM）。
            if self.early_stop_enabled:
                try:
                    if self._check_in_run_early_stop(pid, self._safe_tail_file(log_file, lines=200)):
                        self._early_stopped = True
                        break
                except Exception as exc:  # pragma: no cover - 建议性，绝不崩溃
                    logger.warning(f"in-run early-stop check failed: {exc}")

            logger.info(
                f"PID={pid} alive | elapsed={elapsed/3600:.1f}h | "
                f"GPU={gpu_info.get('utilization', 'N/A')} | "
                f"last_log: {log_tail[-1] if log_tail else 'N/A'}"
            )

        # 实验结束（或被硬杀）—— 向 backend 询问真实的运行结果。Slurm 报告
        # sacct 终止态；仅基于 pid 的 backend 返回 unknown，此时改用预算/耗时分类。
        elapsed = time.time() - started
        log_tail = self._safe_tail_file(log_file, lines=50)

        final = self._safe_final_status(pid)
        success = final.get("success")

        # 契约：在激活的预算下对运行分类（无预算时为建议性 -> SUCCESS/TIMEOUT；
        # 强制预算时给出完整状态）。
        from .experiment_contract import classify_run_outcome
        active_seconds = self._extract_active_train_seconds(log_tail)
        terminated = "crash" if success is False else "completed"
        contract_status = classify_run_outcome(
            active_seconds or elapsed, self.budget, terminated=terminated
        )
        # 向后兼容的 `status`：与以前一样是 "completed"/"failed"。新增的
        # `contract_status`（SUCCESS/BUDGET_EXCEEDED/TIMEOUT/CRASH）是增量字段，
        # 仅在配置了预算时才具参考意义。
        status = "failed" if success is False else "completed"

        if pid in self._active_experiments:
            self._active_experiments[pid]["status"] = status

        metrics = self._extract_metrics(log_tail)
        # E：空指标诊断。一个*已完成*却未产出任何指标的运行，本身就是一个值得
        # 暴露的信号（它曾导致 INCOMPARABLE 洪水），因此附上一段精简诊断，
        # 供 loop 反馈给代码智能体。
        metrics_diagnosis = {}
        if not metrics and status == "completed":
            try:
                metrics_diagnosis = self._diagnose_empty_metrics(log_tail)
            except Exception as exc:  # pragma: no cover - 诊断绝不能崩溃
                logger.warning(f"metrics diagnosis failed: {exc}")
        # 训练内早停把运行标记为一次“已完成、预算友好”的运行（而非崩溃）：模型
        # 到达平台期后提前结束训练。契约状态保持 SUCCESS（它确实是一次干净运行，
        # 只是更短），因此晋级闸门仍允许真正更好的早停模型被保留；`early_stopped`
        # 标志记录了这一事实。
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
        """检查是否有被跟踪的实验已结束。"""
        for pid, exp in list(self._active_experiments.items()):
            if exp["status"] == "running" and not self._is_process_alive(pid):
                exp["status"] = "completed"
                return True
        return False

    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否仍在运行（零成本）。"""
        return self.backend.is_process_alive(pid)

    def _terminate(self, pid: int) -> bool:
        """尽最大努力终止一个超出硬预算的运行。

        本地 pid：先 SIGTERM，短暂停顿宽限后 SIGKILL。Slurm backend 通过
        ``cancel`` 覆盖；否则若 backend 有 ``cancel`` 则降级调用之，没有则
        留给 OS / Slurm 的 --time 来回收。
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
        """从训练日志尾部读取 ``active_train_seconds=...``。"""
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
        # 安全读取 GPU 状态，任何异常都降级为 N/A
        try:
            return self.backend.get_gpu_status()
        except Exception:
            return {"utilization": "N/A"}

    def _safe_final_status(self, pid: int) -> dict:
        # 安全读取最终状态，不支持 final_status 的 backend 视为不确定
        try:
            return self.backend.final_status(pid) or {}
        except Exception:
            return {"state": "unknown", "success": None}

    def _safe_tail_file(self, filepath: str, lines: int = 50) -> list[str]:
        # 安全读取日志尾部，异常时返回空列表
        try:
            return self.backend.tail_file(filepath, lines=lines)
        except Exception:
            return []

    def _extract_metrics(self, log_lines: list[str]) -> dict:
        """尝试从训练日志提取常用指标。

        优先级（可靠性从高到低）：
          1. ``RESULT {...}`` —— 训练脚本结尾打印的单行 JSON（A：结构化指标契约）。
             这是权威的、对空白安全的协议，优先于各种临时的文本正则。训练脚本
             只需打印 ``RESULT {"validation_accuracy": 0.982, "test_accuracy": 0.979}``。
          2. 区分 split 的 ``key=value`` 行（validation_* / test_* / train_*）。
          3. 通用模式（向后兼容）：loss / accuracy / FGD / FID / epoch / step。

        split 职责：``validation_*`` 的值用于逐轮选择；``test_*`` 的值被加上标记，
        使下游代码能把它视为“仅独立验收”（绝不反馈给选择逻辑）。
        """
        import re

        metrics = {}
        # 1. 结构化 RESULT 契约 —— 取最后一个有效值，使其覆盖任何正则提取的值。
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
                    metrics = cleaned  # 结构化契约覆盖正则输出
        if metrics:
            return metrics

        # 2/3. 正则回退（旧式 / 非 RESULT 训练脚本）
        for line in reversed(log_lines):
            # 先匹配区分 split 的指标（validation 与 test）
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
            # 通用模式（向后兼容）
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
        """E：当一次*已完成*运行未产出任何指标时的结构化诊断。

        与其静默返回空字典（曾导致 INCOMPARABLE“无候选指标”洪水），不如
        分类提取失败的原因，使 loop 能给代码智能体可执行的反馈：
          - (none)            指标可提取 -> 返回 {}（无需诊断）。
          - result_missing:   完全没有 ``RESULT {...}`` 行，也没有正则指标 ——
                              训练脚本未输出结构化契约。
          - log_unavailable:  尾部返回空（日志路径不匹配）。
          - result_no_numeric:有 RESULT 行，但里面没有数值（全是字符串/None）。

        返回一段精简字典，并入实验结果下的 ``metrics_diagnosis``（仅建议性，
        绝不用于 verdict 决策）。
        """
        import re

        if not log_lines:
            return {"reason": "log_unavailable", "tail_empty": True,
                    "hint": "Log path mismatch or empty file; launch_experiment log_file "
                            "must match the file the monitor tails."}

        # 如果日志已能解析出指标，就没必要诊断了
        if self._extract_metrics(log_lines):
            return {}

        has_result = any(re.search(r"RESULT\s+\{", line) for line in log_lines)
        if not has_result:
            return {"reason": "result_missing", "lines": len(log_lines),
                    "hint": "Training script never printed a structured 'RESULT {...}' "
                            "line; add one (e.g. print('RESULT ' + json.dumps(metrics))) "
                            "or rely on regex-parseable 'accuracy=...' text."}

        # 有 RESULT 但没有数值（全是字符串/None）
        return {"reason": "result_no_numeric", "lines": len(log_lines),
                "hint": "RESULT line existed but had no numeric values; emit floats "
                        "(e.g. validation_accuracy as 0.98, not '98%')."}

    def _notify_completion(self, result: dict):
        """实验结束（成功或失败）时发送通知。"""
        outcome = result.get("status", "completed").upper()
        logger.info(
            f"EXPERIMENT {outcome} | PID={result['pid']} | "
            f"Time={result['elapsed_hours']:.1f}h | "
            f"State={result.get('terminal_state', '?')} | "
            f"Metrics={result.get('metrics', {})}"
        )
