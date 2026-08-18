"""
实验有效性契约（P0-1）+ 受保护写边界（P0-2/D0）。

以向后兼容的方式实现 SDD ADR-001 / ADR-002 设计：

  * A（实验有效性契约）：对 budget / evaluation / comparability 做 schema 校验；
    提供指纹辅助函数，使得候选运行只有在 dataset+evaluator+cohort+budget
    一致时才相互可比。
  * D0（受保护写边界）：allowlist / denylist 规则 + 受保护文件哈希门，使智能体
    在没有显式授权时，无法修改 evaluator、data、tests、governance 等。

所有函数都是“增量式”的：当新的 config 字段缺失时，现有 loop 仍照常工作
（默认值保留原有行为）。校验尽量只做“建议性”提示，自身绝不导致 loop 崩溃。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autodl.contract")


# --- Schema / 默认值 -----------------------------------------------------

# 预算默认值：limit=0 / hard_wall_clock_limit=0 表示“不强制预算”（旧行为）
DEFAULT_BUDGET = {
    "mode": "active_wall_clock_seconds",
    "limit": 0,                 # 0 => 不强制执行预算（旧行为）
    "hard_wall_clock_limit": 0,  # 0 => 无硬上限（旧行为）
    "timer": "monotonic",
}

# 支持的预算计量模式
SUPPORTED_BUDGET_MODES = {"active_wall_clock_seconds", "optimizer_steps", "samples_or_tokens"}

DEFAULT_EVALUATION = {
    "primary_metric": {"name": "", "direction": "maximize", "unit": ""},
    "validation_metrics": [],   # 驱动逐轮选择的指标名
    "test_metrics": [],         # 仅预留给独立验收的指标名
    "minimum_effect_size": 0.0,
}

DEFAULT_COMPARABILITY = {
    "hardware_cohort_id": "",
    "requires_exact_cohort": True,
}


def _schema_error(path: str, detail: str) -> str:
    # 构造一条 schema 错误信息
    return f"experiment.{path}: {detail}"


def validate_experiment_config(cfg: dict) -> list[str]:
    """返回 ``cfg``（``experiment`` 配置块）的 schema 违规列表。

    当配置块缺失（旧模式）或完全合法时，返回空列表。
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


# --- 指纹 / 可比性 -------------------------------------------------------

