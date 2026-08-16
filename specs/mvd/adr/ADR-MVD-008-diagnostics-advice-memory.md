# ADR-MVD-008 — Diagnostics / Advice / Memory 版本与权限

- **ADR ID**：ADR-MVD-008
- **主题**：诊断/建议/记忆的版本化与权限
- **Owner**：ARCH-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：study-contract/v1
- **关联 Gate**：G1 → G4/F2
- **日期**：2026-08-17

## 决策

- **Diagnostics**（机器判定归因诊断）：结构化、版本化输出，绑定 metric identity 与 ledger。
- **Advice**（给迭代 agent 的建议）：来自机器判定，可追溯、可关闭（不静默接受）。
- **Memory**（共享记忆）：版本化、只追加；跨阶段一致（loop-shared-memory）。
- **权限**：诊断/建议可被 iterative principal 读取；不赋予对 contract/ledger 的写权限。
- 机器判定 `llm_narrative_can_override: false` —— LLM 叙述不得覆盖机器事实。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 无版本化的自由文本诊断 | 不可追溯、不可重放 |
| LLM 自述可覆盖机器事实 | 违反 machine facts over narrative |
| 诊断/建议无权限控制 | 可能被迭代 agent 误写契约 |

## 风险

- 诊断若与 metric identity 解绑，会导致归因错位。
- advice 若被当成硬约束，可能产生误导；需标记为 advisory 非 binding。

## 回滚

- 若某版本诊断有误，追加更正记录（不覆盖），保持可追溯。

## Owner 与生效

- Owner：ARCH-01
- 生效条件：G1 批准后生效。
