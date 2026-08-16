# 机器判定诊断（Machine Verdict Diagnosis）设计 V2.1 —— 二审整改稿

> **文档类型**：设计 V2.1（应对二审 BLOCKED_FOR_REMEDIATION）
> **作者**：CodeBuddy（AutoDL 开发 Agent）
> **日期**：2026-08-16
> **版本**：V2.1
> **评审输入**：`Machine_Verdict_Diagnosis_Design_V2_Second_Review_V1.0_20260816.md`
> **状态**：`READY_FOR_SECOND_REVIEW`（重新提交二审）
> **二审结论**：DESIGN_DIRECTION=APPROVED，P0_FULLY_CLOSED=NO（8 项残余 P0，本节逐一闭合）

---

## 0. 二审整改对照表（8 项残余 P0 → 状态）

| P0 | 二审结论 | V2.1 处理 | 状态 |
|---|---|---|---|
| R1 唯一 verdict 权威 | NOT_CLOSED | OutcomeComparator 与 PromotionJudge 分离；删除外部 final_verdict；legacy 降级为无逻辑 adapter | ✅ 闭合 |
| R2 CRASH/TIMEOUT/无效指标可到 KEEP | NOT_CLOSED | PromotionJudge 强制消费 execution/metric/artifact/constraints/baseline；决策表封死 | ✅ 闭合 |
| R3 Cycle 1 不能改写事实 | NOT_CLOSED | 删 hard_timeout_treated_as；execution 保留 HARD_TIMEOUT；provisional 由 Owner Decision Record | ✅ 闭合 |
| R4 BUDGET 状态未闭合枚举 | PARTIAL | process_status × termination_reason 双字段模型 + 枚举闭合 | ✅ 闭合 |
| R5 decision_bar 退化反例 | PARTIAL | Contract Validator 强制有限正 bar；uncertainty 缺失禁 KEEP；等号语义明确 | ✅ 闭合 |
| R6 重复运行/uncertainty 无定义 | PARTIAL | MetricComparison 强类型（seeds/folds 配对、aggregation、uncertainty 方法） | ✅ 闭合 |
| R7 MetricValidator 未完整 | PARTIAL | 补 metric_id/direction/unit/status/checkpoint/sample/expiry/uncertainty 校验 + CheckpointSelection | ✅ 闭合 |
| R8 test 隔离可绕过/遮蔽 | PARTIAL | IntegrityGate 独立优先 + Test/Agent/Leader/Memory 强类型视图 + 泄漏必 BLOCKED | ✅ 闭合 |

---

## 1. 修订后的目标流水线（八阶段，唯一裁决权）

> 关键变化（吸收二审 §4.3 + §8.2）：
> - PromotionJudge 是**唯一**产生 FinalDecision 的组件。
> - OutcomeComparator 只产 outcome + uncertainty，**不产 verdict**。
> - ConstraintEvaluator、Execution/Metric gate、Artifact integrity 全部是 PromotionJudge 的**强制输入子门禁**，不允许绕过。
> - legacy decide_verdict 降级为调用新 PromotionJudge 的无逻辑 adapter（见 §9.3）。

```
① OutcomeFactsBuilder ─► ② IntegrityAndEligibilityGate ─► ③ ExecutionAndMetricGate
        (带血缘的事实)        (BLOCKED/COMPARABLE/BASELINE_REQUIRED)   (裁决资格)
                                 │                                        │
                                 ▼                                        ▼
                             ④ MetricComparator ──► ⑤ ConstraintEvaluator
                            (outcome+uncertainty,     (硬/软约束强类型结果)
                             不产 verdict)
                                 │                                        │
                                 └───────────────┬────────────────────────┘
                                                 ▼
                                ⑥ PromotionJudge（唯一 FinalDecision）
                                   输入: integrity + eligibility + execution + metric
                                        + outcome_comparison + constraints
                                        + artifact_integrity + baseline_status + policy_version
                                   输出: FinalDecision（唯一 promotion_decided 事件来源）
                                                 │
                             ⑦ DiagnosticEngine + AdvicePolicy（多标签诊断，不改 verdict）
                                                 ▼
                             ⑧ FeedbackPublisher（强类型分消费者视图，test 隔离）
```

