# PHASE PLAN — P3 统计严谨性

```yaml
phase_id: "P3"
task_id: "LE-REFINE-MACHINE-JUDGE"
objective: >-
  增强机器判定的统计严谨性：decide_verdict 支持多种子聚合（多指标取均值/中位），
  并支持基于实测噪声（pooled_std）的动态 min_effect_size 校准，避免单一偶然结果
  误判 KEEP，使晋级基于可信统计而非噪声。
dependencies: ["P2"]
scope:
  allow:
    - "core/experiment_contract.py"   # decide_verdict 多种子 + 噪声校准
    - "core/loop.py"                  # _machine_judge 传入种子/噪声上下文（可选）
    - "tests/test_git_vcs.py"         # 多种子判定测试
  deny:
    - "core/git_vcs.py"
    - "core/ledger.py"
    - "core/safety.py"
    - "core/resilience.py"            # P5 再动
acceptance:
  - "pytest tests/ -q 全部通过（含现有 242）"
  - "新增测试覆盖：decide_verdict 接受多个候选值（列表）取均值后再比；空列表/单值兼容"
  - "新增测试覆盖：提供 noise_std 时，min_effect_size 动态为 max(配置值, k*noise_std)"
  - "legacy（单值、无 noise）行为不变"
  - "无 lint 错误"
budget:
  max_cycles: 3
  max_api_calls: 60
  max_wall_seconds: 1200
subagents:
  enabled: false
  ownership: {}
exit_on_fail: "retry_up_to_3_then_replan"
```

## 入口校验
- [x] 必填字段齐全
- [x] P2 已完成（GATE PASS），基线 242 测试绿

## 执行策略
1. `decide_verdict` 支持 `candidate_metrics[primary]` / `champion_metrics[primary]` 为 list（多种子），
   聚合取均值后再判定；仍兼容单值（float/str）。
2. 新增可选参数 `noise_std`：若提供，`effective_effect_size = max(配置 min_effect_size, 2*noise_std)`
   （置信规则 2×pooled_std），动态拒绝噪声级改进。
3. 补充多种子 + 噪声校准测试，验证 legacy 不变。

## 执行结果
- [x] 新增 `_aggregate_metric`：list/tuple → 均值；单值 → float；bool/空/非数值 → None。
- [x] `decide_verdict` 支持多种子聚合 + `noise_std` 动态校准（effective = max(配置, 2*noise_std)）。
- [x] 新增 7 个统计测试。
- [x] 完整测试 **249 passed**（242 + 7）。

## GATE 判定
- **PASS**（全部验收判据满足）
- 完成时间：2026-08-15
- 改动：`core/experiment_contract.py` + `tests/test_git_vcs.py`
- 状态：进入 P4（自我迭代闭环）
