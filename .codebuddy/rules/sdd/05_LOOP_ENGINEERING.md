# SDD 05 — Loop Engineering 机制契约（无人值守自我迭代）

> **状态：MANDATORY**（强制）。本项目必须支持 Loop Engineering——在无人干预下，
> 通过机器驱动的自我评估、决策、晋级/回退闭环，持续迭代解决深度学习训练问题。
> 本契约定义机制要求，代码必须满足后方可开启 `unattended_24x7_authorized`。

## 1. 定义

**Loop Engineering** = 一个 agent 循环在**无人干预**下，能够：
1. 持续提出并验证实验假设（THINK→EXECUTE→MONITOR→REFLECT）
2. **机器驱动**判定每个候选是改进(KEEP)还是变差(DISCARD)（非 LLM 自述）
3. 自动保留改进、回退变差（晋级/隔离）
4. **收敛**：避免重复假设、无进展空转、资源耗尽
5. **自愈**：从错误/断点恢复并继续迭代

## 2. 必需机制（缺一不可）

### M1. 自主循环主控（已具备）
- `while running` 无限循环，`max_cycles=-1` 支持无人值守。
- 每 cycle：THINK→EXECUTE→MONITOR→REFLECT。

### M2. 机器判定闭环（必须接入）★核心缺口
- `_reflect` 必须调用 `decide_verdict(candidate, champion, primary_metric, min_effect_size)`。
- 判定结果 `KEEP/DISCARD/INCOMPARABLE` 为**机器权威**。
- LLM 只提供 hypothesis/解释，`llm_narrative_can_override=false`（不可覆盖机器判定）。
- 判定依据 `contract_status`（SUCCESS/BUDGET_EXCEEDED/TIMEOUT/CRASH）+ validation 主指标 + min_effect_size + 置信规则。

### M3. 隔离与晋级（必须接入）★核心缺口
- code agent 在**独立候选 worktree** 写代码（`GitExperimentVcs.create_candidate_worktree`），共享工作区零污染。
- KEEP → `promote_to_champion`（parent-SHA 乐观锁，fast-forward only）。
- DISCARD/CRASH → 冠军分支不变，候选与制品保留可追溯。
- STALE（并发过期）→ 重放重测。

### M4. 制品先归档（必须）★核心缺口
- 训练完成后、判定前，用 `build_artifact_manifest` 固化 metrics/log/checkpoint/diff + SHA256。
- 每次判定调用 `ledger.record_verdict`，形成不可变血缘：
  `champion_before → candidate → verdict → champion_after`。

### M5. 收敛保障（必须强化）
- 假设去重：`repeated_hypothesis_limit` 内相同假设不允许重复执行。
- 无进展兜底：`no_progress_streak` 触发后进入等待，避免空转。
- **搜索空间收敛**：候选生成必须基于当前 champion，逐步缩小搜索范围（simplicity criterion）。
- 资源配额：预算 + hard_wall_clock_limit + max_parallel 约束。

### M6. 自愈恢复（必须强化）
- 错误冷却后自动继续（非终止）。
- 崩溃后从 `ledger.jsonl` 重放，标记未完成候选。
- 优雅关闭（SIGTERM/SIGINT）保存状态，重启后从断点续跑。

## 3. 状态机（实验 + 晋级）

```
THINK → EXECUTE → MONITOR → [ARCHIVE] → VERDICT → [PROMOTE|DISCARD|STALE]
  ↑                                                          │
  └────────────── 下一 cycle（基于新 champion）─────────────┘
```

实验状态：`PROPOSED → SCHEDULED → RUNNING → FINISHED{SUCCESS/TIMEOUT/BUDGET_EXCEEDED/CRASH/INCOMPARABLE}`
晋级状态：`PENDING → KEEP_PROMOTED / DISCARDED / STALE_REPLAY`

## 4. 无人值守准入（Gate 条件）

开启 `unattended_24x7_authorized` 前必须全部满足：
- [ ] M2 机器判定已接入 `_reflect`
- [ ] M3 隔离 worktree + 晋级已接入 `_execute`/REFLECT
- [ ] M4 artifact manifest + verdict ledger 在判定前归档
- [ ] M5 收敛（假设去重 + no_progress + 资源配额）
- [ ] M6 自愈（错误恢复 + 崩溃重放 + 断点续跑）
- [ ] 完整测试套件通过（含 Loop Engineering 集成测试）
- [ ] Gate 4（Integration & Recovery）独立 QA 通过

## 5. 不变量

- 机器事实 > LLM 自述（判定永远基于结构化指标）。
- 冠军永不回退（DISCARD/CRASH 不动 champion）。
- Archive before decide（无 manifest 不判定）。
- 无预算约束不得无人值守运行。

## 6. 验收（QA）

| ID | 检查项 |
|----|--------|
| LE-01 | 无人值守 5+ cycles，无人工干预持续迭代 |
| LE-02 | 机器判定正确：改进 KEEP、变差 DISCARD、缺指标 INCOMPARABLE |
| LE-03 | 晋级 fast-forward-only，parent 乐观锁拒绝过期 |
| LE-04 | 每次判定前有 artifact manifest（SHA256） |
| LE-05 | 假设去重：相同假设被拒/跳过 |
| LE-06 | 崩溃后可从 ledger 重放恢复继续 |
| LE-07 | 资源预算/配额全程生效，无超限 |