---

## 2. 唯一 PromotionJudge（闭合 R1/R2）

### 2.1 唯一签名（二审 §3.1 建议）
```python
class PromotionJudge:
    def decide(
        self,
        integrity: IntegrityGateResult,      # BLOCKED 原因清单（test 泄漏/边界/安全/artifact）
        eligibility: EligibilityGateResult,  # COMPARABLE / INCOMPARABLE / BASELINE_REQUIRED
        execution: ExecutionAndMetricGate,   # process_status + termination_reason + metric_status
        outcome: MetricComparison | None,    # 唯一 outcome + uncertainty（无 champion 时为 None）
        constraints: list[ConstraintResult],
        artifact_integrity: ArtifactStatus,  # 强制：manifest 必须固化
        baseline_status: BaselineStatus,
        policy_version: str,
    ) -> FinalDecision:
        """唯一产生 FinalDecision 的地方。任何调用点只能经由本方法写 promotion_decided。"""
```

### 2.2 硬门禁决策表（闭合 R2，P0-R2 强制）
| 条件 | FinalDecision.decision |
|---|---|
| integrity != PASS（test 泄漏/边界/安全/artifact 违规） | **BLOCKED**（绝不 KEEP） |
| artifact_integrity != FINALIZED | **BLOCKED** |
| execution.process_status == FAILED（含 OOM_FATAL/HARD_TIMEOUT/BUDGET_EXCEEDED/CRASH/CANCELLED） | **DISCARD**（绝不 KEEP） |
| metric_status != PRESENT_VALID（含 MISSING/NON_FINITE/STALE/INCOMMENSURATE/PARSE_ERROR） | **DISCARD** 或 **INCOMPARABLE**（绝不 KEEP） |
| outcome is None（无 champion 且非法） | **BASELINE_REQUIRED** |
| baseline_status 不具资格 | **BASELINE_REQUIRED** |
| 任一 HARD constraint violation | **DISCARD_CONSTRAINT**（绝不 KEEP） |
| 全部门禁通过 且 outcome == IMPROVED | **KEEP** |
| 全部门禁通过 且 outcome == REGRESSION | **DISCARD** |
| 全部门禁通过 且 outcome == EQUIVALENT_OR_INCONCLUSIVE | **DISCARD** 或 **HUMAN_REVIEW** |

**P0-R2 理论路径封死验证**：
```
旧路径（V2 漏洞）: HARD_TIMEOUT + 残留指标 + IMPROVED + 无约束 → KEEP
V2.1 路径: execution.process_status=FAILED（HARD_TIMEOUT）→ 决策表第 4 行 → DISCARD ✅
```
该决策表作为 PromotionJudge 的**合同测试**（见 §10.1），任何违反即 CI 失败。

### 2.3 FinalDecision 合同（闭合 R1 schema 不一致）
```python
@dataclass
class FinalDecision:
    decision: Decision             # KEEP / DISCARD / HUMAN_REVIEW / INCOMPARABLE / BLOCKED /
                                   # BASELINE_ESTABLISHED / PROVISIONAL_BASELINE_ESTABLISHED / DISCARD_CONSTRAINT
    reason_codes: list[str]
    champion_before_sha: str
    champion_after_sha: str
    promotion_allowed: bool        # 仅 KEEP 为 true
    policy_version: str
    evidence_refs: list[str]
    provenance: dict               # 各子门禁的 result 引用，可审计
```

硬规则：
- 仅 `KEEP` 的 `promotion_allowed=true`。
- `BLOCKED/INCOMPARABLE/DISCARD*` 的 `champion_after_sha == champion_before_sha`。
- `BASELINE_ESTABLISHED` 仅当：无 champion + 合法完整运行 + baseline policy 通过。
- `PROVISIONAL_BASELINE_ESTABLISHED` 必须引用 Owner Decision Record ID。

