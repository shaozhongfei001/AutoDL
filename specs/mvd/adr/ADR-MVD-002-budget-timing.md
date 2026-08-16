# ADR-MVD-002 — Active Training Time、Hard Timeout、Timing Events

- **ADR ID**：ADR-MVD-002
- **主题**：预算与计时语义
- **Owner**：ARCH-01 + DEV-RUN-01
- **状态**：DRAFT_FOR_G1_REVIEW
- **生效版本**：budget-contract/v1
- **关联 Gate**：G1 → G4/F2
- **日期**：2026-08-17

## 决策

分离 **active-train budget**（仅计纯训练时间）与 **hard wall-clock timeout**（绝对上限）。

- active-train 使用 `MONOTONIC_ACTIVE_TRAIN_V1`：monotonic 计时，仅统计 active_train_seconds。
- 不计入 active budget：queue、setup、compile、warmup（前 N epoch 排除策略）、evaluation、artifact finalize。
- hard timeout 独立生效，超出即强制终止训练进程（fencing）。
- 必需时序事件：queue/setup/compile/warmup/active_train/evaluation/artifact_finalize/total_wall。
- 历史 300/420 仅作候选证据，最终值由 G0/G1 环境测量提出、Owner 决策。

## 替代方案

| 替代 | 否决理由 |
|---|---|
| 统一 wall-clock 单预算 | 无法区分训练 vs 系统开销，导致不可复现 |
| 把 queue/compile 计入预算 | 不公平，不同负载下失真 |
| 直接沿用 300/420 | Owner 决策约束：历史值不能直接成为生产事实 |

## 风险

- active_train_seconds 依赖训练脚本正确上报时序；若脚本不报，需 monitor 侧估算（可能导致偏差）。
- hard timeout 过短可能误杀正常训练，过长可能资源浪费。

## 回滚

- 若 active-train 时序不可靠，回退为 wall-clock 预算（记录为例外，QA 评审）。
- hard timeout 值可经 Owner 决策调整，不视为 schema 变更。

## Owner 与生效

- Owner：ARCH-01 + DEV-RUN-01
- 生效条件：G1 预算合同批准后生效。
