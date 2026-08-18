# ADR-MVD-007 — OwnerDecisionRecord、Provisional 与 HUMAN_REVIEW

- **ADR ID**：ADR-MVD-007
- **主题**：Owner 决策记录与 provisional baseline
- **Owner**：HUMAN_OWNER + ARCH-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：study-contract/v1
- **关联 Gate**：G1 → G5
- **日期**：2026-08-17

## 决策

- **OwnerDecisionRecord（ODR）**：任何业务/风险值决策必须落为带 ID 的 Owner 决策记录（如 `ODR-MVD-20260816-001`）。
- **Provisional baseline**：允许 provisional，但 `provisional_requires_exact_owner_record: true`；auto-keep 禁止（`provisional_auto_keep_allowed: false`）。
- **C1 provisional**：保持 DRAFT/NOT_EFFECTIVE（OB-2 DEFERRED_DRAFT_NOT_EFFECTIVE）。
- **HUMAN_REVIEW**：置信不足、delta 不足、high-complexity-small-gain、意外约束违反 → 一律 HUMAN_REVIEW，不做自动判定。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 无 ODR 直接决策 | 无法追溯 Owner 授权 |
| provisional 自动生效 | 违反 OB-2（deferred draft not effective） |
| 自动 KEEP（无 HR） | 违反 fail-safe，机器判定不可独立签署 |

## 风险

- 若 ODR 缺失导致决策不可追溯，G1 门禁（40 位 SHA 记录）不通过。
- provisional 若被误当正式 baseline，违反 C8 控制。

## 回滚

- 若某决策需撤销，追加 ODR 变更记录（不覆盖原记录），保持 append-only。

## Owner 与生效

- Owner：HUMAN_OWNER + ARCH-01
- 生效条件：G1 批准后，ODR 记录为权威决策来源。