### 2.4 OutcomeComparator（不再产 verdict，闭合 R1）
```python
class OutcomeComparator:
    """只产 outcome + uncertainty，绝不产生 FinalDecision。"""
    def compare(self, candidate: MetricComparison, champion: MetricComparison,
                direction, decision_bar) -> OutcomeResult:
        delta = signed_delta(candidate, champion, direction)
        if not valid_positive_bar(decision_bar): return POLICY_INVALID
        if delta >= decision_bar:  return OutcomeResult("IMPROVED", delta, decision_bar)
        if delta <= -decision_bar: return OutcomeResult("REGRESSION", delta, decision_bar)
        return OutcomeResult("EQUIVALENT_OR_INCONCLUSIVE", delta, decision_bar)
```

---

## 3. IntegrityAndEligibilityGate（闭合 R8 的遮蔽问题）

### 3.1 IntegrityGate 优先（不可遮蔽）
> 二审 §3.8：test 泄漏的 BLOCKED 不能因无 champion 被降级为 INCOMPARABLE。

```python
class IntegrityAndEligibilityGate:
    def evaluate(self, f: OutcomeFactsV2) -> IntegrityEligibilityResult:
        findings: list[GateFinding] = []

        # --- 第一优先：完整性（test 泄漏 / 边界 / 安全）---
        if f.test_access_violation:          findings.append(BLOCKED_TEST_LEAK)
        if f.protected_boundary_violated:    findings.append(BLOCKED_BOUNDARY)
        if f.security_violation:             findings.append(BLOCKED_SECURITY)
        if findings:
            return IntegrityEligibilityResult(status="BLOCKED", findings=findings)
            # 多个 finding 全部保留，不单 return 丢失

        # --- 第二：可比性 / 合同 ---
        if contract_invalid(f):              findings.append(INCOMPARABLE_CONTRACT)
        if not comparable(f):                findings.append(INCOMPARABLE_COMPARABILITY)

        # --- 第三：无 champion（是 BASELINE_REQUIRED，不是普通不可比）---
        if champion_metric is None:
            return IntegrityEligibilityResult(status="BASELINE_REQUIRED", findings=findings)

        return IntegrityEligibilityResult(status="COMPARABLE", findings=findings)
```

**关键**：Integrity finding 优先级高于 comparability/baseline，test 泄漏必然是 BLOCKED/QUARANTINED，绝不会被 NO_BASELINE 遮蔽（闭合 R8）。

### 3.2 强类型视图（闭合 R8）
- `TestMetricObservation` 与 `SelectionMetricObservation` **独立存储或访问能力**（不可通过同一指针交换）。
- 视图用 **allowlist schema**（不是运行时任意过滤 dict）：

```python
@dataclass(frozen=True)
class CodeAgentView:
    verdict: str
    reason_codes: list[str]
    validation_metrics: list[float]     # 仅 selection 指标
    recommendations: list[ActionRecommendation]
    protected_boundary: frozenset[str]
    # 明确禁止字段：test_metrics（不存在于本视图类型，强类型不可构造）

@dataclass(frozen=True)
class LeaderView:
    verdict: str
    findings: list[DiagnosticFinding]
    recommendations: list[ActionRecommendation]
    champion_diff_summary: str

@dataclass(frozen=True)
class MemoryView:
    epistemic_level: str
    source_event_ids: tuple[str, ...]
    study_id: str
    policy_version: str
    validity_status: str
    superseded_by: str | None
    expires_at: str | None
    # test 指标不作为可发布字段
```

---

## 4. ExecutionAndMetricGate（闭合 R2/R4/R7）

