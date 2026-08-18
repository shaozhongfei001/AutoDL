# ADR-MVD-009 — G0—G6 授权语义与 F0—F9 Crosswalk

- **ADR ID**：ADR-MVD-009
- **主题**：Gate 授权语义与阶段映射
- **Owner**：MAIN-00 + ARCH-01 + QA-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：study-contract/v1 + PROJECT_STATUS.yaml
- **关联 Gate**：全 Gate（G0—G6）
- **日期**：2026-08-17

## 决策

定义 G0—G6 授权语义，并与开发阶段 F0—F9 交叉映射：

| Gate | 授权语义 | 对应 F 阶段 |
|---|---|---|
| G0 | Evidence Closure | F0（证据闭合） |
| G1 | Contract Baseline 冻结 | F0（合同冻结） |
| G2 | HLD Approval | F0（HLD 设计） |
| G3 | Build Readiness | F0（任务/测试/权限）→ 开始 F1 |
| G4 | Strict Contracts / 编码 | F1—F2 |
| G5 | Pilot / 真实 loop | F3+（pilot） |
| G6 | 24x7 无人值守 | F9（production） |

- 每个 Gate 通过需对应退出条件 + QA 独立签署。
- 授权语义明确 `unattended_24x7_authorized`、`pilot_authorized`、`implementation_authorized` 各自独立为 false 直到对应 Gate。
- `production_ready` 仅在 Gate 6 后可为 true。
- C8/C9 历史数据仅 `DIAGNOSTIC_AND_REPLAY_ONLY`，不构成 Gate 通过证据。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 无 Gate 直接进入 24x7 | 违反 Gate 6 准入 |
| Gate 间授权可隐式继承 | 需显式授权，防越权 |

## 风险

- 若授权语义不清，可能误在 G1 阶段编码（应 NO）。本 ADR 明确 `implementation_authorized=NO` 直至 G3/G4。
- crosswalk 若不同步，阶段/授权不一致。

## 回滚

- 若 Gate 状态误设，通过 PROJECT_STATUS.yaml + ODR 更正（保留变更记录）。

## Owner 与生效

- Owner：MAIN-00 + ARCH-01 + QA-01
- 生效条件：G1 批准后作为全 Gate 授权语义权威。
