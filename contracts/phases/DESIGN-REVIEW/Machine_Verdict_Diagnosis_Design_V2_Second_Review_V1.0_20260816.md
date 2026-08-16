# AutoDL 机器判定诊断设计 V2 二审报告

**报告版本：** V1.0  
**二审对象：** Machine_Verdict_Diagnosis_Design_V2_20260816.md  
**对照基准：** Machine_Verdict_Attribution_Design_Expert_Review_V1.0_20260816.md  
**评审角色：** AutoDL 高级架构评审专家  
**评审日期：** 2026-08-16  

---

## 1. 二审结论

    SECOND_REVIEW=BLOCKED_FOR_REMEDIATION
    DESIGN_DIRECTION=APPROVED
    P0_FULLY_CLOSED=NO
    IMPLEMENTATION_AUTHORIZED=NO
    PRODUCTION_READY=NO
    FROZEN=NO

V2 已经完成实质性整改，不是对 V1 的表面改写。以下方向已经成立：

- 正式从因果归因降级为机器判定诊断。
- 建立多层、多标签输出。
- 修复 V1 已发现的负改进误落 IMPROVED 的基本反例。
- 删除 train_metric > 0。
- 引入 MetricObservation、capability profile、动作语义和分级反馈。
- 明确 validation 用于选优、test 不进入逐轮 Agent。
- 不再声称 RL、交叉验证、时序任务可直接复用普通 train/validation gap。

但二审仍不能批准，原因是 V2 的“文档声明”与“可执行伪代码”之间存在数条 P0 断裂：

1. PromotionJudge 尚未成为唯一 verdict 权威。
2. execution、metric status、artifact 完整性没有进入最终 verdict 的强制输入。
3. Cycle 1 通过配置把 HARD_TIMEOUT 改写为 BUDGET_REACHED，属于重写机器事实。
4. decision_bar 仍存在零值、非有限值、无 uncertainty 等未封闭边界。
5. MetricValidator 未完成文档承诺的完整 metric identity 和 best-checkpoint 校验。
6. test 隔离仍主要依靠检测和发布层约定，尚未形成不可绕过的权限与投影视图。
7. legacy decide_verdict 与新流水线并存，会形成第二条裁决路径。

这些问题可能导致错误 KEEP、掩盖 BLOCKED、使用无资格 baseline 或将 test 信息泄漏到自动优化闭环，因此必须继续整改。

---

## 2. V1 P0 整改闭环矩阵

| P0 项 | V2 状态 | 二审结论 | 说明 |
|---|---|---|---|
| 因果降级 | 基本完成 | CONDITIONALLY_CLOSED | 名称和 claim level 已调整；但 AttributionReportV2 仍沿用 Attribution，顶层与 finding 均有 causal_claim_level，可能冲突 |
| 分层多标签 | 已设计 | PARTIAL | findings 已多标签；outcome、constraints、verdict 的生成仍分散，最终裁决可被多处形成 |
| 阈值互斥分区 | 核心反例已修 | PARTIAL | decision_bar 为正且有限时互斥；bar=0、NaN、None、负阈值、无重复数据时尚未闭合 |
| 零值/负值处理 | 语义已修 | CONDITIONALLY_CLOSED | 删除 >0 正确；但 MetricObservation.value 仍为必填 float，与 MISSING/PARSE_ERROR 状态不一致 |
| BUDGET_REACHED/HARD_TIMEOUT | 名称已拆 | NOT_CLOSED | BUDGET_EXCEEDED 未进入 DTO/分类器；且允许配置把 HARD_TIMEOUT 重写成 BUDGET_REACHED |
| Cycle 1 baseline 资格 | 提出 policy | NOT_CLOSED | 只有建议，没有 Owner 决策记录；PROVISIONAL 的晋级规则与回归要求未定义 |
| metric identity | 字段已增加 | PARTIAL | Validator 未比较 metric_id、direction、unit、status、checkpoint selection、sample_count policy |
| PromotionJudge 唯一权威 | 文档声明 | NOT_CLOSED | promotion_judge 返回 outcome，final_verdict 在另一函数生成，旧 decide_verdict 仍并存 |
| test 隔离 | 原则和测试已写 | PARTIAL | 没有强类型 view schema、读取权限和独立 test 存储边界；泄漏检测顺序还会被 NO_BASELINE 遮蔽 |

