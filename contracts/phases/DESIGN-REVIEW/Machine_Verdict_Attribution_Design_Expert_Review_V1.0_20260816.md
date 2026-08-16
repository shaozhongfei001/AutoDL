# AutoDL 机器判定归因设计专家评审与改进建议

**报告版本：** V1.0  
**评审对象：** ATTRIBUTION_DESIGN_REVIEW.md  
**评审角色：** AI Model Training AutoResearch Architecture Reviewer  
**评审日期：** 2026-08-16  
**评审性质：** 独立设计评审，不替代实现与独立 QA  

---

## 1. 总体结论

### 1.1 门禁结论

    DESIGN_DIRECTION=APPROVED
    IMPLEMENTATION_READY=NO
    DESIGN_GATE=BLOCKED_FOR_REMEDIATION
    PRODUCTION_READY=NO
    FROZEN=NO

设计方向值得保留：使用机器事实生成结构化反馈，明显优于只输出 KEEP、DISCARD、INCOMPARABLE；将方向 minimize/maximize 交给指标合同，也符合跨任务框架的基本要求；规则归因用于裁决解释、LLM 用于提出后续假设，这一职责分离是正确的。

但当前版本尚不能直接实现，原因不是文档不够详细，而是存在数个会改变机器判定结果的结构性问题：

1. 当前模块实际提供的是“结果诊断”，不是严格的“因果归因”。一次候选通常同时修改多个因素，不能从一次结果证明具体超参数是原因。
2. 单一 reason 混合了运行终态、可比性、晋级结果、学习行为信号和建议，导致信息互斥、优先级冲突和事实丢失。
3. 当前 REGRESSION、NO_IMPROVE、IMPROVED 区间没有形成完备互斥分区，在部分合法配置下会把负改进误判为 IMPROVED。
4. train_metric > 0 才有效的规则不成立。零值、负值都可能是合法指标，缺失和零不能混为一谈。
5. “train 与 validation 的关系跨所有领域通用”是过度概括。它适合指标可交换的监督学习与部分 LLM 训练，但对交叉验证、强化学习、无监督学习和多目标优化并不天然成立。
6. Cycle 1 是硬超时运行，却被用作 baseline/champion。当前规则会优先判为 BUDGET_TIMEOUT，与原机器判定 INCOMPARABLE 及后续比较逻辑不一致。
7. UNDERFIT、EVAL_ANOMALY、confidence、reason_from_gap 等关键能力只存在于分类表或伪代码名称中，没有形成可执行定义。

因此建议批准“设计整改与受控试点”，不批准直接合入现有 _machine_judge。

### 1.2 六个评审维度结论

| 维度 | 结论 | 核心判断 |
|---|---|---|
| 通用性 | PARTIAL | 契约与执行失败可跨领域复用；学习行为诊断必须按能力 profile 扩展，不能只换 advice 文案 |
| 覆盖全面性 | PARTIAL | 已覆盖常见基本类别，但缺少数据/评估污染、统计不稳定、约束退化、多目标、运行恢复等关键类别 |
| 判定逻辑 | BLOCKED | 阈值分区、早停优先级、零值处理、无 champion、超时 baseline 均存在确定性问题 |
| 可落地性 | PARTIAL | 文件改动点清楚，但 OutcomeFacts 无法支持文档宣称的部分计算，数据来源和质量状态不完整 |
| 架构 | MAJOR_REDESIGN | 应拆成事实标准化、资格门禁、晋级裁决、诊断检测、建议策略五层 |
| 风险与盲点 | HIGH | 最大风险是把诊断性相关关系当因果事实，写入跨轮记忆后持续误导 Agent |

---

## 2. 值得保留的设计

以下部分可以吸收进下一版：

1. **机器事实优先。** 裁决和证据必须来自结构化运行数据，不使用 Agent 自述替代。
2. **有向差值。** 将 maximize/minimize 统一为“正数表示候选更好”，适合作为晋级层的基础原语。
3. **OutcomeFacts 边界。** 在领域运行结果与诊断器之间建立 DTO 是正确的隔离思路。
4. **确定性 advice。** 在无人值守闭环中，建议策略应可版本化、可测试、可审计。
5. **无状态 Agent 反馈。** 通过 framework 注入最近实验、失败路径和结构化反馈，能降低盲试。
6. **真实实验回放。** 用 Cycle 1—4 建立回归测试比仅靠合成数据更可信。
7. **显式 domain 配置。** 不依赖指标名猜测领域的方向正确。

这些优点应保留，但要放入更严格的分层合同。

---

## 3. P0 级结构性问题

### 3.1 “结果诊断”与“因果归因”没有区分

Cycle 2 同时发生：

- 学习率由 1e-4 降到 5e-5。
- 引入 micro batch 与梯度累积。

validation_loss 改善只能支持：

> 该候选整体配方相对基线表现更好。

它不能支持：

> 降低学习率是改善原因。

