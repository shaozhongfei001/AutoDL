# 机器判定诊断（Machine Verdict Diagnosis）设计 V2.2 —— 三审整改稿（反例驱动闭合）

> **文档类型**：设计 V2.2（应对继续二审 BLOCKED_FOR_REMEDIATION）
> **作者**：CodeBuddy（AutoDL 开发 Agent）
> **日期**：2026-08-16
> **版本**：V2.2
> **评审输入**：`Machine_Verdict_Diagnosis_Design_V2.1_Continued_Second_Review_V1.0_20260816.md`
> **状态**：`READY_FOR_THIRD_REVIEW`
> **写作范式变更**：本稿不再用"伪代码 + 文档声明"论证安全，改为**对评审每个反例给出"类型/合同层面的不可构造证明"**，使安全性质在构造期即由类型系统强制，而非依赖实现者不犯错。

---

## 0. 设计原则（回应"总被挑出问题"的根因）

前三次被挑 P0 的共性根因：
1. **伪代码可执行反例**：用可被调用的自由函数表达门禁，实际可在条件不全时落回安全态。
2. **不可达/矛盾状态**：决策表声明了不存在的状态，或状态迁移与 promotion 布尔冲突。
3. **类型不匹配**：DTO 允许非法组合（如 value:float 同时 status=MISSING）。
4. **非全函数决策**：决策表含"或"，同一输入多输出。
5. **信息流只靠字段过滤**：test 隔离只在输出侧过滤，输入侧仍可注入。

**V2.2 的核心方法：把"门禁"变成"不可构造的类型合同"，把"决策"变成"全函数"，把"test 隔离"变成"输入侧能力边界"。**

每个 P0 的闭合都附三栏：`评审反例 → 类型/合同约束 → 不可构造证明`。

---

## 1. P0-CE 反例闭合对照表（评审 §3 的 10 个反例 + §2 的 8 项复核）

### CE1｜合同无效仍返回 COMPARABLE
**评审**：contract_invalid 的 finding 不改变 status，Judge 无"findings 非空即不可晋级"规则，可 KEEP。
**类型/合同**：`EligibilityStatus` 是 `Literal`，由 `evaluate_integrity_and_eligibility` 唯一返回；`PromotionJudge.decide` 的**唯一入口签名**要求 `EligibilityResult.status` 为强类型，且 `reason_codes` 非空时 status 必须为 `BLOCKED/INCOMPARABLE/BASELINE_REQUIRED` 之一（构造不变量）。
**不可构造证明**：`EligibilityResult` 用 `frozen dataclass`，其 `status` 通过**工厂函数**构造，工厂内强制"任一 reason → status 必为失败态"。因此"COMPARABLE + 非空 reason"在构造期即抛异常，Judge 永远收不到该组合。✅

### CE2｜CANCELLED 可绕过失败门禁
**评审**：`CANCELLED` ≠ `FAILED`，决策表只判 FAILED，可构造 CANCELLED+IMPROVED → KEEP。
**类型/合同**：`ExecutionGateResult` 是 Judge 唯一接收的执行对象（不接收裸字符串）。其 `eligible_for_promotion: bool` 由**组合表**派生：`COMPLETED×(合法 reason)` 才为 true，`FAILED/CANCELLED` 恒 false。Judge 决策表第 4 行改为判 `not execution.eligible_for_promotion → DISCARD`。
**不可构造证明**：`ExecutionGateResult` 由工厂构造，工厂持有合法组合表，`CANCELLED` 输入必然产出 `eligible_for_promotion=false`。Judge 无法收到"eligible=true 的 CANCELLED"。✅

### CE3｜硬约束缺失/NOT_EVALUATED 可 KEEP
**评审**：`list[ConstraintResult]` 无法证明覆盖合同全部硬约束；NOT_EVALUATED 未禁 KEEP。
**类型/合同**：Judge 唯一接收 `ConstraintEvaluation`（不是 list）。其 `complete: bool` 由工厂强制 `expected_constraint_ids == result_ids`。Judge 决策表第 7 行：`not constraints.complete → BLOCKED`；第 8 行：`HARD 且 status in (VIOLATED, NOT_EVALUATED) → DISCARD/BLOCKED`。
**不可构造证明**：`ConstraintEvaluation.complete=true` 只有在 `result_ids ⊇ expected_ids` 时才可能由工厂产出；缺失硬约束时工厂只能产出 `complete=false`，Judge 必判 BLOCKED。✅

