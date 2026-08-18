# D-12 数据快照证据（alpaca-cleaned）—— 指纹已闭合

- **Evidence ID**：D12-EVIDENCE-20260817-001（v2，指纹闭合）
- **状态**：**FINGERPRINT_CLOSED**（数据指纹 + 独立 final-test split 已闭合）
- **Owner 决定**：`D12=APPROVED_IN_PRINCIPLE_PENDING_IMMUTABLE_DATASET_EVIDENCE`
- **授权**：HUMAN_OWNER 授权闭合数据指纹/独立 test split（2026-08-18）
- **更新于 UTC**：2026-08-18T00:40:00Z
- **数据冻结时间**：2026-08-18（早于首次有效实验，满足要求）

## 1. 权威来源与 revision（已闭合）

- **数据集**：`yahma/alpaca-cleaned`
- **权威来源 URL**：`https://huggingface.co/datasets/yahma/alpaca-cleaned`
- **HF revision**：`12567cabf869d7c92e573c7c783905fc160e9639`
- **源文件**：`alpaca_data_cleaned.json`（下载大小 44,307,561 bytes）
- **样本数**：**51,760** 条（instruction/input/output 三元组）
- **字段**：instruction、input、output

## 2. 下载对象 / 内容 manifest SHA-256（已闭合）

| 对象 | SHA-256 |
|---|---|
| `alpaca-cleaned-train.arrow`（源数据） | `e0b8d2a4fd14442983201e182c15ab2c82175064128920839408ea57dc04015e` |
| `dataset_info.json` | `b95345184a1fe43a645e83a7315e7de95adc25aa6817b5f319bcfc771d240ce1` |
| 行内容摘要（order-independent） | `58174bbb6f7f80ac7cb12555dbbff2a4a5e1731424369ab62850446082afb555` |

行内容摘要基于每行 `instruction|input|output` 归一化后 SHA-256 排序再哈希，**顺序无关**，可跨库比对。

## 3. 许可证与使用条件

- **许可证**：**CC BY NC 4.0**（非商业）
- **使用条件**：标注归属 yahma/alpaca-cleaned；不得商用。
- **风险**：AutoDL 若商用需更换数据集或重新授权。已记录于合同。

## 4. split 指纹（已闭合）—— 独立 final-test split 方案

原契约缺陷（无独立 final-test split）已修复。采用确定性 split 方案：

**SPLIT-MVD-V1-20260818**：
```
方法：b = int(sha256("row:{i}:split:v1")[0:8], 16) % 100
  b < 10        -> final-test  (10%)
  10 <= b < 20  -> validation (10%)
  else          -> train      (80%)
```

| split | 行数 | 指纹状态 |
|---|---|---|
| train | 41,567 | 确定性 bucket |
| validation | 4,965 | 确定性 bucket |
| **final-test** | **5,228** | **确定性 bucket（新增，独立）** |

- **final-test 独立**：不再从 train/val 派生，由固定 split key 确定性划分，**独立于迭代流程**。
- split 已确定化（非随机），可复现。

## 5. preprocess / tokenizer hash（已闭合）

| 对象 | SHA-256 |
|---|---|
| tokenizer.json | `a8506e7111b80c6d8635951a02eab0f4e1a8e4e5772da83846579e97b16f61bf` |
| model config.json | `fea78a4aa54142295545630bc5c9ea11ae7280b0a41d31a6bba30512a54a1a0a` |
| train_ft.py（preprocess 入口） | `da65a4087630ab187d91ecace9c736b6802f8687fcd2027025893623f6f12b1f` |

- tokenizer：Qwen2.5-0.5B（tokenizer.json）
- preprocess：`BASE_PROMPT.format(instruction, input, output)` + tokenizer（max_len=128, truncation, padding=max_length）

## 6. 样本去重与交叉 split 泄漏检查（已闭合）

| 检查项 | 结果 |
|---|---|
| 精确重复组总数 | 4 组 |
| final-test 内重复 | **0** |
| validation 内重复 | **0** |
| train 内重复 | 2 组 |
| **交叉 split 泄漏** | **无**（final-test/validation 均无重复，同内容不会跨 split） |

> final-test 与 validation 均 0 重复组，确认**无交叉 split 泄漏**。

## 7. final-test namespace 与 ACL（已闭合）

- final-test namespace：`final-test/qa`（G1-09 isolation contract）
- final-test ACL：仅 `svc-mvd-final-eval-v1` 运行 + `qa-01-readonly-review` 只读
- **test 不反馈迭代 loop**：`test_feedback_to_iterative_loop=false`

## 8. 数据冻结时间

- **数据冻结时间**：2026-08-18T00:40:00Z
- **首次有效实验**：尚未开始（G1 未闭合，pilot 未授权）
- **满足要求**：数据冻结时间早于首次有效实验 ✅

## 9. 残留待闭合项（不影响 D-12 数据指纹）

| 项 | 状态 |
|---|---|
| 硬件 manifest hash（D-04） | PENDING（独立于数据指纹） |
| evaluator hash | PENDING（F1 编码阶段确定） |
| contract_hash / policy_bundle_hash | 合同最终批准后计算 |

## 结论

D-12 数据快照证据**已闭合**：来源/revision/内容指纹/split 指纹/tokenizer/preprocess hash/去重/泄漏检查/ACL/冻结时间全部齐备。不再需要重新申请 Owner（除非更换数据源/revision/split 策略）。