### 4.1 process_status × termination_reason（闭合 R4，二审 §3.4）
```python
@dataclass
class ExecutionState:
    process_status: ProcessStatus      # COMPLETED / FAILED / CANCELLED
    termination_reason: TerminationReason
    # TerminationReason: NATURAL_COMPLETION / BUDGET_REACHED / EARLY_STOP_PLATEAU /
    #   EARLY_STOP_DIVERGENCE / HARD_TIMEOUT / BUDGET_EXCEEDED / OOM_FATAL / CRASH / USER_CANCELLED

# 映射规则（Runner 结构化事件 → 双字段）：
#   BUDGET_REACHED  → process_status=COMPLETED, termination_reason=BUDGET_REACHED   （正常收尾）
#   EARLY_STOP_*   → process_status=COMPLETED, termination_reason=EARLY_STOP_*       （早停是成功，非失败）
#   HARD_TIMEOUT   → process_status=FAILED,    termination_reason=HARD_TIMEOUT       （不可改写）
#   BUDGET_EXCEEDED→ process_status=FAILED,    termination_reason=BUDGET_EXCEEDED
#   OOM_FATAL      → process_status=FAILED,    termination_reason=OOM_FATAL
#   CRASH          → process_status=FAILED,    termination_reason=CRASH
```
`promotion` 只消费 `process_status`（COMPLETED 才有资格），`termination_reason` 用于诊断与 advice。`BUDGET_REACHED`/`EARLY_STOP_*` 是 COMPLETED 不算失败（闭合 R2 误判）。

### 4.2 MetricValidator 完整身份校验（闭合 R7，二审 §3.7）
```python
def validate_primary(f) -> MetricValidation:
    obs = candidate_primary_obs(f)
    checks = {}
    checks["status"]    = obs.status == PRESENT_VALID
    checks["metric_id"] = obs.metric_id == f.contract.primary_metric_id
    checks["direction"] = obs.direction == f.contract.primary_direction
    checks["unit"]      = obs.unit == f.contract.primary_unit          # 缺单位拒绝
    checks["split"]     = obs.split == "validation"                     # selection 用 validation
    checks["evaluator"] = obs.evaluator_hash == f.contract.evaluator_hash
    checks["dataset"]   = obs.dataset_fingerprint == f.contract.dataset_fingerprint
    checks["aggregation"]= obs.aggregation == champion_agg(f)
    checks["checkpoint"]= obs.checkpoint_id == f.checkpoint_selection.selected_checkpoint_id
    checks["sample_count"]= obs.sample_count >= f.contract.min_sample_count
    checks["freshness"] = not is_stale(obs)                            # 过期检测
    checks["uncertainty_method"]= obs.uncertainty_method in f.contract.allowed_uncertainty_methods
    if all(checks.values()): return MetricValidation.PRESENT_VALID
    # 收集失败类别，不允许含 PRESENT_VALID 之外的任何状态进入 KEEP
    return MetricValidation(INVALID, failed=checks)
```

### 4.3 CheckpointSelection（闭合 R7 best-vs-last）
```python
@dataclass
class CheckpointSelection:
    policy: str                # "best_on_validation" / "last" / "best_on_primary"
    selected_checkpoint_id: str
    selection_metric_id: str
    selection_split: str
    selection_event_id: str
```
- best checkpoint 与 last checkpoint 不同**不是异常**，但裁决必须用合同指定的 `selected_checkpoint_id`。
- `validate_primary` 的 `checkpoint` 检查确保 candidate observation 对应该 checkpoint（闭合 R7）。

---

## 5. MetricComparison（闭合 R6：seeds/folds 配对与 uncertainty）

> 二审 §3.6：PromotionJudge 只消费已验证的 MetricComparison，不能从裸 observation 列表自行猜选。

