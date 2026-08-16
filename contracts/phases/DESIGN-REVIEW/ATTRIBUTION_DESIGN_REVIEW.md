# 机器判定归因（Machine Verdict Attribution）通用性设计 —— 评审文档

> **文档类型**：设计评审稿（DESIGN REVIEW DRAFT）
> **作者**：CodeBuddy（AutoDL 开发 Agent）
> **日期**：2026-08-16
> **状态**：`READY_FOR_EXTERNAL_REVIEW`（请外部 AI 专家全面评审）
> **评审诉求**：通用性、覆盖全面性、可落地性、跨领域（LLM / 深度学习 / 统计ML / RL）正确性

---

## 0. 评审请求（评审提示词，可直接复制给评审方）

> 你是 AutoDL（自主深度学习研究 Agent）项目的高级架构评审专家。请针对我以下这份 **「机器判定归因（Machine Verdict Attribution）」设计文档** 做全面、严格的评审。
>
> 评审重点：
> 1. **通用性**：归因分类（reason）与判定逻辑是否真正跨领域（LLM 微调 / 深度学习小模型 / 统计机器学习 / 强化学习）通用？是否有领域特定的隐性假设？
> 2. **覆盖全面性**：失败模式分类是否考虑周全？是否有遗漏的、真实训练中常见的失败模式？
> 3. **判定逻辑正确性**：用我文档第 4 节给出的真实试点数据（Cycle 1-4）验证逻辑，判定顺序、阈值、边界条件是否正确？`train_metric` 缺失/异常（如等于 0）时的容错是否合理？
> 4. **可落地性**：`OutcomeFacts` 数据从框架哪里来？是否有框架拿不到的字段？落地改动点是否合理？
> 5. **架构**：纯规则归因 vs LLM 归因的取舍是否合理？`reason→advice` 规则表 + 领域定制模板的设计是否可扩展？
> 6. **风险与盲点**：归一化（direction 抽象）、过拟合阈值标定、评估异常检测（EVAL_ANOMALY）、OOM 检测等是否有隐患？
>
> 请给出：总体结论、按优先级的改进建议清单、以及你认为最关键的 1-3 个待决策点。

---

## 1. 背景（引出话题的完整上下文）

### 1.1 项目背景
**AutoDL** 是一个自主深度学习研究 Agent 框架（重构自 autoresearcher）。它让一个 **leader（规划）+ code agent（执行）+ writing agent（总结）** 的多个无状态 LLM 智能体，在一个机器判定的闭环里自动做实验：leader 提出假设 → code agent 写训练脚本并跑训练 → **机器判定（M2）** 决定 KEEP / DISCARD → leader 基于结果提出下一轮假设。

核心原则（SDD 契约）：**机器事实优先于 LLM 自述**。即晋级判定必须基于结构化指标（validation_loss / accuracy 等），不能依赖智能体自述。

### 1.2 讨论起点
在一次真实的 **Qwen2.5-0.5B LLM 微调无人值守试点**中，观察到：
- **code agent 具备自主优化训练代码的能力**（真实案例：Cycle 2 时它主动把 lr 从 1e-4 降到 5e-5，并引入梯度累积 `micro_bs=2+acc_steps=4`，validation_loss 从 1.1466 降到 1.0128，被 KEEP）。
- 但机器判定只输出 `INCOMPARABLE / DISCARD / KEEP` 三个词，**没有解释"为什么被 DISCARD"**。这导致 code agent 在下一轮优化时，往往只能"盲试另一个超参"，不知道上一轮失败的确切原因（是过拟合？欠拟合？超时？还是单纯没超过 champion？）。

由此引出讨论：**如何让机器判定输出"可操作的归因"（reason + evidence + advice），从而指导无状态 code agent 更高效地优化？**

### 1.3 关键约束（影响设计）
- code agent **无状态**（每次派发全新 context），跨轮认知靠 framework 注入信号（recent_experiments / dead_ends / insights / metrics_feedback）补偿。
- 归因必须**由机器计算**（读日志、算指标趋势、看契约状态），**不允许 LLM 自述**（SDD "机器事实优先"）。
- 要训练的模型**不止 LLM**，还包括数理统计机器学习模型（LR/GBDT/SVM）、深度学习小模型（CNN/ResNet）、可能还有强化学习（DQN/PPO）。因此归因**必须跨领域通用**。