def compute_fingerprint(fields: dict) -> str:
    """对一组可比性相关字段计算确定性的 SHA-256 指纹。"""
    canonical = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def comparability_fingerprint(cfg: dict, data_fingerprint: str = "", evaluator_fingerprint: str = "") -> dict:
    """为配置块构建可比性指纹字典。

    ``data_fingerprint`` / ``evaluator_fingerprint`` 若未显式传入，则回退到
    ``experiment.comparability`` 下声明的值。
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
    """两个运行是否共享同一可比性指纹（从而自动晋级判定有效）。旧模式下恒为 True。"""
    if not a or not b:
        return True
    if a.get("requires_exact_cohort", True) or b.get("requires_exact_cohort", True):
        return a.get("hash") == b.get("hash")
    # 双方都放弃精确 cohort 要求时：仍要求 budget + evaluator + data 一致。
    return (
        a.get("budget_mode") == b.get("budget_mode")
        and a.get("budget_limit") == b.get("budget_limit")
        and a.get("data_fingerprint") == b.get("data_fingerprint")
        and a.get("evaluator_fingerprint") == b.get("evaluator_fingerprint")
    )


# --- 预算辅助函数 --------------------------------------------------------

def resolve_budget(experiment: dict) -> dict:
    # 解析预算配置，返回带 enforced 标志的字典
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


def _aggregate_metric(value):
    """把一个主指标值聚合成单个 float。

    支持 list/tuple（多个 seed -> 取均值）、单个数值/字符串；拒绝 bool。
    当值不可用（None / 不可解析）时返回 ``None``。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None  # bool 不是合法的指标信号
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        nums = []
        for v in value:
            if isinstance(v, bool):
                return None
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                return None
        return sum(nums) / len(nums)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def decide_verdict(
    candidate_metrics: dict,
    champion_metrics: dict,
    primary_metric: str,
    direction: str = "maximize",
    minimum_effect_size: float = 0.0,
    confidence_rule: str = "exceed_min_effect_size",
    noise_std: float = 0.0,
) -> dict:
    """机器权威的晋级 verdict（ADR-002 / P3 统计）。

    比较候选与当前冠军在 ``primary_metric`` 上的表现。返回 ``verdict`` 为
    KEEP / DISCARD / INCOMPARABLE 之一，并附带数值 ``delta``。

    P3 新增：
    * ``candidate_metrics[primary]`` / ``champion_metrics[primary]`` 可以是多个
      seed 运行的列表 -> 比较前先聚合成均值。
    * ``noise_std``（跨 seed 测得的噪声）会收紧效应量门槛：
      ``effective = max(配置的最小效应量, 2 * noise_std)``，使“提升小于测量噪声”
      的候选永远不会被 KEEP。

    当任一方缺少该指标时，verdict 为 INCOMPARABLE。
    """
    # --- 健壮性守卫（P1）---
    if not primary_metric or not isinstance(primary_metric, str):
        return {"verdict": "INCOMPARABLE", "reason": "primary_metric missing or invalid", "delta": None}
    if direction not in ("maximize", "minimize"):
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"invalid direction '{direction}' (must be maximize/minimize)",
            "delta": None,
        }
    # 效应量必须是非负数字；能解析数值字符串就解析，解析不了则拒绝，
    # 而不是留到后面比较时才抛异常。
    try:
        effect_size = float(minimum_effect_size) if minimum_effect_size not in (None, "", 0, 0.0) else 0.0
        if effect_size < 0:
            return {"verdict": "INCOMPARABLE", "reason": "minimum_effect_size must be >= 0", "delta": None}
    except (TypeError, ValueError):
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"minimum_effect_size not numeric: {minimum_effect_size!r}",
            "delta": None,
        }
    try:
        noise_std_f = float(noise_std) if noise_std not in (None, "", 0, 0.0) else 0.0
        if noise_std_f < 0:
            return {"verdict": "INCOMPARABLE", "reason": "noise_std must be >= 0", "delta": None}
    except (TypeError, ValueError):
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"noise_std not numeric: {noise_std!r}",
            "delta": None,
        }
    # 有效门槛：配置的效应量，再叠加上测量噪声（2 倍规则）收紧。
    effective_effect = max(effect_size, 2.0 * noise_std_f) if noise_std_f > 0 else effect_size

    if not isinstance(candidate_metrics, dict) or not isinstance(champion_metrics, dict):
        return {"verdict": "INCOMPARABLE", "reason": "candidate/champion metrics must be dicts", "delta": None}
    cand = _aggregate_metric(candidate_metrics.get(primary_metric))
    champ = _aggregate_metric(champion_metrics.get(primary_metric))
    if cand is None or champ is None:
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"primary metric '{primary_metric}' missing/non-numeric on candidate or champion",
            "delta": None,
        }

    delta = (cand - champ) if direction == "maximize" else (champ - cand)
    improved = delta > 0
    meets_effect = (not effective_effect) or (delta >= effective_effect)

    if improved and meets_effect:
        return {
            "verdict": "KEEP",
            "reason": (
                f"{primary_metric} cand={cand:.5f} vs champion={champ:.5f} "
                f"(delta {delta:.5f}, min_effect_size {effective_effect:.5f}, "
                f"noise_std {noise_std_f})"
            ),
            "delta": delta,
        }
    return {
        "verdict": "DISCARD",
        "reason": (
            f"{primary_metric} cand={cand:.5f} vs champion={champ:.5f} "
            f"({'improved but below min_effect_size' if improved else 'not improved'})"
        ),
        "delta": delta,
    }


# 足以允许候选晋级的“干净契约状态”集合。
# 空状态（未配置预算的旧 monitor）按 SUCCESS 处理。
CLEAN_CONTRACT_STATUSES = {"SUCCESS", ""}


