"""
进度快照导出（progress snapshot export）模块。

把项目运行状态渲染为人类可读的 Markdown 进度快照：
- exp_{cycle}_{pid}.md：每实验一份独立、只写一次的快照
- Dashboard.md：全局总览索引（按实验链接各快照）
- Daily/YYYY-MM-DD.md（可选，兼容旧 Obsidian vault 同步）：追加式每日循环笔记

原名为 core/obsidian.py；因职责从「Obsidian 专用笔记」扩展为「通用进度快照
导出」，重命名为 core/snapshots.py，类名改为 SnapshotExporter。为兼容，
仍可输出到 Obsidian vault（通过 config 的 obsidian 段），但核心职能是本地
倚账本生成每实验快照与总览索引。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional

import yaml

from .execution import ExecutionBackend, LocalExecutionBackend, build_execution_backend
from .memory import MemoryManager


class SnapshotExporter:
    """项目级进度快照 Markdown 导出器（兼容输出到 Obsidian vault）。"""

    def __init__(
        self,
        config: dict,
        project_dir: str | Path,
        backend: Optional[ExecutionBackend] = None,
    ):
        self.config = config or {}
        self.project_dir = Path(project_dir).resolve()
        self.project_name = self.project_dir.name
        self.workspace = self.project_dir / self.config.get("project", {}).get("workspace", "workspace")
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_path = self.workspace / "state.json"
        self.backend = backend or LocalExecutionBackend(self.workspace)

        self.obsidian_config = self.config.get("obsidian", {})
        self.enabled = bool(self.obsidian_config.get("enabled", False))
        self.vault_path = self.obsidian_config.get("vault_path", "")
        self.project_subdir = self.obsidian_config.get("project_subdir", "DeepResearcher/{project_name}")
        self.dashboard_note = self.obsidian_config.get("dashboard_note", "Dashboard.md")
        self.daily_dir = self.obsidian_config.get("daily_dir", "Daily")
        self.auto_append_daily = bool(self.obsidian_config.get("auto_append_daily", True))
        self.local_fallback_dir = self.obsidian_config.get("local_fallback_dir", "progress_tracking")

    def is_enabled(self) -> bool:
        return self.enabled

    def refresh_all(self, memory: MemoryManager, cycle_count: int) -> dict:
        if not self.is_enabled():
            return {"status": "disabled"}

        dashboard = self.refresh_dashboard(memory=memory, cycle_count=cycle_count)
        daily = self.append_daily_entry(memory=memory, cycle_count=cycle_count, event_type="manual_refresh")
        return {"status": "ok", "dashboard": dashboard, "daily": daily}

    def refresh_dashboard(self, memory: MemoryManager, cycle_count: int) -> dict:
        if not self.is_enabled():
            return {"status": "disabled"}

        base_dir = self._base_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        dashboard_path = base_dir / self._dashboard_filename()
        state = self._load_state()
        dashboard_path.write_text(self._render_dashboard(memory=memory, state=state, cycle_count=cycle_count))
        return {"status": "written", "path": str(dashboard_path)}

    def append_daily_entry(
        self,
        memory: MemoryManager,
        cycle_count: int,
        event_type: str = "cycle_complete",
        reflection: Optional[dict] = None,
        directive: Optional[str] = None,
    ) -> dict:
        if not self.is_enabled() or (event_type == "cycle_complete" and not self.auto_append_daily):
            return {"status": "disabled"}

        base_dir = self._base_dir()
        daily_path = base_dir / self.daily_dir / self._daily_filename()
        daily_path.parent.mkdir(parents=True, exist_ok=True)

        state = self._load_state()
        entry = self._render_daily_entry(
            memory=memory,
            state=state,
            cycle_count=cycle_count,
            event_type=event_type,
            reflection=reflection or {},
            directive=directive,
        )

        if daily_path.exists():
            existing = daily_path.read_text().rstrip()
            daily_path.write_text(f"{existing}\n\n{entry}\n")
        else:
            header = f"# {self.project_name} — Daily Log — {time.strftime('%Y-%m-%d')}\n\n"
            daily_path.write_text(f"{header}{entry}\n")

        return {"status": "written", "path": str(daily_path)}

    def _base_dir(self) -> Path:
        if self.vault_path:
            subdir = self.project_subdir.format(project_name=self.project_name)
            return Path(self.vault_path).expanduser() / subdir
        return self.workspace / self.local_fallback_dir

    def _dashboard_filename(self) -> str:
        return self.dashboard_note if self.vault_path else "Dashboard.txt"

    def _daily_filename(self) -> str:
        return f"{time.strftime('%Y-%m-%d')}.md" if self.vault_path else f"{time.strftime('%Y-%m-%d')}.txt"

    def _load_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def _parse_log_sections(self, memory: MemoryManager) -> tuple[list[str], list[str]]:
        milestones: list[str] = []
        decisions: list[str] = []
        current = None
        for line in memory.get_log().splitlines():
            stripped = line.strip()
            if stripped == "## Key Results":
                current = "milestones"
            elif stripped == "## Recent Decisions":
                current = "decisions"
            elif stripped.startswith("["):
                if current == "milestones":
                    milestones.append(stripped)
                elif current == "decisions":
                    decisions.append(stripped)
        return milestones, decisions

    def _read_pending_directive(self) -> str:
        directive_path = self.workspace / "HUMAN_DIRECTIVE.md"
        if directive_path.exists():
            return directive_path.read_text().strip()
        return ""

    def _read_log_tail(self, log_file: str, lines: int = 8) -> str:
        if not log_file:
            return ""
        try:
            return "\n".join(self.backend.tail_file(log_file, lines=lines))
        except Exception:
            path = Path(log_file)
            if path.is_absolute() and path.exists():
                return "\n".join(path.read_text().splitlines()[-lines:])
        return ""

    def _pid_alive(self, pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            return self.backend.is_process_alive(int(pid))
        except Exception:
            return False

    def _format_status(self, state: dict) -> str:
        status = state.get("status", "idle")
        pid = state.get("pid")
        if status == "running" and self._pid_alive(pid):
            started_at = state.get("started_at")
            elapsed = ""
            if started_at:
                elapsed = f", {((time.time() - float(started_at)) / 3600):.1f}h"
            return f"TRAINING (PID {pid}{elapsed})"
        if status == "completed":
            return "COMPLETED"
        if status == "error":
            return "ERROR"
        if status == "failed":
            terminal_state = state.get("terminal_state")
            if terminal_state and terminal_state != "unknown":
                return f"FAILED ({terminal_state})"
            return "FAILED"
        if status == "no_pid":
            return "FAILED (no PID)"
        return "IDLE"

    def _render_dashboard(self, memory: MemoryManager, state: dict, cycle_count: int) -> str:
        milestones, decisions = self._parse_log_sections(memory)
        pending_directive = self._read_pending_directive()
        best_result = milestones[-1] if milestones else "None yet"
        latest_decisions = decisions[-3:] if decisions else []
        log_tail = state.get("last_training_logs") or self._read_log_tail(state.get("log_file", ""))
        latest_snapshot = log_tail or "No active or recent training log."
        suggested_next = state.get("suggested_next_step") or (latest_decisions[-1] if latest_decisions else "Continue with current research direction.")

        lines = [
            f"# {self.project_name} Dashboard",
            "",
            f"_Last refreshed: {time.strftime('%Y-%m-%d %H:%M:%S')}_",
            "",
            f"- Output target: {'Obsidian vault' if self.vault_path else 'project-local text fallback'}",
            "",
            "## Project",
            f"- Name: {self.project_name}",
            f"- Path: `{self.project_dir}`",
            "",
            "## Goal",
            memory.get_brief().strip() or "PROJECT_BRIEF.md is empty.",
            "",
            "## Current Status",
            f"- Status: {self._format_status(state)}",
            f"- Cycles completed: {cycle_count}",
            "",
            "## Best Result",
            f"- {best_result}",
            "",
            "## Latest Training Snapshot",
            "```text",
            latest_snapshot,
            "```",
            "",
            "## Recent Decisions",
        ]

        if latest_decisions:
            lines.extend([f"- {entry}" for entry in latest_decisions])
        else:
            lines.append("- None yet")

        lines.extend(
            [
                "",
                "## Pending Directive",
                pending_directive if pending_directive else "None",
                "",
                "## Suggested Next Step",
                suggested_next,
                "",
            ]
        )
        return "\n".join(lines)

    def _render_daily_entry(
        self,
        memory: MemoryManager,
        state: dict,
        cycle_count: int,
        event_type: str,
        reflection: dict,
        directive: Optional[str],
    ) -> str:
        milestones, decisions = self._parse_log_sections(memory)
        latest_metric = state.get("last_metrics", {})
        latest_metric_text = ", ".join(f"{k}={v}" for k, v in latest_metric.items()) if latest_metric else "none"
        last_milestone = reflection.get("milestone") or state.get("last_milestone") or (milestones[-1] if milestones else "none")
        last_decision = reflection.get("decision") or state.get("last_decision") or (decisions[-1] if decisions else "none")
        blocker = state.get("last_error") or "none"
        consumed = directive or state.get("last_directive") or "none"

        lines = [
            f"## {time.strftime('%H:%M:%S')} — Cycle {cycle_count} ({event_type})",
            "",
            f"- Status: {self._format_status(state)}",
            f"- Best/new result: {last_milestone}",
            f"- Metrics: {latest_metric_text}",
            f"- Decision: {last_decision}",
            f"- Directive consumed: {consumed}",
            f"- Blocker: {blocker}",
        ]
        return "\n".join(lines)


def _load_config(project: Path, config_name: str) -> dict:
    config_path = project / config_name
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


# ---------------------------------------------------------------------------
# B+C 轻量方案：per-exp 快照纯函数 + 全局 Dashboard 总览索引
# ---------------------------------------------------------------------------
# 以「实验 ID（exp_{cycle}_{pid}）」为粒度，将账本中每一条实验记录渲染为
# 独立、只写一次的 Markdown 快照文件；全局 Dashboard 仅作为总览索引，把
# 所有实验快照文件链接起来。纯函数，不依赖 ExecutionBackend / Obsidian vault，
# 由调用方（loop 或独立 CLI）注入数据源，从而与核心循环完全解耦。
# ---------------------------------------------------------------------------


def make_experiment_id(cycle: int, pid) -> str:
    """构造稳定的实验 ID：exp_{cycle}_{pid}。

    cycle 为整数、pid 可缺省（缺省用 0000 占位以保证文件名唯一可排序）。
    """
    pid_part = str(int(pid)) if pid not in (None, "", 0) else "0000"
    return f"exp_{int(cycle):03d}_{pid_part}"


def _fmt_metrics(metrics) -> str:
    """把 metrics 字典渲染为紧凑的 key=value 行。"""
    if not isinstance(metrics, dict) or not metrics:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in metrics.items())


def render_experiment_snapshot(entry: dict) -> str:
    """把账本中的单条实验记录渲染为人类可读的 Markdown 快照文本。

    entry 预期为 ledger/experiments.jsonl 中一条记录：含 cycle、pid、
    hypothesis、metrics、verdict、conclusion、artifact_manifest_uri 等字段。
    """
    cycle = entry.get("cycle")
    pid = entry.get("pid")
    exp_id = make_experiment_id(cycle or 0, pid)
    ts = entry.get("ts")
    lines = [
        f"# Experiment {exp_id}",
        "",
        f"- Cycle: `{cycle}`",
        f"- PID: `{pid if pid is not None else '--'}`",
        f"- Log file: `{entry.get('log_file') or '--'}`",
        f"- Timestamp: `{ts}`",
        "",
    ]
    hypothesis = (entry.get("hypothesis") or "").strip()
    if hypothesis:
        lines += ["## Hypothesis", "", "```text", hypothesis, "```", ""]
    status = entry.get("status") or ""
    verdict = entry.get("verdict") or ""
    if status:
        lines.append(f"- Status: `{status}`")
    if verdict:
        lines.append(f"- Verdict: `{verdict}`")
    metrics = entry.get("metrics")
    if isinstance(metrics, dict) and metrics:
        # 避免把整个 dict 塞进去，只渲染标量/字符串类型的指标。
        scalar = {k: v for k, v in metrics.items()}
        lines.append(f"- Metrics: {_fmt_metrics(scalar)}")
    lines.append("")
    conclusion = (entry.get("conclusion") or "").strip()
    if conclusion:
        lines += ["## Conclusion", "```text", conclusion, "```", ""]
    manifest = entry.get("artifact_manifest_uri")
    if manifest:
        lines += [f"- Artifact manifest: `{manifest}`"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def merge_entries_by_cycle(entries) -> list:
    """把账本中「同一实验」的多次记录（launch + verdict）聚合为一份快照数据。

    一轮实验在账本里通常有多次写操作：launch（含 pid/log_file）与 verdict
    （含 metrics/verdict/conclusion）。按 cycle 分组后，把 launch 侧的身份字段
    （pid、log_file、status）与 verdict 侧的结果字段（metrics、verdict、
    conclusion、artifact_manifest_uri）合并为一条 dict，从而一个实验一份快照。
    """
    groups: dict = {}
    for entry in entries:
        cycle = entry.get("cycle")
        if cycle is None:
            continue
        g = groups.setdefault(cycle, {})
        # 身份字段优先来自 launch 记录（有 pid 的那条）。
        for key in ("pid", "log_file", "status", "experiment_id"):
            if entry.get(key) and not g.get(key):
                g[key] = entry.get(key)
        # 结果字段以非空的覆盖为准。
        for key in ("hypothesis", "metrics", "verdict", "conclusion",
                    "artifact_manifest_uri", "contract_status", "promotion_status"):
            val = entry.get(key)
            if val not in (None, "", {}):
                g[key] = val
        g["cycle"] = cycle
        # 时间取最早（launch 时间）作为起始时间。
        if "ts" not in g or (entry.get("ts") is not None and entry.get("ts") < g.get("ts")):
            if entry.get("ts") is not None:
                g["ts"] = entry.get("ts")
    return list(groups.values())


def write_experiment_snapshot(records_dir, entry: dict, overwrite: bool = True) -> Optional[Path]:
    """把单条实验记录写入独立快照文件 exp_{cycle}_{pid}.md。

    - records_dir: 快照输出目录（本地 progress_tracking 风格位置）。
    - entry: 单条 ledger 记录。
    - overwrite: 每次刷新是否覆盖（True=只写一次语义下最后一次为准，False=存在则跳过）。
    返回写出的文件路径；数据不足时返回 None。
    """
    cycle = entry.get("cycle")
    if cycle is None:
        return None
    out_dir = Path(records_dir)
    exp_id = make_experiment_id(cycle, entry.get("pid"))
    # 新实现统一为 .md；两种来源的 .txt 历史由 Dashboard 索引列出。
    path = out_dir / f"{exp_id}.md"
    if path.exists() and not overwrite:
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(render_experiment_snapshot(entry), encoding="utf-8")
    return path


def build_dashboard_index(records_dir, records_dir_abs: Optional[Path] = None) -> str:
    """根据已有 exp_*.md 快照文件，生成全局 Dashboard 总览索引（Markdown）。

    仅作为「总览索引」：列出每个实验 ID、相关 metrics，并链接到对应快照文件。
    不覆写旧 Dashboard.md；由调用方决定写到哪（本地 progress_tracking 或 vault）。
    """
    out_dir = Path(records_dir)
    snapshot_files = sorted(out_dir.glob("exp_*.md")) if out_dir.exists() else []
    lines = [
        "# Dashboard",
        "",
        "> 总览索引：列出全部实验快照（exp_{cycle}_{pid}.md）。",
        "",
        f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## Experiments",
        "",
    ]
    if not snapshot_files:
        lines.append("_No experiment snapshots yet._")
        lines.append("")
        return "\n".join(lines)

    all_index = []
    for p in snapshot_files:
        # 从文件首行标题提取实验 ID，作为稳定的显示名与链接锚点。
        exp_id = p.stem
        try:
            first = p.read_text(encoding="utf-8").splitlines()[0]
            if first.startswith("# "):
                exp_id = first[2:].strip()  # e.g. "Experiment exp_013_0000"
        except Exception:
            pass
        rel = p.name
        all_index.append(f"- `{exp_id}`  →  [`{rel}`]({rel})")
    lines += all_index
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Refresh progress snapshot Markdown from Deep Researcher project state")
    parser.add_argument("--project", type=str, required=True, help="Path to project directory")
    parser.add_argument("--config", type=str, default="config.yaml", help="Project config file")
    parser.add_argument("--dashboard-only", action="store_true", help="Only refresh Dashboard.md")
    parser.add_argument("--daily-only", action="store_true", help="Only append daily note")
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    config = _load_config(project_dir, args.config)
    memory = MemoryManager(
        project_dir=project_dir,
        brief_max=config.get("memory", {}).get("brief_max_chars", 3000),
        log_max=config.get("memory", {}).get("log_max_chars", 2000),
        milestone_max=config.get("memory", {}).get("milestone_max_chars", 1200),
        max_recent=config.get("memory", {}).get("max_recent_entries", 15),
    )
    backend = build_execution_backend(
        config=config,
        controller_workspace=project_dir / config.get("project", {}).get("workspace", "workspace"),
    )
    exporter = SnapshotExporter(config=config, project_dir=project_dir, backend=backend)
    cycle_path = project_dir / config.get("project", {}).get("workspace", "workspace") / ".cycle_counter"
    cycle_count = int(cycle_path.read_text().strip()) if cycle_path.exists() else 0

    if not exporter.is_enabled():
        print("Progress export disabled. Set obsidian.enabled=true in project config.")
        return

    if args.dashboard_only:
        result = exporter.refresh_dashboard(memory=memory, cycle_count=cycle_count)
    elif args.daily_only:
        result = exporter.append_daily_entry(memory=memory, cycle_count=cycle_count, event_type="manual_refresh")
    else:
        result = exporter.refresh_all(memory=memory, cycle_count=cycle_count)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