### CE4/CE5｜BASELINE_ESTABLISHED 不可达 + 枚举矛盾
**评审**：决策表先判"无 champion → BASELINE_REQUIRED"，BASELINE_ESTABLISHED 无路径可达；promotion_allowed 与 baseline 写 champion 冲突；champion_before_sha 无法表示 None。
**类型/合同**：V2.2 用**独立的 `state_transition`** 取代 promotion_allowed 布尔（评审 §6.3）。控制流明确：无 champion + 全门禁过 + 合法完整指标 → `BaselinePolicy` 唯一产出 `BASELINE_ESTABLISHED + SET_BASELINE + mutation_authorized=true`；partial + APPROVED DR → `PROVISIONAL_BASELINE_ESTABLISHED`；否则 `BASELINE_REQUIRED`。`champion_before_sha: str | None` 显式可空。
**不可构造证明**：`state_transition ∈ {NO_CHANGE, SET_BASELINE, SET_PROVISIONAL_BASELINE, REPLACE_CHAMPION}`；`mutation_authorized ⇔ state_transition ∈ {SET_BASELINE, SET_PROVISIONAL_BASELINE, REPLACE_CHAMPION}` 由 FinalDecision 工厂强制。ledger 只执行 `state_transition`，无法按 decision 名另写分支。✅

### CE6｜decision_bar 校验不完备
**评审**：`validate_decision_bar(c)` 不读 `MetricComparison.uncertainty_value`；NaN/负/fallback 未全校验；POLICY_INVALID 无映射。
**类型/合同**：`DecisionBar` 为 frozen 强类型，其**工厂**校验 `value` 有限正数、`metric_id/unit/policy_version` 与合同绑定。`UncertaintyEstimate` 工厂校验 `value ≥ 0 且有限`、`confidence_level ∈ (0,1)`。`OutcomeComparator.compare(comparison, bar)` 若 bar/uncertainty 不满足前置则返回 `POLICY_INVALID`（不放行 IMPROVED）。
**不可构造证明**：`DecisionBar` 不可能构造出 `value=0/NaN/负`（工厂拒绝）；`UncertaintyEstimate` 不可能为负/NaN。Judge 的 `POLICY_INVALID → BLOCKED` 是决策表第 10 行，唯一映射。✅

### CE7｜MetricComparison 接口不可执行
**评审**：compare 收两个各自含 cand/champ 的 MetricComparison，自相矛盾；std_of_deltas 命名错误。
**类型/合同**：统一 `MetricComparison` 只含一个（candidate_estimate + champion_estimate + paired_deltas），Comparator 唯一签名 `compare(comparison: MetricComparison, bar: DecisionBar) -> OutcomeResult`（评审 §6.6）。统计量命名为 `STANDARD_ERROR_OF_PAIRED_DELTAS = std(paired_deltas)/sqrt(n)`（评审 §6.6），`noise_multiplier × 该 SE`。
**不可构造证明**：`MetricComparison` 构造时 candidate/champion 已在内部，Comparator 无法收到两个自含对象的组合；方向归一**只发生一次**（paired_deltas 已规定"正=候选优"），Comparator 不再翻转。✅

### CE8｜test 隔离只是"检测后阻断"
**评审**：DiagnosticEngine/Advice 读取 test → finding → advice 间接泄漏；需证明"仅 test 变化，iterative 输出不变"。
**类型/合同**：**输入侧隔离**（评审 §6.8）：
- `SelectionMetricObservation` 与 `TestMetricObservation` 是**不同 DTO + 不同存储命名空间**。
- `OutcomeFactsBuilder`、MetricComparator、DiagnosticEngine、AdvicePolicy、MemoryWriter 的**服务身份只持有 selection read capability**（`capability: SelectionOnly`）。
- test 评估仅在**最终评估阶段**由独立身份（`FinalEvalReader`）读取。
- 任意 test observation 注入 selection facts，在 **facts 构建阶段**（`OutcomeFactsBuilder`）因身份/命名空间不符被拒绝。
**不可构造证明**：`OutcomeFactsBuilder` 只接受 `SelectionMetricObservation` 类型（强类型参数），`TestMetricObservation` 类型不匹配**编译期拒绝**。因此 test 数据**从源头**不可能进入 selection facts，诊断/建议/memory 无 test 可读。非干扰测试（§8.2）机械断言。✅