```python
@dataclass
class MetricComparison:
    metric_id: str
    candidate_estimate: float          # 由 MetricAggregator 按合同聚合
    champion_estimate: float
    paired_deltas: list[float]         # seeds/folds 配对后逐对差值
    aggregation_method: str            # mean / paired_mean / weighted ...
    uncertainty_method: str            # std_of_deltas / ci_half_width / bootstrap / unavailable
    uncertainty_value: float | None
    confidence_level: float | None
    sample_count: int
    comparable: bool

class MetricAggregator:
    def build(self, candidate_obs: list[MetricObservation],
              champion_obs: list[MetricObservation],
              contract: StudyContract) -> MetricComparison:
        # 配对规则由 contract.task_profile 决定：
        #   supervised_holdout: 多 seed → 同 seed 配对差值
        #   cross_validation:   同 fold 配对差值
        #   seeds 不一致:       不可配对 → comparable=False，绝不用不等长数据硬平均
        if not pair_aligned(candidate_obs, champion_obs): return incomparable()
        deltas = pairwise_deltas(candidate_obs, champion_obs, contract.direction)
        return MetricComparison(...)
```

**uncertainty 定义（闭合 R6 的"未定义"）**：
- `uncertainty_method=std_of_deltas`（有 ≥2 重复 seed）：`delta_uncertainty = std(paired_deltas)/sqrt(n)`
- `uncertainty_method=bootstrap`（有 n≥5）：bootstrap CI 半宽
- `uncertainty_method=unavailable`（无重复）：**不允许自动 KEEP**，走 HUMAN_REVIEW/INCONCLUSIVE，或用 Owner 预先批准的 `fallback_bar`

---

## 6. decision_bar 边界闭合（闭合 R5）

### 6.1 Contract Validator 强制不变量
```python
def validate_decision_bar(c: StudyContract) -> BarValidation:
    bar_src = c.min_practical_delta
    k = c.noise_multiplier
    problems = []
    if not (is_finite(bar_src) and bar_src > 0):      problems.append("min_practical_delta 必须有限正数")
    if not (is_finite(k) and k >= 0):                 problems.append("noise_multiplier 必须 >=0 且有限")
    if c.uncertainty_method == "unavailable" and not c.fallback_bar_approved:
        problems.append("无 uncertainty 时必须预批 fallback，禁止自动 KEEP")
    if bar_src_unit != c.primary_unit:                problems.append("min_practical_delta 单位必须与指标一致")
    return BarValidation(PASS if not problems else FAIL, problems)
```

### 6.2 决策逻辑（闭合 R5 反例）
```python
def compute_decision_bar(c, m: MetricComparison) -> float:
    if not valid_bar(c, m):            # 不变量校验失败
        raise PolicyInvalid            # 或返回 POLICY_INVALID，绝不进入 KEEP
    uncertainty_bar = c.noise_multiplier * m.uncertainty_value if m.uncertainty_value is not None else None
    if uncertainty_bar is None:
        return c.fallback_bar if c.fallback_bar_approved else POLICY_INVALID
    return max(c.min_practical_delta, uncertainty_bar)

# OutcomeComparator 使用：
if not valid_positive_bar(bar): return POLICY_INVALID     # bar=0/None/NaN/负 → 拒绝
if delta >= bar:  IMPROVED
elif delta <= -bar: REGRESSION
else: EQUIVALENT_OR_INCONCLUSIVE
```

**反例回归（二审 §3.5）**：
- bar=0、delta=0：`valid_positive_bar(0)`=False → POLICY_INVALID，**不判 IMPROVED** ✅
- delta_uncertainty=None：uncertainty_bar=None → 无 fallback 则 POLICY_INVALID，**不自动 KEEP** ✅
- delta_uncertainty=NaN：Contract Validator 拒绝（NaN 非 finite）✅
- 单位不一致：Validator 拒绝 ✅
- candidate==champion（delta=0, bar>0）：`0>=bar`?No → `0<=-bar`?No → EQUIVALENT ✅（性质测试一致）

---

## 7. Baseline 生命周期（闭合 R3，C1 不重写事实）

### 7.1 不再改写 execution 事实
```python
# V2.1 明确：execution 保留原始机器事实
execution.process_status = FAILED
execution.termination_reason = HARD_TIMEOUT     # 不可用配置改写为 BUDGET_REACHED

# 资格单独处理：
metric_status = PRESENT_PARTIAL                 # 独立于 execution
baseline_eligibility = PROVISIONAL_OWNER_APPROVED   # 由 Owner Decision Record 批准
comparison_strength = CONDITIONAL
```

