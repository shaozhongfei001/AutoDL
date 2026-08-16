# ADR-MVD-005 — Hard Constraints Complete Set 与 Fail-Closed

- **ADR ID**：ADR-MVD-005
- **主题**：硬约束完整集与 fail-closed
- **Owner**：ARCH-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：constraint-contract/v1
- **关联 Gate**：G1 → G4
- **日期**：2026-08-17

## 决策

hard constraints 必须是**完整清单或显式空集合**，禁止缺省（`completeness_required: true`）。

- 字段必须存在且为 list 类型，禁止 PENDING/TBD 遗留。
- 完整性机器可验证。
- 候选硬约束（待 Owner 决策）：
  - resource_quota_1xRTX3060L
  - dependency_change_forbidden
  - data_readonly
  - governance_contracts_readonly
  - tests_oracle_readonly
  - destructive_git_forbidden
  - no_test_feedback_to_iterative_agent
- **fail-closed**：违反任一 hard constraint，阻止该 candidate 晋级，转 HUMAN_REVIEW。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 硬约束缺省（隐含默认） | 不透明，无法机器验证完整性 |
| 仅软约束无阻断 | 无法保证安全/隔离底线 |
| 允许部分约束（非完整） | 违反 completeness 要求 |

## 风险

- 若硬约束集合遗漏关键项（如 data 只读），可能造成破坏性操作。需 SEC-01 复核完整集。
- 空集合若被误用（应有约束却为空），需 Owner 明确决策为空。

## 回滚

- 硬约束集变更走 Change Request，Owner 批准后更新合同，不静默修改。

## Owner 与生效

- Owner：ARCH-01
- 生效条件：G1 约束合同批准后生效。