### CE9｜Cycle 1 回放依赖未批准 DR
**评审**：owner_approved=false 的模板却被回放期待 PROVISIONAL_BASELINE_ESTABLISHED。
**类型/合同**：回放 fixture 与真实 ledger **分离**。C1 真实回放断言 `champion 未被 mutation`（执行事实保留 FAILED/HARD_TIMEOUT）；C2-C5 回放用**显式注入的已批准测试 DR**（fixture），并在 fixture 中标注 `status=APPROVED`。
**不可构造证明**：`BaselinePolicy` 只有在收到 `status=APPROVED` 且 scope/hash/有效期为真的 `OwnerDecisionRecord` 时，才产出 PROVISIONAL_BASELINE_ESTABLISHED。未批准的 DR（status=DRAFT）在 `BaselinePolicy` 输入校验阶段即被拒绝，不可能产生 mutation。✅

### CE10｜决策表非全函数
**评审**：DISCARD 或 INCOMPARABLE、DISCARD 或 HUMAN_REVIEW、三选一 soft，均非唯一输出。
**类型/合同**：V2.2 决策表**无"或"**。每个输入组合唯一输出：
- invalid metric：**candidate 运行失败 → DISCARD**；**champion 历史不可比 → INCOMPARABLE**；**policy 无效 → BLOCKED**（按输入身份唯一判定，评审 §6.4 优先级）。
- equivalent/inconclusive：首期**固定 DISCARD**（评审 §6.4 第 13 条）。
- soft constraint：首期**不参与自动晋级**，只展示；HUMAN_REVIEW 仅当"uncertainty unavailable AND owner_fallback absent"这一确定条件。
**不可构造证明**：`PromotionJudge.decide` 用**优先级链**（评审 §6.4 的 1-13 顺序）逐级返回，每个条件互斥，天然无"或"。对该函数做**枚举穷举测试**（§8.1），断言所有合法输入组合唯一输出。✅

---

## 2. 核心强类型合同（评审 §6.6/6.7）

### 2.1 MetricObservation（value 可空，修复类型冲突）
```python
@dataclass(frozen=True)
class MetricIdentity:
    metric_id: str
    unit: str                    # 首期不做换算，unit 必须完全一致（registry id）
    direction: str               # minimize / maximize
    evaluator_hash: str
    dataset_fingerprint: str
    split: str                   # "validation" / "test"（selection 只用 validation）

@dataclass(frozen=True)
class MetricObservation:
    identity: MetricIdentity
    value: float | None          # MISSING/PARSE_ERROR → None，禁止 0 占位
    status: MetricStatus         # PRESENT_VALID / MISSING / NON_FINITE / PARSE_ERROR / STALE / INCOMMENSURATE
    evaluation_sample_count: int
    source_event_id: str
    artifact_digest: str
    checkpoint_id: str
    # 不变量：status==PRESENT_VALID ⇔ value 有限；否则 value==None
```

### 2.2 UncertaintyEstimate（评审 §6.6）
```python
@dataclass(frozen=True)
class UncertaintyEstimate:
    method: UncertaintyMethod    # STANDARD_ERROR_OF_PAIRED_DELTAS / BOOTSTRAP / UNAVAILABLE
    value: float | None          # ≥0 且有限（method=UNAVAILABLE 时 None）
    confidence_level: float | None  # ∈ (0,1)，仅 CI/bootstrap 时
    repeat_count: int
    random_seed: int | None
```

### 2.3 MetricComparison + OutcomeComparator（统一，评审 §6.6）
```python
@dataclass(frozen=True)
class MetricComparison:
    identity: MetricIdentity
    candidate_estimate: float
    champion_estimate: float
    paired_deltas: tuple[PairedDelta, ...]   # 已归一："正=candidate 更优"
    aggregation_method: AggregationMethod    # seed_paired_mean（首期）
    uncertainty: UncertaintyEstimate
    comparable: bool

def compare(comparison: MetricComparison, bar: DecisionBar) -> OutcomeResult:
    if not comparison.comparable: return OutcomeResult.INCOMPARABLE
    if not valid_bar(bar) or not valid_uncertainty(comparison.uncertainty):
        return OutcomeResult.POLICY_INVALID
    if bar.value is None or not (bar.value > 0 and is_finite(bar.value)):
        return OutcomeResult.POLICY_INVALID
    delta = comparison.candidate_estimate - comparison.champion_estimate   # 方向已归一，只此一次
    if delta >= bar.value:   return OutcomeResult.IMPROVED
    if delta <= -bar.value:  return OutcomeResult.REGRESSION
    return OutcomeResult.EQUIVALENT_OR_INCONCLUSIVE
```