**总体：9 项中没有发现方向性回退，但仍有 3 项未闭合、4 项部分闭合、2 项条件闭合。P0_FULLY_CLOSED=NO。**

---

## 3. 仍阻断二审的 P0 问题

### 3.1 P0-R1｜唯一 verdict 权威尚未实现

V2 架构图声明：

    PromotionJudge → KEEP / DISCARD / HUMAN_REVIEW

但第 4.4 节的 promotion_judge 实际返回：

    IMPROVED / REGRESSION / EQUIVALENT_OR_INCONCLUSIVE

这些是 outcome，不是 verdict。

第 4.5 节又通过独立 final_verdict 生成 KEEP/DISCARD；同时第 10 节提出旧 decide_verdict 保持兼容过渡。当前实际存在三种可能的裁决位置：

1. promotion_judge。
2. final_verdict。
3. legacy decide_verdict。

这与“唯一权威”直接冲突。

**必须整改：**

- 将第 4.4 节组件改名为 OutcomeComparator。
- 新建唯一 PromotionJudge，输入全部 gate 结果后只返回 FinalDecision。
- final_verdict 不得作为独立公共函数存在，或它本身就是 PromotionJudge 的唯一实现。
- legacy decide_verdict 只能成为调用新 PromotionJudge 的兼容 adapter，不能保留旧逻辑。
- ledger 只能接受 PromotionJudge 发出的 promotion_decided 事件。

建议唯一签名：

    PromotionJudge.decide(
        eligibility,
        execution,
        metric_validation,
        outcome_comparison,
        constraint_evaluation,
        artifact_integrity,
        baseline_status,
        policy_version
    ) -> FinalDecision

### 3.2 P0-R2｜CRASH、TIMEOUT、无效指标仍可能走到 KEEP

V2 的 final_verdict 只接收：

- eligibility。
- outcome。
- constraints。

它没有接收：

- execution。
- metric status。
- artifact manifest status。
- baseline eligibility。

因此存在理论路径：

1. execute_result 中残留一个可解析的旧 validation 指标。
2. 当前运行实际 HARD_TIMEOUT 或 CRASHED。
3. OutcomeComparator 算出 IMPROVED。
4. constraints 为空。
5. final_verdict 返回 KEEP。

即使实现者主观上不会这样写，设计合同也必须把该路径封死。

**必须整改：**

| 条件 | FinalDecision |
|---|---|
| contract/test/protected boundary 违规 | BLOCKED |
| execution 为 CRASHED/OOM_FATAL/HARD_TIMEOUT/CANCELLED/BUDGET_EXCEEDED | DISCARD 或 BLOCKED，绝不 KEEP |
| metric 非 PRESENT_VALID | DISCARD/INCOMPARABLE，绝不 KEEP |
| artifact manifest 未完整固化 | BLOCKED |
| baseline 不具资格 | BASELINE_REQUIRED/INCOMPARABLE |
| hard constraint 违反 | DISCARD_CONSTRAINT |
| 全部门禁通过且 outcome=IMPROVED | KEEP |

这张决策表必须成为 PromotionJudge 的合同测试。

### 3.3 P0-R3｜Cycle 1 不能被配置“改写事实”

V2 建议：

    hard_timeout_treated_as: BUDGET_REACHED

这是不可接受的语义。HARD_TIMEOUT 和 BUDGET_REACHED 是 runner 产生的机器事实，不能由 Study 配置把一种事实重命名为另一种事实。

正确处理：

- execution_fact 仍记录 HARD_TIMEOUT。
- metric_eligibility 可记录 PARTIAL_METRIC_AVAILABLE。
- Owner 可批准该指标作为 PROVISIONAL_BASELINE。
- Provisional 是 baseline 资格，不是 execution 事实。

推荐：

    execution = HARD_TIMEOUT
    metric_status = PRESENT_PARTIAL
    baseline_eligibility = PROVISIONAL_OWNER_APPROVED
    comparison_strength = CONDITIONAL

此外，当前“V2 默认建议”不是 Owner 裁决，不能在整改表中标记已闭合。需要单独 Owner Decision Record，明确：