---

## 2. 设计目标与核心洞察

### 2.1 目标
1. 让机器判定在 verdict 之外，输出 **结构化归因**：`reason`（分类）+ `evidence`（机器证据）+ `advice`（可操作建议）+ `confidence`（置信度）。
2. 归因要**跨领域通用**（LLM / DL / ML / RL），不绑定具体指标名。
3. 归因要**可落地**：接入现有 `_machine_judge`，注入 leader REFLECT + code agent 下一轮 task。

### 2.2 核心洞察（支撑通用性）
**不同领域的"指标语义"不同**：
| 领域 | 典型模型 | 主指标 | 方向 | 典型失败模式 |
|------|---------|-------|------|-------------|
| LLM 微调 | Qwen2.5 | validation_loss | 越小越好 | 过拟合、OOM、超时 |
| 深度学习 | CNN/ResNet | accuracy / val_loss | 越大越好(acc) | 过拟合、不收敛、梯度爆炸 |
| 统计ML | LR/GBDT/SVM | AUC / F1 / logloss | 越大越好(F1) | 欠拟合、特征问题、类别不平衡 |
| 强化学习 | DQN/PPO | reward | 越大越好 | 不收敛、奖励稀疏 |

**但底层失败模式的本质是相通的** —— 都是"模型在训练集的表现 vs 在验证集的表现"之间的关系出了问题。因此：

> **通用归因应基于「train 与 val 的关系 + 契约状态」，而不是具体领域指标名。**

把指标抽象成两个可比较的量，并统一归一化：
- **train_gain**：训练集上相对初始的改善（衡量"模型是否在学"）
- **val_quality**：验证集上相对 champion 的改善（衡量"是否真进步"）
- **generalization_gap**：train 与 val 的差距（衡量"是否泛化"）

**方向（direction）由配置驱动**，归因逻辑本身不感知领域：
```yaml
evaluation:
  primary_metric:
    name: validation_loss
    direction: minimize        # 或 maximize（accuracy 时）
  train_metric: train_loss      # 学习行为监测（可选，缺失则 overfit 检测降级）
```

---

## 3. 归因数据结构（落地的 schema）

### 3.1 统一输入 DTO（OutcomeFacts）
从 `execute_result` + ledger 提取，**屏蔽领域差异**：
```python
@dataclass
class OutcomeFacts:            # 由框架从 execute_result 提取
    contract_status: str       # SUCCESS/CRASH/TIMEOUT/BUDGET_EXCEEDED/OOM
    early_stopped: bool
    primary_metric: float | None    # validation_loss / accuracy / auc ...
    primary_direction: str          # "minimize" / "maximize"（配置）
    train_metric: float | None      # 可空（容错：train_loss=0 或缺失）
    val_sequence: list[float]       # 各 epoch 的 primary metric 序列（早停/趋势）
    champion_metric: float | None   # 当前 champion
    noise_std: float                # 指标噪声（配置）
    effect_size: float              # 最小效应（配置，effective bar）
    elapsed_seconds: float
    budget_limit_seconds: float
    oom_signal: bool                # log 里检测到 OOM 关键字
```

### 3.2 输出（Attribution）
```python
@dataclass
class Attribution:
    reason: str                    # 归因类别（机器计算）
    confidence: float              # 0-1，证据强度
    evidence: dict                 # 机器可验证的支撑数值
    advice: str                    # reason→建议的规则映射（非 LLM）
    domain: str                    # 检测到的领域（llm/dl/ml/rl）——用于 advice 定制
```

---

## 4. 归因分类（reason）与判定逻辑

### 4.1 完整 reason 分类表（含契约层 + 学习行为层）

