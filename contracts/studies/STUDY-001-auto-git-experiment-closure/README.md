# STUDY-001 — auto-git-experiment-closure

> 首个 SDD 治理试点研究：验证 AutoDL 引入"实验有效性合同 + 事务隔离晋级 + 受保护写入边界"机制的可执行性与安全性。
> **状态：DRAFT / 未批准**。本目录文件均为"详细设计"产物，不构成任何实施授权。

## 目录文件

| 文件 | 内容 | 状态 |
|------|------|------|
| `STUDY_CONTRACT.yaml` | 机器可读研究合同（数据/评估/预算/环境/变更边界/晋级/审批） | DRAFT |
| `ADR-001-experiment-validity-contract.md` | P0-1 实验有效性合同设计（预算/评估/split/比较性/状态机） | DRAFT |
| `ADR-002-transactional-isolation-promotion.md` | P0-2 事务隔离与安全晋级设计（worktree/champion/账本/机器判定） | DRAFT |
| `QA_GATE_PLAN.md` | 独立 QA Gate 1/Gate 2 验收矩阵 | DRAFT |

## 关键事实（基线）

- **基线 commit**：`1331cfcec07ea673f0c1b540e1f9b9f0d667bebe`
- **hardware cohort**：`COHORT-RTX3060L-6G`（RTX 3060 Laptop 6GB, CUDA 12.4, torch 2.5.0+cu124）
- **数据**：MNIST official idx-ubyte raw（4 项 SHA256 已在合同 Data Contract 固化）
- **预算**：active_wall_clock=300s / hard=420s
- **split 职责**：validation 选优（maximize），test 仅独立验收（不回流）

## 当前审批状态

- HUMAN_OWNER / MAIN-00 / ARCH-01 / SEC-01 / QA-01：**全部 PENDING**
- `implementation_authorized=false`、`pilot_authorized=false`

## 下一步（需 Owner 批准后）

1. 审阅并批准 Study Contract + 2 份 ADR
2. 授权实施（阶段 1：A 合同 + 阶段 2：D0 写入保护）
3. 实施后提交代码，QA-01 执行 Gate 2
4. 试点 `max_parallel=1`，跑首个候选实验
