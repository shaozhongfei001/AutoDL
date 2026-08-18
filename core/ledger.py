"""
实验账本（Experiment ledger）—— 记录每一次研究周期的只追加日志。

以 ``workspace/experiments.jsonl`` 形式存储（每行一个 JSON 对象）。只追加的
设计意味着：它能在控制器崩溃后存活、永远不需要“解析-重写”、并且以零 LLM
成本保持人类与工具都可读。几个轻量的纯 Python 读取函数（``recent`` /
``summary`` / ``best_metric`` / ``detect_stagnation`` / ``check_phase_gate``）
把原始轨迹转化为紧凑信号，由主循环注入到 THINK 上下文。

这是 v2 的脊梁：关于“试过什么、发生了什么”的持久记忆——这正是此前的智能体
所缺失的（两层 MEMORY_LOG 会自动压缩，导致细节被静默丢弃）。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autodl.ledger")


class ExperimentLedger:
    """实验周期的只追加 JSONL 账本。"""

    def __init__(self, workspace: Path, filename: str = "experiments.jsonl"):
        self.path = Path(workspace) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        cycle: int,
        hypothesis: str = "",
        action: str = "",
        status: str = "",
        metrics: Optional[dict] = None,
        pid: Optional[int] = None,
        log_file: str = "",
        conclusion: str = "",
        ts: Optional[float] = None,
        # --- ADR-002 版本化字段（可选，向后兼容） ---
        champion_before_sha: str = "",
        candidate_sha: str = "",
        champion_after_sha: str = "",
        verdict: str = "",
        promotion_status: str = "",
        artifact_manifest_uri: str = "",
    ) -> Optional[dict]:
        """追加一条周期结果。永不抛异常——日志失败绝不能让研究循环崩溃。"""
        entry = {
            "ts": time.time() if ts is None else float(ts),
            "cycle": int(cycle),
            "action": str(action or ""),
            "status": str(status or ""),
            "hypothesis": str(hypothesis or "")[:500],
            "metrics": {k: v for k, v in (metrics or {}).items()},
            "pid": pid,
            "log_file": str(log_file or ""),
            "conclusion": str(conclusion or "")[:500],
            # 版本化字段（使用旧路径时为空）
            "champion_before_sha": str(champion_before_sha or ""),
            "candidate_sha": str(candidate_sha or ""),
            "champion_after_sha": str(champion_after_sha or ""),
            "verdict": str(verdict or ""),
            "promotion_status": str(promotion_status or ""),
            "artifact_manifest_uri": str(artifact_manifest_uri or ""),
        }
        try:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:  # pragma: no cover - 磁盘故障分支
            logger.warning(f"Failed to append to experiment ledger: {exc}")
            return None
        return entry

    def record_verdict(
        self,
        *,
        cycle: int,
        experiment_id: str = "",
        metrics: Optional[dict] = None,
        verdict: str = "",
        champion_before_sha: str = "",
        candidate_sha: str = "",
        champion_after_sha: str = "",
        promotion_status: str = "",
        artifact_manifest_uri: str = "",
        reason: str = "",
    ) -> Optional[dict]:
        """向账本追加一条晋级 verdict 事件（只追加）。

        ``verdict`` 取值为 KEEP / DISCARD / CRASH / INCOMPARABLE 之一。机器决策
        具有权威性；``reason`` 可携带数值依据，从而无需 LLM 也能审计。
        """
        return self.record(
            cycle=cycle,
            action=f"verdict:{experiment_id}",
            status=f"verdict_{verdict.lower()}" if verdict else "verdict",
            metrics=metrics,
            conclusion=f"{verdict}: {reason}".strip(),
            champion_before_sha=champion_before_sha,
            candidate_sha=candidate_sha,
            champion_after_sha=champion_after_sha,
            verdict=verdict,
            promotion_status=promotion_status,
            artifact_manifest_uri=artifact_manifest_uri,
        )

    def all(self) -> list[dict]:
        """返回每一条格式良好的记录；格式错误的行会被跳过。"""
        if not self.path.exists():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    def recent(self, n: int = 5) -> list[dict]:
        # 返回最近 n 条记录
        n = int(n)
        return self.all()[-n:] if n > 0 else []

    def summary(self, n: int = 5) -> str:
        """把最近 ``n`` 次实验渲染成紧凑的上下文块。"""
        entries = self.recent(n)
        if not entries:
            return ""
        lines = []
        for e in entries:
            metrics = e.get("metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            metric_str = ", ".join(f"{k}={v}" for k, v in metrics.items()) or "no metrics"
            hypo = (e.get("hypothesis") or "").strip()
            if len(hypo) > 160:
                hypo = hypo[:157] + "..."
            status = e.get("status") or e.get("action") or "?"
            line = f"- cycle {e.get('cycle', '?')} [{status}] {hypo} ({metric_str})"
            conclusion = (e.get("conclusion") or "").strip()
            if conclusion:
                conclusion = conclusion[:160]
                line += f" -> {conclusion}"
            lines.append(line)
        return "\n".join(lines)

    def best_metric(self, metric_key: str, direction: str = "higher_better") -> Optional[float]:
        # 取某指标的历史最佳值
        return best_metric(self.all(), metric_key, direction)


def _metric_values(entries: list[dict], metric_key: str) -> list[tuple[int, float]]:
    """提取携带数值指标的 (索引, 值) 列表。"""
    out: list[tuple[int, float]] = []
    for i, e in enumerate(entries):
        metrics = e.get("metrics")
        if not isinstance(metrics, dict):
            continue
        if metric_key in metrics:
            try:
                out.append((i, float(metrics[metric_key])))
            except (TypeError, ValueError):
                continue
    return out


def best_metric(entries: list[dict], metric_key: str, direction: str = "higher_better") -> Optional[float]:
    # 按方向取最大或最小指标值
    values = [v for _, v in _metric_values(entries, metric_key)]
    if not values:
        return None
    return max(values) if direction == "higher_better" else min(values)


def detect_stagnation(
    entries: list[dict],
    metric_key: str,
    direction: str = "higher_better",
    threshold_cycles: int = 3,
    min_delta: float = 0.0,
) -> dict:
    """基于指标轨迹的数据驱动停滞信号。

    返回判定字典；当最佳指标在至少 ``threshold_cycles`` 个“含指标”的周期内
    提升未超过 ``min_delta`` 时，``stagnating`` 为 True。仅为建议，由调用方
    决定如何处理。
    """
    verdict = {
        "stagnating": False,
        "metric_key": metric_key,
        "best": None,
        "recent_best": None,
        "cycles_since_improvement": 0,
        "n_points": 0,
    }
    if not metric_key:
        verdict["reason"] = "no metric_key configured"
        return verdict

    points = _metric_values(entries, metric_key)
    verdict["n_points"] = len(points)
    if len(points) <= threshold_cycles:
        verdict["reason"] = "not enough metric points yet"
        if points:
            verdict["best"] = best_metric(entries, metric_key, direction)
        return verdict

    higher = direction == "higher_better"
    best_val = points[0][1]
    cycles_since_improvement = 0
    for _, val in points[1:]:
        improved = (val > best_val + min_delta) if higher else (val < best_val - min_delta)
        if improved:
            best_val = val
            cycles_since_improvement = 0
        else:
            cycles_since_improvement += 1

    recent_vals = [v for _, v in points[-threshold_cycles:]]
    verdict["best"] = best_val
    verdict["recent_best"] = max(recent_vals) if higher else min(recent_vals)
    verdict["cycles_since_improvement"] = cycles_since_improvement
    verdict["stagnating"] = cycles_since_improvement >= threshold_cycles
    return verdict


def check_phase_gate(
    entries: list[dict],
    metric_key: str,
    threshold: float,
    direction: str = "higher_better",
) -> dict:
    """建议性的晋级闸门：最佳指标是否已好到足以继续？"""
    best = best_metric(entries, metric_key, direction)
    if best is None:
        return {"gate_met": False, "best_metric": None, "blocker_reason": "no metric recorded yet"}
    met = best >= threshold if direction == "higher_better" else best <= threshold
    reason = "" if met else (
        f"best {metric_key}={best} has not cleared the gate threshold {threshold} ({direction})"
    )
    return {"gate_met": met, "best_metric": best, "blocker_reason": reason}