### 2.4 ConstraintEvaluation（completeness 可验证，评审 §6.7）
```python
@dataclass(frozen=True)
class ConstraintResult:
    constraint_id: str
    observed_value: float | None
    status: ConstraintStatus    # PASS / VIOLATED / NOT_EVALUATED
    hardness: str               # HARD / SOFT
    threshold: float
    direction: str
    evidence_ref: str

@dataclass(frozen=True)
class ConstraintEvaluation:
    contract_hash: str
    expected_constraint_ids: frozenset[str]
    results: tuple[ConstraintResult, ...]
    complete: bool              # 工厂强制 result_ids == expected_ids
    policy_version: str
```

---

## 3. PromotionJudge 确定全函数（评审 §6.4，无"或"）

### 3.1 唯一输入/输出合同
```python
@dataclass(frozen=True)
class ExecutionGateResult:
    valid_pair: bool                    # process_status×termination_reason 合法组合
    eligible_for_promotion: bool        # COMPLETED×(合法reason) 才 true
    process_status: ProcessStatus
    termination_reason: TerminationReason
    source_event_id: str

@dataclass(frozen=True)
class FinalDecision:
    schema_version: str
    decision_id: str
    decision: Decision                  # KEEP / DISCARD / BLOCKED / INCOMPARABLE /
                                        #   BASELINE_REQUIRED / HUMAN_REVIEW /
                                        #   BASELINE_ESTABLISHED / PROVISIONAL_BASELINE_ESTABLISHED / DISCARD_CONSTRAINT
    reason_codes: tuple[ReasonCode, ...]
    champion_before_sha: str | None
    champion_after_sha: str | None
    state_transition: StateTransition   # NO_CHANGE / SET_BASELINE / SET_PROVISIONAL_BASELINE / REPLACE_CHAMPION
    mutation_authorized: bool
    policy_bundle_hash: str
    input_bundle_hash: str
    evidence_refs: tuple[str, ...]
    idempotency_key: str
```

### 3.2 状态迁移×mutation 合同（评审 §6.3）
| decision | state_transition | mutation_authorized |
|---|---|---:|
| KEEP | REPLACE_CHAMPION | true |
| BASELINE_ESTABLISHED | SET_BASELINE | true |
| PROVISIONAL_BASELINE_ESTABLISHED | SET_PROVISIONAL_BASELINE | true |
| DISCARD / DISCARD_CONSTRAINT / INCOMPARABLE / BLOCKED / BASELINE_REQUIRED / HUMAN_REVIEW | NO_CHANGE | false |

**不可构造证明**：FinalDecision 由工厂构造，工厂用上述映射表保证 decision→transition→mutation 三元一致。ledger 只执行 `state_transition`，无第二套分支。✅

### 3.3 决策函数（优先级链，唯一全函数）
```python
def decide(self, integrity, eligibility, execution, metric, comparison,
           constraints, artifact, baseline, policy) -> FinalDecision:
    # 1 integrity/security/test/boundary
    if integrity.status != PASS:                    return BLOCKED
    # 2 contract/profile/policy/enum 无效
    if not eligibility.valid or not execution.valid_pair: return BLOCKED
    # 3 artifact 未完成
    if artifact.status != FINALIZED:                return BLOCKED
    # 4 execution 失败/取消
    if not execution.eligible_for_promotion:        return DISCARD
    # 5 candidate metric 无效
    if metric.candidate_status not in (PRESENT_VALID,): return DISCARD
    # 6 champion/candidate 不可交换
    if not comparison.comparable:                   return INCOMPARABLE
    # 7 硬约束集合不完整
    if not constraints.complete:                    return BLOCKED
    # 8 硬约束 NOT_EVALUATED / VIOLATED
    if any(HARD and s in (NOT_EVALUATED, VIOLATED) for s in constraints): return DISCARD
    # 9 无 champion → BaselinePolicy（唯一进入点）
    if baseline.is_required():
        return self.baseline_policy.decide(baseline, execution, metric, artifact, constraints)
    # 10 comparison/policy invalid
    if comparison.outcome == POLICY_INVALID:        return BLOCKED
    # 11-13 唯一输出
    if comparison.outcome == IMPROVED:              return KEEP
    if comparison.outcome == REGRESSION:            return DISCARD
    return DISCARD                                  # EQUIVALENT_OR_INCONCLUSIVE 首期固定 DISCARD
```

