# ADR-MVD-003 — Validation/Test 两平面隔离（namespace/principal/ACL）

- **ADR ID**：ADR-MVD-003
- **主题**：validation/test 两平面隔离
- **Owner**：ARCH-01 + SEC-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：isolation-contract/v1
- **关联 Gate**：G1 → G4
- **日期**：2026-08-17

## 决策

将 **validation（selection）** 与 **test（final acceptance）** 分为两个独立平面：

- **namespace 分离**：`selection/iterative` vs `final-test/qa`，不共享。
- **principal 分离**：`DEV-ITERATIVE`（逐轮）vs `QA-01`（最终验收）vs `DEV-VCS-01`（committer），互不兼任。
- **ACL 分离**：selection 对 iterative principal 读写；test 仅对 final_eval_principal + owner 只读。
- **feedback 禁止**：test 结果绝不反馈逐轮迭代 Agent（`test_feedback_to_iterative_loop: false`）。
- 隔离可由机器验证（namespace/principal/ACL 分离均可机器检查）。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 单平面共享 test | 无法防止 test 自适应过拟合 |
| 仅 namespace 分离（不分离 principal） | 同 principal 仍可绕过 ACL，隔离不完整 |
| 仅文档承诺无机器验证 | SDD 要求 machine facts，需可验证 |

## 风险

- 若 config/runner 误将 test 路径暴露给 iterative agent，隔离失效。需 F1/F2 用独立 fixture 验证。
- principal 身份若无法在工具层强制（如依赖自述），需用 VCS/artifact ACL 兜底。

## 回滚

- 若发现隔离绕过，立即 fail-closed：阻止该 candidate 晋级，转 HUMAN_REVIEW。

## Owner 与生效

- Owner：ARCH-01 + SEC-01
- 生效条件：G1 隔离合同批准后生效。