也不能支持：

> 梯度累积是改善原因。

要形成因果声明，至少需要单因素消融、受控重放、多种子重复或更强的实验设计。当前模块应改名或明确分级：

| 输出层级 | 允许声明 |
|---|---|
| OBSERVATION | 候选指标、运行终态、资源事实 |
| ASSOCIATION | 某个候选 diff 与结果同时出现 |
| DIAGNOSTIC_SIGNAL | 数据符合过拟合、平台期等检测模式 |
| ABLATION_SUPPORTED | 单因素消融支持某项改动 |
| REPLICATED_CAUSAL_EVIDENCE | 多次受控重复支持因果关系 |

默认 causal_claim_level 必须为 NONE 或 ASSOCIATION。不得把规则 advice 写入记忆为“已证实原因”。

### 3.2 单一 reason 不能表达真实实验

同一个实验可能同时满足：

- 运行成功。
- 相对 champion 有统计显著改善。
- train/validation gap 增大。
- 峰值显存违反硬约束。
- 早停因平台期触发。

用一个 reason 无法同时表达这些事实。当前优先级会丢失重要信息：

- early_stopped 会遮蔽 IMPROVED。
- OVERFIT 会遮蔽相对 champion 的真实改善。
- OOM 关键字会遮蔽一次已恢复的非终止性 OOM。

必须分层：

| 层 | 示例 |
|---|---|
| eligibility | COMPARABLE、INCOMPARABLE、CONTRACT_INVALID |
| execution | COMPLETED、CRASHED、HARD_TIMEOUT、OOM_FATAL |
| outcome | IMPROVED、EQUIVALENT、REGRESSION、NO_BASELINE |
| constraints | PASS、RESOURCE_VIOLATION、SAFETY_VIOLATION |
| diagnostics | OVERFIT_SIGNAL、PLATEAU、HIGH_VARIANCE，可多选 |
| recommendation | 可执行动作候选，可多选 |

verdict 由 eligibility、outcome 和 constraints 决定；diagnostics 只解释和指导下一步，不反向偷偷改写 verdict。

### 3.3 当前阈值逻辑存在确定性误判

现有逻辑：

    if improve <= -noise_std:
        REGRESSION
    elif abs(improve) <= effect_size:
        NO_IMPROVE
    else:
        IMPROVED

反例：

    noise_std = 0.05
    effect_size = 0.02
    improve = -0.03

结果：

- -0.03 没有小于等于 -0.05，因此不是 REGRESSION。
- 绝对值 0.03 大于 0.02，因此不是 NO_IMPROVE。
- 最终落入 IMPROVED，尽管候选实际更差。

这属于 P0 逻辑错误。最低可行修复：

    decision_bar = max(practical_delta, noise_multiplier * delta_uncertainty)

    if improve >= decision_bar:
        IMPROVED
    elif improve <= -decision_bar:
        REGRESSION
    else:
        EQUIVALENT_OR_NO_EVIDENCE

更优方案是对 candidate 与 champion 的差值构造置信区间：

- 差值置信区间下界仍超过最小实际改善：IMPROVED。
- 差值置信区间上界仍低于负的退化阈值：REGRESSION。
- 其余：EQUIVALENT、INCONCLUSIVE 或 HUMAN_REVIEW。

noise_std 不应只是单个配置常量，而应来自同一 Study、同一 hardware cohort、同一评估器的重复运行。

### 3.4 train_metric 的零值处理不正确

以下值都可能合法：

- loss = 0：完美拟合、小规模合成数据、四舍五入或特殊任务。
- reward = 0：RL 的合法基准值。
- correlation = 0：合法无相关结果。
- reward 或对数似然为负：合法指标。

因此：

    train_metric is not None and train_metric > 0

不能作为可用性判断。

应增加显式质量状态：

    train_metric_status:
      PRESENT_VALID
      MISSING
      NON_FINITE
      PARSE_ERROR
      STALE
      INCOMMENSURATE

零值只要是 finite 且符合 metric contract，就是 PRESENT_VALID。当前试点中的 train_loss=0.0 是 bug，必须由采集证据证明，不能仅依据数值为零推断。

### 3.5 train 与 validation 并非天然可比较

计算 generalization gap 必须同时满足：

1. train 与 validation 使用同一 metric_id。
2. 方向、单位和变换完全一致。
3. 对应同一 checkpoint。
4. 聚合方法和样本权重一致。
5. train 指标不是训练过程中 batch loss 的最后一个值，而是可比较的训练集评估值。

常见不成立场景：

- 训练指标是 cross_entropy，验证主指标是 accuracy。
- 训练指标是 mini-batch 滑动平均，验证指标是全量数据集均值。
- 统计 ML 使用 K 折交叉验证，没有单一 val_sequence。
- RL 的在线训练 reward 与独立 evaluation return 来自不同策略分布和环境种子。
- LLM 训练 loss 使用 token 加权，验证 loss 使用样本平均。

