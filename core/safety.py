"""
零成本安全辅助函数 —— 仅对状态与账本（ledger）做纯函数计算，不涉及 GPU/网络。

这些函数让长时间运行的智能体保持“诚实”，而不必额外消耗 token：

- ``scan_violations``：把异常状态（例如反复无进展、状态卡在 "running"）以建议
  性字符串暴露出来，由主循环注入到 THINK 上下文中。
- ``seconds_until_allowed``：主动式防烧钱限流器：根据最近的周期启动时间戳，
  返回需要等待多久，从而保证智能体永远不会超过 ``max_per_hour`` 个周期
  （在陷入循环时保护预算）。

这里的所有函数都刻意写成纯函数、无副作用，方便用构造好的输入做单元测试——
不调用 nvidia-smi、不启动子进程、不读取系统时钟。
"""

from __future__ import annotations

import re


# --- M5 收敛：假设去重 -------------------------------------------------------

def normalize_hypothesis(hypothesis: str) -> str:
    """为一条假设/计划生成稳定、抗碰撞的键。

    统一转小写、合并空白、去除标点，使同一想法的两种不同表述映射到同一个键。
    ``None`` / 空字符串映射为 ``""``，保证调用方永远拿到字符串。
    """
    if not hypothesis:
        return ""
    text = " ".join(str(hypothesis).lower().split())
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def is_hypothesis_duplicate(
    hypothesis: str,
    attempted: list[str] | set[str],
    repeated_hypothesis_limit: int = 1,
) -> bool:
    """判断 ``hypothesis`` 是否已被尝试到应当被拒绝的程度。

    ``attempted`` 是此前已尝试过的假设集合（已归一化或原始文本均可）。
    当某假设的归一化键出现次数达到 ``repeated_hypothesis_limit`` 时即视为重复。
    默认 limit=1（合同默认值）表示同一想法的第二次出现即为重复；limit=0 则完全禁用去重。
    """
    if repeated_hypothesis_limit <= 0:
        return False
    key = normalize_hypothesis(hypothesis)
    if not key:
        return False
    count = 0
    for prev in attempted:
        if normalize_hypothesis(prev) == key:
            count += 1
    return count >= repeated_hypothesis_limit


def check_hypothesis_dedup(
    hypothesis: str,
    attempted: list[str] | set[str],
    repeated_hypothesis_limit: int = 1,
) -> dict:
    """M5 去重闸门的一键判断：主循环是否应该运行这条假设？

    返回一个决策字典，主循环无需额外记账即可直接使用：

    - ``allowed``：假设是全新的（或去重已关闭）时为 True。
    - ``reason``：被拒绝时给 THINK 上下文的简短建议文案。
    - ``key``：归一化键（无内容可键入时为 ""）。
    """
    if repeated_hypothesis_limit <= 0:
        return {"allowed": True, "reason": "", "key": normalize_hypothesis(hypothesis)}
    duplicate = is_hypothesis_duplicate(hypothesis, attempted, repeated_hypothesis_limit)
    return {
        "allowed": not duplicate,
        "reason": (
            "duplicate hypothesis — already attempted within "
            f"repeated_hypothesis_limit={repeated_hypothesis_limit}; try a "
            "materially different approach."
            if duplicate
            else ""
        ),
        "key": normalize_hypothesis(hypothesis),
    }


# --- M5 收敛：无进展升级 -----------------------------------------------------

def escalate_no_progress(
    no_progress_streak: int,
    *,
    widen_threshold: int = 3,
    lower_target_threshold: int = 6,
    terminate_threshold: int = 10,
) -> dict:
    """当主循环持续无进展时，返回升级决策。

    仅依据 ``no_progress_streak``（纯值，可单元测试）。返回以下之一：

    - ``level="normal"``：保持现状继续。
    - ``level="widen"``：拓宽搜索空间（新区域 / 不同智能体）。
    - ``level="lower_target"``：放宽本批次的目标 / 目标指标。
    - ``level="terminate"``：停止无人值守工作，交还人工处理。

    该决策仅为建议，主循环自行决定如何转换为具体动作。
    """
    if no_progress_streak < widen_threshold:
        return {"level": "normal", "advice": "", "streak": int(no_progress_streak)}
    if no_progress_streak < lower_target_threshold:
        return {
            "level": "widen",
            "advice": (
                f"{no_progress_streak} no-progress cycles — widen the search "
                "space (different region / agent / hyperparameter family) and "
                "stop repeating the same plan."
            ),
            "streak": int(no_progress_streak),
        }
    if no_progress_streak < terminate_threshold:
        return {
            "level": "lower_target",
            "advice": (
                f"{no_progress_streak} no-progress cycles — relax the target "
                "metric / scope for this cohort or wait for new signal before "
                "retrying."
            ),
            "streak": int(no_progress_streak),
        }
    return {
        "level": "terminate",
        "advice": (
            f"{no_progress_streak} no-progress cycles — terminating unattended "
            "iteration; hand back to a human operator."
        ),
        "streak": int(no_progress_streak),
    }


def scan_violations(
    state: dict,
    fail_count: int,
    now: float,
    fail_threshold: int = 3,
    stale_state_hours: int = 6,
) -> list[str]:
    """返回当前状态的建议性违规信息列表。"""
    violations: list[str] = []
    state = state if isinstance(state, dict) else {}

    if fail_threshold and fail_count >= fail_threshold:
        violations.append(
            f"{fail_count} consecutive no-progress cycles on the same plan — "
            "try a materially different approach or wait for new signal."
        )

    updated = state.get("updated_at")
    status = state.get("status")
    if updated is not None and status == "running" and stale_state_hours:
        try:
            age_hours = (float(now) - float(updated)) / 3600.0
        except (TypeError, ValueError):
            age_hours = 0.0
        if age_hours > stale_state_hours:
            violations.append(
                f"State has been 'running' for {age_hours:.1f}h without an update "
                f"(> {stale_state_hours}h) — training may be stuck or the process died."
            )

    return violations


def seconds_until_allowed(
    timestamps: list[float],
    now: float,
    max_per_hour: int,
    window: int = 3600,
) -> float:
    """根据最近的周期启动时间，返回启动下一个周期前需要等待的秒数。

    当限流被禁用（``max_per_hour`` <= 0）或近期次数未超预算时返回 0.0；
    否则返回最早一条在窗口内的时间戳滚出 ``window`` 之前还需等待的秒数。
    """
    if not max_per_hour or max_per_hour <= 0:
        return 0.0
    recent = [t for t in (timestamps or []) if (now - t) < window]
    if len(recent) < max_per_hour:
        return 0.0
    # 等待足够多的“最旧窗口内启动”滚出，使计数回到 max_per_hour 以下，
    # 而不只是等最老的那一条
    recent_sorted = sorted(recent)
    target = recent_sorted[len(recent) - max_per_hour]
    return max(0.0, float(window) - (float(now) - float(target)))


def prune_timestamps(timestamps: list[float], now: float, window: int = 3600) -> list[float]:
    """丢弃超过 ``window`` 秒的旧时间戳。"""
    return [t for t in (timestamps or []) if (now - t) < window]