1. Cycle 1 是否符合当时预算合同。
2. partial metric 是否允许建立 provisional baseline。
3. C2 相对 provisional baseline 的 KEEP 是否只是临时冠军。
4. 临时冠军何时必须在合法合同下重跑。
5. 重跑不通过时如何撤销 provisional lineage。

### 3.4 P0-R4｜BUDGET 状态仍未形成闭合枚举

V2 声称拆分：

- BUDGET_REACHED。
- HARD_TIMEOUT。
- BUDGET_EXCEEDED。
- CANCELLED。

但 OutcomeFactsV2 的 terminal_cause 注释和 ExecutionClassifier 均未处理 BUDGET_EXCEEDED；EARLY_STOP 也只存在注释，没有清晰的 execution/termination 双字段模型。

建议拆为：

    process_status:
      COMPLETED
      FAILED
      CANCELLED

    termination_reason:
      NATURAL_COMPLETION
      BUDGET_REACHED
      EARLY_STOP_PLATEAU
      EARLY_STOP_DIVERGENCE
      HARD_TIMEOUT
      BUDGET_EXCEEDED
      OOM_FATAL
      CRASH
      USER_CANCELLED

BUDGET_REACHED 可以是 COMPLETED；HARD_TIMEOUT/BUDGET_EXCEEDED 是 FAILED。不得把 termination reason 直接当完整 execution 状态。

### 3.5 P0-R5｜decision_bar 仍有退化反例

在以下前提下，V2 三分区是互斥的：

    decision_bar 为有限正数

但设计尚未强制该不变量。

反例一：

    min_practical_delta = 0
    delta_uncertainty = 0
    decision_bar = 0
    delta = 0

由于第一条使用 delta >= decision_bar，candidate 与 champion 完全相同会被判 IMPROVED，与性质测试“candidate==champion → EQUIVALENT”矛盾。

反例二：

    delta_uncertainty = None

计算会失败。

反例三：

    delta_uncertainty = NaN

max 的行为和后续比较可能产生不可预测结果或全部落入默认区间。

反例四：

    min_practical_delta 的单位与 metric unit 不一致

数值可算但语义错误。

**必须整改：**

- Contract Validator 强制 min_practical_delta > 0 且 finite。
- noise_multiplier >= 0 且 finite。
- delta_uncertainty >= 0 且 finite。
- 阈值携带 metric_id、unit 和 policy_version。
- uncertainty 不可用时，不允许自动 KEEP；进入 HUMAN_REVIEW、INCONCLUSIVE 或使用预先批准的 fallback。
- 明确边界等号语义并测试。

建议：

    if not valid_positive_bar:
        return POLICY_INVALID
    if delta >= +bar:
        IMPROVED
    elif delta <= -bar:
        REGRESSION
    else:
        EQUIVALENT_OR_INCONCLUSIVE

### 3.6 P0-R6｜重复运行与 delta uncertainty 没有可执行定义

OutcomeFactsV2 使用 observation 列表，但 signed_delta 仍接收单个 candidate observation 和 champion observation。以下问题未定义：

- 多 seeds 如何配对。
- champion 与 candidate seeds 不一致如何处理。
- cross-validation 如何按 fold 配对。
- delta_uncertainty 是标准差、标准误还是置信区间半宽。
- 缺少重复运行时使用什么 fallback。
- candidate_primary 如何从 observation 列表中选取。

必须增加 MetricAggregate 或 ComparisonSample：

    MetricComparison:
      metric_id
      candidate_estimate
      champion_estimate
      paired_deltas
      aggregation_method
      uncertainty_method
      uncertainty_value
      confidence_level
      sample_count
      comparable

PromotionJudge 只能消费已验证的 MetricComparison，不能直接从裸 observation 列表自行猜选。

### 3.7 P0-R7｜MetricValidator 尚未完成 metric identity

当前 Validator 只检查：

- value finite。
- evaluator hash。
- dataset fingerprint。
- split。
- aggregation。

尚未检查：

- obs.status。
- metric_id。
- direction。
- unit。
- candidate 与 champion 的同一 metric contract。
- checkpoint selection policy。
- best checkpoint 与 last checkpoint。
- sample_count 及样本权重政策。
- observation 是否过期。
- uncertainty 方法。