OutcomeFacts 必须携带 metric identity、split、aggregation、checkpoint、sample_count 和 evaluator hash。无法证明可交换时，generalization detector 应返回 NOT_APPLICABLE 或 UNAVAILABLE，不得默认为 gap=None 后继续暗示没有过拟合。

### 3.6 “跨领域失败本质相通”的结论过强

可通用的是：

- 合同违规。
- 运行失败。
- 指标缺失或非法。
- 与 champion 的有向差值。
- 资源和安全约束。

不能无条件通用的是学习行为：

| 任务 profile | 合理诊断 |
|---|---|
| supervised_holdout | train/validation gap、学习曲线、校准 |
| cross_validation | 折间差异、配对折差值、方差 |
| time_series | 滚动窗口、时间漂移、泄漏检测 |
| language_modeling | token 加权 loss、perplexity/BPB、下游约束 |
| reinforcement_learning | 独立评估环境、episode return 分布、IQM/Bootstrap、reward hacking |
| unsupervised | 重构/对比目标与下游代理指标，通常无直接 train/val gap 语义 |

因此，domain 不应只影响 advice 文案。应改为必填 task_profile 或 capability_profile，由 profile 决定可用 detector、所需字段、统计方法和建议动作。

### 3.7 超时、预算到期与正常完成没有分开

AutoResearch 固定预算模式中，“主动训练达到预算并正常收尾”是正常完成，不是失败。

至少应区分：

- BUDGET_REACHED：训练按合同达到预算并正常输出结果。
- HARD_TIMEOUT：runner 的硬兜底超时，进程未按预期结束。
- BUDGET_EXCEEDED：实际主动训练超过合同允许范围。
- CANCELLED：人为或系统取消。

当前 BUDGET_TIMEOUT 把这些语义混为一谈，并建议“减少 epochs”，会破坏固定时间预算的实验设计。

### 3.8 Cycle 1 baseline 的资格矛盾

文档称 Cycle 1：

- 训练 2.5 小时后被硬终止。
- 获得 validation_loss。
- 机器 verdict 为 INCOMPARABLE。
- Cycle 2 又使用 Cycle 1 指标作为 champion。

必须决策：

1. 如果 Cycle 1 违反合同且不可比较，它不能自动成为正式 champion。
2. 如果允许用部分运行建立 provisional baseline，Study Contract 必须明确 partial_metric_eligibility，且 champion 状态应标为 PROVISIONAL。
3. 如果硬终止只是预期预算结束，状态应改为 BUDGET_REACHED，而不是 TIMEOUT。

在此决策前，Cycle 2 的“与 champion 一致”只能算条件成立。

### 3.9 confidence 没有可计算定义

规则输出 0—1 confidence 容易制造虚假精确度。当前没有：

- 标注集。
- detector 校准。
- 误报/漏报统计。
- 证据质量到概率的映射。

V1 建议输出 evidence_strength：

- HIGH：结构化 runner/evaluator 直接事实。
- MEDIUM：多项一致机器信号。
- LOW：日志启发式或字段不完整。
- UNAVAILABLE：证据不足。

只有在有标注实验集并完成校准后，才将 confidence 解释为概率。

---

## 4. 对 Cycle 1—4 的重新验证

### 4.1 可确认的部分

在假定以下条件成立时：

- Cycle 1 可作为合法或临时 baseline。
- candidate 与 champion 使用同一 evaluator、数据、预算和环境。
- direction=minimize。
- 阈值配置有效。

有向差值计算正确：

| Cycle | 差值 | 可确认结果 |
|---|---:|---|
| 2 | 1.1466 - 1.0128 = +0.1338 | 明显正向改善 |
| 3 | 1.0128 - 1.1557 = -0.1429 | 明显退化 |
| 4 | 1.0128 - 1.0105 = +0.0023 | 小幅正差，是否有效取决于噪声与实际改善阈值 |

### 4.2 不能由这组数据证明的内容

Cycle 1—4 没有验证：

- OVERFIT。
- UNDERFIT。
- EVAL_ANOMALY。
- PLATEAU_EARLY_STOP。
- maximize 指标。
- train/validation gap。
- 多种子统计。
- RL、统计 ML、CNN 等跨领域行为。
- confidence。
- reason→advice 的有效性。

因此，“判定逻辑无需改动即正确分类全部数据”应改成：

> 这组数据验证了 minimize 方向下，相对 champion 有向差值的三个基本回放路径；没有验证完整归因分类或跨领域通用性。

### 4.3 建议的真实数据回放状态

| Cycle | eligibility | execution | outcome | diagnostics | 建议 verdict |
|---|---|---|---|---|---|
| 1 | 待决：partial baseline policy | HARD_TIMEOUT 或 BUDGET_REACHED 待澄清 | NO_BASELINE | train metric 质量异常 | PROVISIONAL_BASELINE 或 INCOMPARABLE |
| 2 | 若 C1 合法则 COMPARABLE | COMPLETED | IMPROVED | train signal unavailable | KEEP |
| 3 | COMPARABLE | COMPLETED | REGRESSION | train signal unavailable | DISCARD |
| 4 | COMPARABLE | COMPLETED | EQUIVALENT/NO_EVIDENCE | train signal unavailable | DISCARD |