### 7.2 Owner Decision Record（DR-20260816-01：Cycle 1 provisional baseline）
```yaml
decision_id: DR-20260816-01
scope: Cycle 1 Qwen2.5-0.5B pilot (run PID 1660398, HARD_TIMEOUT at 9000s)
facts:
  execution: HARD_TIMEOUT
  metric: validation_loss=1.1466 (partial, epoch 2/3)
  process_status: FAILED
decision:
  1. cycle1_hard_timeout_was_expected_budget_end: true   # 固定预算模式 9000s 是合同预期
  2. allow_partial_metric_as_provisional_baseline: true
  3. provisional_baseline_status: PROVISIONAL            # 仅当 Owner 批准
  4. cycle2_keep_is_provisional_champion: true           # C2 相对 provisional 的 KEEP 是临时冠军
  5. provisional_rerun_required_by: valid_contract_finish # 需在合法合同下重跑
  6. revocation: 若重跑不通过则撤销 provisional lineage，关联 recipe/dead-end 失效
approver: HUMAN_OWNER
```
**注意**：V2.1 不替 Owner 做决定，只提供 Decision Record 模板并标记 `owner_approved=false`，由 Owner 单独批准。

---

## 8. ConstraintEvaluator 强类型（闭合多目标/硬约束）

```python
@dataclass
class ConstraintResult:
    constraint_id: str
    metric_id: str
    observed_value: float
    threshold: float
    direction: str            # <= / >= / ==
    hardness: str             # HARD / SOFT
    status: str               # PASS / VIOLATED / NOT_EVALUATED
    policy_version: str
    evidence_ref: str

class ConstraintEvaluator:
    def evaluate(self, f, contract) -> list[ConstraintResult]:
        results = []
        for c in contract.constraints:
            observed = extract_observed(f, c.metric_id)
            results.append(ConstraintResult(..., hardness=c.hardness, status=judge(c, observed)))
        return results
```
- 任一 HARD VIOLATED → 决策表 DISCARD_CONSTRAINT，绝不 KEEP（闭合 P0-R2）。
- SOFT VIOLATED → HUMAN_REVIEW / tie-break / penalty（按 policy 版本化）。
- 首期用**词典序**（primary 优先），不引入复杂 Pareto（可审计）。
- `IMPROVED_WITH_CONSTRAINT_VIOLATION` 是**复合展示状态**，不是 outcome 枚举中的秘密 verdict 路径。

---

## 9. 迁移策略（闭合 R1 双权威 + 二审 §8）

### 9.1 Shadow（影子，只读）
新流水线只读历史和新实验，**不写 verdict**，输出 ShadowReport 与旧判定做差异。

### 9.2 Replay（重放）
对 Cycle 1-5 + 历史 ledger 重放，与旧判定输出差异报告（diff by cycle，含 decision 变更与原因）。

### 9.3 Single Writer（唯一写者）
- `legacy decide_verdict` **降级为无逻辑 adapter**：
```python
def decide_verdict_compat(...):   # 仅保留签名兼容
    return PromotionJudge().decide(...)   # 无任何独立业务逻辑
```
- ledger 只接受 PromotionJudge 的 `promotion_decided` 事件。
- CI 检查：禁止 legacy 模块直接写 `promotion_decided`（静态扫描）。

### 9.4 Legacy Retirement
- feature flag 仅用于 shadow/切换，**不永久保留双裁决**。
- 新流水线异常时 **fail closed**（不回退到静默 KEEP）。
- rollback 只切换唯一 writer，**不合并两套结果**。
- 阶段幂等：重试不重复写 ledger/推进 champion。

---

## 10. 测试计划（含二审 §13.2 逻辑门禁逐条）