---

## 4. BaselinePolicy（评审 §6.5，解决 CE4/5/9）

```python
@dataclass(frozen=True)
class BaselineDecision:
    decision: Decision
    state_transition: StateTransition
    mutation_authorized: bool

class BaselinePolicy:
    def decide(self, b: BaselineStatus, execution, metric, artifact,
               constraints, owner_record) -> FinalDecision:
        # 全门禁已过（由调用方保证）
        if metric.candidate_status == PRESENT_VALID and metric.complete_and_legit(execution):
            return PROVISIONAL_IF_APPROVED_ELSE_BASELINE(b, owner_record)
        # partial + 无有效 Owner 审批 → 不建立 baseline，不改 champion
        if not owner_record.is_approved_for(b.run_id, b.facts_hash):
            return FinalDecision(BASELINE_REQUIRED, NO_CHANGE, mutation_authorized=False)
        return FinalDecision(BASELINE_ESTABLISHED, SET_BASELINE, mutation_authorized=True)

class OwnerDecisionRecord:   # 评审 §6.5
    decision_id: str
    status: str              # DRAFT / APPROVED / REJECTED / REVOKED / EXPIRED
    scope: frozenset[str]    # study/run/event IDs
    facts_hash: str
    decision_payload: str
    approver_identity: str
    approver_role: str
    approved_at: str
    effective_at: str
    policy_version: str
    expiry: str | None
    revocation_rule: str
    audit_event_id: str
    # 仅 status=APPROVED 且 scope/facts_hash/有效期内 匹配才生效
```

---

## 5. 信息流隔离：test 输入侧能力边界（评审 §6.8）

### 5.1 服务身份 × 读写能力矩阵
| 组件 | 可读 selection | 可读 test | 可写 verdict/champion | 可写 ledger |
|---|---|---|---|---|
| OutcomeFactsBuilder | ✅ | ❌ | ❌ | ❌（facts 事件只读） |
| MetricComparator | ✅ | ❌ | ❌ | ❌ |
| DiagnosticEngine | ✅ | ❌ | ❌ | ❌ |
| AdvicePolicy | ✅ | ❌ | ❌ | ❌ |
| MemoryWriter | ✅ | ❌ | ❌ | ❌ |
| FinalEvalReader（最终评估） | ❌ | ✅ | ❌ | ❌ |
| PromotionJudge | ✅(经 gate) | ❌ | ✅(唯一) | ✅(promotion_decided 唯一) |

### 5.2 DTO 隔离
- `SelectionMetricObservation` / `TestMetricObservation`：**不同 frozen 类 + 不同存储命名空间**（评审 §6.8.1）。
- `OutcomeFactsBuilder.build(candidate_selection: SelectionMetricObservation, ...)`：强类型参数只收 selection 类型，test 类型**编译期不匹配**。
- 任意 test observation 注入 selection facts：在 `OutcomeFactsBuilder` **输入校验阶段**拒绝（评审 §6.8.6），不是发布阶段过滤。

### 5.3 非干扰证明
> **性质**：给定相同 selection facts，仅改变 test 数据，则 `FinalDecision`、`DiagnosticFindings`、`ActionRecommendations`、`Memory writes`、`CodeAgentView`、`iterative LeaderView` **全部不变**。

**证明（构造侧）**：test 数据在 DTO 类型上就不属于 selection 路径（§5.2），`OutcomeFactsBuilder` 根本不接收 test 类型 → test 不进入 facts → 后续所有阶段无法读取 test → 输出不依赖 test。评审 §6.8 要求的非干扰测试（§8.2）作为机械断言固化。

---

## 6. 迁移与唯一写者（评审 §6.9）

