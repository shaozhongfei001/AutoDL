"""
Zero-cost safety helpers — pure functions over state + ledger, no GPU/network.

These keep a long-running agent honest without spending tokens:

- ``scan_violations`` surfaces bad states (repeated no-progress, stale
  "running" state) as advisory strings the loop injects into the THINK context.
- ``seconds_until_allowed`` is the proactive anti-burn rate limiter: given the
  recent cycle-start timestamps, it returns how long to wait so the agent never
  exceeds ``max_per_hour`` cycles (protecting budget when stuck in a loop).

Everything here is deliberately pure and side-effect-free so it is unit-testable
with crafted inputs — no nvidia-smi, no subprocess, no clock.
"""

from __future__ import annotations

import re


# --- M5 convergence: hypothesis de-duplication -----------------------------

def normalize_hypothesis(hypothesis: str) -> str:
    """Stable, collision-resistant key for a hypothesis / plan.

    Lowercases, collapses whitespace and strips punctuation so that two text
    phrasings of the same idea map to the same key. ``None`` / empty maps to
    ``""`` so callers always get a string.
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
    """Whether ``hypothesis`` has already been tried often enough to reject it.

    ``attempted`` is the collection of previously-attempted hypotheses (already
    normalized, or raw — both work). A hypothesis is a duplicate once its
    normalized key has been seen at least ``repeated_hypothesis_limit`` times.
    A limit of 1 (the contract default) means the second occurrence of the same
    idea is already a duplicate; 0 disables de-duplication entirely.
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
    """One-call M5 gate: should the loop run this hypothesis?

    Returns a decision dict the loop can act on without extra bookkeeping:

    - ``allowed``: True when the hypothesis is novel (or de-duplication is off).
    - ``reason``: short advisory string for the THINK context when rejected.
    - ``key``: the normalized key ("" when nothing to key on).
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


# --- M5 convergence: no-progress escalation ---------------------------------

def escalate_no_progress(
    no_progress_streak: int,
    *,
    widen_threshold: int = 3,
    lower_target_threshold: int = 6,
    terminate_threshold: int = 10,
) -> dict:
    """Return an escalation decision when the loop keeps making no progress.

    Based only on ``no_progress_streak`` (pure, unit-testable). Returns one of:

    - ``level="normal"``: keep going as-is.
    - ``level="widen"``: widen the search space (new region / different agent).
    - ``level="lower_target"``: relax the goal / target metric for this cohort.
    - ``level="terminate"``: stop unattended work and hand back to a human.

    The decision is advisory; the loop decides how to translate it into actions.
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
    """Return advisory violation messages for the current state."""
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
    """How long to wait before starting another cycle, given recent starts.

    Returns 0.0 when rate limiting is disabled (``max_per_hour`` <= 0) or the
    recent count is under budget. Otherwise returns the seconds until the
    oldest in-window timestamp rolls past ``window``.
    """
    if not max_per_hour or max_per_hour <= 0:
        return 0.0
    recent = [t for t in (timestamps or []) if (now - t) < window]
    if len(recent) < max_per_hour:
        return 0.0
    # Wait until enough of the oldest in-window starts roll off to bring the
    # count back under max_per_hour — not just the single oldest one.
    recent_sorted = sorted(recent)
    target = recent_sorted[len(recent) - max_per_hour]
    return max(0.0, float(window) - (float(now) - float(target)))


def prune_timestamps(timestamps: list[float], now: float, window: int = 3600) -> list[float]:
    """Drop timestamps older than ``window`` seconds."""
    return [t for t in (timestamps or []) if (now - t) < window]
