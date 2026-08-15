# PHASE PLAN — P2 收敛保障

```yaml
phase_id: "P2"
task_id: "LE-REFINE-MACHINE-JUDGE"
objective: >-
  把已实现的收敛工具（core/safety.py 的 check_hypothesis_dedup / escalate_no_progress）
  真正接入主循环 core/loop.py：THINK 前置做假设去重，no_progress 升级与机器判定联动，
  使无人值守迭代具备收敛性（不重复假设、无进展时升级而非空转）。
dependencies: ["P1"]            # 依赖 P1 已合入
scope:
  allow:
    - "core/loop.py"            # 接入假设去重 + no_progress 升级
    - "tests/test_loop_engineering.py"  # 收敛接入测试
  deny:
    - "core/experiment_contract.py"     # P1 已固化，本阶段隔离
    - "core/safety.py"                  # 工具已实现，本阶段只消费不改
    - "core/git_vcs.py"
    - "core/ledger.py"
    - "core/resilience.py"              # P5 再动
acceptance:
  - "pytest tests/ -q 全部通过（含现有 236）"
  - "新增测试覆盖：THINK 假设重复时被 gate（allowed=false）、去重后换思路"
  - "新增测试覆盖：no_progress 升级（widen/lower_target/terminate）在 loop 中被消费"
  - "legacy 路径（dedup 关闭）行为不变"
  - "无 lint 错误"
budget:
  max_cycles: 3
  max_api_calls: 60
  max_wall_seconds: 1200
subagents:
  enabled: false                # 单一所有权，lead 直接执行
  ownership: {}
exit_on_fail: "retry_up_to_3_then_replan"
```

## 入口校验
- [x] 必填字段齐全
- [x] P1 已完成（GATE PASS），基线 236 测试绿
- [x] safety.py 收敛工具已存在（le-resilience 实现），本阶段只接入消费

## 执行策略
1. 审查 `_apply_no_progress_fallback` 与 THINK 调用链（loop.py 152-198、617-673）。
2. THINK 后接入 `check_hypothesis_dedup`：重复则追加"duplicate"提示给 LLM（换思路），并记录 attempted 集合。
3. no_progress 追踪处接入 `escalate_no_progress`：升级 level 消费（widen→提示拓宽、lower_target→降低目标、terminate→记录待人工）。
4. 补充测试，验证 legacy 不变。

## 执行结果
- [x] `__init__` 新增 `_dedup_enabled`/`_repeated_hypothesis_limit`/`_attempted_hypotheses`（config: experiment.loop_engineering.dedup）。
- [x] THINK 后接入 `_apply_hypothesis_dedup`：重复假设 → wait + advisory，记录 attempted 集合。
- [x] `_apply_no_progress_fallback` 接入 `escalate_no_progress`：返回 `no_progress_escalation`(widen/lower_target/terminate) + advice。
- [x] 新增 6 个收敛测试（ConvergenceTests）。
- [x] 完整测试 **242 passed**（236 + 6）。

## GATE 判定
- **PASS**（全部验收判据满足）
- 完成时间：2026-08-15
- 改动：`core/loop.py` + `tests/test_loop_engineering.py`
- 状态：进入 P3（统计严谨性）
