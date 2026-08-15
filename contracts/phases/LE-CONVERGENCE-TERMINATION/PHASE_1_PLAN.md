# PHASE PLAN — P1 无人值守主动终止条件（I1, P0）

```yaml
phase_id: "P1"
task_id: "LE-CONVERGENCE-TERMINATION"
objective: >-
  为无人值守循环添加主动收敛/终止策略：max_cycles=-1 下，若连续 N 轮无 KEEP 或无
  新真实改进，或 no_progress_escalation 达到 terminate，循环应自动收敛停止，
  而非无限空转。产出可审计的终止原因并固化。
dependencies: []
scope:
  allow:
    - "core/loop.py"                    # 终止判定逻辑
    - "core/experiment_contract.py"     # 收敛策略辅助（可选）
    - "tests/test_loop_engineering.py"  # 终止测试
    - "examples/mnist_gpu/config.yaml"  # convergence 配置
  deny:
    - "core/git_vcs.py"
    - "core/ledger.py"
    - "core/resilience.py"
    - "core/safety.py"
acceptance:
  - "pytest tests/ -q 全部通过（含现有 253）"
  - "新增测试：连续 N 轮无 KEEP 触发自动终止（返回终止原因）"
  - "新增测试：no_progress_escalation=terminate 时真正停止（非仅 advisory）"
  - "新增测试：legacy（max_cycles=-1 且未配置 convergence）行为不变（不误终止）"
  - "无 lint 错误"
budget:
  max_cycles: 3
  max_api_calls: 50
  max_wall_seconds: 1000
subagents:
  enabled: false
  ownership: {}
exit_on_fail: "retry_up_to_3_then_replan"
```

## 入口校验
- [x] 必填字段齐全
- [x] 基于验收报告 I1（P0 无主动终止条件）
- [x] 基线 253 测试绿

## 执行策略
1. 在 loop.py 引入 `convergence` 策略：`max_no_improvement_rounds`（连续无 KEEP 即终止）。
2. `no_progress_escalation` 达 `terminate` 时，记录终止原因并返回停止信号（非仅 advisory）。
3. 在 `run()` 主循环尾部检查收敛条件，触发时设置 `self._running=False` + 记录终止原因到 ledger/memory。
4. 补充测试，验证 legacy 不变。

## 执行结果
- [x] `__init__` 引入 `_conv_max_no_improvement_rounds`（default 10，0 禁用 legacy）+ `_no_improvement_streak` + `_convergence_reason`。
- [x] `_machine_judge` 判定处：KEEP 重置 streak，DISCARD/INCOMPARABLE 递增。
- [x] `run()` 主循环尾部：max_cycles<0 时，streak>=limit 或 no_progress=terminate → 记录终止原因 + 停止。
- [x] 新增 5 个收敛测试（ConvergenceTerminationTests）。
- [x] 完整测试 **258 passed**（253 + 5）。

## GATE 判定
- **PASS**（全部验收判据满足）
- 完成时间：2026-08-15
- 改动：`core/loop.py` + `tests/test_loop_engineering.py`
- 状态：I1（P0）已修复；I2/I3 待后续阶段