尤其是 best-vs-last 目前只存在于早停说明和测试清单中，没有进入可执行 Validator。

建议增加：

    CheckpointSelection:
      policy
      selected_checkpoint_id
      selection_metric_id
      selection_split
      selection_event_id

MetricValidator 必须验证 candidate observation 对应 selected checkpoint。best checkpoint 与最后 checkpoint 不同不是异常，但裁决必须使用合同指定的那个。

### 3.8 P0-R8｜test 隔离仍可被绕过或被遮蔽

当前 EligibilityGate 顺序：

1. contract invalid。
2. comparable。
3. champion_metric is None。
4. test leaked。

若同时没有 champion 且发生 test 泄漏，函数会先返回 INCOMPARABLE，test 泄漏的 BLOCKED 被遮蔽。

此外，OutcomeFactsV2 允许 candidate_metric_observations 包含任意 split，FeedbackPublisher 只用文字说明不发布 test，没有强类型 view contract。

必须整改：

1. test/protected-boundary/security violation 作为独立 IntegrityGate，优先于可比性。
2. 不允许用单一 return 丢失多个 gate finding。
3. TestMetricObservation 与 SelectionMetricObservation 使用独立存储或访问能力。
4. LeaderView、CodeAgentView、MemoryView 使用 allowlist schema，不是运行时随意过滤字典。
5. test 结果不进入 OutcomeComparator、diagnostics、advice、recent_experiments、dead_ends、insights、metrics_feedback。
6. test 泄漏终态为 BLOCKED/QUARANTINED，不得降级为 INCOMPARABLE。

---

## 4. 八阶段架构二审

### 4.1 架构优点

- 流水线方向清晰。
- facts 与诊断分离。
- diagnostics 明确不改 verdict。
- advice 不再冒充事实。
- publish 开始考虑不同消费者视图。
- capability profile 为跨领域扩展提供了正确入口。

### 4.2 当前职责断裂

| 断裂 | 影响 |
|---|---|
| PromotionJudge 名称与返回值不一致 | outcome 与 verdict 混淆 |
| Constraint evaluation 不在八阶段图中 | final verdict 在图外形成 |
| Execution/Metric 只产状态但不硬门禁 promotion | 失败运行可能继续裁决 |
| Artifact integrity 没有阶段 | 半成品结果可能进入 verdict |
| legacy decide_verdict 并存 | 双权威 |
| test isolation 只有 publish 和检测 | 上游组件仍可能消费 test |

### 4.3 推荐的目标流水线

可以保留八阶段，但应重构为：

| 阶段 | 组件 | 权威输出 |
|---|---|---|
| 1 | OutcomeFactsBuilder | 带字段血缘和质量的事实 |
| 2 | IntegrityAndEligibilityGate | BLOCKED/COMPARABLE/BASELINE_REQUIRED 及完整 findings |
| 3 | ExecutionAndMetricGate | 运行与指标是否具备裁决资格 |
| 4 | MetricComparator | outcome 与 uncertainty，不产生 verdict |
| 5 | ConstraintEvaluator | 硬/软约束结果 |
| 6 | PromotionJudge | 唯一 FinalDecision |
| 7 | DiagnosticEngine + AdvicePolicy | 多标签诊断与动作候选，不改 verdict |
| 8 | FeedbackPublisher | 强类型、分消费者视图 |

Artifact integrity 可放入阶段 2 或阶段 3，但必须在 PromotionJudge 前成为硬门禁。

如果坚持原八组件划分，则必须把 ConstraintEvaluator、artifact、execution、metric 全部作为 PromotionJudge 内部强制子门禁，并删除外部 final_verdict。

---

## 5. FinalDecision 合同建议

当前 verdict 字段注释只包含 KEEP/DISCARD/HUMAN_REVIEW，但 final_verdict 还会返回 INCOMPARABLE，schema 不一致。

建议：

    FinalDecision:
      decision:
        KEEP
        DISCARD
        HUMAN_REVIEW
        INCOMPARABLE
        BLOCKED
        BASELINE_ESTABLISHED
        PROVISIONAL_BASELINE_ESTABLISHED
      reason_codes
      champion_before_sha
      champion_after_sha
      promotion_allowed
      policy_version
      evidence_refs

硬规则：

