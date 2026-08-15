# 端到端验收报告 — PILOT-MNIST-GPU

> 无人值守真实 GPU 多轮 CNN 搜索 + 机器判定晋级
> 日期：2026-08-15
> 授权：HUMAN_OWNER（`OWNER-PILOT-20260815-01`，pilot_authorized=true）
> 状态：**机制验证通过 / 暴露 3 项改进点（见 §5）**

## 1. 试运行概要

- 目标：mnist_gpu 固定预算（300s active_train / 420s hard）下自动搜索 CNN 改进，由机器判定晋级。
- 环境：RTX 3060 Laptop 6GB，CUDA 12.4，torch 2.5.0+cu124；DeepSeek API。
- 配置：`max_cycles=-1`（无限多轮）、`experiment.loop_engineering.enabled`、`dedup.enabled`、`noise_std=0.0018`、`evaluation.min_effect_size=0.005`。
- 运行：>35 cycles，**18 次机器判定**，44 条 ledger 事件，全部无人值守（无人工介入）。

## 2. 机器判定结果

| Cycle | 判定 | 说明 |
|-------|------|------|
| 2 | INCOMPARABLE | 首个真实训练 → 建立基线（validation≈0.987） |
| 5,6,8,10,12,14,15,17,18,19,20,25,30 | DISCARD (×13) | 候选相对基线均未超噪声阈值 |
| 9,11,13,24 | INCOMPARABLE (×4) | metrics 缺失/不可比较 |

**判定分布：5 INCOMPARABLE + 13 DISCARD + 0 KEEP**

## 3. 核心机制验证（全部达成）

| 机制 | 验证点 | 结果 |
|------|--------|------|
| **M1 自主循环** | >35 cycles 无人值守自动推进 | ✅ |
| **M2 机器判定权威** | 18 次判定全由 `decide_verdict` 基于指标，无 LLM 自述 | ✅ |
| **M3 隔离/晋级** | `gate_verdict_by_contract_status` 门禁（CRASH/TIMEOUT 不 KEEP） | ✅ |
| **M4 制品归档** | 判定前归档 + verdict 写 ledger（44 条可审计） | ✅ |
| **M5 收敛** | 假设去重 + no_progress 升级（部分，见 §5） | ⚠️ 部分 |
| **M6 自愈** | 错误冷却 + 持续运行不崩 | ✅ |
| **D0 写入保护** | agent 反复 run_shell 被拒，引导 launch_experiment | ✅ |
| **monitor 捕获** | 每次训练 PID + metrics 提取 + contract_status | ✅ |
| **P3 统计严谨性** | validation 0.9822~0.9904 相对基线 0.987 的改进均 <0.5pp 被 DISCARD | ✅ |

## 4. 关键洞察：0 KEEP 的正确性

本次所有候选（validation 0.9822~0.9904）相对基线 0.987 的改进 delta ≤0.34pp，
**均小于 min_effect_size 0.5pp 及噪声校准 bar（max(0.005, 2×0.0018)=0.005）**，故全被 DISCARD。

这是**机器判定严格性的正确体现**：MNIST 精度已饱和（98-99%），任何候选都无法产生超噪声的真实改进，
因此机器正确地拒绝了所有"假改进"，**未误晋级噪声级提升**。这正是"只晋级真实超噪声改进"的设计意图。

## 5. 暴露的 3 项改进点（下一重构方向输入）

### I1. 无主动终止条件（P0）★
`max_cycles=-1` 下循环**不自然收敛**：无 `dedup blocked`/`no_progress_escalation terminate` 触发，
agent 持续空转（35+ cycles 仍在跑，多数为 D0 拦截 run_shell）。
- 修复方向：无人值守需**主动终止条件**——如"连续 N 轮无 KEEP"或"budget 耗尽"自动收敛，或
  `no_progress_escalation` 到 terminate 时真正停止（而非仅 advisory）。

### I2. code agent 工具约束适应差（P1）
agent 反复用 `run_shell` 尝试被 D0 禁止的 `;`/`>`/`&&`，浪费大量 API 调用，未及时改用 launch_experiment。
- 修复方向：code agent system prompt / tool 描述更强制性地引导"训练必须用 launch_experiment"。

### I3. 空指标判定偏多（P1）
4 次 INCOMPARABLE 中部分因 metrics 为空（monitor 未从日志提取到指标）。
- 修复方向：训练脚本指标输出格式契约化校验，或 monitor 对空指标给出更明确诊断。

## 6. 验收结论

- **机制层面：PASS**。机器判定闭环、monitor 捕获、D0 保护、统计严谨性、多轮自主推进全部在真实 GPU 运行中验证。
- **任务层面：条件 PASS**。因 MNIST 饱和精度下无真实超噪声改进（0 KEEP 属预期），且暴露 I1 无终止条件问题。
- **无人值守能力：已验证**（>35 cycles 无人工介入），但需修复 I1 才可 24x7 长期无人值守。

## 7. 建议下一步（重构方向）

1. **修复 I1（无主动终止条件）**：为无人值守添加收敛/终止策略（连续 N 轮无改进自动停止）。
2. **修复 I2（agent 工具引导）**：强化 code agent 对 launch_experiment 的使用。
3. **修复 I3（空指标诊断）**：指标提取契约化。
4. 可选：换一个更可能有超噪声改进的任务（非饱和 MNIST）验证 KEEP 晋级路径。
