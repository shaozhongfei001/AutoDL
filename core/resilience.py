"""
M6 self-healing — crash replay, checkpoint resume, and exponential backoff.

Pure, side-effect-light helpers so the unattended loop can recover from a
crash / interruption instead of terminating:

- ``classify_recoverable`` + ``recoverable_candidates`` read the append-only
  experiment ledger and decide which unfinished candidates may be resumed.
- ``Checkpoint`` records ``last_cycle`` / ``last_state`` atomically so a
  restart can pick up exactly where the process left off.
- ``compute_backoff`` returns an exponential backoff with jitter for error
  cooldown, so repeated failures do not burn cycles.

Everything here is deliberately a pure function over dicts/lists/paths — the
loop integrates these by passing real ledger entries and a checkpoint path.
"""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autodl.resilience")

# Terminal ledger statuses that are NOT resumable.
_TERMINAL_STATUSES = {"completed", "success", "failed", "verdict_keep",
                      "verdict_discard", "verdict_crash", "verdict_incomparable"}

# Statuses that clearly mean the candidate never got to a resumable point.
_NON_RESUMABLE_ACTIONS = {"no_experiment", "wait", ""}


# --- ledger replay ----------------------------------------------------------

def _normalize_status(entry: dict) -> str:
    status = entry.get("status") or entry.get("action") or ""
    return str(status).lower()


def classify_recoverable(entry: dict) -> dict:
    """Classify a single ledger entry as resumable / terminal / not-applicable.

    Returns a dict with ``recoverable`` (bool) and ``reason`` (str). A candidate
    is resumable when its status is not terminal and it actually represents an
    experiment (as opposed to a "wait" or "no_experiment" cycle) OR it was
    explicitly recorded as ``crash`` (a monitor-detected crash we want to retry).
    """
    status = _normalize_status(entry)
    pid = entry.get("pid")
    log_file = entry.get("log_file") or ""

    # A crash verdict is resumable even though it is terminal-ish: a
    # monitor-detected crash is exactly what we want to retry after a reboot.
    if "crash" in status:
        return {"recoverable": True, "reason": "monitor-reported crash; safe to retry"}

    if status in _TERMINAL_STATUSES:
        return {"recoverable": False, "reason": f"terminal status: {status}"}

    action = (entry.get("action") or "").lower()

    # Never recorded as an experiment -> nothing to resume.
    if action in _NON_RESUMABLE_ACTIONS and not pid and not log_file:
        return {"recoverable": False, "reason": "no experiment was launched"}

    # In-flight (launched / running / scheduled / proposed) with some handle.
    if pid or log_file or action in {"experiment", "launched", "running",
                                     "scheduled", "proposed", "pending"}:
        return {"recoverable": True, "reason": "unfinished candidate present"}

    return {"recoverable": False, "reason": "no resumable experiment handle"}


def recoverable_candidates(entries: list[dict]) -> list[dict]:
    """Return the subset of ledger entries that may be resumed after a crash.

    Each returned entry is augmented with a ``_recovery`` dict from
    :func:`classify_recoverable` so the loop can decide what to do. Pure and
    side-effect free — safe to call on every startup.
    """
    out: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        verdict = classify_recoverable(entry)
        if verdict["recoverable"]:
            copy = dict(entry)
            copy["_recovery"] = verdict
            out.append(copy)
    return out


def recover_verdict_history(entries: list[dict]) -> dict:
    """Rebuild the machine-verdict history from the ledger for M2/M5 integration.

    Filters ledger entries whose ``action`` starts with ``"verdict:"`` (the M2
    convention), returning:

    - ``verdicts``: all verdict entries (newest last) — each carries ``verdict``,
      ``promotion_status``, ``candidate_sha``, ``champion_before_sha``,
      ``artifact_manifest_uri``, ``metrics`` and the experiment id.
    - ``last_verdict``: the most recent verdict entry (or ``None`` if none).
    - ``promoted_candidates``: candidate SHAs that reached a KEEP promotion —
      useful for M5 hypothesis/plan de-duplication after a resume.

    Pure and side-effect free; safe to call on every startup.
    """
    verdicts = []
    promoted = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        action = str(entry.get("action") or "")
        if not action.startswith("verdict:"):
            continue
        verdicts.append(entry)
        if str(entry.get("verdict") or "").upper() == "KEEP":
            promoted.append(entry.get("candidate_sha"))
    return {
        "verdicts": verdicts,
        "last_verdict": verdicts[-1] if verdicts else None,
        "promoted_candidates": promoted,
    }