| reason | 触发条件（机器可验证） | code agent 应做的优化 |
|--------|----------------------|---------------------|
| `OOM` | 显存溢出信号（log 关键字） | 降 batch / 梯度累积 / 降 max_len |
| `CRASH` | contract_status = CRASH | 修复脚本错误 / 路径 |
| `BUDGET_TIMEOUT` | contract = TIMEOUT / BUDGET_EXCEEDED | 减 epochs / 减 max-examples / 提效率 |
| `NO_METRIC` | primary_metric 缺失 | 补 RESULT / epoch 指标行 |
| `EVAL_ANOMALY` | val 序列异常（突跳/无单调性），疑似评估 bug | 先检查评估代码，再动模型 |
| `OVERFIT` | train 明显好于 val（gap 超阈值） | 降 lr / 加正则 / 早停 / 更多数据 |
| `UNDERFIT` | train 和 val 都差、几乎不降 | 提 lr / 加 warmup / 加 epochs |
| `PLATEAU_EARLY_STOP` | 早停触发（平台期） | 已在收敛，微调或接受 |
| `REGRESSION` | 比 champion 差超过噪声 | 反向调整，回退方向 |
| `NO_IMPROVE` | 在噪声带内无实质进步 | 需更大改变以超过 champion |
| `IMPROVED` | 真进步，新 champion | 记录获胜超参/配方供复用 |

### 4.2 判定逻辑（纯规则，领域无关）

```
def attribute_outcome(f: OutcomeFacts) -> Attribution:
    # 契约层（最高优先，任何领域通用）
    if f.oom_signal:                       return reason="OOM"
    if f.contract_status == "CRASH":       return reason="CRASH"
    if f.contract_status in ("TIMEOUT","BUDGET_EXCEEDED"): return reason="BUDGET_TIMEOUT"

    # 指标层：需要 primary metric 存在
    if f.primary_metric is None:
        return reason="NO_METRIC"

    # 归一化：把指标转成"相对 champion 的改善量"（正=更好，direction 已归一）
    improve = delta_value(f.primary_metric, f.champion_metric, f.primary_direction)
    # delta_value: minimize 时 = champion - candidate；maximize 时 = candidate - champion

    # 学习行为层（基于 train/val，容错 train 缺失）
    if f.train_metric is not None and f.train_metric > 0:   # 容错 train=0/缺失
        gap = gap_value(f.train_metric, f.primary_metric, f.primary_direction)
        # gap>0 表示 train 明显好于 val（过拟合信号）
    else:
        gap = None   # 无法检测过拟合，退化为只看 val 是否进步

    # 判定（优先级从"是否真进步"出发）
    if f.early_stopped:
        reason = "PLATEAU_EARLY_STOP" if plateau(f.val_sequence) else reason_from_gap(gap)
    elif gap is not None and gap > f.generalization_threshold:
        reason = "OVERFIT"
    elif improve <= -f.noise_std:             # 比 champion 差超过噪声
        reason = "REGRESSION"
    elif abs(improve) <= f.effect_size:       # 在噪声带内无实质进步
        reason = "NO_IMPROVE"
    else:
        reason = "IMPROVED"
```

### 4.3 用真实试点数据验证（Qwen2.5-0.5B 微调）

**实测数据：**
| Cycle | validation_loss | 机器判定 | 备注 |
|-------|----------------|---------|------|
| 1 | 1.1466 | INCOMPARABLE | baseline，训练 2.5h 超时被硬终止，但获得指标 |
| 2 | 1.0128 | **KEEP** | lr=5e-5+梯度累积（code agent 自主优化），新 champion |
| 3 | 1.1557 | DISCARD | 退化 |
| 4 | 1.0105 | DISCARD | 略优于 C1 但未超 C2 champion |

**用判定逻辑验证（假设 noise_std=0.02, effect_size=0.05, champion 取前一轮）：**
- **Cycle 2**：primary=1.0128, champion=C1 的 1.1466, direction=minimize → improve = 1.1466 - 1.0128 = **0.1338 > effect_size** → `IMPROVED` ✅（与 KEEP 一致）
- **Cycle 3**：primary=1.1557, champion=1.0128 → improve = 1.0128 - 1.1557 = **-0.1429 < -noise** → `REGRESSION` ✅（与 DISCARD 一致）
- **Cycle 4**：primary=1.0105, champion=1.0128 → improve = 1.0128 - 1.0105 = **0.0023**，abs ≤ effect_size → `NO_IMPROVE` ✅（与 DISCARD 一致）