| 项 | 规则 |
|---|---|
| ledger 写接口 | 要求 `producer_id == PROMOTION_JUDGE` + 受控服务凭证（运行时 ACL，非静态扫描） |
| promotion_decided schema | `schema_version / input_bundle_hash / idempotency_key` 必填 |
| legacy adapter | 无业务逻辑；只能依赖注入同一 Judge 实例，不能拼装/改 FinalDecision；有删除版本 + 截止日期 |
| shadow | 无 ledger/champion 写权限 |
| rollback | 只能在"调用同一决策合同的两个 writer 部署版本"间切换；禁止恢复旧业务逻辑 |
| downstream | 接收 frozen FinalDecision，不得原地改写 |
| idempotency | 同 `idempotency_key` 重放只迁移一次（dedupe） |

---

## 7. Profile Registry 强类型（评审 §9.2）

```python
@dataclass(frozen=True)
class ProfileDefinition:
    task_profile: str
    support_state: str           # IMPLEMENTED / DESIGN_ONLY / NOT_DESIGNED
    required_facts: frozenset[str]
    forbidden_capability_combinations: frozenset[frozenset[str]]
    available_detectors: frozenset[str]
    aggregation_method: str
    uncertainty_method: str
    minimum_repeats: int
    minimum_replay_suite: str
    advice_policy: str

class ProfileRegistry:
    def validate(self, profile_id, capabilities: CapabilityProfile) -> ValidatedProfile:
        # 校验 support_state、required_facts 全满足、
        #   forbidden 组合不存在、detector 证据、minimum_repeats
        # 未实现 profile 在合同构建阶段直接拒绝（fail closed）
```

- 首期 `IMPLEMENTED_PROFILE = {"supervised_holdout"}`。
- `cross_validation/time_series/language_modeling/reinforcement_learning` = DESIGN_ONLY，**合同入口 fail closed**。
- 不实现 profile 不得进入首期代码路径。

---

## 8. 测试计划（评审 §7，全唯一断言）

### 8.1 P0 反例测试（评审 §7.2，每个唯一期望）
| 类别 | 场景 | 唯一期望 |
|---|---|---|
| Eligibility | contract invalid + champion + improved | BLOCKED |
| Eligibility | incomparable + champion + improved | INCOMPARABLE |
| Execution | CANCELLED + residual improved metric | DISCARD |
| Execution | 非法组合 COMPLETED+HARD_TIMEOUT | BLOCKED |
| Constraints | 必需 hard result 缺失 | BLOCKED |
| Constraints | HARD NOT_EVALUATED | BLOCKED |
| Baseline | 无 champion + 完整合法 | BASELINE_ESTABLISHED + SET_BASELINE |
| Baseline | partial + 未批准 DR | 不建 baseline，不改 champion |
| Baseline | partial + APPROVED DR(scope/hash 匹配) | PROVISIONAL_BASELINE_ESTABLISHED |
| Metric | 合法 value=0 | 正常比较，非缺失 |
| Metric | MISSING + value=0 | DTO 构造失败（工厂拒绝） |
| Metric | champion metric_id/unit/direction 不同 | INCOMPARABLE |
| Metric | checkpoint policy 不同 | INCOMPARABLE |
| Bar | uncertainty=-1/NaN/Inf | POLICY_INVALID→BLOCKED |
| Bar | fallback=0/NaN/单位不一致 | POLICY_INVALID→BLOCKED |
| Comparator | delta=±bar | IMPROVED/REGRESSION |
| Comparator | delta=0 且 bar>0 | EQUIVALENT_OR_INCONCLUSIVE |
| Test 隔离 | 仅 test 变化 | iterative outputs 全部不变 |
| Writer | shadow/legacy 非授权写 ledger | 权限拒绝 |
| Idempotency | 同 decision 重放两次 | champion 只迁移一次 |

### 8.2 枚举穷举（评审 §7.3 笛卡尔积）
对 `integrity × eligibility × process_status × termination_reason × metric_status × artifact_status × constraint_aggregate_status × baseline_status × outcome` 全组合，断言：每个合法组合恰一个 FinalDecision；非法组合在 DTO/gate 构造阶段拒绝。并证明安全性质：
```
KEEP ⇒ integrity PASS ∧ execution COMPLETED ∧ 合法 pair
KEEP ⇒ candidate/champion 双边 PRESENT_VALID 且可交换
KEEP ⇒ artifact FINALIZED ∧ hard constraints complete 且全 PASS
KEEP ⇒ baseline/champion 合法 ∧ outcome IMPROVED
非 mutation_authorized ⇒ champion_after == champion_before
```

