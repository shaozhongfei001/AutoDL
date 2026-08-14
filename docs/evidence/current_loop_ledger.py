# Evidence: AutoDL 当前实验台账记录
# Source: core/loop.py:466-499
# Supports: 确认"当前项目仅写台账，无 git 回退/commit"（P0 缺失项）

def _record_to_ledger(self, think_result, execute_result, reflect_result):
    """Append this cycle's outcome to the experiment ledger and capture a
    durable insight when the reflection produced a milestone."""
    metrics = execute_result.get("final_metrics") or {}
    if execute_result.get("experiment_launched"):
        status = execute_result.get("experiment_status") or "launched"
    else:
        status = think_result.get("action", "") or "no_experiment"
    terminal_state = execute_result.get("terminal_state", "")
    conclusion = reflect_result.get("milestone") or reflect_result.get("decision", "")
    # 只写入 JSON 台账（experiments.jsonl），无任何 git 操作
    self.ledger.record(
        cycle=self.cycle_count,
        hypothesis=think_result.get("hypothesis") or think_result.get("task", ""),
        action=think_result.get("action", ""),
        status=status,
        metrics=metrics,
        pid=execute_result.get("pid"),
        log_file=execute_result.get("log_file", ""),
        conclusion=conclusion,
    )
    if self.journal is not None and reflect_result.get("milestone"):
        self.journal.append_insight(reflect_result["milestone"])

# 结论：
# - 当前项目用 experiments.jsonl 记录实验结果（status/metrics/conclusion）
# - 但**没有 git commit 保留改进**、**没有 git reset 回退坏改动**
# - 对比 autoresearch：改进时不形成可回溯的 commit 历史，变差时不回退，
#   迭代无法保证"单调向优"，代码仓库也不随实验演进