- 只有 KEEP 的 promotion_allowed=true。
- BLOCKED、INCOMPARABLE、DISCARD 的 champion_after_sha 等于 champion_before_sha。
- BASELINE_ESTABLISHED 只在无 champion、合法完整运行和 baseline policy 通过时使用。
- PROVISIONAL_BASELINE_ESTABLISHED 必须引用 Owner Decision Record。

---

## 6. 无 champion 与 baseline 建立逻辑

当前 eligibility_gate 将无 champion 直接返回 INCOMPARABLE，但 V2 同时希望输出 NO_BASELINE 并建立 provisional baseline，语义冲突。

建议：

1. 无 champion 不是普通不可比错误，而是 BASELINE_REQUIRED。
2. 该实验仍需经过 execution、metric、artifact、constraint gate。
3. 全部合格后由 PromotionJudge 返回 BASELINE_ESTABLISHED。
4. 只有 legacy partial run 才走 PROVISIONAL_BASELINE policy。
5. 后续候选必须明确比较对象是正式还是 provisional baseline。

这可避免首轮永远因无 champion 被截断。

---

## 7. 数据模型与字段血缘二审

### 7.1 已取得的进步

- MetricObservation 有 metric identity 的基本字段。
- OutcomeFactsV2 引入合同 hash、代码 SHA、环境 cohort、manifest hash 和 policy versions。
- resource 与 error 开始结构化。

### 7.2 仍缺少字段来源矩阵

V2 声称 OutcomeFactsBuilder 联合多个来源，但没有逐字段说明权威来源、fallback 和冲突处理。

必须补充：

| 字段组 | 权威来源 | 禁止 fallback |
|---|---|---|
| champion/candidate SHA | Workspace/Promotion Manager | Agent 自述 |
| contract hash | Contract Registry | prompt 文本 |
| execution/terminal cause | Runner 结构化事件 | 日志关键字作为 HIGH 证据 |
| evaluator/data fingerprint | Evaluation Contract/Artifact Manifest | 文件名猜测 |
| metric observation | Evaluator 结构化输出 | 从自然语言摘要解析 |
| test access | Access Audit | Agent 自报 |
| policy version | Policy Registry | 默认最新版本追溯套用 |
| artifact integrity | Artifact Manager | 文件存在即视为完整 |

### 7.3 必须强类型化的字段

以下 list[dict] 或 dict 仍是架构盲区：

- budget_events。
- resource_events。
- early_stop_event。
- structured_errors。
- change_summary。
- capabilities。
- policy_versions。

这些字段参与 P0 裁决，应定义 schema/dataclass 和版本，不应以开放字典进入 PromotionJudge。

### 7.4 MetricObservation.value 类型冲突

value 定义为 float，但 status 又允许 MISSING、PARSE_ERROR。应选择：

- value: float | None，并以 status 约束；或
- 缺失时不创建 MetricObservation，另建 MetricCollectionStatus。

不得出现 status=MISSING 但 value 被伪造为 0 的兼容路径。

---

## 8. 落地性与迁移策略二审

### 8.1 阶段 0—4 是否现实

总体分阶段合理，但阶段 1 当前包含资格、运行、指标、统计裁决和 profile，范围偏大。建议在阶段 1 前增加迁移阶段：

| 子阶段 | 目的 |
|---|---|
| 1A Shadow | 新流水线只读历史和新实验，不写 verdict |
| 1B Replay | 对 Cycle 1—4 和历史 ledger 重放，与旧判定做差异报告 |
| 1C Single Writer | PromotionJudge 成为唯一写 verdict 的组件 |
| 1D Legacy Retirement | legacy decide_verdict 删除或只保留无逻辑 adapter |

### 8.2 对 _machine_judge 的侵入

“从内联判定改成流水线编排”方向可控，但必须满足：

- feature flag 只用于 shadow 与切换，不能永久保留双裁决。
- 新旧裁决同时运行时，只有旧或新一方有写权限。
- 每个阶段幂等；重试不重复写 ledger 或推进 champion。
- 发生新流水线异常时 fail closed，不回退到静默 KEEP。
- rollback 只切换唯一 writer，不合并两套结果。

### 8.3 当前兼容声明的风险

“V1 已存在 decide_verdict 保持兼容过渡”若不进一步限定，会成为长期第二权威。必须在设计中给出：

