# 基线噪声研究 — STUDY-001

> 目的：校准 `minimum_effect_size` 并填充 `baseline_noise_evidence`。
> 执行日期：2026-08-15
> 基线脚本：`examples/mnist_gpu/train.py`（受控基线，`--seed` + validation holdout 5000，split seed=20260815）
> 硬件 cohort：`COHORT-RTX3060L-6G`（RTX 3060 Laptop 6GB, CUDA 12.4, torch 2.5.0+cu124）
> 结果：`minimum_effect_size` 0.5pp **验证通过**（> 2×pooled_std 0.36pp）

## 原始数据（3 seeds，同基线，3 epochs, batch 64）

| seed | validation_accuracy | validation_loss | test_accuracy | active_train_seconds |
|------|--------------------|-----------------|---------------|----------------------|
| 17   | 0.9878             | 0.0405          | 0.9889        | 14.35                |
| 29   | 0.9884             | 0.0406          | 0.9877        | 14.27                |
| 43   | 0.9912             | 0.0315          | 0.9875        | 14.47                |

原始输出文件：`noise/seed_17.txt`、`noise/seed_29.txt`、`noise/seed_43.txt`

## 统计

### validation_accuracy（逐轮选优指标）
- mean = **0.9891**
- std = **0.0018** ≈ **0.18 pp**
- 2 × pooled std = **0.36 pp**

### test_accuracy（独立验收指标）
- mean = **0.9880**
- std = **0.0008** ≈ **0.08 pp**

### active_train_seconds
- mean = **14.36 s**，min 14.27 / max 14.47
- 远低于 300 s 预算（约 4.8%），预算余量充足

## 校准结论

1. **minimum_effect_size = 0.5 pp**（合同预设）> 2×pooled_std（0.36 pp），**满足**置信规则，余量 0.14 pp。
2. 置信规则 `difference_must_exceed_2x_pooled_std` 保留。
3. 注意：validation 噪声（0.18pp）> test 噪声（0.08pp），符合预期（validation 从 60000 中分出 5000，样本量更小）。选优基于 validation 指标是正确且更保守的选择。
4. 训练时长稳定（14.3-14.5s），单候选预算（300s）可容纳 ~20 个 epoch，搜索空间执行可行。

## QA 复核提示

- 复核人可重跑：`cd examples/mnist_gpu && .venv/bin/python train.py --epochs 3 --batch_size 64 --seed {17,29,43}` 复现以上数值（容差：因 GPU/驱动确定性，±0.001 以内为可接受）。
- 数据指纹 / 模型架构未在噪声研究中改动。