---

## 5. 建议的目标架构

不建议让 attribute_outcome 同时完成所有工作。建议拆成以下流水线：

| 阶段 | 组件 | 输入 | 输出 |
|---|---|---|---|
| 1 | OutcomeFactsBuilder | execute_result、ledger、Study/Experiment Contract | 标准化事实与字段质量 |
| 2 | EligibilityGate | 合同 hash、数据、评估器、环境、预算、父 champion | COMPARABLE/INCOMPARABLE/BLOCKED |
| 3 | ExecutionClassifier | runner 结构化事件 | COMPLETED/CRASHED/OOM_FATAL/HARD_TIMEOUT |
| 4 | MetricValidator | 指标值、序列、样本数、checkpoint | VALID/INVALID/MISSING/STALE |
| 5 | PromotionJudge | candidate/champion 分布、阈值、约束 | KEEP/DISCARD/HUMAN_REVIEW |
| 6 | DiagnosticEngine | profile、学习曲线、资源、评估事实 | 0..N 个 DiagnosticFinding |
| 7 | AdvicePolicy | findings、profile、change diff、权限 | 0..N 个 ActionRecommendation |
| 8 | FeedbackPublisher | 结构化报告 | leader、code agent、memory、ledger 的分级视图 |

关键原则：

- PromotionJudge 是 verdict 的唯一权威。
- DiagnosticEngine 不重新计算另一个 verdict。
- AdvicePolicy 生成候选动作，不生成事实。
- FeedbackPublisher 必须阻止 test 结果进入逐轮 Agent。
- 所有输出都记录 policy_version 和 detector_version。

---

## 6. 建议的数据模型 V2

### 6.1 MetricObservation

    MetricObservation:
      metric_id
      value
      direction
      unit
      split
      checkpoint_id
      step
      timestamp
      aggregation
      sample_count
      evaluator_hash
      dataset_fingerprint
      status
      uncertainty

status 必须区分 PRESENT_VALID、MISSING、NON_FINITE、PARSE_ERROR、STALE。

### 6.2 OutcomeFactsV2

    OutcomeFactsV2:
      schema_version
      study_id
      experiment_id
      study_contract_hash
      experiment_contract_hash
      champion_before_sha
      candidate_sha
      champion_metric_observations
      candidate_metric_observations
      train_curve
      validation_curve
      execution_status
      terminal_cause
      budget_events
      resource_events
      artifact_manifest_hash
      evaluator_hash
      dataset_fingerprint
      environment_cohort
      early_stop_event
      structured_errors
      log_diagnostics
      change_summary

重要变化：

- 不再用一个 contract_status 表达所有状态。
- 不再用 oom_signal 布尔值覆盖结构化终态。
- metric 使用 observation，而不是裸 float。
- champion_metric 可不存在，并显式进入 NO_BASELINE。
- generalization_threshold 不放入事实 DTO，而来自已版本化 detector policy。

### 6.3 DiagnosticFinding

    DiagnosticFinding:
      code
      layer
      severity
      applicability
      evidence_strength
      detector_version
      evidence_refs
      observed_values
      limitations
      causal_claim_level

### 6.4 ActionRecommendation

    ActionRecommendation:
      action_code
      priority
      rationale_finding_refs
      parameters
      prerequisites
      expected_effect
      risks
      allowed_change_scope
      requires_new_study
      requires_human_review
      policy_version

### 6.5 AttributionReportV2

    AttributionReportV2:
      eligibility
      execution
      outcome
      constraints
      verdict
      findings
      recommendations
      unknowns
      evidence_completeness
      policy_versions

可以继续向 UI 展示一个 primary_reason，但它只能由上述结构派生，不能作为唯一存储事实。

---

## 7. 修订后的判定逻辑

### 7.1 第一层：资格与可比性

先检查：

- Study/Experiment Contract 是否有效。
- candidate 是否基于当前 champion。
- evaluator、数据、split、环境 cohort、预算是否一致。
- Artifact Manifest 是否完整。
- test 是否被错误用于逐轮选优。

任一 P0 不一致时，停止自动比较：

    eligibility = INCOMPARABLE or BLOCKED
    verdict = INCOMPARABLE

不得继续用 primary_metric 强行排序。

### 7.2 第二层：运行终态

优先使用 runner 的结构化事件：

    if terminal_cause == OOM_FATAL:
        execution = OOM_FATAL
    elif terminal_cause == HARD_TIMEOUT:
        execution = HARD_TIMEOUT
    elif terminal_cause == CRASH:
        execution = CRASHED
    elif terminal_cause == BUDGET_REACHED and finalization_ok:
        execution = COMPLETED