- adapter 签名。
- 无独立业务逻辑约束。
- 删除版本。
- CI 检查禁止 legacy 模块直接写 promotion_decided。

---

## 9. 跨领域二审

### 9.1 结论

V2 已停止用 domain 名称猜 detector，并明确 RL 不复用普通 train/validation gap。方向通过。

但 capability profile 尚是任意 dict，无法防止配置自相矛盾，例如：

    task_profile = reinforcement_learning
    comparable_train_validation_metric = true
    episodic_evaluation = false

### 9.2 必须增加 Profile Registry

每个 profile 定义：

- required facts。
- forbidden capability combinations。
- available detectors。
- aggregation and uncertainty method。
- minimum real replay suite。
- advice policy。

Contract Validator 必须验证 profile，而不是信任任意布尔值。

### 9.3 当前支持范围应明确

建议 V2.1 写明：

    IMPLEMENTED_PROFILE=NONE
    FIRST_IMPLEMENTATION_PROFILE=supervised_holdout
    DESIGNED_NOT_IMPLEMENTED=cross_validation,time_series,language_modeling,reinforcement_learning

当前表格是未来设计，不是已经支持。unsupervised 出现在 task_profile 枚举中，却没有最低事实和专项阶段，应标为 NOT_DESIGNED 或移出 V2 首期范围。

---

## 10. 多目标与硬约束残余风险

当前 constraints 为 list[str]，final_verdict 使用 any(hard)，但 hard 没有数据模型，且软约束路径返回 outcome 而不是 verdict。

必须改为：

    ConstraintResult:
      constraint_id
      metric_id
      observed_value
      threshold
      direction
      hardness
      status
      policy_version
      evidence_ref

规则：

- 任一 HARD violation：不得 KEEP。
- SOFT violation：按 policy 进入 HUMAN_REVIEW、tie-break 或 penalty。
- primary、secondary、hard constraints、tie breakers 的优先顺序版本化。
- 不建议 V1 就引入复杂 Pareto 自动晋级；首期采用词典序策略更可审计。

IMPROVED_WITH_CONSTRAINT_VIOLATION 若保留，应明确它是复合展示状态，不是 outcome 枚举中的另一条秘密 verdict 路径。

---

## 11. evidence_strength、Advice 与 Memory 残余风险

### 11.1 evidence_strength

HIGH/MEDIUM/LOW/UNAVAILABLE 可以用于 V1，但需规则表：

| 强度 | 最低条件 |
|---|---|
| HIGH | 结构化权威事件，字段完整，detector 条件满足 |
| MEDIUM | 多个一致机器信号，但缺少重复或标定 |
| LOW | 日志启发式、单次异常或数据不完整 |
| UNAVAILABLE | detector 不适用或证据不足 |

缺少证据永远不能提高强度。顶层 evidence_completeness 应由 findings 派生，不由调用方自由填写。

### 11.2 Advice 版本化

文件命名不等于治理完成，还需：

- YAML schema。
- policy hash。
- policy approver。
- action_code 到 allowed change scope 的映射。
- requires_new_study 的强制门禁。
- profile adapter 的方向测试。
- policy 变更的生效时间与不追溯规则。

### 11.3 Memory 分层

当前分层正确，但缺少：

- 写入权限。
- provenance。
- supersedes/invalidates。
- 过期策略。
- 当 detector policy 更新时如何处理旧 finding。
- provisional baseline 被撤销后如何失效关联 recipe/dead end。

建议每条 memory entry 保存：

    epistemic_level
    source_event_ids
    study_id
    policy_version
    validity_status
    superseded_by
    expires_at

---

## 12. 仍需整改项

### P0｜二审通过前必须完成

