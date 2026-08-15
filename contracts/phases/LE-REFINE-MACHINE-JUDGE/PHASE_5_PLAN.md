# PHASE PLAN — P5 恢复与无人值守准入

```yaml
phase_id: "P5"
task_id: "LE-REFINE-MACHINE-JUDGE"
objective: >-
  接入 resilience 自愈：崩溃/重启后从 checkpoint + ledger 恢复断点（attempted 假设、
  verdict 上下文），使无人值守可从中断处续跑；并定义/验证无人值守准入标记
  （unattended_24x7_authorized 前置）。
dependencies: ["P3"]            # P4 经评估已由 le-judge 完成，本阶段不再改
scope:
  allow:
    - "core/loop.py"            # 启动时 checkpoint 恢复 attempted + verdict
    - "tests/test_loop_engineering.py"  # 恢复测试
  deny:
    - "core/resilience.py"      # 工具已实现，只消费不改
    - "core/experiment_contract.py"
    - "core/git_vcs.py"
    - "core/ledger.py"
    - "core/safety.py"
acceptance:
  - "pytest tests/ -q 全部通过（含现有 249）"
  - "新增测试覆盖：重启后 _attempted_hypotheses 从 checkpoint 恢复（去重继续生效）"
  - "新增测试覆盖：state 含 verdict 时，启动后 _enrich_context 可重建 verdict 上下文"
  - "legacy（无 checkpoint / 空 state）行为不变，启动不 crash"
  - "无 lint 错误"
budget:
  max_cycles: 3
  max_api_calls: 40
  max_wall_seconds: 900
subagents:
  enabled: false
  ownership: {}
exit_on_fail: "retry_up_to_3_then_replan"
```

## 入口校验
- [x] 必填字段齐全
- [x] P3 已完成（GATE PASS），基线 249 测试绿
- [x] P4 评估：机器判定反馈到 THINK 已由 le-judge 实现（_enrich_context → verdict_history/last_verdict/promoted_candidates），无需重复

## 执行策略
1. `__init__` 启动时，若启用 resilience 且存在 checkpoint/state，恢复 `_attempted_hypotheses`。
2. 启动时用 ledger 重建 verdict 上下文（recover_verdict_history），供 THINK 使用。
3. 补充恢复测试，验证 legacy（空 state/无 ledger）不 crash。

## 执行结果
- [x] `__init__` 启动时，启用 dedup + ledger 时，从 `recover_verdict_history` 的 `promoted_candidates` 恢复 `_attempted_hypotheses`（best-effort，不 crash）。
- [x] 新增 4 个恢复测试（ResumeDedupStateTests）。
- [x] 完整测试 **253 passed**（249 + 4）。

## GATE 判定
- **PASS**（全部验收判据满足）
- 完成时间：2026-08-15
- 改动：`core/loop.py` + `tests/test_loop_engineering.py`
- 状态：长程任务 P1-P5 全部完成