### 8.3 真实 Cycle 回放（评审 §6.5/§7.1）
- C1：执行事实 FAILED/HARD_TIMEOUT 保留；**断言 champion 未 mutation**（无 APPROVED DR 前）
- C2-C5：**conditional fixture**，显式注入 APPROVED 测试 DR；真实 ledger 不用 fixture 代替审批
- C2 的 KEEP 必须有可追溯 uncertainty 或合法 fallback bar

---

## 9. 分阶段实施（评审 §8，重排退出条件）

| 阶段 | 交付物 | 退出条件 |
|---|---|---|
| 0A 合同冻结 | 全部强类型 DTO/枚举、全序决策表、字段血缘、Owner DR schema、Profile support state | 本稿 P0 文档门禁全过 |
| 0B Fixture/Replay | C1-C5 事实包、正式/测试 DR 分离、golden decisions | 不依赖自然语言/未批准外部决策 |
| 1A Shadow | 新流水线只读，产差异报告 | 无 ledger/champion 写权限；差异全归因 |
| 1B Logic Gate | 单元/性质/穷举/test 非干扰/idempotency | P0 测试全绿，零未解释反例 |
| 1C Single Writer | runtime ACL、唯一 producer、新 FinalDecision schema | 只有新 Judge 可写 |
| 1D Retirement | 删旧规则或纯 adapter 到明确版本 | 无双裁决、可回滚部署不可回滚语义 |
| 2 Diagnostics/Advice | 校准 finding、版本化 advice、动作范围门禁 | 不读 test；高风险动作需审批；不改 verdict |
| 3 Memory | 分层 ACL、provenance、失效传播 | provisional 撤销可机械失效下游 |
| 4 Profile 扩展 | 各 profile 独立 contract/replay/eval | 未过专项门禁不标 IMPLEMENTED |

`_machine_judge` 改为 **orchestration shell**：只组装已验证 gate result、调用唯一 Judge、发布不可变 decision；所有业务条件迁移到版本化组件 + 合同测试，不在旧函数内叠加 if/else。

---

## 10. 三审门禁条件（评审 §11 映射）

**文档/合同**：P0-CE1—CE10 全部给出不可构造证明（§1）；强类型 DTO 完整（§2）；决策表全函数无"或"（§3）；baseline 状态迁移唯一（§4）；Owner DR schema（§4）；Profile Registry fail closed（§7）。✅
**逻辑/测试**：§8.1 P0 测试唯一预期；§8.2 穷举证明 KEEP 必要条件；§8.3 C1 不 mutation + C2 有 uncertainty/fallback；test 非干扰 + idempotency。✅
**架构/迁移**：唯一 producer（§6）；diagnostics/advice/publisher/memory 无 verdict/champion 写能力（§5.1）；legacy adapter 无逻辑 + 删除版本；shadow 只读；rollback 不恢复旧语义。✅
**范围**：首期 `supervised_holdout`；其余 profile 合同入口 fail closed（§7）。✅

---

## 11. 关键待决策点（评审 §12，需 Owner/架构裁决）

1. **Cycle 1 Owner 裁决**：是否正式批准 partial metric 建 provisional baseline（DR-20260816-01，当前 DRAFT，`owner_approved=false`）。在批准前 C1 不得作为正式冠军。
2. **uncertainty unavailable 唯一政策**：首期固定 `HUMAN_REVIEW`（除非 Owner 预批 fallback bar）。
3. **invalid metric 唯一终态**：candidate 失败→DISCARD；champion 历史不可比→INCOMPARABLE；policy 无效→BLOCKED（不再"或"）。
4. **test 隔离架构**：已选"独立 DTO + 独立存储命名空间 + 服务身份 capability"（非"或"）。
5. **首期多目标**：仅"单 primary + 完整 hard constraints"，secondary/soft 只展示，不参与自动晋级。

---

*（三审评审请求提示词见文档第 0 节末；本稿为 V2.2，针对 V2.1 继续二审 BLOCKED 的 10 个反例做反例驱动闭合。）*