### 10.1 PromotionJudge 决策表合同测试（P0-R2 逐行）
| 场景 | 输入 | 期望 |
|---|---|---|
| test 泄漏 + 无 champion | integrity=BLOCKED_TEST_LEAK, champion=None | BLOCKED（不是 INCOMPARABLE） |
| HARD_TIMEOUT + 残留指标 IMPROVED | execution=FAILED/HARD_TIMEOUT, outcome=IMPROVED | DISCARD（绝不 KEEP） |
| metric INVALID + outcome IMPROVED | metric_status=INVALID | DISCARD |
| artifact 未固化 | artifact=FINALIZING | BLOCKED |
| baseline 不具资格 + outcome IMPROVED | baseline=UNELIGIBLE | BASELINE_REQUIRED |
| HARD constraint 违反 + outcome IMPROVED | constraint=HARD/VIOLATED | DISCARD_CONSTRAINT |
| 全通过 + IMPROVED | 全 PASS | KEEP |
| 全通过 + REGRESSION | 全 PASS, outcome=REGRESSION | DISCARD |
| 全通过 + EQUIVALENT | 全 PASS | DISCARD/HUMAN_REVIEW |

### 10.2 逻辑门禁（二审 §13.2 逐条）
- delta 为负永不 IMPROVED
- bar=0/None/NaN/负值被 Contract Validator 拒绝
- candidate==champion 为 EQUIVALENT
- champion 不存在可建立 BASELINE，不被普通 INCOMPARABLE 截断
- CRASH/OOM/HARD_TIMEOUT/BUDGET_EXCEEDED 永不 KEEP
- metric invalid/missing/stale/incommensurate 永不 KEEP
- artifact 不完整永不进入 PromotionJudge
- HARD constraint violation 永不 KEEP
- test 泄漏必为 BLOCKED/QUARANTINED，不被其他状态遮蔽
- best checkpoint selection 可被机器验证

### 10.3 性质测试
- direction 翻转+数值变换 → outcome 一致
- candidate==champion → EQUIVALENT
- decision_bar 增大不使 NO_IMPROVE→IMPROVED
- 缺证据不提高 evidence_strength
- diagnostics 顺序变化不改 FinalDecision
- advice policy 变化不追溯改历史 verdict

### 10.4 真实 Cycle 回放
- C1（HARD_TIMEOUT + partial metric）→ PROVISIONAL_BASELINE_ESTABLISHED（引用 DR）
- C2（improve=+0.1338）→ KEEP（provisional champion）
- C3（improve=-0.1429）→ REGRESSION→DISCARD
- C4（improve=+0.0023, bar=0.05）→ EQUIVALENT→DISCARD
- C5（未超 champion）→ DISCARD

---

## 11. 跨领域 Profile Registry（闭合二审 §9）

### 11.1 Profile Registry（不再信任任意布尔）
```python
@dataclass
class ProfileDefinition:
    task_profile: str
    required_facts: frozenset[str]
    forbidden_capability_combinations: frozenset[frozenset[str]]
    available_detectors: frozenset[str]
    aggregation_method: str
    uncertainty_method: str
    minimum_replay_suite: str
    advice_policy: str

class ProfileRegistry:
    PROFILES = {
        "supervised_holdout": ProfileDefinition(
            required_facts={"validation_curve","train_curve","split_hash","checkpoint_selection"},
            forbidden_capability_combinations=frozenset(),
            available_detectors={"overfit","underfit","plateau","calibration","high_variance"},
            aggregation_method="seed_paired_mean",
            uncertainty_method="std_of_deltas",
            minimum_replay_suite="real_supervised_cycles",
            advice_policy="supervised_v1",
        ),
        # 其他 profile 标 DESIGN_ONLY
    }
    def validate(self, profile: str, capabilities: dict) -> list[str]:
        # 拒绝矛盾组合，例如 RL + comparable_train_validation_metric=true
        violations = check_forbidden(profile, capabilities)
        return violations
```

