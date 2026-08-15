"""
Experiment Validity Contract (P0-1) + Protected Write Boundary (P0-2/D0).

Implements the SDD ADR-001 / ADR-002 design in a backwards-compatible way:

  * A (experiment validity contract): schema-validated config for
    budget / evaluation / comparability; a fingerprint helper so candidate
    runs are only compared when they share dataset+evaluator+cohort+budget.
  * D0 (protected write boundary): allowlist / denylist rules and a
    protected-file hash gate, so the agent cannot mutate evaluators, data,
    tests, or governance without an explicit allowance.

All functions are additive: the existing loop keeps working when the new
config keys are absent (defaults preserve current behavior). Failures are
advisory where possible and never crash the loop by themselves.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autoresearcher.contract")


# --- Schema / defaults -----------------------------------------------------

DEFAULT_BUDGET = {
    "mode": "active_wall_clock_seconds",
    "limit": 0,                 # 0 => no budget enforcement (legacy behavior)
    "hard_wall_clock_limit": 0,  # 0 => no hard cap (legacy behavior)
    "timer": "monotonic",
}

SUPPORTED_BUDGET_MODES = {"active_wall_clock_seconds", "optimizer_steps", "samples_or_tokens"}

DEFAULT_EVALUATION = {
    "primary_metric": {"name": "", "direction": "maximize", "unit": ""},
    "validation_metrics": [],   # names whose values drive per-round selection
    "test_metrics": [],         # names reserved for independent acceptance only
    "minimum_effect_size": 0.0,
}

DEFAULT_COMPARABILITY = {
    "hardware_cohort_id": "",
    "requires_exact_cohort": True,
}


def _schema_error(path: str, detail: str) -> str:
    return f"experiment.{path}: {detail}"


def validate_experiment_config(cfg: dict) -> list[str]:
    """Return a list of schema violations for ``cfg`` (the ``experiment`` block).

    Returns an empty list when valid or when the block is absent (legacy mode).
    """
    if not isinstance(cfg, dict):
        return [_schema_error("", "experiment block must be a mapping")]
    errors: list[str] = []

    budget = cfg.get("budget") or {}
    if isinstance(budget, dict):
        mode = budget.get("mode", DEFAULT_BUDGET["mode"])
        if mode not in SUPPORTED_BUDGET_MODES:
            errors.append(_schema_error("budget.mode", f"unsupported mode '{mode}'"))
        try:
            limit = float(budget.get("limit", 0))
            if limit < 0:
                errors.append(_schema_error("budget.limit", "must be >= 0"))
        except (TypeError, ValueError):
            errors.append(_schema_error("budget.limit", "must be a number"))
        try:
            hard = float(budget.get("hard_wall_clock_limit", 0))
            if hard < 0:
                errors.append(_schema_error("budget.hard_wall_clock_limit", "must be >= 0"))
        except (TypeError, ValueError):
            errors.append(_schema_error("budget.hard_wall_clock_limit", "must be a number"))

    evaluation = cfg.get("evaluation") or {}
    if isinstance(evaluation, dict):
        pm = evaluation.get("primary_metric") or {}
        if isinstance(pm, dict) and pm.get("name"):
            if pm.get("direction") not in ("maximize", "minimize"):
                errors.append(_schema_error("evaluation.primary_metric.direction",
                                            "must be 'maximize' or 'minimize'"))
        try:
            mes = float(evaluation.get("minimum_effect_size", 0.0))
            if mes < 0:
                errors.append(_schema_error("evaluation.minimum_effect_size", "must be >= 0"))
        except (TypeError, ValueError):
            errors.append(_schema_error("evaluation.minimum_effect_size", "must be a number"))

    comparability = cfg.get("comparability") or {}
    if isinstance(comparability, dict):
        if comparability.get("requires_exact_cohort") not in (None, True, False):
            errors.append(_schema_error("comparability.requires_exact_cohort",
                                        "must be a boolean"))

    return errors


# --- Fingerprint / comparability -------------------------------------------

def compute_fingerprint(fields: dict) -> str:
    """Deterministic SHA-256 over a set of comparability-relevant fields."""
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def comparability_fingerprint(cfg: dict, data_fingerprint: str = "", evaluator_fingerprint: str = "") -> dict:
    """Build the comparability fingerprint dict for a config block.

    ``data_fingerprint`` / ``evaluator_fingerprint`` fall back to the values
    declared under ``experiment.comparability`` when not passed explicitly.
    """
    experiment = cfg.get("experiment") or {}
    comparability = experiment.get("comparability") or DEFAULT_COMPARABILITY
    budget = experiment.get("budget") or DEFAULT_BUDGET
    evaluation = experiment.get("evaluation") or DEFAULT_EVALUATION

    data_fp = data_fingerprint or str(comparability.get("data_fingerprint", "") or "")
    eval_fp = evaluator_fingerprint or str(comparability.get("evaluator_fingerprint", "") or "")

    fingerprint = compute_fingerprint({
        "hardware_cohort_id": comparability.get("hardware_cohort_id", ""),
        "budget_mode": budget.get("mode", DEFAULT_BUDGET["mode"]),
        "budget_limit": budget.get("limit", 0),
        "data_fingerprint": data_fp,
        "evaluator_fingerprint": eval_fp,
    })
    return {
        "hash": fingerprint,
        "hardware_cohort_id": comparability.get("hardware_cohort_id", ""),
        "requires_exact_cohort": comparability.get("requires_exact_cohort", True),
        "budget_mode": budget.get("mode", DEFAULT_BUDGET["mode"]),
        "budget_limit": budget.get("limit", 0),
        "data_fingerprint": data_fp,
        "evaluator_fingerprint": eval_fp,
    }


def are_comparable(a: dict, b: dict) -> bool:
    """True when two runs share the same comparability fingerprint (so an
    automatic promotion decision is valid). Always True in legacy mode."""
    if not a or not b:
        return True
    if a.get("requires_exact_cohort", True) or b.get("requires_exact_cohort", True):
        return a.get("hash") == b.get("hash")
    # Both opted out of exact cohort: still require budget + evaluator + data.
    return (
        a.get("budget_mode") == b.get("budget_mode")
        and a.get("budget_limit") == b.get("budget_limit")
        and a.get("data_fingerprint") == b.get("data_fingerprint")
        and a.get("evaluator_fingerprint") == b.get("evaluator_fingerprint")
    )


# --- Budget helpers --------------------------------------------------------

def resolve_budget(experiment: dict) -> dict:
    budget = (experiment or {}).get("budget") or DEFAULT_BUDGET
    try:
        limit = float(budget.get("limit", 0))
    except (TypeError, ValueError):
        limit = 0.0
    try:
        hard = float(budget.get("hard_wall_clock_limit", 0))
    except (TypeError, ValueError):
        hard = 0.0
    return {
        "mode": budget.get("mode", DEFAULT_BUDGET["mode"]),
        "limit": limit,
        "hard_wall_clock_limit": hard,
        "enforced": bool(limit > 0 or hard > 0),
    }


def decide_verdict(
    candidate_metrics: dict,
    champion_metrics: dict,
    primary_metric: str,
    direction: str = "maximize",
    minimum_effect_size: float = 0.0,
    confidence_rule: str = "exceed_min_effect_size",
) -> dict:
    """Machine-authoritative promotion verdict (ADR-002).

    Compares a candidate against the current champion on ``primary_metric``.
    Returns a dict with ``verdict`` in {KEEP, DISCARD, INCOMPARABLE} and a
    numeric ``delta``. ``minimum_effect_size`` (>0) must be exceeded for KEEP,
    otherwise a small-but-positive delta is still DISCARD (noise guard). When
    either side lacks the metric the verdict is INCOMPARABLE.
    """
    cand = candidate_metrics.get(primary_metric) if isinstance(candidate_metrics, dict) else None
    champ = champion_metrics.get(primary_metric) if isinstance(champion_metrics, dict) else None
    if cand is None or champ is None:
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"primary metric '{primary_metric}' missing on candidate or champion",
            "delta": None,
        }
    try:
        cand_f = float(cand)
        champ_f = float(champ)
    except (TypeError, ValueError):
        return {"verdict": "INCOMPARABLE", "reason": "primary metric not numeric", "delta": None}

    delta = (cand_f - champ_f) if direction == "maximize" else (champ_f - cand_f)
    improved = delta > 0
    meets_effect = (not minimum_effect_size) or (delta >= minimum_effect_size)

    if improved and meets_effect:
        return {
            "verdict": "KEEP",
            "reason": (
                f"{primary_metric} {cand_f} vs champion {champ_f} (delta {delta:.5f}, "
                f"min_effect_size {minimum_effect_size})"
            ),
            "delta": delta,
        }
    return {
        "verdict": "DISCARD",
        "reason": (
            f"{primary_metric} {cand_f} vs champion {champ_f} "
            f"({'improved but below min_effect_size' if improved else 'not improved'})"
        ),
        "delta": delta,
    }


def classify_run_outcome(active_train_seconds: float, budget: dict, terminated: str = "completed") -> str:
    """Map wall-clock elapsed time + budget + termination source to a status.

    Returns one of: ``SUCCESS`` / ``BUDGET_EXCEEDED`` / ``TIMEOUT`` / ``CRASH``.
    In legacy mode (budget not enforced) a completed run is always SUCCESS.
    """
    if terminated == "crash":
        return "CRASH"
    if not budget.get("enforced"):
        return "SUCCESS" if terminated == "completed" else "TIMEOUT"
    hard = float(budget.get("hard_wall_clock_limit") or 0)
    if hard > 0 and active_train_seconds >= hard:
        return "TIMEOUT"
    limit = float(budget.get("limit") or 0)
    if limit > 0 and active_train_seconds >= limit:
        return "BUDGET_EXCEEDED"
    return "SUCCESS" if terminated == "completed" else "CRASH"


# --- Protected write boundary (D0) ------------------------------------------

# D0 default write boundary: by default we protect the critical denylist
# boundaries (evaluator/data/config/tests/governance/artifacts) but do NOT
# restrict ordinary file writes. Set an explicit allowlist in config to narrow
# writes to specific files/dirs (e.g. for a strict candidate worktree).
DEFAULT_WRITE_ALLOWLIST = []
DEFAULT_WRITE_DENYLIST_DIRS = [
    "data/",
    ".codebuddy/",
    "contracts/",
    "tests/",
    "artifacts/",
]
DEFAULT_WRITE_DENYLIST_FILES = [
    "config.yaml",
    "core/monitor.py",
    "core/ledger.py",
    "core/experiment_contract.py",
    "core/safety.py",
    "PROJECT_BRIEF.md",
    "state.json",
    "MEMORY_LOG.md",
    ".lock",
]


class ProtectedWritePolicy:
    """Encapsulates allowlist/denylist rules + a hash gate for protected files.

    All path checks operate on POSIX-style workspace-relative strings (the
    same convention the tools/execution layer already uses).
    """

    def __init__(
        self,
        allowlist: Optional[list[str]] = None,
        denylist_dirs: Optional[list[str]] = None,
        denylist_files: Optional[list[str]] = None,
        protected_hashes: Optional[dict] = None,
    ):
        self.allowlist = list(allowlist) if allowlist is not None else list(DEFAULT_WRITE_ALLOWLIST)
        self.denylist_dirs = list(denylist_dirs) if denylist_dirs is not None else list(DEFAULT_WRITE_DENYLIST_DIRS)
        self.denylist_files = list(denylist_files) if denylist_files is not None else list(DEFAULT_WRITE_DENYLIST_FILES)
        self.protected_hashes = dict(protected_hashes or {})

    @staticmethod
    def _norm(rel: str) -> str:
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        return "/".join(parts)

    def _matches_prefix(self, rel: str, prefixes: list[str]) -> bool:
        for prefix in prefixes:
            p = prefix.rstrip("/") + "/"
            if rel == prefix.rstrip("/") or rel.startswith(p):
                return True
            if rel.startswith(prefix):
                return True
        return False

    def allows_write(self, rel: str) -> tuple[bool, str]:
        """Return (allowed, reason). A write is allowed if it is NOT denylisted
        AND (allowlist empty OR it matches the allowlist)."""
        rel = self._norm(rel)
        if not rel:
            return False, "empty path"
        # denylist files
        for f in self.denylist_files:
            if rel == f or rel.endswith("/" + f):
                return False, f"denylisted file: {f}"
        # denylist dirs (prefix match)
        if self._matches_prefix(rel, self.denylist_dirs):
            return False, f"denylisted directory: {rel}"
        # allowlist: if non-empty, require a match
        if self.allowlist:
            if not self._matches_prefix(rel, self.allowlist):
                return False, f"not in write allowlist: {rel}"
        return True, "ok"

    def snapshot_hashes(self, workspace: Path) -> dict:
        """Snapshot SHA-256 of configured protected files (relative to workspace)."""
        snap: dict = {}
        if not self.protected_hashes:
            return snap
        for rel, _expected in self.protected_hashes.items():
            p = Path(workspace) / self._norm(rel)
            if p.exists():
                snap[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return snap

    def assert_unchanged(self, workspace: Path) -> list[str]:
        """Return a list of protected-file violation messages; empty if intact."""
        violations = []
        current = self.snapshot_hashes(workspace)
        for rel, expected in self.protected_hashes.items():
            got = current.get(rel)
            if got is not None and got != expected:
                violations.append(f"protected file modified: {rel}")
        return violations
