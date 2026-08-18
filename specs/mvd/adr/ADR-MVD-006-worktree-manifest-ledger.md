# ADR-MVD-006 — Worktree、Manifest、Ledger、CAS、Fencing

- **ADR ID**：ADR-MVD-006
- **主题**：事务隔离与产物账本
- **Owner**：ARCH-01 + DEV-VCS-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：artifact-ledger-contract/v1 + isolation-contract/v1
- **关联 Gate**：G1 → G4
- **日期**：2026-08-17

## 决策

采用以下机制保证事务隔离与可追溯：

- **Worktree 隔离**：每个 candidate 在独立 worktree 中开发（isolate before mutate）。
- **Manifest + SHA-256**：候选实验产物必须先落 manifest（含 SHA-256）再进入 KEEP/DISCARD（archive before decide）。
- **Append-only ledger**：ledger 只追加，不可变；记录所有实验事务。
- **CAS（内容寻址）**：产物以内容哈希寻址，避免冲突/覆盖。
- **Fencing**：hard timeout / 资源配额超限时强制终止（fencing）训练进程。
- **原子发布**：`RENAME_TO_FINAL_OR_ABORT`。
- **Replay**：从 sha256-manifest + ledger 可重放；stale candidate → replay and retest。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 直接在共享工作区修改 | 破坏隔离，违反 Isolate before mutate |
| 无 manifest 直接判定 | 违反 Archive before decide |
| 可覆盖 ledger | 不可追溯，违反 append-only |

## 风险

- worktree 管理开销；需 DEV-VCS-01 在 G4 验证跨 worktree 一致性。
- CAS 与 git 大文件冲突；已设 `git_large_binaries_forbidden`。
- fencing 误触发可能丢失候选结果；需保留 artifact_finalize 时序。

## 回滚

- 若 worktree 机制阻塞，回退为隔离分支（git branch）+ 相同 manifest/ledger 契约，QA 评审。

## Owner 与生效

- Owner：ARCH-01 + DEV-VCS-01
- 生效条件：G1 产物/账本合同批准后生效。