日志关键字只能作为低证据 fallback。必须把非致命、已恢复的 OOM 与 OOM_FATAL 分开。

### 7.3 第三层：指标有效性

检查：

- None、NaN、Inf。
- evaluator 与 dataset fingerprint。
- sample_count。
- checkpoint 对齐。
- 指标是否来自 validation。
- 聚合方式与 champion 是否一致。

primary metric 无效时：

    outcome = UNKNOWN
    verdict = DISCARD or INCOMPARABLE
    finding = NO_VALID_PRIMARY_METRIC

具体 verdict 由 Study Policy 规定，但永远不能 KEEP。

### 7.4 第四层：相对 champion 的结果

有向差值：

    signed_delta =
      candidate - champion, when maximize
      champion - candidate, when minimize

推荐统计规则：

1. 以相同 seeds 或折构造配对差值。
2. 计算 delta 的置信区间或 bootstrap 区间。
3. separate minimum practical improvement 与 statistical uncertainty。

首版可用的安全规则：

    uncertainty_bar = noise_multiplier * delta_uncertainty
    decision_bar = max(min_practical_delta, uncertainty_bar)

    if signed_delta >= decision_bar:
        outcome = IMPROVED
    elif signed_delta <= -decision_bar:
        outcome = REGRESSION
    else:
        outcome = EQUIVALENT_OR_INCONCLUSIVE

配置校验必须拒绝负 threshold、非 finite 值和缺少单位的阈值。

### 7.5 第五层：约束与多目标

即使主指标改善，只要违反硬约束，也不能 KEEP：

- peak VRAM。
- hard budget。
- latency。
- 模型大小。
- 安全/公平性指标。
- 依赖或受保护边界。

    if hard_constraint_violated:
        verdict = DISCARD_CONSTRAINT
    elif outcome == IMPROVED:
        verdict = KEEP
    elif outcome in REGRESSION, EQUIVALENT_OR_INCONCLUSIVE:
        verdict = DISCARD

### 7.6 第六层：诊断信号

诊断允许多标签：

- OVERFIT_SIGNAL。
- UNDERFIT_SIGNAL。
- OPTIMIZATION_DIVERGENCE。
- PLATEAU。
- HIGH_VARIANCE。
- TRAINING_INSTABILITY。
- EVAL_ANOMALY。
- RESOURCE_REGRESSION。
- DATA_QUALITY_SIGNAL。
- REWARD_HACKING_SIGNAL。

这些 finding 为下一轮提供信息，但不应覆盖上层 eligibility 和 verdict。

---

## 8. Generalization、Underfit 与异常检测的正确边界

### 8.1 不采用统一 gap_ratio=0.2

    abs(train - val) / val

存在以下问题：

- val 接近 0 时爆炸。
- val 为负时语义异常。
- 不同指标范围不同。
- 某些任务存在稳定、合理的非零 gap。

建议按 profile 标定：

    standardized_gap =
      (observed_gap - expected_gap_baseline) / gap_uncertainty

只有在 metric commensurability=true 且有 baseline gap 分布时启用。没有标定数据时返回 DETECTOR_UNAVAILABLE，不设置跨领域默认 0.2。

### 8.2 UNDERFIT 不能仅用“train 和 val 都高”

UNDERFIT 至少需要：

- 指标相对 chance/reference baseline 的位置。
- train curve 是否持续改善。
- 是否用尽预算。
- 模型容量或优化是否成为瓶颈的辅助证据。

“loss 高”没有通用绝对含义；“accuracy 低”也依赖类别数和基线。

### 8.3 EVAL_ANOMALY 不能以不单调为主要证据

validation 曲线不单调是正常现象。更可靠的异常信号：

- NaN/Inf。
- evaluator、split 或样本数变化。
- checkpoint 与 step 不一致。
- 指标越界。
- 多次完全相同且日志显示评估未执行。
- 相对历史稳健分布的突变，并同时存在数据或执行异常。
- test/validation 混用。

单纯突跳只能产生 LOW evidence_strength，不应直接断言评估 bug。

### 8.4 早停是终止原因，不是唯一结果

应同时表达：

    execution.termination = EARLY_STOP_PLATEAU
    outcome = IMPROVED
    diagnostics = [PLATEAU]

或：

    execution.termination = EARLY_STOP_DIVERGENCE
    outcome = REGRESSION
    diagnostics = [OPTIMIZATION_DIVERGENCE]

因此删除 early_stopped 对 primary reason 的短路覆盖。

---

## 9. 跨领域扩展策略

### 9.1 用 capability profile 取代只换文案

建议配置：

    evaluation:
      task_profile: supervised_holdout
      capabilities:
        paired_candidate_champion: true
        comparable_train_validation_metric: true
        learning_curve_available: true
        repeated_seeds_available: true
        cross_validation_available: false
        episodic_evaluation: false