1. 将 OutcomeComparator 与 PromotionJudge 分离，删除外部第二 verdict 生成点。
2. PromotionJudge 强制消费 execution、metric status、artifact、constraints 和 baseline status。
3. 取消 hard_timeout_treated_as=BUDGET_REACHED；保留原始机器事实。
4. 提交 Cycle 1 Owner Decision Record，定义 provisional baseline 生命周期。
5. 补齐 BUDGET_EXCEEDED、EARLY_STOP 等状态模型。
6. 强制 decision_bar 为有限正数，定义 uncertainty 缺失 fallback 和边界等号。
7. 增加 MetricComparison，定义 seeds/folds 配对、aggregate 和 uncertainty。
8. 完整校验 metric_id、direction、unit、status、checkpoint selection、sample policy。
9. 建立 IntegrityGate 与强类型 test 隔离视图。
10. 删除或无逻辑化 legacy decide_verdict，保证 single writer。
11. 修复 FinalDecision 枚举与 INCOMPARABLE/BLOCKED/BASELINE 状态不一致。
12. 将 hard constraints 变成强类型输入，不允许 any(hard) 式未定义判断。

### P1｜实施计划批准前完成

1. 补充字段血缘矩阵和冲突优先级。
2. 将 P0 dict/list[dict] 改为版本化类型。
3. 建立 Profile Registry 与配置一致性校验。
4. 定义 evidence_strength 规则。
5. 定义 advice policy schema、批准与生效机制。
6. 定义 memory provenance、失效和 supersession。
7. 增加 shadow/replay/single-writer/retirement 迁移计划。

### P2｜跨领域扩展前完成

1. cross-validation 的 paired fold contract。
2. time-series 的窗口、cutoff 和泄漏门禁。
3. RL 的 episode distribution、environment fingerprint、IQM/bootstrap 和 cost constraints。
4. unsupervised profile 的范围裁决。

---

## 13. 通过二审的门禁条件

V2.1 满足以下条件后，可重新提交二审：

### 13.1 文档与合同门禁

1. P0-R1—R8 均有明确设计修订，不只列测试名称。
2. 唯一 PromotionJudge 的输入、输出、状态表和失败关闭规则完整。
3. FinalDecision schema 与所有返回值一致。
4. Cycle 1 有正式 Owner Decision Record，不重写 execution 事实。
5. MetricComparison、CheckpointSelection、ConstraintResult、Test/Agent Views 有强类型定义。
6. 所有 P0 字段有来源—权威—质量—fallback 矩阵。

### 13.2 逻辑门禁

必须在设计附录中逐条证明或以可执行测试说明：

- delta 为负永不 IMPROVED。
- bar=0/None/NaN/负值被 Contract Validator 拒绝。
- candidate==champion 为 EQUIVALENT。
- champion 不存在可建立 baseline，不被普通 INCOMPARABLE 截断。
- CRASH/OOM/HARD_TIMEOUT/BUDGET_EXCEEDED 永不 KEEP。
- metric invalid/missing/stale/incommensurate 永不 KEEP。
- artifact 不完整永不进入 PromotionJudge。
- HARD constraint violation 永不 KEEP。
- test 泄漏必为 BLOCKED/QUARANTINED，不能被其他状态遮蔽。
- best checkpoint selection 可被机器验证。

### 13.3 架构门禁

- 只有一个组件能写 promotion_decided。
- diagnostics、advice、publish 都无权修改 FinalDecision。
- legacy adapter 不包含业务判断。
- shadow 模式不写冠军或正式 verdict。
- 新旧切换有回滚和唯一 writer 保障。

### 13.4 范围门禁

- 首期只批准 supervised_holdout。
- cross_validation、time_series、RL、unsupervised 明确为 DESIGN_ONLY/NOT_IMPLEMENTED。
- Profile Registry 能拒绝矛盾 capability。

达到以上门禁后，二审可转为：

    SECOND_REVIEW=APPROVED
    DESIGN_GATE=PASS_FOR_IMPLEMENTATION
    IMPLEMENTATION_AUTHORIZED=SUBJECT_TO_SDD_GATE

---

## 14. 最终裁决

V2 已吸收 V1 评审的大部分架构思想，整改质量较高，适合作为 V2.1 的基础；但目前仍存在可能造成错误晋级的 P0 路径，不能批准直接实现。

最终结论：

    BLOCKED_FOR_REMEDIATION

下一步应优先整改：

1. 唯一 verdict 权威与完整硬门禁。
2. Cycle 1 事实语义和 provisional baseline。
3. decision_bar/MetricComparison 完整边界。
4. metric/checkpoint identity。
5. test 隔离和 legacy single-writer 迁移。

完成上述整改后再提交 V2.1 二审，不建议在现版本上直接进入编码。