**结论**：判定逻辑无需改动即正确分类了全部 3 个非首轮判定。且 `train_loss=0.0`（实测是 0，一个数据/契约 bug）被容错处理（gap=None），退化为只看 val 进步——符合实际。

> **重要发现（支撑容错设计）**：本次试点 train_loss 实测为 0.0（code agent 脚本未正确记录）。这暴露了 **框架契约问题**：应强制要求训练脚本输出 train_metric，否则 OVERFIT 检测会降级。

---

## 5. reason → advice 规则映射（机器生成，非 LLM）

### 5.1 基础模板（跨领域）
```python
ADVICE = {
  "OOM":           "Reduce VRAM: lower batch_size / max_len, or use gradient accumulation",
  "CRASH":         "Inspect traceback; fix script error or invalid path before rerunning",
  "BUDGET_TIMEOUT":"Reduce epochs/max-examples or increase efficiency; run was killed by budget",
  "NO_METRIC":     "Training script did not emit parseable metrics; add RESULT/epoch metric line",
  "PLATEAU_EARLY_STOP": "Training plateaued; try lr schedule, more capacity, or accept convergence",
  "OVERFIT":       "Train improved but val did not: lower lr, add regularization/early-stop, or more data",
  "UNDERFIT":      "Both train and val stayed high: raise lr, add warmup, or more epochs",
  "REGRESSION":    "Candidate is worse than champion: revert direction, tune the opposite way",
  "NO_IMPROVE":    "Within noise band of champion: need a larger change to exceed the champion",
  "IMPROVED":      "New champion — record the winning hyper-params/recipe for reuse",
  "EVAL_ANOMALY":  "Validation metric looks anomalous: verify the evaluation code/data split first",
}
```

### 5.2 领域定制模板（只改 advice 措辞，不改归因逻辑）
```python
DOMAIN_ADVICE = {
  "llm": {"OVERFIT": "...reduce lr or add dropout/early-stop; consider LoRA regularization"},
  "dl":  {"OVERFIT": "...lower lr, add weight decay/dropout, or data augmentation"},
  "ml":  {"OVERFIT": "...increase regularization(C), prune features, or get more data"},
  "rl":  {"OVERFIT": "...check reward shaping; reduce replay overfit; tune entropy"},
}
```

### 5.3 domain 检测
- **推荐**：config 显式声明 `evaluation.domain: llm`（最可靠）
- 备选启发式：指标含 `loss`+transformer → llm；含 `auc/f1` → ml；含 `reward` → rl
- **建议**：用 config 显式声明，避免启发式误判。归因逻辑不变，只换 advice 模板。

---

## 6. 落地改动点

| 改动 | 位置 | 说明 |
|------|------|------|
| 新增 `Attribution` + `attribute_outcome()` + `ADVICE` 表 | `core/attribution.py`（新） | 纯函数，可单测 |
| 提取 `OutcomeFacts` | `_machine_judge`（loop.py） | 从 execute_result 组装 |
| 调用 `attribute_outcome` | `_machine_judge`（loop.py） | verdict 追加 reason/evidence/advice/confidence |
| 注入 leader REFLECT + code agent task | `_enrich_context` + leader prompt | 把 reason/advice 带进下一轮 |
| 阈值配置 | `config.yaml evaluation` | 补 `generalization_threshold`、`domain` |
| 单测 | `tests/test_attribution.py`（新） | 覆盖各 reason + 用真实试点数据回归 |

### 单测用例（用真实试点数据 + 合成）
- C2→IMPROVED（1.0128 vs 1.1466）
- C3→REGRESSION（1.1557 vs 1.0128）
- C4→NO_IMPROVE（1.0105 vs 1.0128）
- train_loss=0 → gap=None 容错，退化为 NO_IMPROVE/IMPROVED
- 方向最大化（accuracy）：improve 逻辑反转仍正确
- OOM/CRASH/TIMEOUT 契约层优先

---

## 7. 设计剩余的不确定点（待决策）

