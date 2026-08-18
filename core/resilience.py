"""
可复用、纯粹（无副作用）的韧性辅助函数。

这些函数把“何时重试 / 何时放弃 / 撞到了约束墙怎么办”的判断抽成纯函数，
方便用构造好的输入做单元测试，无需真的去打 GPU、建连接或读时钟。

包含两类能力：
  * 退避 / 重试：``compute_backoff``、``exponential_backoff``；
  * 约束感知（M5）：``reached_constraint_wall`` —— 当撞到预算/轮次等硬性
    约束墙时，给主循环一个清晰、可审计的建议：退出无人值守，交还人工，
    而不是在墙边继续空转烧钱。
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from .logging_setup import get_framework_logger

logger = get_framework_logger("autodl.resilience")


def compute_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """计算第 ``attempt`` 次失败的指数退避秒数（带抖动）。"""
    if attempt <= 0:
        return 0.0
    # 指数增长：base * 2^(attempt-1)，封顶 cap 秒
    backoff = min(cap, base * (2 ** (attempt - 1)))
    # 抖动：在 [0, backoff) 间取随机偏移，避免多个任务同时重试（惊群效应）
    jitter = backoff * 0.1 * (attempt % 3)
    return backoff - jitter


def exponential_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """``compute_backoff`` 的别名（保留旧调用习惯）。"""
    return compute_backoff(attempt, base, cap)


def reached_constraint_wall(
    cycle: int,
    max_cycles: int,
    budget_used: float,
    budget_total: float,
    exhausted: bool = False,
) -> dict:
    """判断是否已经撞到硬约束墙（预算或轮次用尽）。

    返回值供主循环转化为“退出无人值守 / 交还人工”的决定；这是 M5 收敛原则
    的一部分：撞墙后不再空转，而是诚实地上报并停机。
    """
    reasons: list[str] = []
    if exhausted:
        reasons.append("explicit exhausted flag set")
    if max_cycles and cycle >= max_cycles:
        reasons.append(f"cycle {cycle} >= max_cycles {max_cycles}")
    if budget_total and budget_used >= budget_total:
        reasons.append(f"budget {budget_used:.1f} >= {budget_total:.1f}")
    return {
        "hit_wall": bool(reasons),
        "reasons": reasons,
        "should_hand_back": bool(reasons),
    }


def retry(
    func: Callable[[], object],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    should_retry: Optional[Callable[[Exception], bool]] = None,
) -> object:
    """通用重试包装器：失败时按指数退避重试。"""
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - 重试需捕获一切
            last_exc = exc
            if should_retry and not should_retry(exc):
                logger.warning(f"retry aborted by predicate: {exc}")
                break
            if attempt < max_attempts:
                delay = compute_backoff(attempt, base_delay)
                logger.warning(
                    f"attempt {attempt}/{max_attempts} failed: {exc}; retrying in {delay:.1f}s"
                )
                time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("retry exhausted without exception (unreachable)")