Detector 根据 capability 启用，而不是根据 llm/dl/ml/rl 名称猜测。

### 9.2 各 profile 最低要求

| profile | 必需事实 | 特有诊断 |
|---|---|---|
| supervised_holdout | train/val 同指标曲线、split hash | generalization gap、underfit、calibration |
| cross_validation | 每折 candidate/champion 配对值 | fold variance、instability |
| time_series | 时间窗口、cutoff、滚动评估 | temporal drift、look-ahead leakage |
| language_modeling | token 权重、tokenizer、context、BPB/loss | token-level gap、length shift |
| reinforcement_learning | 独立 eval episodes、seeds、环境版本 | high variance、policy collapse、reward hacking |

RL 不应直接复用普通 train reward 与 val reward gap。建议使用独立 evaluation environment，并报告 episode return 分布、成功率、约束成本和 bootstrap/IQM。

### 9.3 多目标与约束

通用 AutoResearch 不应只存一个 primary metric。至少支持：

- primary objective。
- secondary observations。
- hard constraints。
- tie breakers。

主指标改善但显存、延迟或安全约束退化时，输出 IMPROVED_WITH_CONSTRAINT_VIOLATION，verdict 为 DISCARD 或 HUMAN_REVIEW。

---

## 10. reason→advice 设计改进

### 10.1 Advice 不是机器事实

evidence 是事实；diagnostic finding 是规则结论；advice 是下一步假设。三者必须使用不同字段和记忆层级。

禁止将：

> lower lr will fix overfit

写成事实。更准确的表达：

> 观察到过拟合信号。候选动作之一是测试更强正则或调整训练强度；需要受控实验验证。

### 10.2 用动作语义代替自然语言硬编码

基础层输出 action_code：

- REDUCE_MEMORY_FOOTPRINT。
- VERIFY_EVALUATION_PIPELINE。
- RESTORE_CHAMPION_AND_ABLATE_DIFF。
- INCREASE_REGULARIZATION_STRENGTH。
- ADJUST_OPTIMIZATION_SCHEDULE。
- IMPROVE_DATA_COVERAGE。
- RUN_REPEATED_SEEDS。

profile adapter 再翻译为具体参数。

这样可避免现有模板中的问题：

- OOM 基础建议包含 max_len，偏 LLM。
- “提高 C”在 LR/SVM 中通常意味着减弱正则，容易方向相反。
- “反向调整”假设超参数响应单调，真实训练中常不成立。
- RL reward shaping 会改变目标合同，可能必须新建 Study，不能作为普通自动建议。

### 10.3 建议对象必须带保护信息

每条建议包含：

- prerequisites。
- allowed_change_scope。
- risks。
- requires_new_study。
- requires_human_review。
- expected evidence。

凡涉及数据、split、evaluator、reward function、主指标和预算模式的建议，必须进入 Change Request 或新 Study，不得直接派发给 Code Agent。

### 10.4 Advice 策略版本化

建议规则不应直接散落在 core/attribution.py 常量中。建议使用版本化 policy：

    policies/advice/base_v1.yaml
    policies/advice/supervised_v1.yaml
    policies/advice/rl_v1.yaml

每个 ledger event 记录 advice_policy_version。规则变更不追溯改写历史建议。

---

## 11. 与相邻机制的正确衔接

### 11.1 与 _machine_judge

不建议 attribute_outcome 内部再产生另一套判定。建议：

1. _machine_judge 调用 EligibilityGate 和 PromotionJudge，形成唯一 verdict。
2. DiagnosticEngine 接收 verdict 与标准化事实，生成 findings。
3. AdvicePolicy 根据 findings 生成 recommendations。
4. 三者一起写入 ledger，但权威层级不同。

### 11.2 与早停

- direction、min_delta、patience 必须来自同一 Study Contract。
- early stop event 携带 cause、step、best_checkpoint 和 best_metric。
- 评估必须使用 best checkpoint，而不是默认最后 checkpoint。

### 11.3 与空指标诊断

NO_METRIC 应引用 metrics_diagnosis 的结构化代码：

- RESULT_MISSING。
- NO_NUMERIC_VALUE。
- LOG_UNAVAILABLE。
- PARSE_SCHEMA_MISMATCH。
- METRIC_NON_FINITE。

不要把所有情况压成同一 advice。

### 11.4 与跨轮记忆

建议分级写入：

| 记忆层 | 可写内容 |
|---|---|
| FACT | candidate diff、指标、终态、manifest hash |
| DIAGNOSTIC_HYPOTHESIS | OVERFIT_SIGNAL 等规则发现 |
| DEAD_END | 已重复或受控验证的无效方向 |
| RECIPE | 完整候选配方，不拆分为未经验证的因果参数 |
| CAUSAL_EVIDENCE | 只有消融/重复达到门槛后写入 |

一次多参数 DISCARD 不足以把每个参数都写成 dead end。

### 11.5 与 Code Agent