def summarize_recovery(entries: list[dict]) -> dict:
    """Aggregate a replay summary over all ledger entries.

    Returns counts by recovery class plus the list of recoverable cycles so the
    loop can log a concise startup report and decide whether to resume.
    """
    total = 0
    resumable: list[dict] = []
    terminal = 0
    not_applicable = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        total += 1
        verdict = classify_recoverable(entry)
        if verdict["recoverable"]:
            resumable.append(entry)
        elif "terminal" in verdict["reason"]:
            terminal += 1
        else:
            not_applicable += 1
    return {
        "total_entries": total,
        "resumable": resumable,
        "resumable_cycles": [e.get("cycle") for e in resumable],
        "terminal_count": terminal,
        "not_applicable_count": not_applicable,
    }


# --- checkpoint resume ------------------------------------------------------

class Checkpoint:
    """Crash-safe, atomic checkpoint of loop progress.

    Stores ``last_cycle`` and an opaque ``last_state`` dict in ``state.json``
    (matching the workspace layout the loop already uses). Writes are atomic
    (write-temp + rename) so a mid-write crash never leaves a corrupt file.
    """

    def __init__(self, workspace: Path, filename: str = "state.json"):
        self.path = Path(workspace) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def load(self) -> dict:
        """Return the persisted checkpoint dict (empty dict if none)."""
        return self._read()

    def save(self, *, last_cycle: Optional[int] = None,
             last_state: Optional[dict] = None) -> dict:
        """Atomically persist the checkpoint. Returns the new checkpoint dict."""
        data = self._read()
        if last_cycle is not None:
            data["last_cycle"] = int(last_cycle)
        if last_state is not None and isinstance(last_state, dict):
            data["last_state"] = last_state
        data["checkpoint_ts"] = time.time()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic on POSIX
        return data

    def resume_point(self) -> dict:
        """Return a compact resume recommendation for the loop.

        - ``has_checkpoint``: whether any checkpoint exists.
        - ``next_cycle``: ``last_cycle + 1`` when a checkpoint exists else 1.
        - ``last_cycle`` / ``last_state``: raw persisted values (or defaults).
        """
        data = self._read()
        last_cycle = data.get("last_cycle")
        if last_cycle is None:
            return {"has_checkpoint": False, "next_cycle": 1,
                    "last_cycle": None, "last_state": {}}
        return {"has_checkpoint": True, "next_cycle": int(last_cycle) + 1,
                "last_cycle": int(last_cycle),
                "last_state": data.get("last_state") or {}}


# --- error cooldown & exponential backoff -----------------------------------

def compute_backoff(
    attempt: int,
    *,
    base_seconds: float = 30.0,
    max_seconds: float = 3600.0,
    factor: float = 2.0,
    jitter: float = 0.1,
    rng: Optional[random.Random] = None,
) -> float:
    """Exponential backoff (seconds) for the ``attempt``-th retry (0-based).

    ``backoff = min(max_seconds, base * factor**attempt)`` plus optional uniform
    jitter of ``±jitter * backoff`` so a fleet of processes does not stampede
    at the same instant. Pass a seeded ``rng`` for deterministic tests.
    """
    base = max(0.0, float(base_seconds))
    factor = max(1.0, float(factor))
    raw = base * (factor ** max(0, int(attempt)))
    capped = min(max(0.0, float(max_seconds)), raw)
    if jitter and jitter > 0:
        rng = rng if rng is not None else random
        offset = rng.uniform(-jitter, jitter) * capped
        return max(0.0, capped + offset)
    return capped


def next_retry_delay(current_delay: float, *, max_seconds: float = 3600.0,
                     factor: float = 2.0) -> float:
    """Step a running backoff state forward one retry (no attempt counter needed).

    Returns ``min(max_seconds, max(base_seconds, current_delay) * factor)``.
    ``current_delay <= 0`` is treated as the first retry from a small base.
    """
    base = 1.0
    if current_delay and current_delay > 0:
        base = float(current_delay)
    return min(max(0.0, float(max_seconds)), base * max(1.0, float(factor)))