**不确定点 1：generalization_threshold 的默认值（过拟合判定）**
`gap > threshold` 判过拟合。但不同领域 train/val gap 的尺度差异巨大（LLM 的 loss gap vs ML 的 AUC gap）。**建议**：用**相对比例** `gap_ratio = |train-val|/val > 0.2` 判过拟合，比绝对阈值更跨领域稳健，但需标定。

**不确定点 2：REGRESSION vs NO_IMPROVE 的分界**
我用 `noise_std` 分界（差超过噪声=REGRESSION，在噪声内=NO_IMPROVE）。但 noise_std 需每领域配置/标定。**建议**：用 `max(noise_std, effect_size)` 作为分界（P3 已用此 effective bar），保证一致性。

**不确定点 3：train_metric 缺失时的 overfit 检测**
实测 train_loss=0 导致无法检测过拟合。**建议**：框架应**强制要求训练脚本输出 train_metric**（契约强化），否则 OVERFIT 检测降级为"仅 val 趋势"。这是框架契约 vs 归因能力的一个权衡。

---

## 8. 与相邻机制的衔接

- **与早停（early_stop）**：`PLATEAU_EARLY_STOP` 复用 monitor 的早停结果；早停的 `direction: lower_better` 与归因的 `primary_direction` 应统一来自配置，避免两套方向定义。
- **与空指标诊断（E）**：`NO_METRIC` 归因与现有 `metrics_diagnosis`（result_missing/no_numeric/log_unavailable）衔接，归因可引用诊断的 reason。
- **与跨轮记忆（MemoryManager）**：`IMPROVED` 归因应把"获胜超参配方"写入 insights（跨轮记忆 L2），供未来轮复用；`REGRESSION`/`NO_IMPROVE` 写入 dead_ends，避免重复。这是归因驱动跨轮知识积累的结合点。
- **与 code agent 优化能力**：本设计是"让归因指导优化"的核心。配合跨轮演化轨迹记忆（记录每次改 train_ft.py 的 diff + 对应结果），code agent 能从"盲试"升级为"基于归因 + 轨迹的定向优化"。

---

## 9. 附：完整讨论对话原文（引出与演进过程）

> 以下为从"引出话题"到"细化设计"的关键对话原文摘录，保留推理过程，供评审参考。

### 9.1 用户提问（话题二引出）
> "你同意我的机器判定反馈归因，但归因结构与归因逻辑、分类是否具备通用性或则是否考虑全面，因为我们要训练的模型不仅仅是微调LLM，还有数理统计机器学习模型和深度学习小模型等多种领域模型"

### 9.2 设计演进（CodeBuddy 的回应要点）
1. **先记录真实试点数据**（Cycle 1-4 的 validation_loss + 判定），发现 `train_loss: 0.0` 这一关键数据/契约 bug，直接支撑了"容错设计"。
2. **核心洞察**：不同领域指标语义不同，但失败模式本质相通（train vs val 关系 + 契约状态）→ 归因应基于"train/val 关系 + 契约"，而非具体指标名。
3. **归一化设计**：`delta_value` 按 direction（minimize/maximize）把指标转成"相对 champion 的改善量"，使归因逻辑领域无关。
4. **容错设计**：`train_metric` 缺失/为 0 时 gap=None，overfit 检测降级为"仅 val 趋势"，避免崩溃。
5. **用实测数据验证逻辑**：Cycle 2→IMPROVED、Cycle 3→REGRESSION、Cycle 4→NO_IMPROVE 全部正确匹配，证明逻辑无需改。
6. **补充领域定制**：domain 字段只改 advice 措辞，不改归因逻辑；config 显式声明 domain 避免启发式误判。
7. **补充遗漏类别**：`EVAL_ANOMALY`（评估 bug，非模型问题）、`IMPROVED`（成功归因）、`UNDERFIT`、`PLATEAU_EARLY_STOP`。

### 9.3 用户确认
> "你的建议我都接受，先细化深入话题二：机器判定归因的通用性（跨领域模型），我们把这个部分细化到落地程度"

### 9.4 本文档的形成
基于上述演进，产出本评审文档（第 3-8 节为细化后的落地设计）。

---

*（评审请求提示词见文档第 0 节，可直接复制。）*