Code Agent 获得：

- machine facts。
- verdict。
- findings 及限制。
- recommendations。
- champion diff。
- allowlist 与 protected boundaries。

Code Agent 不应直接获得 test 指标、未经校准的因果声明或可修改晋级策略的权限。

---

## 12. 落地改动建议

### 12.1 推荐模块

| 模块 | 职责 |
|---|---|
| core/diagnostics/models.py | MetricObservation、OutcomeFactsV2、Finding、Recommendation |
| core/diagnostics/facts.py | 从 execute_result、ledger、合同构建事实 |
| core/diagnostics/eligibility.py | 可比性和合同门禁 |
| core/diagnostics/outcome.py | 有向差值、统计区间、outcome |
| core/diagnostics/execution.py | runner 终态分类 |
| core/diagnostics/detectors/ | profile 化诊断器 |
| core/diagnostics/advice.py | 版本化动作策略 |
| core/diagnostics/publish.py | leader/code/memory 的分级反馈 |

如果暂不拆包，也必须在单文件中维持上述纯函数边界，不得保留一个超大 attribute_outcome。

### 12.2 对现有改动表的修订

| 原改动 | 修订建议 |
|---|---|
| OutcomeFacts 从 execute_result 提取 | 增加 OutcomeFactsBuilder，联合 Contract、Ledger、Artifact Manifest；字段带质量状态 |
| _machine_judge 调用 attribute_outcome | 改为唯一 PromotionJudge 先裁决，DiagnosticEngine 后解释 |
| verdict 追加 reason/evidence/advice/confidence | 改为分层 AttributionReportV2；confidence 暂改 evidence_strength |
| 注入 leader 与 code agent | 使用 FeedbackPublisher 生成不同视图，隔离 test 与治理字段 |
| config 增加 threshold/domain | 改为 task_profile、capabilities、statistical policy、detector policy |
| tests/test_attribution.py | 扩展为合同、性质、边界、回放、profile 和端到端测试 |

### 12.3 Ledger 事件

建议新增：

- outcome_facts_built。
- eligibility_evaluated。
- execution_classified。
- metric_validated。
- promotion_decided。
- diagnostics_emitted。
- advice_emitted。
- feedback_published。

每个事件记录 schema_version、policy_version、输入 hash 和 evidence refs。

---

## 13. 必须补充的测试

### 13.1 P0 单元测试

1. noise_std 大于 effect_size 且 improve 为负，不能落入 IMPROVED。
2. improve 等于正/负 decision_bar 的边界。
3. champion_metric=None，输出 NO_BASELINE，不抛异常。
4. primary_metric=0、train_metric=0、负 reward 均可被识别为合法值。
5. NaN、Inf、parse error 分开处理。
6. early stop 且指标改善，同时输出 IMPROVED 与 PLATEAU。
7. 指标改善且 gap 增大，同时输出 IMPROVED 与 OVERFIT_SIGNAL。
8. BUDGET_REACHED 正常完成，不判 BUDGET_TIMEOUT。
9. OOM 日志出现但训练恢复，不能判 OOM_FATAL。
10. evaluator、dataset、cohort 不一致时不得比较。
11. best checkpoint 与 last checkpoint 不同，使用合同规定的 checkpoint。
12. 硬约束违反时，即使主指标改善也不能自动 KEEP。

### 13.2 性质测试

- direction 翻转并同步数值变换后，outcome 应保持一致。
- candidate 与 champion 相同，结果必须在等价区间。
- decision_bar 增大不能让原 NO_IMPROVE 变成 IMPROVED。
- 缺少更多证据不能提高 evidence_strength。
- diagnostics 顺序变化不能改变 verdict。
- advice policy 变化不能追溯改变历史 verdict。

### 13.3 Profile 测试

- supervised：同指标 train/val gap。
- cross-validation：配对折差值与折间方差。
- time-series：滚动窗口与 look-ahead leakage。
- LLM：token 加权 loss 与 tokenizer hash。
- RL：多 episode return、不同 seeds、high variance、reward/cost constraint。

### 13.4 真实 Cycle 回放

- C1 必须先按 baseline eligibility 决策完成后再纳入。
- C2、C3、C4 保留为 minimize 基础回放。
- 增加至少一组 maximize 指标真实回放。
- 增加多种子候选与 champion 分布。
- 增加 early stop、OOM、hard timeout 和 metric invalid 的真实日志。

### 13.5 端到端测试

- findings 正确注入 leader。
- Code Agent 只看到 validation 反馈。
- test 结果不进入 recent_experiments、dead_ends、insights 或 metrics_feedback。
- 低证据诊断不会作为 CAUSAL_EVIDENCE 写入。
- policy/version/hash 在 ledger 中完整。

---

## 14. 分阶段实施建议

### 阶段 0：修复事实合同

- 澄清 Cycle 1 的 budget/timeout/baseline 资格。
- 修复 train_metric 采集，不用数值 0 表示缺失。
- 固化 metric、dataset、evaluator、checkpoint、environment 字段。

