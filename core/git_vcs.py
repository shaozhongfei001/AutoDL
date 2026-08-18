"""
基于 Git 的事务隔离与安全晋级（SDD ADR-002 / 第 3B 阶段）。

实现基础框架缺失的“安全晋级”机制：

  * champion 引用（受保护）：只通过 fast-forward（快进）移动，绝不回退；
  * 隔离的候选 worktree：代码智能体永远不能改写共享状态；
  * 父 SHA 乐观锁：防止过期候选覆盖更新的 champion；
  * 制品清单（指标 + 补丁 + 检查点 + sha256）：在任何 KEEP/DISCARD 判定
    被记录之前先归档；
  * 只追加的事件账本：用于回放 / 崩溃恢复。

所有 git 底层命令都显式传入环境变量，使提交归属于项目所有者
（遵循仓库贡献者策略），且绝不改动全局 git config。
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

# 贡献者策略：提交作者必须署名为项目所有者
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "shaozhongfei001",
    "GIT_AUTHOR_EMAIL": "shaozhongfei@163.com",
    "GIT_COMMITTER_NAME": "shaozhongfei001",
    "GIT_COMMITTER_EMAIL": "shaozhongfei@163.com",
}


class VcsError(RuntimeError):
    """当 git/vcs 操作以“不可静默吞掉”的方式失败时抛出（例如晋级冲突）。"""


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # 统一封装 git 调用：指定仓库、捕获输出、注入作者环境变量
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
    """返回 ``ref`` 的完整 SHA（会解析分支名）。"""
    proc = _run(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return proc.stdout.strip()


def is_descendant(repo: Path, ancestor: str, descendant: str) -> bool:
    """若 ``descendant`` 的历史中包含 ``ancestor``（即可快进）则返回 True。"""
    # --is-ancestor：是祖先返回 0，不是祖先返回 1；非祖先不能抛异常，
    # 否则一个合法的“不可快进”候选会崩溃，而不是被干净地拒绝。
    proc = _run(repo, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
    return proc.returncode == 0


class GitExperimentVcs:
    """由真实 git 仓库支撑的安全晋级控制器。"""

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

    # --- champion 冠军分支 -----------------------------------------------------

    def ensure_champion_ref(self) -> str:
        """若 champion 引用不存在，则创建指向当前 main HEAD 的引用。"""
        try:
            return head_sha(self.repo, self.champion_ref)
        except VcsError:
            _run(self.repo, "branch", self.champion_ref, "main")
            return head_sha(self.repo, self.champion_ref)

    def promote_to_champion(self, candidate_sha: str, expected_parent_sha: str) -> dict:
        """把 ``candidate_sha`` 快进晋级到 champion 引用。

        乐观锁：若 champion 已经移动到 ``expected_parent_sha`` 之后，则拒绝晋级
        （``ok=False``），让调用方重新回放并重测。champion 引用只向前移动。
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

    # --- 候选 worktree ---------------------------------------------------------

    def create_candidate_worktree(self, experiment_id: str, base_sha: str, parent: Path) -> Path:
        """基于 ``base_sha`` 为候选创建隔离的 worktree，返回其路径。

        代码智能体只能在 worktree 内部写入。支持断点续跑（幂等）：
        若 worktree/分支已存在则复用，而非重建。
        """
        branch = f"{self.candidate_ref_prefix}-{experiment_id}"
        worktree = Path(parent) / f"candidate-{experiment_id}"
        # 续跑时 git 已注册过该 worktree（会写入 ``.git`` 标记文件），直接返回原路径
        if (worktree / ".git").exists():
            return worktree
        # 确保父目录存在，git 才能创建 worktree
        worktree.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run(self.repo, "worktree", "add", str(worktree), base_sha, "-b", branch)
        except VcsError as exc:
            # 分支已存在（续跑）-> 挂载已有分支；--force 可绕过上次半途
            # 残留的 “path already exists” 保护。
            if "already exists" in str(exc):
                _run(self.repo, "worktree", "add", "--force", str(worktree), branch)
            else:
                raise
        return worktree

    def commit_candidate(self, worktree: Path, message: str, files: list[str] | None = None) -> str:
        """在 worktree 内提交 allowlist 允许的候选文件，返回提交 SHA。"""
        if files:
            _run(self.repo, "-C", str(worktree), "add", "-A", "--", *files)
        else:
            _run(self.repo, "-C", str(worktree), "add", "-A")
        _run(self.repo, "-C", str(worktree), "commit", "-m", message)
        return self._worktree_head(worktree)

    def _worktree_head(self, worktree: Path) -> str:
        # 读取 worktree 当前的 HEAD SHA
        proc = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=GIT_ENV, check=True,
        )
        return proc.stdout.strip()

    # --- 制品清单 --------------------------------------------------------------

    def build_artifact_manifest(
        self,
        experiment_id: str,
        worktree: Path,
        metrics: dict,
        log_file: Path | None = None,
        checkpoint: Path | None = None,
        extra_files: list[Path] | None = None,
    ) -> dict:
        """把候选制品快照成带 SHA-256 的不可变清单。

        清单必须在任何 verdict（判定）被记录之前归档，这样即使候选被 DISCARD，
        日后仍可被复现。
        """
        files: list[dict] = []

        def _snap(p, role: str) -> None:
            # 允许调用方传入字符串或 Path，这里统一转成 Path
            p = Path(p) if isinstance(p, str) else p
            if p is None or not p.exists():
                return
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            try:
                rel = str(p.relative_to(worktree))
            except ValueError:
                # 文件位于 worktree 之外（例如集中日志目录）：记录绝对路径以保证可复现
                rel = str(p.resolve())
            files.append({"path": rel, "role": role, "sha256": digest})

        _snap(log_file, "log")
        _snap(checkpoint, "checkpoint")

        # candidate.patch = 相对 champion 基线的 diff
        champion_sha = head_sha(self.repo, self.champion_ref)
        diff = _run(self.repo, "diff", champion_sha, self._worktree_head(worktree)).stdout
        if diff:
            patch = worktree / f"{experiment_id}.patch"
            patch.write_text(diff)
            _snap(patch, "patch")

        for extra in (extra_files or []):
            _snap(extra, "artifact")

        # 对整个清单（排除自引用的 digest 字段）做 SHA-256，使得对 metrics、
        # champion_sha、candidate_sha 或文件快照的任何篡改都可被检测——而不只是
        # 改 ``files`` 字段。
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
