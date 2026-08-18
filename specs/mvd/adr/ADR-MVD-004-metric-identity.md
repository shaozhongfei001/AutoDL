# ADR-MVD-004 — Metric Identity、Direction、Checkpoint、Paired Statistics

- **ADR ID**：ADR-MVD-004
- **主题**：指标同一性与统计
- **Owner**：ARCH-01 + DEV-EVAL-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：metric-identity/v1 + statistical-policy/v1
- **关联 Gate**：G1 → G4/F2
- **日期**：2026-08-17

## 决策

冻结 **metric identity**：dataset/split/preprocess/evaluator/unit/direction/aggregation/checkpoint-selection/hardware cohort 全部固化。

- primary metric：`validation_loss`，direction=MINIMIZE。
- checkpoint-selection：`BEST_VALIDATION_LOSS`（从 validation 最优 checkpoint 取值）。
- 统计：paired mean（PAIRED_MEAN_V1）、uncertainty=PAIRED_SE_V1、confidence=差值超过 2x pooled SE。
- min_practical_delta：正且有限（POSITIVE_FINITE），由 DEV-EVAL 校准后 Owner 决策。
- C8/C9 历史数据（0.7723/0.9188）仅诊断/replay，不得建立 metric baseline 或反推 delta。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 用 test 指标选优 | 违反隔离，test 自适应过拟合 |
| 单一指标无 direction 记录 | 无法机器验证比较方向 |
| 无 checkpoint 策略（取最后 epoch） | 与 BEST_VALIDATION_LOSS 行为不一致，不可复现 |

## 风险

- paired 统计依赖同 seed 配对；seed 缺失会导致配不齐，须进入 HUMAN_REVIEW。
- checkpoint_selection 若实现与策略不符，需 F2 golden test 校验。

## 回滚

- 若 paired SE 计算有缺陷，回退为独立样本统计（记录例外），QA 评审。

## Owner 与生效

- Owner：ARCH-01 + DEV-EVAL-01
- 生效条件：G1 指标/统计合同批准后生效。
