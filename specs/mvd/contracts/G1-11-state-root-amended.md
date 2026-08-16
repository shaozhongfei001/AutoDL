# G1-11a — 运行态 State Root 修订（D-11）

- **策略 ID**：MVD-STATE-ROOT-V2
- **状态**：APPROVED_AS_AMENDED_D11
- **Owner 决定**：`D11=APPROVED_AS_AMENDED_EXTERNAL_RUNTIME_STATE_ROOT`
- **生效**：STUDY-MVD-SH-QWEN-001（G1）
- **更新于 UTC**：2026-08-17T05:00:00Z

## 正式决定（Owner）

运行态 artifact/ledger **不得写入 specs/**，必须位于 Git worktree 外。

```text
MVD_STATE_ROOT=/home/szf/mvd-state
artifact.root=${MVD_STATE_ROOT}/studies/${study_id}/artifacts
ledger.path=${MVD_STATE_ROOT}/studies/${study_id}/ledger/events.jsonl
```

## State Root 属性（Tech Lead 实测记录，2026-08-17）

| 属性 | 值 |
|---|---|
| realpath | `/home/szf/mvd-state` |
| filesystem / device | ext4, /dev/nvme0n1p6 |
| owner / group | szf / szf |
| mode | 775 (rwxrwxr-x) |
| 可用空间 | 247 GB |
| 是否在 Git worktree 内 | **否**（git rev-parse 确认非 git 仓库） |

## 原子 rename 能力

ext4 支持原子 rename（`rename()` 同文件系统内原子替换）。已确认 `/home/szf/mvd-state` 与 `/home/szf/env/AutoDL`、`/home/szf/env/AutoDL_governance` 位于**同一文件系统**（/dev/nvme0n1p6），artifact 原子发布（RENAME_TO_FINAL_OR_ABORT）可用。

## Append-only / 防覆盖策略

- ledger：append-only，`events.jsonl` 只追加；运行态不提供覆盖/删除接口。
- artifact：CAS + SHA256，内容寻址，已发布产物不可覆盖。
- 原子发布：rename 到最终名或 abort，避免部分写入被读取。

## Retention 与恢复策略

- retention_policy_id：`MVD-RET-001`（candidate artifacts 保留 30 天，champion baseline 永久）。
- 恢复：从 sha256-manifest + append-only ledger 可完整重放（replay_required=true）。

## 禁止 Code Agent 写入的 ACL 证据

- 目标 ACL：`svc-mvd-iterative-v1`、`svc-mvd-final-eval-v1` 对 `artifact/` 有写（各自命名空间），对 `ledger/` 只读；`svc-mvd-committer-v1` 对 ledger append；`qa-01-readonly-review` 全只读。
- **Code Agent（LLM 迭代 agent）禁止写入 ledger 与已发布 artifact**，仅能通过 svc principals 间接写入。
- 当前 OS 层 owner=szf 仅为开发期占位，G2 需映射为 service identity + ACL（见 D-10）。

## specs/mvd/ledger/ 用途

- `specs/mvd/ledger/` 仅保存 ledger **schema** 或**示例**，不保存运行态 ledger。
- 运行态 ledger 在 `${MVD_STATE_ROOT}/studies/${study_id}/ledger/events.jsonl`。

## 影响

- 本修订替换原方案（原 artifact_root=`artifacts/mvd/`、ledger_path=`specs/mvd/ledger/`，不批准）。
- 更新 G1-10 artifact-ledger contract 的路径。