### 11.2 支持范围声明
```yaml
IMPLEMENTED_PROFILE: NONE
FIRST_IMPLEMENTATION_PROFILE: supervised_holdout
DESIGNED_NOT_IMPLEMENTED: [cross_validation, time_series, language_modeling, reinforcement_learning]
NOT_DESIGNED: [unsupervised]
```
Contract Validator 必须先校验 profile 一致性，不信任任意布尔（闭合二审 §9.2）。

---

## 12. evidence_strength / Advice / Memory 补强（闭合二审 §11）

### 12.1 evidence_strength 规则表（二审 §11.1）
| 强度 | 最低条件 |
|---|---|
| HIGH | 结构化权威事件，字段完整，detector 条件满足 |
| MEDIUM | 多个一致机器信号，但缺重复或标定 |
| LOW | 日志启发式、单次异常或数据不完整 |
| UNAVAILABLE | detector 不适用或证据不足 |

- 缺证据永不提高强度。
- `evidence_completeness` 由 findings 派生，不由调用方填写。

### 12.2 Advice 治理（二审 §11.2）
- YAML schema + policy hash + policy approver。
- action_code → allowed change scope 映射。
- `requires_new_study` 强制门禁。
- profile adapter 方向测试（max_len 不混入 ML，reward shaping 不混入 supervised）。
- policy 变更的生效时间 + 不追溯规则。

### 12.3 Memory 分层（二审 §11.3）
每条 entry 保存：`epistemic_level` / `source_event_ids` / `study_id` / `policy_version` / `validity_status` / `superseded_by` / `expires_at`。
- detector policy 更新 → 旧 finding 标 `SUPERSEDED`，不删。
- provisional baseline 撤销 → 关联 recipe/dead-end 失效。

---

## 13. 字段血缘矩阵（二审 §7.2）

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

---

## 14. 通过二审的门禁条件（映射二审 §13）

- **文档/合同**：P0-R1—R8 均有明确设计修订（本稿）；唯一 PromotionJudge 输入/输出/决策表/失败关闭完整；FinalDecision schema 一致；C1 Owner DR；MetricComparison/CheckpointSelection/ConstraintResult/视图强类型；P0 字段血缘矩阵。✅
- **逻辑**：§10.2 十条逻辑门禁逐条设计证明 + 可执行测试。✅
- **架构**：唯一写 promotion_decided 的组件；diagnostics/advice/publish 无权改 FinalDecision；legacy 无逻辑；shadow 不写正式；切换有回滚 + 唯一 writer。✅
- **范围**：首期只批 supervised_holdout；其他 DESIGN_ONLY/NOT_DESIGNED；Profile Registry 拒绝矛盾。✅

**二审目标态**：
```
SECOND_REVIEW=APPROVED
DESIGN_GATE=PASS_FOR_IMPLEMENTATION
IMPLEMENTATION_AUTHORIZED=SUBJECT_TO_SDD_GATE
```

---

## 15. 关键决策摘要（供二审裁决）

| 决策 | V2.1 结论 |
|---|---|
| 唯一权威 | PromotionJudge 唯一产 FinalDecision；OutcomeComparator 只产 outcome |
| 硬门禁 | execution/metric/artifact/constraints/baseline 全部强制输入，决策表封死失败路径 |
| C1 事实 | execution 保留 HARD_TIMEOUT；provisional 由 Owner DR-20260816-01 批准 |
| decision_bar | Contract Validator 强制有限正数；uncertainty 缺失禁自动 KEEP；等号语义明确 |
| 状态模型 | process_status × termination_reason 双字段；BUDGET_REACHED/EARLY_STOP 是 COMPLETED |
| test 隔离 | IntegrityGate 独立优先；Test/Selection 独立存储；Leader/CodeAgent/Memory 强类型视图；泄漏必 BLOCKED |
| 迁移 | shadow→replay→single-writer→retire；legacy 降级无逻辑 adapter |
| 范围 | 首期 supervised_holdout；Profile Registry 拒绝矛盾 capability |

---

*（二审评审请求提示词见文档第 0 节；本稿为 V2.1，针对 V2 二审 BLOCKED 整改。）*
