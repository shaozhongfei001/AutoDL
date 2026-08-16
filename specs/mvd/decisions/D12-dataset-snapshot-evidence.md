# D-12 数据快照证据（alpaca-cleaned）

- **Evidence ID**：D12-EVIDENCE-20260817-001
- **状态**：APPROVED_IN_PRINCIPLE_PENDING_IMMUTABLE_DATASET_EVIDENCE
- **Owner 决定**：`D12=APPROVED_IN_PRINCIPLE_PENDING_IMMUTABLE_DATASET_EVIDENCE`
- **更新于 UTC**：2026-08-17T05:10:00Z
- **说明**：Owner 原则批准 alpaca-cleaned，本证据补齐来源/许可证/指纹。数据文件级 SHA-256 因本地遍历受限，标注为"待闭合"项。

## 1. 权威来源与 revision

- **数据集**：`yahma/alpaca-cleaned`
- **权威来源 URL**：`https://huggingface.co/datasets/yahma/alpaca-cleaned`
- **说明**：斯坦福原始 alpaca 数据集的清理版本，约 **52K** 条指令样本（instruction/input/output 三元组）。
- **revision**：`PENDING`（需记录加载时的 HF revision/commit sha；通过 HF mirror 加载，revision 未显式锁定）

## 2. 下载对象 / 内容 manifest SHA-256

- 本地缓存：`~/.cache/huggingface/datasets/yahma___alpaca-cleaned/`
- 数据文件级 SHA-256：**待闭合**（本地遍历受限，需 Owner 授权计算或提供官方 manifest）
- requirements/datasets 依赖：`datasets 2.19.1`（G0 012 记录）

## 3. 许可证与使用条件

- **许可证**：**CC BY NC 4.0（Creative Commons Attribution-NonCommercial 4.0）**
- **含义**：非商业使用许可。AutoDL 研究用途需符合 NC 限制。
- **使用条件**：需标注归属（yahma/alpaca-cleaned）；不得商用。
- **风险提示**：若 AutoDL 后续用于商业场景，需更换为可商用许可的数据集，或重新获得授权。

## 4. split 指纹

当前 train_ft.py 的 split 派生方式（需记录，可能存在契约缺陷）：

| split | 来源 | 指纹状态 |
|---|---|---|
| train | `train_test_split(test_size=0.1, seed=seed)` 派生 | **待闭合**（依赖运行时派生） |
| validation | `train_test_split(test_size=0.1, seed=seed)` 派生 | **待闭合** |
| **final-test** | **当前无独立 final-test split** | **缺陷：需新增独立 test split** |

> **契约缺陷**：当前只有 train/val 派生 split，无独立 final-test split。这违反 isolation-contract（G1-09）的 test 独立平面要求。需在 G1 闭合包中定义独立 final-test split 策略。

## 5. preprocess / tokenizer hash

- tokenizer：Qwen2.5-0.5B tokenizer（`model_ft/tokenizer.json`, 6.71 MB）
- tokenizer hash：**待闭合**
- preprocess：`BASE_PROMPT.format(...)` 模板 + tokenizer（max_len=128, truncation, padding=max_length）
- preprocess hash：**待闭合**

## 6. 样本去重与交叉 split 泄漏检查

- 当前通过 `train_test_split(seed=seed)` 派生 train/val，同 seed 下 train 与 val **互斥**（HF 实现）。
- **交叉 split 泄漏检查**：**待执行**（需确认无样本同时出现在 train 与 val；test 独立 split 尚未建立）。
- 去重：**待执行**（需确认 alpaca-cleaned 内无重复样本干扰配对统计）。

## 7. final-test namespace 与 ACL

- final-test namespace：`final-test/qa`（G1-09 isolation contract）
- final-test ACL：仅 `svc-mvd-final-eval-v1` 运行 + `qa-01-readonly-review` 只读
- **当前无 final-test 数据**：需建立独立 final-test split 并放入 final-test namespace。

## 8. 数据冻结时间

- 数据冻结时间必须**早于首次有效实验**。
- 当前试点（C1-C9）在数据 revision 未锁定时进行，**不满足"数据冻结早于实验"**。
- 正式 STUDY-MVD-SH-QWEN-001 首次实验前，必须完成数据冻结 + 指纹 + revision 锁定。

## 9. 待闭合项汇总

| 项 | 状态 |
|---|---|
| HF revision 锁定 | PENDING |
| 数据文件 SHA-256 | PENDING（需授权计算） |
| train/val 指纹 | PENDING（需冻结 split 策略） |
| **独立 final-test split** | **PENDING（契约缺陷）** |
| tokenizer/preprocess hash | PENDING |
| 去重/泄漏检查 | PENDING |
| 数据冻结时间证明 | PENDING |

> Owner 决定：若上述证据成立，不需要再次申请 Owner；若要更换数据源/revision/split 策略，必须重新决策。
> 本文件标注：D-12 为 APPROVED_IN_PRINCIPLE，数据证据在首次有效实验前必须全部闭合。
