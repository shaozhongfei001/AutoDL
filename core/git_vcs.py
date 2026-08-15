"""
Git-backed transactional isolation & safe promotion (SDD ADR-002 / phase 3B).

Implements the safe-promotion machinery that the base framework lacks:

  * champion ref (protected) that only ever moves via fast-forward;
  * isolated candidate worktrees so a code agent never mutates shared state;
  * parent-SHA optimistic locking so a stale candidate cannot clobber a newer
    champion;
  * an artifact manifest (metrics + patch + checkpoint + sha256) that is
    archived BEFORE any KEEP/DISCARD verdict is recorded;
  * an append-only event ledger for replay / crash recovery.

All git plumbing is invoked with explicit env so commits are attributed to the
project owner (per repo contributor policy) and never touch global config.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autodl.gitvcs")

# Contributor policy: commits must be authored by the project owner.
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "shaozhongfei001",
    "GIT_AUTHOR_EMAIL": "shaozhongfei@163.com",
    "GIT_COMMITTER_NAME": "shaozhongfei001",
    "GIT_COMMITTER_EMAIL": "shaozhongfei@163.com",
}


class VcsError(RuntimeError):
    """Raised when a git/vcs operation fails in a way that must not be silently
    swallowed (e.g. a promotion conflict)."""


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            env=GIT_ENV,
            check=check,
        )
    except subprocess.CalledProcessError as exc:
        raise VcsError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc


def head_sha(repo: Path, ref: str = "HEAD") -> str:
    """Return the full SHA of ``ref`` (resolves branch names)."""
    proc = _run(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return proc.stdout.strip()


def is_descendant(repo: Path, ancestor: str, descendant: str) -> bool:
    """True if ``descendant`` contains ``ancestor`` in its history (fast-forward possible)."""
    # ``--is-ancestor`` exits 0 (ancestor) or 1 (not an ancestor); a non-ancestor
    # must NOT raise, otherwise a legitimately non-fast-forward candidate would
    # crash the loop instead of being rejected cleanly.
    proc = _run(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return proc.returncode == 0


class GitExperimentVcs:
    """Safe-promotion controller backed by a real git repository."""

    def __init__(
        self,
        repo: Path,
        champion_ref: str = "champion/STUDY-001",
        candidate_ref_prefix: str = "experiment/STUDY-001",
    ):
        self.repo = Path(repo)
        self.champion_ref = champion_ref
        self.candidate_ref_prefix = candidate_ref_prefix
        self.ensure_champion_ref()

    # --- champion -----------------------------------------------------------

    def ensure_champion_ref(self) -> str:
        """Create the champion ref pointing at the current main HEAD if absent."""
        try:
            return head_sha(self.repo, self.champion_ref)
        except VcsError:
            _run(self.repo, "branch", self.champion_ref, "main")
            return head_sha(self.repo, self.champion_ref)

    def promote_to_champion(self, candidate_sha: str, expected_parent_sha: str) -> dict:
        """Fast-forward promote ``candidate_sha`` onto the champion ref.

        Optimistic lock: if the champion has moved past ``expected_parent_sha``
        the promotion is rejected (``ok=False``) so the caller can replay and
        retest. The champion ref only ever moves forward.
        """
        current = head_sha(self.repo, self.champion_ref)
        if current != expected_parent_sha:
            return {
                "ok": False,
                "reason": "STALE_CANDIDATE",
                "champion_sha": current,
                "expected_parent_sha": expected_parent_sha,
            }
        if not is_descendant(self.repo, expected_parent_sha, candidate_sha):
            return {
                "ok": False,
                "reason": "NOT_FAST_FORWARD",
                "champion_sha": current,
                "candidate_sha": candidate_sha,
            }
        _run(self.repo, "branch", "-f", self.champion_ref, candidate_sha)
        return {
            "ok": True,
            "reason": "PROMOTED",
            "champion_sha": head_sha(self.repo, self.champion_ref),
            "candidate_sha": candidate_sha,
        }

    # --- candidate worktree -------------------------------------------------

    def create_candidate_worktree(self, experiment_id: str, base_sha: str, parent: Path) -> Path:
        """Create an isolated worktree for a candidate from ``base_sha``.

        Returns the worktree path. The code agent may only write inside it.
        Idempotent for resume: if the worktree/branch already exists it is
        reused instead of being recreated.
        """
        branch = f"{self.candidate_ref_prefix}-{experiment_id}"
        worktree = Path(parent) / f"candidate-{experiment_id}"
        # A resume will already have registered this worktree (a ``.git`` file
        # marker is written by git); return it as-is rather than re-adding.
        if (worktree / ".git").exists():
            return worktree
        # Ensure the parent directory exists so git can create the worktree.
        worktree.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run(self.repo, "worktree", "add", str(worktree), base_sha, "-b", branch)
        except VcsError as exc:
            # Branch already exists (resume) -> attach the existing branch.
            # ``--force`` bypasses the "path already exists" guard left over
            # from a previous partial add.
            if "already exists" in str(exc):
                _run(self.repo, "worktree", "add", "--force", str(worktree), branch)
            else:
                raise
        return worktree

    def commit_candidate(self, worktree: Path, message: str, files: list[str] | None = None) -> str:
        """Commit the allowlisted candidate files inside the worktree. Returns SHA."""
        if files:
            _run(self.repo, "-C", str(worktree), "add", "-A", "--", *files)
        else:
            _run(self.repo, "-C", str(worktree), "add", "-A")
        _run(self.repo, "-C", str(worktree), "commit", "-m", message)
        return self._worktree_head(worktree)

    def _worktree_head(self, worktree: Path) -> str:
        proc = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=GIT_ENV, check=True,
        )
        return proc.stdout.strip()

    # --- artifact manifest --------------------------------------------------

    def build_artifact_manifest(
        self,
        experiment_id: str,
        worktree: Path,
        metrics: dict,
        log_file: Path | None = None,
        checkpoint: Path | None = None,
        extra_files: list[Path] | None = None,
    ) -> dict:
        """Snapshot candidate artifacts into an immutable manifest with SHA-256.

        The manifest must be archived BEFORE any verdict is recorded so a
        DISCARDed candidate can still be reproduced later.
        """
        files: list[dict] = []

        def _snap(p, role: str) -> None:
            # Coerce plain strings to Path so callers may pass either form.
            p = Path(p) if isinstance(p, str) else p
            if p is None or not p.exists():
                return
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            try:
                rel = str(p.relative_to(worktree))
            except ValueError:
                # File lives outside the worktree (e.g. a central log dir):
                # record the absolute path so it is still reproducible.
                rel = str(p.resolve())
            files.append({"path": rel, "role": role, "sha256": digest})

        _snap(log_file, "log")
        _snap(checkpoint, "checkpoint")

        # candidate.patch = diff against the champion baseline
        champion_sha = head_sha(self.repo, self.champion_ref)
        diff = _run(self.repo, "diff", champion_sha, self._worktree_head(worktree)).stdout
        if diff:
            patch = worktree / f"{experiment_id}.patch"
            patch.write_text(diff)
            _snap(patch, "patch")

        for extra in (extra_files or []):
            _snap(extra, "artifact")

        # SHA-256 over the whole manifest (excluding the self-referential
        # digest) so any tamper of metrics, champion_sha, candidate_sha or the
        # file snapshot is detectable — not just changes to ``files``.
        body = {
            "experiment_id": experiment_id,
            "champion_sha": champion_sha,
            "candidate_sha": self._worktree_head(worktree),
            "metrics": metrics,
            "files": files,
        }
        manifest = {
            **body,
            "manifest_sha256": hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        }
        return manifest
