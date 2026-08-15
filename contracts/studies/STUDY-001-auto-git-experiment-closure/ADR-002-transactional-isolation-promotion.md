# ADR-002 — 候选实验的事务隔离与安全晋级（Transactional Isolation & Safe Promotion）

> 状态：**APPROVED_BY_OWNER**（设计已批准，未实施）
> 审批：HUMAN_OWNER via conversation 2026-08-15（`OWNER-APPROVAL-20260815-01`）
> 关联：SDD P0-2（评审 4.2 / 7.1-7.6）、Study CONTRACT `STUDY-001`
> 基线 commit：`1331cfcec07ea673f0c1b540e1f9b9f0d667bebe`
> 作者：MAIN-00（起草）；ARCH-01/SEC-01/QA-01 评审待实施前完成

## 1. 背景与动机

阶段 0 证据闭合确认：
- 当前 `core/` 全仓 **0 处调用 git**（提交/重置/回退/分支/工作树全无）。
- `ledger.record()` 无 commit SHA、无 parent、无 verdict、无 artifact manifest。
- `_reflect` 只写记忆 + advisory 判定（stagnation/phase_gate），**无任何版本化决策**。
- 工具层 `write_file` 仅保护 4 个文件，无 allowlist/denylist 目录级保护。

评审明确指出：**不能直接 `git reset`**（多 Agent/多后端下会覆盖他人修改、无法复现）。Git reset 不是需求本身；需求是**候选实验的事务隔离与安全晋级**。

## 2. 决策

采用"**受保护 champion 分支 + 每候选独立 worktree + 制品先归档 + 追加式事件账本 + 机器权威判定**"机制。

### 2.1 分支与 worktree（评审 7.1）
- **champion 分支**：`champion/STUDY-001`，受保护，只有 fast-forward 晋级。
- **每候选独立 worktree**：`experiment/STUDY-001-<EXP_ID>`，从 champion 检出，**候选 agent 仅在自己的 worktree 内写**。
- code agent 永不直接操作共享工作区；破坏性 `reset --hard` / `clean -fd` / force push **全局禁用**。

### 2.2 候选生命周期（评审 7.3：Archive before decide）
```
SCHEDULED
  → (在独立 worktree) 候选代码 commit
  → RUNNING (训练，受 ADR-001 预算约束)
  → 归档制品: metrics/stdout/checkpoint/candidate.patch/environment/manifest+SHA256
  → VERDICT (KEEP/DISCARD/CRASH/INCOMPARABLE)
  → KEEP: champion fast-forward 至候选 commit (parent SHA 乐观锁)
     DISCARD/CRASH: champion 不变; 候选与制品保留可追溯
```

### 2.3 追加式事件账本（评审 7.5）
- `ledger.jsonl` 追加式写入（不可篡改重写）。
- 字段（对齐实验状态机）：
  ```
  exp_id, study_id, parent_champion_sha, candidate_sha,
  verdict, promotion_status, artifact_manifest_uri, metrics, budget_used,
  reason(machine), llm_narrative(opt), created_at
  ```

### 2.4 机器权威判定（评审 7.2）
- **机器判定为权威**：依据 ADR-001 指标 + min_effect_size + 置信规则 + 复杂度词典序。
- LLM 只提供 hypothesis / 解释，**不能覆盖**机器判定（`llm_narrative_can_override: false`）。
- `high_complexity_small_gain_action: HUMAN_REVIEW`。

### 2.5 并发与过期（评审 7.4）
- `max_parallel: 1`（pilot），候选串行执行。
- KEEP 需 **parent SHA 乐观锁**：若 champion 已被他人推进，则**重放重测**（stale_candidate_action）。
- 崩溃恢复：可从 ledger 重放，标记未完成候选。

## 3. 写入保护（对齐 D0）

- **allowlist**：项目根 `train.py` + `workspace/`（候选 worktree）。
- **denylist/受保护边界**：`data/`、`.codebuddy/rules/sdd/`、`contracts/`、`tests/`、`core/monitor.py`、配置 schema。
- 执行前后验证受保护文件/数据 hash 未变。
- 工具：`write_file`/`launch_experiment`/`run_shell` 在候选 worktree 上下文内执行，绝对路径越界拒绝。

## 4. 落地范围（待 Owner 批准后实施）

- `core/git_vcs.py`（新增）：worktree 管理、champion fast-forward、parent SHA 乐观锁。
- `core/ledger.py`：升级为追加式事件账本（含 SHA/verdict/manifest）。
- `core/tools.py`：worktree 内写文件约束、越界拒绝、run_shell 修复。
- `core/loop.py`：REFLECT 接入机器判定 + 晋级/归档；启用隔离 worktree。
- `core/safety.py`：禁止破坏性 git 命令。

## 5. 验收标准（对齐评审 7.6）

1. KEEP 只推进 champion，候选制品不丢失。
2. DISCARD/CRASH 不动 champion。
3. 崩溃后可从 ledger 重放恢复。
4. 并发 parent 过期不误晋级（重放重测）。
5. 破坏性 git 命令被安全层拒绝。
6. test 结果不用于晋级判定（仅验收，见 ADR-001）。

## 6. 相关

- 依赖 ADR-001（预算/评估/比较性）。
- 依赖 D0（写入保护）先行或并行落地。
- 本 ADR 为 DRAFT，未经 4 方 approval 不进入实施。
