# EVD-G0-018 Mutation Map（worktree / artifact / ledger 变更点现状）

- **Evidence ID**：EVD-G0-018
- **Owner**：DEV-VCS-01
- **Collected by**：CodeBuddy（Tech Lead / ARCH-01）
- **Collected at UTC**：2026-08-16T16:40:00Z
- **Gate**：G0_EVIDENCE_CLOSURE

## 现状变更点（mutation map）

### 1. Worktree 变更
- 见 EVD-G0-011：7 个未跟踪文件（交付文档 + train_v42.py 遗留）。
- 无已跟踪文件被修改（`git status` 显示 0 modified-tracked）。

### 2. champion 写入路径（当前唯一写者）
- `core/loop.py::_try_promote`（约 line 486-488）仅在 KEEP 时被调用。
- champion 指标存入 `ledger`（`experiments.jsonl` 的 best_metric）。
- `core/git_vcs.py` 提供 GitExperimentVcs（提交实验制品）。
- **当前没有 PromotionCommitter**——champion 写入与 git 提交分离，非单一事务。

### 3. ledger 变更
- `core/ledger.py`：追加式写 experiments.jsonl（已具备 append-only 雏形）。
- 每条记录含 cycle / verdict / metrics。
- **没有 idempotency_key / schema_version / input_bundle_hash**（V3.0 P0-020 需要）。

### 4. artifact 变更
- 当前训练脚本保存 model 到 workspace，无 ArtifactManifest 原子化。
- `core/git_vcs.py` 有 manifest 雏形，但未做"先归档后裁决"事务（V3.0 P0-010 需要）。

## 状态
- **CONFIRMED（现状）**：champion 写者=loop._try_promote，无独立 Committer；无 manifest 原子事务。
- **UNKNOWN（G1 冻结项）**：正式 CAS / idempotency / single-writer cutover 合同未冻结。
