# PHASE PLAN — P1 判定健壮性

```yaml
phase_id: "P1"
task_id: "LE-REFINE-MACHINE-JUDGE"
objective: >-
  强化运行时机器判定(_machine_judge)的健壮性：细化 INCOMPARABLE 粒度、
  完善指标缺失/异常处理、加固边界值，使判定在任何输入下都不抛异常且语义准确。
dependencies: []                # 无前置，基于已合入的 _machine_judge 基线
scope:
  allow:
    - "core/experiment_contract.py"     # decide_verdict / gate_verdict_by_contract_status 的健壮性
    - "core/loop.py"                    # _machine_judge 调用点的边界处理
    - "tests/test_loop_engineering.py"  # 判定健壮性测试
    - "tests/test_experiment_contract.py"
  deny:
    - "core/git_vcs.py"                 # P3/P5 再动，本阶段隔离
    - "core/ledger.py"                  # 账本结构本阶段不动
    - "core/resilience.py"              # P5 再动
acceptance:
  - "pytest tests/ -q 全部通过（含现有 226）"
  - "新增测试覆盖：指标非数值、metrics 为空、primary_metric 缺失、direction 非法、min_effect_size 非法 → 均返回明确 INCOMPARABLE 或安全默认，不抛异常"
  - "gate_verdict_by_contract_status 对 CRASH/TIMEOUT/BUDGET_EXCEEDED 强制非 KEEP 有测试"
  - "无 lint 错误"
  - "legacy 路径（未配置 contract）行为不变"
budget:
  max_cycles: 3
  max_api_calls: 60
  max_wall_seconds: 1200
subagents:
  enabled: false                # 本阶段单一所有权，由 lead 直接执行，避免多 agent 冲突
  ownership: {}
exit_on_fail: "retry_up_to_3_then_replan"
```

## 入口校验
- [x] 必填字段齐全（objective/scope.allow/acceptance≥2/budget）
- [x] 依赖 P1 无前置，基线为已合入的 _machine_judge（226 测试绿）
- [x] 范围隔离（git_vcs/ledger/resilience 本阶段不碰）

## 执行结果
- [x] 加固 `decide_verdict`：非法 direction/缺失 primary_metric/负 effect_size/非数值 effect_size → INCOMPARABLE；数值字符串 effect_size 自动转换；bool 指标值 → INCOMPARABLE（拒绝配置错误）。
- [x] 加固 `gate_verdict_by_contract_status`：verdict 非 dict → INCOMPARABLE（不抛异常）。
- [x] 新增 10 个健壮性测试（tests/test_git_vcs.py DecideVerdictTests）。
- [x] 完整测试 **236 passed**（原 226 + 10）。
- [x] 无 lint 错误；legacy 路径未改。

## GATE 判定
- **PASS**（全部验收判据满足）
- 完成时间：2026-08-15
- 改动：`core/experiment_contract.py` + `tests/test_git_vcs.py`
- 状态：进入 P2（收敛保障）
