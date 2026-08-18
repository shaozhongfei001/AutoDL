# MVD V3.0 Owner Decision Record

**Decision ID：** `ODR-MVD-20260816-001`  
**项目：** `auto-deep-researcher-24x7`  
**子系统：** Machine Verdict Diagnosis／Promotion  
**决策角色：** HUMAN_OWNER  
**决策日期：** 2026-08-16  
**确认原文：** “批准”  
**记录状态：** `APPROVED_EFFECTIVE`  

```text
OWNER_DECISION=APPROVE_V3_AND_DELIVERY_PLAN_FOR_GATE_EXECUTION
OWNER_DECISION_ID=ODR-MVD-20260816-001
DECISION_STATUS=APPROVED_EFFECTIVE
CURRENT_GATE=G0_EVIDENCE_CLOSURE
NEXT_AUTHORIZED_ACTION=EXECUTE_G0_EVIDENCE_CLOSURE_ONLY
IMPLEMENTATION_AUTHORIZED=NO
PILOT_AUTHORIZED=NO
UNATTENDED_24X7_AUTHORIZED=NO
PRODUCTION_READY=NO
```

---

## 1. 被批准基线

| 对象 | 决定 | Owner 审阅内容 SHA-256 |
|---|---|---|
| `ADR24X7-MVD-FINAL-V3.0` | APPROVED，成为 MVD 唯一 L2 技术设计输入 | `0bce14e4bcbfc1e46d7a086104f5a63899cd75209abe8a85b9019ea4ec59c008` |
| `ADR24X7-MVD-DELIVERY-PLAN-V1.1` | APPROVED_FOR_GATE_EXECUTION | `71bc9d278b196148b63b899552ac211a1118aec62e7c653009fb479bdf864b5f` |
| `ADR24X7-SDD-GOVERNANCE-V0.1` | APPROVED_FOR_MVD_SCOPE | manifest SHA-256 `475ae8c6dad8b5fd1b6db70a86ec12ce5461e335515f95e389e64a50830f1273` |

批准后的状态盖章文件 SHA-256：

```text
V3_STATUS_STAMPED_SHA256=4505419d1859f37b3f95c36dfd5175d32b16f871eb066eb7271a4db8498da37a
DELIVERY_PLAN_STATUS_STAMPED_SHA256=06ba7842592ce68f2f297a0a4d753ca1793ad3fb0efb2131a96f7f38d5fddbb8
```

V1、V2、V2.1、V2.2 的实现伪代码全部为 `SUPERSEDED_FOR_IMPLEMENTATION`，只允许用于历史追踪、replay、shadow diff 和 legacy adapter 迁移。

---

## 2. OB-1—OB-3 正式决定

### 2.1 OB-1｜V3.0

```text
OB-1=APPROVED
DOCUMENT_ID=ADR24X7-MVD-FINAL-V3.0
FIRST_IMPLEMENTATION_PROFILE=supervised_holdout
IMPLEMENTED_PROFILE=NONE
```

`supervised_holdout` 被批准为首个允许设计和实现的 profile 范围，但尚未实现、测试或获准运行。

### 2.2 OB-2｜Cycle 1 provisional

```text
OB-2=DEFERRED
CYCLE1_PROVISIONAL_AUTHORIZATION_STATUS=DRAFT
CYCLE1_PROVISIONAL_AUTHORIZATION_EFFECTIVE=NO
CYCLE1_EXECUTION_FACT=FAILED/HARD_TIMEOUT
CYCLE1_PARTIAL_METRIC_USAGE=DIAGNOSTIC_AND_REPLAY_ONLY
CHAMPION_MUTATION=NO
```

C1 不建立 provisional baseline。V3.0 replay 的规范结果保持 `BASELINE_REQUIRED + NO_CHANGE`。

### 2.3 OB-3｜fallback bar

```text
OB-3=NOT_APPROVED
FALLBACK_BAR_ENABLED=NO
FALLBACK_BAR_VALUE=NULL
INSUFFICIENT_EVIDENCE_ACTION=HUMAN_REVIEW
```

历史 `bar=0.05` 只允许作为 C1—C4 replay fixture。任何未来 fallback 申请必须针对结果尚未被查看的新 Study，提交 exact metric/unit/direction/cohort scope、数值、校准、有效期和 QA 证据后另行批准。

---

## 3. SDD 治理批准范围

`ADR24X7-SDD-GOVERNANCE-V0.1` 在 MVD 子系统范围内生效，包含：

- 项目开发总契约；
- 约束与护栏；
- 角色、权限和职责分离；
- Gate 0—6、实验状态机和独立 QA；
- Study/Experiment/Artifact 模板。

批准不自动将模板中的示例值变为正式 Study 事实。预算、hardware cohort、metric unit、dataset/evaluator hash、seeds、min practical delta、hard constraints、protected paths 和 principal 仍须在 G1 精确冻结。

---

## 4. 授权边界

本决定当前只授权：

1. 执行 `WP-00 / G0 Evidence Closure`；
2. 固定 repository、branch、base commit、git status；
3. 固定 dependency lock 和基线测试报告；
4. 完成源码、runner、evaluation、VCS mutation map；
5. 冻结 C1—C7 immutable replay fixture 与 cut-off；
6. 提交 QA-G0；
7. 在 G0 后按 Gate 顺序准备 Study、HLD、ADR、schema、任务与测试计划。

本决定没有授权：

```text
IMPLEMENTATION_AUTHORIZED=NO
MAIN_WRITE_PATH_CHANGE_AUTHORIZED=NO
SOURCE_MERGE_AUTHORIZED=NO
SINGLE_WRITER_CUTOVER_AUTHORIZED=NO
AUTO_KEEP_AUTHORIZED=NO
PILOT_AUTHORIZED=NO
UNATTENDED_24X7_AUTHORIZED=NO
PRODUCTION_READY=NO
```

G3 `BUILD_READY` PASS 才能授权编码；G4 只形成 pilot candidate；G5 需 HUMAN_OWNER 另行批准真实受控试点；G6 需 HUMAN_OWNER、QA-01、SEC-01 另行批准有限 24x7。

---

## 5. 当前状态与下一动作

```text
PLAN_COMPLETE=YES
DESIGN_BASELINE_APPROVED=YES
SDD_GOVERNANCE_APPROVED_FOR_MVD_SCOPE=YES
CURRENT_GATE=G0_EVIDENCE_CLOSURE
G0_STATUS=PARTIAL_EVIDENCE_AVAILABLE
NEXT_AUTHORIZED_ACTION=EXECUTE_WP00_G0
QA_G0=PENDING
IMPLEMENTATION_AUTHORIZED=NO
FROZEN=NO
```

ARCH-01/Delivery Tech Lead 应以 `ADR24X7-MVD-DELIVERY-PLAN-V1.1` 第 22 节执行指令启动 WP-00。任何角色不得把本 Owner 批准解释为 G0、G1、G2 或 G3 已通过。

---

## 6. 变更与撤销

- 本记录是 L0 Owner Decision，不得由 Agent、代码、policy 或后续文档静默修改；
- 需要改变 C1 provisional、fallback bar、首期 profile、test 隔离、Gate 授权或 Study 核心策略时，必须生成新的 Owner Decision/Change Request；
- 新记录必须引用并 supersede 本 Decision ID，不得覆盖本文件；
- 任何安全、test 泄漏、writer 分叉或不可恢复状态可触发 Owner 撤销授权，但撤销同样必须形成 append-only 决策记录。