**退出标准：** OutcomeFactsV2 能完整表达 Cycle 1—4，所有字段来源可追踪。

### 阶段 1：实现通用核心

- EligibilityGate。
- ExecutionClassifier。
- MetricValidator。
- PromotionJudge。
- supervised_holdout 基础 profile。

**退出标准：** P0 单元、性质和真实回放全部通过；唯一 verdict 无分叉。

### 阶段 2：实现诊断与建议

- 多标签 findings。
- evidence_strength。
- 动作语义与版本化 advice policy。
- Memory 分层写入。

**退出标准：** advice 不被记录为机器事实，低证据 finding 不生成高风险自动动作。

### 阶段 3：扩展统计 ML / DL

- cross-validation。
- learning curve。
- 多种子统计和 paired delta。

**退出标准：** 真实 AUC/F1/accuracy 项目回放通过。

### 阶段 4：单独设计 RL profile

- 独立评估环境。
- episode return 分布。
- bootstrap/IQM。
- reward/cost constraints 与 reward hacking 信号。

**退出标准：** 不复用不适用的普通 train/val gap；RL 专项 QA 通过。

---

## 15. 按优先级的改进建议

### P0｜实施前必须完成

1. 将“因果归因”降级为“分层结果诊断＋可选因果证据等级”。
2. 拆分 eligibility、execution、outcome、constraints、diagnostics、recommendations。
3. 修复阈值区间，使用互斥 decision bar 或差值置信区间。
4. 删除 train_metric > 0，可用显式字段质量状态。
5. 明确 Cycle 1 的硬超时与 baseline 资格。
6. 将 BUDGET_REACHED 与 HARD_TIMEOUT 分离。
7. 增加 metric identity、split、checkpoint、aggregation、sample_count 和 evaluator hash。
8. 保证 PromotionJudge 是唯一 verdict 权威。
9. 明确 validation 选优、test 独立验收，反馈发布器不得泄漏 test。

### P1｜首个试点前完成

1. 使用 capability profile 控制 detector。
2. 将单一 reason 改为多标签 finding。
3. confidence 改为 evidence_strength，待标注校准后再升级。
4. 增加多目标与硬约束。
5. 将 advice 改成版本化 action policy。
6. 分层写入跨轮记忆，禁止把诊断假设当因果事实。
7. 补充性质测试、边界测试和失败注入。

### P2｜跨领域扩展时完成

1. cross-validation 与 time-series profiles。
2. RL 专项统计与诊断。
3. detector 精度评估与 confidence 校准。
4. advice 采纳率、成功率和副作用的离线评估。
5. 自动消融计划器，用于将 ASSOCIATION 提升为 ABLATION_SUPPORTED。

---

## 16. 最关键的三个待决策点

### 决策 1：系统承诺“结果诊断”还是“因果归因”

**建议：** V1 正式名称采用 Machine Verdict Diagnosis；保留 causal_claim_level。只有受控消融和重复实验才升级因果等级。

这是最重要的语义边界。如果不解决，系统会把一次多变量实验的相关性沉淀成错误长期记忆。

### 决策 2：采用单一 reason 还是分层多标签报告

**建议：** 采用分层多标签。UI 可展示 primary_reason，但 ledger 必须保存完整 eligibility、execution、outcome、constraints 和 findings。

### 决策 3：晋级采用简单 effective bar 还是统计区间

**建议：**

- 首个试点：decision_bar = max(min_practical_delta, k × delta_uncertainty)，并严格校验。
- 稳定版本：使用 paired seeds/folds 的差值置信区间或 bootstrap。
- generalization threshold 不设置跨领域全局默认值；按 profile 与 baseline 标定。
- train metric 是否强制，由 profile 决定；若声明支持 OVERFIT，缺少可比较 train 指标即合同不完整。

---

## 17. 最终批准条件

满足以下条件后，可将 DESIGN_GATE 从 BLOCKED_FOR_REMEDIATION 调整为 PASS_FOR_IMPLEMENTATION：

1. P0 阈值误判反例有回归测试并修复。
2. Cycle 1 baseline 资格完成 Owner/架构裁决。
3. OutcomeFactsV2 字段来源和质量状态完整。
4. verdict 与 diagnostics 分层，唯一晋级权威明确。
5. 零值、负值、NaN、缺失和不可交换指标分别处理。
6. supervised_holdout 之外的 profile 不再被宣称已通用支持。
7. advice 与事实、因果证据分层。
8. test 反馈隔离明确进入接口和端到端测试。
9. P0 单元测试、性质测试、真实 Cycle 回放全部通过。
10. 独立 QA 给出 PASS，且本设计与项目 SDD 总契约无冲突。

在此之前，建议保留当前代码不变，将本报告作为 ATTRIBUTION_DESIGN_REVIEW.md 的整改输入，不直接实现原伪代码。