def gate_verdict_by_contract_status(verdict: dict, contract_status: str) -> dict:
    """用运行的 ``contract_status`` 作为机器 verdict 的硬性闸门。

    ``contract_status`` 取值为 SUCCESS / BUDGET_EXCEEDED / TIMEOUT / CRASH
    （由 :func:`classify_run_outcome` 产生）。一个未干净完成的运行绝不能被
    KEEP——无论原始指标比较结果如何——因为晋级一个被预算杀死或崩溃的候选会
    违反“冠军永不回退”的不变量。

    旧模式（空状态）按 SUCCESS 处理，使 verdict 原样通过。返回带有 ``verdict``
    与 ``contract_status`` 键的 verdict 字典。
    """
    if not isinstance(verdict, dict):
        return {
            "verdict": "INCOMPARABLE",
            "reason": f"verdict not a dict: {type(verdict).__name__}",
            "contract_status": (contract_status or "SUCCESS").upper(),
            "delta": None,
        }
    status = (contract_status or "SUCCESS").upper()
    current = verdict.get("verdict")
    if current == "KEEP" and status not in CLEAN_CONTRACT_STATUSES:
        return {
            "verdict": "DISCARD",
            "reason": (
                f"run did not complete cleanly (contract_status={status}); "
                "refusing to promote a candidate that crashed or exhausted budget"
            ),
            "delta": verdict.get("delta"),
            "contract_status": status,
        }
    # KEEP 保持 KEEP；DISCARD/INCOMPARABLE 本就保守，无需改动。
    out = dict(verdict)
    out["contract_status"] = status
    return out


def classify_run_outcome(active_train_seconds: float, budget: dict, terminated: str = "completed") -> str:
    """把挂钟耗时 + 预算 + 终止来源映射成一个状态。

    返回 SUCCESS / BUDGET_EXCEEDED / TIMEOUT / CRASH 之一。旧模式（不强制预算）
    下，completed 的运行恒为 SUCCESS。
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


# --- 受保护写边界（D0）---------------------------------------------------

# D0 默认写边界：默认保护若干关键的 denylist 边界（evaluator/data/config/tests/
# governance/artifacts），但不限制普通文件写入。在 config 中设置显式 allowlist
# 可把写入收窄到特定文件/目录（例如在严格的候选 worktree 场景下）。
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
    """封装 allowlist/denylist 规则 + 受保护文件的哈希门。

    所有路径检查都基于 POSIX 风格的“工作区相对字符串”（与 tools/execution
    层既有的约定一致）。
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
        # 把路径规范化为正斜杠、去空段的形式
        parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
        return "/".join(parts)

    def _matches_prefix(self, rel: str, prefixes: list[str]) -> bool:
        # 判断 rel 是否匹配任一前缀（目录或完整文件名）
        for prefix in prefixes:
            p = prefix.rstrip("/") + "/"
            if rel == prefix.rstrip("/") or rel.startswith(p):
                return True
            if rel.startswith(prefix):
                return True
        return False

    def allows_write(self, rel: str) -> tuple[bool, str]:
        """返回 (allowed, reason)。一次写入被允许的条件是：未被 denylist 拒绝，
        且（allowlist 为空 或 命中 allowlist）。"""
        rel = self._norm(rel)
        if not rel:
            return False, "empty path"
        # denylist 文件
        for f in self.denylist_files:
            if rel == f or rel.endswith("/" + f):
                return False, f"denylisted file: {f}"
        # denylist 目录（前缀匹配）
        if self._matches_prefix(rel, self.denylist_dirs):
            return False, f"denylisted directory: {rel}"
        # allowlist：若非空则要求命中
        if self.allowlist:
            if not self._matches_prefix(rel, self.allowlist):
                return False, f"not in write allowlist: {rel}"
        return True, "ok"

    def snapshot_hashes(self, workspace: Path) -> dict:
        """对配置中的受保护文件计算 SHA-256 快照（相对工作区）。"""
        snap: dict = {}
        if not self.protected_hashes:
            return snap
        for rel, _expected in self.protected_hashes.items():
            p = Path(workspace) / self._norm(rel)
            if p.exists():
                snap[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return snap

    def assert_unchanged(self, workspace: Path) -> list[str]:
        """返回受保护文件被篡改的消息列表；空列表表示完好。"""
        violations = []
        current = self.snapshot_hashes(workspace)
        for rel, expected in self.protected_hashes.items():
            got = current.get(rel)
            if got is not None and got != expected:
                violations.append(f"protected file modified: {rel}")
        return violations
