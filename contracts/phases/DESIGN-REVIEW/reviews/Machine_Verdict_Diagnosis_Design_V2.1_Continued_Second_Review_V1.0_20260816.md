# AutoDL 机器判定诊断设计 V2.1 继续二审报告

**报告版本：** V1.0  
**评审对象：** `Machine_Verdict_Diagnosis_Design_V2.1_20260816.md`  
**输入文件 SHA-256：** `3b6dead52277903cfbc52b9d57d11ceea2036edf7c4bb356dca5740a842309f5`  
**对照基准：** `Machine_Verdict_Diagnosis_Design_V2_Second_Review_V1.0_20260816.md`  
**评审角色：** AutoDL 高级架构评审专家  
**评审日期：** 2026-08-16  

---

## 1. 继续二审结论

```text
CONTINUED_SECOND_REVIEW=BLOCKED_FOR_REMEDIATION
DESIGN_DIRECTION=APPROVED
P0_FULLY_CLOSED=NO
IMPLEMENTATION_AUTHORIZED=NO
PRODUCTION_READY=NO
NEXT_REVIEW_TARGET=V2.2
```

V2.1 不是表面整改。相较 V2，它已经完成以下重要修正：

- 将 `OutcomeComparator` 与 `PromotionJudge` 分离，明确后者是唯一 `FinalDecision` 生成者。
- 把 execution、metric、artifact、constraint、baseline 纳入裁决输入。
- 不再把 `HARD_TIMEOUT` 配置重命名为 `BUDGET_REACHED`。
- 引入 `process_status × termination_reason`、`MetricComparison`、`CheckpointSelection`、`ConstraintResult`。
- 增加 shadow → replay → single writer → legacy retirement 迁移路线。
- 将首期支持范围收缩到 `supervised_holdout`，其余 profile 明确为未实现。
- 将 test 泄漏检查提升到可比性与 baseline 之前，并开始定义分消费者视图。

这些修订使总体架构方向达到可继续演进的水平，但尚未达到实现授权门槛。当前文本仍存在可执行反例、不可达状态、数据类型冲突和未形成访问边界的 test 隔离。若按 V2.1 直接编码，仍可能发生错误 `KEEP`、错误 baseline 建立、失败运行晋级或 test 派生信息进入自动优化闭环。

因此，本次不能给出 `APPROVED`。

---

## 2. P0 闭环复核矩阵

### 2.1 上一轮 8 项残余 P0

| 项目 | V2.1 复核状态 | 结论依据 |
|---|---|---|
| R1 唯一 verdict 权威 | **CONDITIONALLY_CLOSED** | 拓扑上已删除独立 `final_verdict`，legacy 被定义为无逻辑 adapter；但 `FinalDecision`、baseline 状态迁移及 ledger 写权限仍不一致，唯一写者主要靠声明与静态扫描，尚缺运行时授权。 |
| R2 execution/metric/artifact 强制门禁 | **NOT_CLOSED** | `CANCELLED` 不满足 `process_status == FAILED`，可越过失败门禁；硬约束 `NOT_EVALUATED` 或缺失也未禁止 `KEEP`；eligibility 和 `POLICY_INVALID` 没有完备映射。 |
| R3 Cycle 1 不改写事实及 provisional baseline | **NOT_CLOSED** | execution 事实不再改写，这一半已通过；但 `DR-20260816-01` 明确仍是 `owner_approved=false` 的模板，回放却直接期待 `PROVISIONAL_BASELINE_ESTABLISHED`，正式 Owner 决策尚未发生。 |
| R4 budget/timeout 双字段状态 | **PARTIAL** | 双字段方向正确，`BUDGET_EXCEEDED` 已补齐；但缺合法组合校验，`CANCELLED` 与 `FAILED` 的门禁不一致，`USER_CANCELLED` 映射也未进入完整表。 |
| R5 decision_bar 退化边界 | **PARTIAL** | `min_practical_delta > 0` 已规定；但没有实际校验 `uncertainty_value` 非负且有限，也没有完整校验 `fallback_bar` 的值、单位、metric identity 和 policy version，`POLICY_INVALID` 未映射到最终决策。 |
| R6 重复运行与 uncertainty | **PARTIAL** | 已定义配对思路；但 `OutcomeComparator` 的签名要求两个 `MetricComparison`，而 `MetricComparison` 本身已同时包含 candidate/champion，合同自相矛盾；`std_of_deltas` 与实际标准误公式也不一致。 |
| R7 metric identity 与 checkpoint | **PARTIAL** | candidate 侧校验明显增强；但 champion 侧没有完整执行同一套 identity、freshness、checkpoint、sample policy 校验，继承的 `MetricObservation.value: float` 与 `status=MISSING/PARSE_ERROR` 冲突仍在。 |
| R8 test 隔离 | **PARTIAL** | 泄漏遮蔽顺序已修、发布视图已有 allowlist；但输入事实仍继承通用 `MetricObservation.split`，独立存储与访问能力只写成“或”，未给出不可绕过的读取权限，无法证明 test 派生 advice/memory 不泄漏。 |

**统计：0 项无条件闭合，1 项条件闭合，5 项部分闭合，2 项未闭合。**

### 2.2 其他原始 P0 复核

| 原始 P0 | 状态 | 复核意见 |
|---|---|---|
| 因果降级 | **CLOSED** | 诊断不再宣称自动因果归因，`causal_claim_level` 的方向成立。 |
| 分层多标签 | **CONDITIONALLY_CLOSED** | findings 与 verdict 已分层，diagnostics/advice 不改 verdict；仍需把 `FinalDecision` 设为不可变对象并以运行时写权限防止发布后改写。 |
| 零值/缺失处理 | **PARTIAL** | 比较逻辑不再用 `> 0` 判断存在性；但继承 DTO 仍要求 `value: float`，同时允许 `MISSING/PARSE_ERROR`，实现仍可能用伪造的 `0` 兼容缺失。 |

---

## 3. 仍然成立的 P0 反例

以下反例均由 V2.1 当前伪代码直接构造，不依赖实现者“写错代码”。

### 3.1 P0-CE1｜合同无效仍可返回 COMPARABLE

V2.1 §3.1 中：

```python
if contract_invalid(f): findings.append(INCOMPARABLE_CONTRACT)
if not comparable(f):   findings.append(INCOMPARABLE_COMPARABILITY)
...
return IntegrityEligibilityResult(status="COMPARABLE", findings=findings)
```

当 champion 存在时，即使 `contract_invalid(f)=True` 或 `comparable(f)=False`，函数仍落到最后一行返回 `COMPARABLE`。这些 findings 没有改变 status，PromotionJudge 又没有决策表规则规定“findings 非空即不可晋级”，因此可以继续产生 `KEEP`。

**结论：** eligibility gate 当前不是安全门禁，只是附带警告的记录器。

### 3.2 P0-CE2｜CANCELLED 可绕过失败门禁

模型定义：

```text
process_status = COMPLETED / FAILED / CANCELLED
```

但 §2.2 的硬门禁只判断：

```python
execution.process_status == FAILED
```

表格注释虽把 `CANCELLED` 写进 FAILED 的括号中，但数据模型把两者定义成互斥枚举值。于是可以构造：

```text
process_status=CANCELLED
metric_status=PRESENT_VALID
outcome=IMPROVED
constraints=PASS
artifact=FINALIZED
```

该组合不会命中 FAILED 行，最终可能落入 `KEEP`。

### 3.3 P0-CE3｜硬约束未评估或丢失仍可 KEEP

`ConstraintResult.status` 允许 `NOT_EVALUATED`，但 PromotionJudge 仅阻止 `HARD + VIOLATED`。此外输入只是 `list[ConstraintResult]`，没有证明列表覆盖合同中的全部硬约束。

可构造：

```text
contract.required_hard_constraints=[safety, vram]
constraint_results=[safety: PASS]       # vram 结果丢失
outcome=IMPROVED
其他门禁=PASS
```

或：

```text
vram: HARD + NOT_EVALUATED
```

两种情况都可能 `KEEP`。对硬约束而言，缺失证据必须 fail closed。

### 3.4 P0-CE4｜正式 baseline 建立路径不可达

§2.2 的顺序先规定：

```text
outcome is None（无 champion） → BASELINE_REQUIRED
```

而 §2.3 又声明存在 `BASELINE_ESTABLISHED` 和 `PROVISIONAL_BASELINE_ESTABLISHED`。当前决策表没有任何一行产生这两个决策。

所以在“无 champion + 合法完整运行 + 有效指标 + artifact 完整 + 约束通过”的正常首轮场景下，仍只能命中 `BASELINE_REQUIRED`，不能建立 baseline。两个 `*_BASELINE_ESTABLISHED` 是不可达状态。

### 3.5 P0-CE5｜FinalDecision 枚举与状态迁移矛盾

当前 `Decision` 注释中没有 `BASELINE_REQUIRED`，但决策表会返回它；同时规定“仅 `KEEP` 的 `promotion_allowed=true`”，而 `BASELINE_ESTABLISHED` 必须把 candidate 设为首个 champion。

这产生两种不安全实现选择：

1. 严格遵守 `promotion_allowed=false`，baseline 决策无法更新 champion；
2. 在 ledger 或 Promotion Manager 中为 baseline 增加隐藏特例，形成 PromotionJudge 之外的第二套状态迁移逻辑。

此外，首轮无 champion 时 `champion_before_sha: str` 也无法合法表示 `None`。

### 3.6 P0-CE6｜decision_bar 校验仍不完备

§6.1 的 `validate_decision_bar(c)` 只验证合同字段，没有验证 `MetricComparison.uncertainty_value`。文档声称 NaN 会被 Contract Validator 拒绝，但该函数没有读取 `m`。

当前仍缺：

- `uncertainty_value >= 0 and finite`；
- `confidence_level` 的合法区间和方法对应关系；
- `fallback_bar > 0 and finite`；
- fallback 的 `metric_id/unit/policy_version` 绑定；
- `signed_delta` 为 finite；
- `POLICY_INVALID` 到 `FinalDecision` 的确定映射。

因此“退化值绝不自动晋级”尚未由合同闭合。

### 3.7 P0-CE7｜MetricComparison 接口不可执行

§2.4 定义：

```python
compare(candidate: MetricComparison, champion: MetricComparison, ...)
```

但 §5 的 `MetricComparison` 已同时包含：

```text
candidate_estimate
champion_estimate
paired_deltas
```

`MetricAggregator.build` 也只返回一个 `MetricComparison`。实现者无法判断 comparator 应接收一个比较对象，还是两个各自又包含双方的比较对象。该冲突会直接造成重复聚合、方向处理两次或取错 observation。

另外，`std_of_deltas` 文本实际使用 `std(paired_deltas)/sqrt(n)`，这应命名为 paired-delta standard error，而不是 standard deviation。统计量名称错误会使 `noise_multiplier` 失去稳定语义。

### 3.8 P0-CE8｜test 隔离仍是“检测后阻断”，不是“能力上不可读取”

V2.1 规定 `TestMetricObservation` 与 `SelectionMetricObservation` “独立存储或访问能力”，但没有选定一种架构，也没有定义两种 DTO。继承的 `OutcomeFactsV2.candidate_metric_observations` 仍可包含任意 `split`。

即使 `CodeAgentView` 不含 `test_metrics` 字段，也无法阻止以下派生泄漏：

1. DiagnosticEngine 读取 test 后生成 finding；
2. AdvicePolicy 根据该 finding 生成推荐；
3. 推荐进入 CodeAgentView 或 MemoryView；
4. 原始 test 数值虽未发布，test 信息已通过动作和诊断间接泄漏。

必须证明“仅改变 test 数据，在 selection 事实不变时，verdict、diagnostics、advice、memory 和 CodeAgentView 全部不变”，否则不能视为隔离闭环。

### 3.9 P0-CE9｜Cycle 1 回放使用了尚未生效的 Owner 决策

§7.2 明确说明模板 `owner_approved=false`，但 §10.4 又直接期望：

```text
C1 → PROVISIONAL_BASELINE_ESTABLISHED
C2 → KEEP（provisional champion）
```

测试预期不能依赖未获批准的外部决策。当前 record 既在 `decision` 中写入 `true`，又声明 Owner 尚未批准，状态自相矛盾。

在正式审批前，C1 的正确回放预期只能是“保留 `FAILED/HARD_TIMEOUT` 事实，provisional 建立待 Owner 决策”，不能宣称已经建立临时冠军。

### 3.10 P0-CE10｜决策表不是确定的全函数

以下表项包含斜杠选项：

- invalid metric → `DISCARD` **或** `INCOMPARABLE`；
- equivalent/inconclusive → `DISCARD` **或** `HUMAN_REVIEW`；
- soft constraint → `HUMAN_REVIEW / tie-break / penalty`。

同一输入可产生多个合法输出，测试也无法给出唯一断言。唯一 PromotionJudge 只有在其决策函数对所有合法输入组合都给出唯一结果时才真正成立。

---

## 4. 八阶段架构复核

### 4.1 总体判断

八阶段拓扑已经清晰，职责方向基本正确；没有再次出现 DiagnosticEngine 或 AdvicePolicy 显式改写 verdict 的路径。问题集中在各阶段的**合同边界不够强**，使“唯一裁决”仍可能消费不可信、矛盾或不完整的 gate result。

| 阶段 | 当前优点 | 残余问题 | 评审状态 |
|---|---|---|---|
| 1 Facts | 开始强调权威来源与 manifest | 仍继承开放 `dict/list[dict]`；selection/test 未物理或能力隔离；缺逐字段质量与冲突规则 | PARTIAL |
| 2 Integrity/Eligibility | test 泄漏优先级已修 | contract/comparability findings 不改变 status；artifact 职责在此阶段和 Judge 输入间重复 | BLOCKING |
| 3 Execution/Metric | execution 与 termination 已拆 | 缺枚举组合不变量；`CANCELLED` 门禁遗漏；candidate/champion 未对称验证 | BLOCKING |
| 4 MetricComparator | 不再产生 verdict | 输入签名与 DTO 冲突；统计量命名及 fallback 语义未闭合 | BLOCKING |
| 5 ConstraintEvaluator | 硬/软约束已结构化 | 缺 completeness aggregate；`NOT_EVALUATED` 和缺失硬约束可放行 | BLOCKING |
| 6 PromotionJudge | 唯一决策组件的方向正确 | 决策表非全函数，baseline 不可达，状态迁移合同矛盾 | BLOCKING |
| 7 Diagnostic/Advice | 明确不修改 FinalDecision | 尚不能证明不读取 test；evidence 与动作治理只有规则摘要 | PARTIAL |
| 8 Publisher | allowlist 视图方向正确 | 只隔离字段，不能隔离由 test 派生的 finding/advice；LeaderView 边界不明确 | PARTIAL |

### 4.2 verdict 改写路径判断

- **显式第二 verdict 函数：** V2.1 已消除，方向通过。
- **ledger 写入权：** 文档声称只接受 `promotion_decided`，但没有 producer identity、运行时 ACL、schema version 和 idempotency key；静态扫描不能替代运行时权限。
- **baseline 隐藏改写：** 因 `promotion_allowed` 与 baseline 建立矛盾，实际实现很可能把首冠写入逻辑放到 Promotion Manager 或 ledger 特例中，重新形成 Judge 外状态改写。
- **回滚：** “rollback 只切换唯一 writer”是正确原则，但需明确旧 writer 是否也是调用同一 Judge 的 adapter；禁止切回已退休的旧判定逻辑。

因此：**唯一裁决拓扑条件通过，唯一状态迁移权尚未通过。**

---

## 5. 判定逻辑专项复核

### 5.1 decision_bar 互斥性

当且仅当以下前置条件全部满足时，三分区本身是互斥且完备的：

```text
signed_delta ∈ finite real
decision_bar ∈ finite real and decision_bar > 0
metric_id/unit/direction/policy_version 一致
uncertainty 输入已验证且方法受合同支持
```

在这些前提下：

```text
delta >= +bar                 → IMPROVED
delta <= -bar                 → REGRESSION
-bar < delta < +bar           → EQUIVALENT_OR_INCONCLUSIVE
```

V2.1 已写对分区公式，但未把全部前置条件做成不可构造的强类型，因此只能评为 **formula correct / contract incomplete**。

### 5.2 无 champion

无 champion 不应直接调用 OutcomeComparator。正确控制流是：

```text
integrity → contract/profile → execution → artifact → candidate metric → constraints
  └─ 任一失败：按失败类型结束
  └─ 全部通过且无 champion：进入 BaselinePolicy
       ├─ 完整合格指标：BASELINE_ESTABLISHED
       ├─ partial + 有效 Owner Approval：PROVISIONAL_BASELINE_ESTABLISHED
       └─ 否则：BASELINE_REQUIRED / HUMAN_REVIEW（由政策唯一确定）
```

不能先因 `outcome is None` 返回 `BASELINE_REQUIRED`，再期待后续行建立 baseline。

### 5.3 零值、负值与不可交换指标

- 合法的 metric 值可以是 `0` 或负数，存在性只能由 observation/status 表达。
- `MISSING/PARSE_ERROR` 应使用 `value=None`，或根本不构造 observation，禁止以 `0` 占位。
- `INCOMMENSURATE` 必须由 candidate 与 champion 双边 identity 比较得出，不能只验证 candidate 对合同的匹配。
- unit 只是字符串相同仍不够；若支持比例、百分点等换算，必须使用明确 conversion policy。首期建议不做自动换算，字符串及 unit registry ID 必须完全一致。

### 5.4 best-vs-last checkpoint

V2.1 已正确指出 best 与 last 不同不是异常，也增加 `selected_checkpoint_id` 校验。但仍需补齐：

- champion 与 candidate 都必须使用同一 `CheckpointSelectionPolicy`；
- `selection_event_id` 必须在 artifact manifest 中可追溯；
- policy 为 `best_on_validation` 时，选择过程不得读取 test；
- evaluator observation 必须绑定 artifact digest，而不只绑定 checkpoint 名称；
- 对 early stop 恢复出的 best checkpoint，要验证恢复后的权重 hash 与评估输入一致。

---

## 6. V2.2 必须采用的详细整改方案

### 6.1 修复 Gate 状态传播

禁止以“status=COMPARABLE + 非空错误 findings”表达不可比。建议：

```python
@dataclass(frozen=True)
class EligibilityResult:
    status: EligibilityStatus  # COMPARABLE / INCOMPARABLE / BASELINE_REQUIRED / BLOCKED
    reason_codes: tuple[EligibilityReason, ...]
    contract_hash: str
    evidence_refs: tuple[str, ...]

def evaluate_integrity_and_eligibility(f) -> EligibilityResult:
    integrity_reasons = collect_integrity_violations(f)
    if integrity_reasons:
        return blocked(integrity_reasons)
    if contract_invalid(f):
        return blocked(POLICY_OR_CONTRACT_INVALID)
    if not comparable(f):
        return incomparable(comparability_reasons(f))
    if champion_absent(f):
        return baseline_required(NO_CHAMPION)
    return comparable()
```

所有错误 finding 必须在 status 中有决定性表达；禁止被下游当作普通 warning 忽略。

### 6.2 定义 execution/termination 合法组合表

| process_status | 合法 termination_reason | promotion eligibility |
|---|---|---|
| COMPLETED | NATURAL_COMPLETION、BUDGET_REACHED、EARLY_STOP_PLATEAU、EARLY_STOP_DIVERGENCE | 继续检查其他门禁 |
| FAILED | HARD_TIMEOUT、BUDGET_EXCEEDED、OOM_FATAL、CRASH | 不可 KEEP |
| CANCELLED | USER_CANCELLED、SYSTEM_CANCELLED | 不可 KEEP |

任何非法组合，例如 `COMPLETED + HARD_TIMEOUT`、`FAILED + BUDGET_REACHED`，应返回 `BLOCKED/POLICY_INVALID`，不能只按 `process_status` 放行。PromotionJudge 应消费已验证的：

```python
ExecutionGateResult(valid_pair, eligible_for_promotion, process_status,
                    termination_reason, source_event_id)
```

而不是直接相信可任意构造的两个字符串。

### 6.3 把 FinalDecision 改为确定、不可变、可迁移的状态合同

建议最小合同：

```python
@dataclass(frozen=True)
class FinalDecision:
    schema_version: str
    decision_id: str
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]
    champion_before_sha: str | None
    champion_after_sha: str | None
    state_transition: StateTransition
    # NO_CHANGE / SET_BASELINE / SET_PROVISIONAL_BASELINE / REPLACE_CHAMPION
    mutation_authorized: bool
    policy_bundle_hash: str
    input_bundle_hash: str
    evidence_refs: tuple[str, ...]
    idempotency_key: str
```

不应继续用“仅 KEEP 的 `promotion_allowed=true`”覆盖 baseline。应明确：

| decision | state_transition | mutation_authorized |
|---|---|---:|
| KEEP | REPLACE_CHAMPION | true |
| BASELINE_ESTABLISHED | SET_BASELINE | true |
| PROVISIONAL_BASELINE_ESTABLISHED | SET_PROVISIONAL_BASELINE | true |
| 其他 | NO_CHANGE | false |

ledger 必须只执行 `FinalDecision.state_transition`，不得按 decision 名称再写一套分支。

### 6.4 将 PromotionJudge 写成有优先级的确定全函数

推荐决策优先级：

1. integrity/security/test/boundary violation → `BLOCKED`；
2. contract/profile/policy/枚举组合无效 → `BLOCKED`；
3. artifact 未完成或 manifest 不一致 → `BLOCKED`；
4. execution 为 FAILED/CANCELLED → `DISCARD`；
5. candidate metric MISSING/NON_FINITE/PARSE_ERROR/STALE → `DISCARD`；
6. candidate/champion identity 不可交换 → `INCOMPARABLE`；
7. 任一必需 HARD constraint 缺失或 NOT_EVALUATED → `BLOCKED`；
8. 任一 HARD constraint VIOLATED → `DISCARD`；
9. 无 champion → 唯一进入 BaselinePolicy；
10. comparison/policy invalid → `BLOCKED`；
11. outcome IMPROVED → `KEEP`；
12. outcome REGRESSION → `DISCARD`；
13. outcome EQUIVALENT_OR_INCONCLUSIVE → 按版本化政策固定为一个值，首期建议 `DISCARD`。

不要在决策表中保留“或”。若业务确需人工路径，应由明确条件决定，例如：

```text
uncertainty unavailable AND owner_fallback absent → HUMAN_REVIEW
```

而不是让调用方在两个 verdict 中任选。

### 6.5 单独定义 BaselinePolicy 与正式 Owner Decision Record

Owner record 必须至少包含：

```text
decision_id
status = DRAFT / APPROVED / REJECTED / REVOKED / EXPIRED
scope（study/run/event IDs）
facts_hash
decision_payload
approver_identity + approver_role
approved_at + effective_at
policy_version
expiry/rerun_deadline
revocation_rule
signature_or_audit_event_id
```

只有 `status=APPROVED` 且 scope、facts hash、有效期全部匹配时，PromotionJudge 才能产生 `PROVISIONAL_BASELINE_ESTABLISHED`。

在 Cycle 1 正式审批前：

- V2.1 不得把 C1 的 provisional 结果标为已闭合；
- C1 回放应断言“没有发生 champion mutation”；
- C2—C5 的回放必须标为 conditional fixture，显式注入一份已批准的测试 Decision Record；
- 真实 ledger 不得使用测试 fixture 代替 Owner 审批。

### 6.6 统一 MetricObservation、MetricComparison 与 DecisionBar

建议：

```python
@dataclass(frozen=True)
class MetricObservation:
    identity: MetricIdentity
    value: float | None
    status: MetricStatus
    evaluation_sample_count: int
    source_event_id: str
    artifact_digest: str

@dataclass(frozen=True)
class UncertaintyEstimate:
    method: UncertaintyMethod
    value: float | None
    confidence_level: float | None
    repeat_count: int
    random_seed: int | None

@dataclass(frozen=True)
class MetricComparison:
    identity: MetricIdentity
    candidate_estimate: float
    champion_estimate: float
    paired_deltas: tuple[PairedDelta, ...]
    aggregation_method: AggregationMethod
    uncertainty: UncertaintyEstimate
    comparable: bool

@dataclass(frozen=True)
class DecisionBar:
    metric_id: str
    unit: str
    value: float
    policy_version: str
    source: BarSource
```

强制不变量：

- `status=PRESENT_VALID` 当且仅当 `value` 有限；
- 缺失/解析失败时 `value=None`，禁止伪造 `0`；
- candidate 和 champion 先分别通过同一 validator，再进行 pair；
- `uncertainty.value` 必须非负且有限；
- `confidence_level` 在 `(0,1)`；
- fallback bar 也必须有限正数并绑定同一 metric/unit/policy；
- 首期只实现 `supervised_holdout` 的同 seed 配对；未实现 profile 不得进入该代码路径；
- 将 `std(paired_deltas)/sqrt(n)` 命名为 `STANDARD_ERROR_OF_PAIRED_DELTAS`；bootstrap 必须规定 resample unit、置信度、重复次数和随机种子。

OutcomeComparator 的唯一签名应为：

```python
compare(comparison: MetricComparison, bar: DecisionBar) -> OutcomeResult
```

方向归一只允许发生一次；若 `paired_deltas` 已是“正数代表 candidate 更优”，Comparator 不得再次翻转。

### 6.7 将 constraints 改为完整性可验证的 aggregate

```python
@dataclass(frozen=True)
class ConstraintResult:
    constraint_id: str
    observed_value: float | None
    status: ConstraintStatus  # PASS / VIOLATED / NOT_EVALUATED
    ...

@dataclass(frozen=True)
class ConstraintEvaluation:
    contract_hash: str
    expected_constraint_ids: frozenset[str]
    results: tuple[ConstraintResult, ...]
    complete: bool
    policy_version: str
```

规则：

- `expected_constraint_ids != result_ids` → `complete=false` → 禁止 KEEP；
- HARD + NOT_EVALUATED → `BLOCKED`；
- HARD + VIOLATED → `DISCARD`；
- SOFT 路径必须由 policy 给出唯一结果，不得写成三选一；
- 首期若尚未完成多目标策略，应明确“单 primary + hard constraints”，secondary 只展示，不参与自动晋级；不要用“词典序”一句话代替完整的 tie-break、缺失值和阈值合同。

### 6.8 把 test 隔离从视图过滤升级为信息流隔离

最低实现要求：

1. `SelectionMetricObservation` 与 `TestMetricObservation` 使用不同 DTO 和不同存储命名空间；
2. OutcomeFactsBuilder、MetricComparator、DiagnosticEngine、AdvicePolicy、MemoryWriter 的服务身份只有 selection read capability；
3. test 评估只能在冻结/最终评估阶段由独立身份读取；
4. iterative `LeaderView` 不含 test；若最终报告需要 test，另建 `FinalEvaluationLeaderView`；
5. Access Audit 不可用时 fail closed；
6. 任意 test observation 注入 selection facts 时，在 facts 构建阶段拒绝，而不是等发布阶段过滤。

必须增加非干扰测试：

```text
给定相同 selection facts，只改变 test values：
FinalDecision 不变
DiagnosticFindings 不变
ActionRecommendations 不变
Memory writes 不变
CodeAgentView 不变
iterative LeaderView 不变
```

只有最终评估专用视图允许变化。

### 6.9 强化唯一 writer

除静态扫描外，增加：

- ledger 写接口要求 `producer_id=PROMOTION_JUDGE` 和受控服务凭证；
- `promotion_decided` schema 带 `schema_version/input_bundle_hash/idempotency_key`；
- adapter 只能通过依赖注入调用同一 Judge 实现，不能自行拼装或修改 FinalDecision；
- shadow 身份没有 ledger/champion 写权限；
- legacy 删除版本和截止日期写入迁移计划；
- rollback 只能在两个“调用同一决策合同的 writer 部署版本”之间切换，不能恢复旧业务逻辑；
- downstream 接收 `frozen FinalDecision`，不得原地改写。

### 6.10 完成 Profile Registry、Advice、Memory 与 evidence 治理

这些项目不一定全部阻断 V2.2 文档通过，但必须在对应实施阶段设置退出门禁：

- Registry 的 `validate` 同时验证 support state、required facts、forbidden combinations、detector applicability 和 minimum repeats；不能只调用 `check_forbidden`。
- `capabilities: dict` 改为带证据来源的版本化 `CapabilityProfile`。
- 区分 `fact_reliability` 与 `diagnostic_evidence_strength`。结构化事件可提高事实可靠性，但不能单独把“过拟合”等诊断提升为 HIGH。
- HIGH/MEDIUM 的 detector 需有回放集上的校准记录、适用 profile、已知误报/漏报和版本。
- Advice 需真正给出 schema、hash、approver、effective time、风险等级和 action scope enforcement，不只列治理要点。
- Memory 需定义每一层的 writer ACL、可读角色、provisional/quarantined 状态、supersession/invalidation 传播和删除/保留策略。

---

## 7. 测试与验收整改

### 7.1 当前测试计划的关键问题

- `DISCARD/HUMAN_REVIEW`、`DISCARD/INCOMPARABLE` 不是可断言的唯一期望。
- “artifact 不完整永不进入 PromotionJudge”与决策表“Judge 接收 artifact 并返回 BLOCKED”矛盾，必须二选一。建议允许 Judge 消费不可晋级的 gate result 并返回 BLOCKED，以保证统一审计。
- C1 使用未批准 DR 期待 provisional baseline，不成立。
- C2 的 `KEEP` 未给出 repeats、uncertainty 或正式 fallback bar，和“uncertainty 缺失禁止自动 KEEP”冲突。
- “direction 翻转 + 数值变换 outcome 一致”过宽。只有同步变换数值、direction、bar 和 unit 的等价变换才应保持结果。
- `NO_IMPROVE` 不是当前 outcome 枚举，性质测试名称应改为 `EQUIVALENT_OR_INCONCLUSIVE`。

### 7.2 V2.2 必须新增的 P0 测试

| 类别 | 必测性质/场景 | 唯一期望 |
|---|---|---|
| Eligibility | contract invalid + champion exists + improved | BLOCKED，永不 KEEP |
| Eligibility | incomparable + champion exists + improved | INCOMPARABLE，永不 KEEP |
| Execution | CANCELLED + residual improved metric | DISCARD，永不 KEEP |
| Execution | 非法组合 COMPLETED + HARD_TIMEOUT | BLOCKED |
| Constraints | 必需 hard result 缺失 | BLOCKED |
| Constraints | HARD NOT_EVALUATED | BLOCKED |
| Baseline | 无 champion + 完整合法运行 | BASELINE_ESTABLISHED + SET_BASELINE |
| Baseline | partial + 未批准 DR | 不建立 baseline，不修改 champion |
| Baseline | partial + scope/hash 匹配的 APPROVED DR | PROVISIONAL_BASELINE_ESTABLISHED |
| Metric | 合法 `value=0` | 可正常比较，不视为缺失 |
| Metric | status=MISSING + value=0 | DTO 构造失败 |
| Metric | champion metric_id/unit/direction 不同 | INCOMPARABLE |
| Metric | candidate/champion checkpoint policy 不同 | INCOMPARABLE/BLOCKED，按固定政策唯一断言 |
| Bar | uncertainty=-1/NaN/Inf | POLICY_INVALID → BLOCKED |
| Bar | fallback=0/NaN/单位不一致 | POLICY_INVALID → BLOCKED |
| Comparator | delta=±bar | 分别 IMPROVED/REGRESSION |
| Comparator | delta=0 且 bar>0 | EQUIVALENT_OR_INCONCLUSIVE |
| Test 隔离 | 仅 test 数据变化 | iterative outputs 全部不变 |
| Writer | shadow/legacy 非授权身份写 ledger | 权限拒绝 |
| Idempotency | 同 decision 重放两次 | champion 只迁移一次 |

### 7.3 穷举与性质验证

对有限枚举做笛卡尔积测试或模型检查，至少覆盖：

```text
integrity × eligibility × process_status × termination_reason
× metric_status × artifact_status × constraint_aggregate_status
× baseline_status × outcome
```

每一个合法组合必须恰好产生一个 `FinalDecision`；非法组合必须在 DTO/gate 构造阶段拒绝。全空间需证明以下安全性质：

```text
KEEP ⇒ integrity PASS
KEEP ⇒ execution COMPLETED 且 termination pair 合法
KEEP ⇒ candidate/champion metrics 双边 PRESENT_VALID 且可交换
KEEP ⇒ artifact FINALIZED
KEEP ⇒ hard constraints complete 且全部 PASS
KEEP ⇒ baseline/champion 合法
KEEP ⇒ outcome IMPROVED
非 mutation_authorized ⇒ champion_after == champion_before
```

---

## 8. 落地性与阶段计划复核

V2 的阶段 0—4 与 V2.1 的迁移路线总体可行，但必须重排退出门禁：

| 阶段 | 交付物 | 退出条件 |
|---|---|---|
| 0A 合同冻结 | Enum/DTO、全序决策表、字段血缘、Owner DR schema、Profile support state | 本报告 P0 文档门禁全部通过 |
| 0B Fixture 与 replay | C1—C5 的事实包、正式/测试 DR 分离、golden decisions | 不依赖自然语言或未批准外部决策 |
| 1A Shadow | 新流水线只读运行，产差异报告 | 无 ledger/champion 写权限；全部差异完成归因 |
| 1B Logic Gate | 单元、性质、枚举穷举、test 非干扰、idempotency | P0 测试全绿，零未解释反例 |
| 1C Single Writer | runtime ACL、唯一事件 producer、新 FinalDecision schema | 只有新 Judge 可写；旧 adapter 无逻辑且无独立写权 |
| 1D Retirement | 删除旧规则或保留纯 adapter 到明确截止版本 | 无双裁决、可回滚部署但不可回滚旧语义 |
| 2 Diagnostics/Advice | calibrated finding、版本化 advice、动作范围门禁 | 不读 test；高风险动作需审批；不改 verdict |
| 3 Memory | 分层 ACL、provenance、失效传播 | provisional 撤销可机械失效下游记忆 |
| 4 Profile 扩展 | 每个 profile 的独立 contract/replay/eval | 未通过专项门禁不得标 IMPLEMENTED |

对现有 `_machine_judge` 的侵入可以控制，但前提是把它变成 orchestration shell，而不是在旧函数内部逐步叠加 if/else。建议 `_machine_judge` 只负责组装已验证 gate result、调用唯一 Judge、发布不可变 decision；所有业务条件迁移到版本化组件及合同测试中。

---

## 9. 跨领域复核

### 9.1 已通过的方向

- 不再通过 domain 名称猜 detector。
- 明确 `cross_validation/time_series/language_modeling/RL` 均未实现。
- 首期限定 `supervised_holdout`。
- RL 不再错误复用普通 train/validation gap。

### 9.2 仍需修订

`ProfileRegistry.validate(profile, capabilities: dict)` 当前只展示 `check_forbidden`，并未验证 `required_facts`、支持状态、minimum replay、minimum repeats 或 detector 所需证据。`capabilities` 仍是任意字典，尚未真正被 registry 替代。

V2.2 应让 registry 返回强类型 `ValidatedProfile`，未实现 profile 在合同构建阶段直接拒绝。§5 中关于 cross-validation 配对的伪代码应标注为非可执行设计示例，避免实现者误以为已经获得首期授权。

---

## 10. 残余 P1/P2 风险

### P1｜实施计划批准前关闭

1. 字段血缘矩阵增加：字段级 source event、authority、quality、freshness、冲突优先级、允许 fallback、缺失处置；当前按“字段组”列两列不足以机械审计。
2. 把 `provenance: dict`、`capabilities: dict`、`policy_versions: dict`、budget/resource/error/change 等 P0 相关开放字典改为版本化类型。
3. 明确 artifact integrity 是 Stage 2 还是 Stage 3 的权威输出，PromotionJudge 只消费一个权威结果，避免两处各自解释 FINALIZED。
4. 完成 evidence calibration、Advice schema/审批与 Memory writer ACL。
5. 为 policy bundle 建立不可变 hash，历史 replay 必须使用当时 policy，不得默认套用最新版本。

### P2｜跨领域扩展前关闭

1. cross-validation：fold identity、配对单位、nested CV、selection bias 和重复 CV 合同。
2. time series：cutoff、滚动窗口、horizon、泄漏检查、窗口依赖下的不确定性。
3. language modeling：token weighting、数据污染、checkpoint/early-stop、一致 tokenizer 与 corpus fingerprint。
4. RL：environment/version、episode distribution、IQM/bootstrap、seed 配对、cost/safety constraints、reward hacking 检测。
5. 多目标：若超出“单 primary + hard constraints”，需单独设计 lexicographic/Pareto/tie-break 及缺失证据政策。

---

## 11. V2.2 通过继续二审的门禁条件

### 11.1 文档与合同门禁

- 修复 EligibilityGate：任何 contract/comparability 错误都不返回 COMPARABLE。
- FinalDecision enum、baseline 状态、nullable SHA、state transition 和 mutation 权限完全一致。
- PromotionJudge 决策表无“或”，对全部合法组合是唯一、完备、确定的全函数。
- CANCELLED 与非法 execution/termination 组合均被 fail closed。
- 硬约束集合可验证完整；缺失和 NOT_EVALUATED 不得 KEEP。
- MetricObservation、MetricComparison、UncertaintyEstimate、DecisionBar、ConstraintEvaluation、OwnerDecisionRecord 强类型完整。
- candidate/champion 使用对称 validator，metric/checkpoint/artifact identity 全链路可追溯。
- C1 有真正 `APPROVED` 或明确 `REJECTED` 的 Owner Decision Record；在此前不得把 provisional 路径写成真实已通过结果。
- test 使用独立 DTO、存储命名空间和读取 capability，不再依赖输出字段过滤。

### 11.2 逻辑与测试门禁

- §7.2 所列 P0 测试全部有唯一预期并通过。
- PromotionJudge 枚举空间穷举通过，证明 `KEEP` 的全部必要条件。
- C1—C5 replay fixture 固化事实、policy 和 Owner record hash；C2 `KEEP` 必须有可追溯 uncertainty 或合法 fallback。
- test 非干扰测试通过。
- duplicate event/idempotency、shadow 越权写、legacy 越权写测试通过。

### 11.3 架构与迁移门禁

- ledger/champion store 运行时只授权一个 producer。
- diagnostics/advice/publisher/memory 没有 FinalDecision 或 champion 写能力。
- legacy adapter 无业务逻辑、无独立写权，并有删除版本。
- shadow 不写正式 verdict、ledger 或 champion。
- rollback 不恢复旧判定逻辑，不合并两套结果。

### 11.4 范围门禁

- `IMPLEMENTED_PROFILE` 在代码完成前仍为 `NONE`。
- 首个实现只允许 `supervised_holdout`，且 registry 验证 required facts 和 minimum repeats。
- cross-validation、time-series、language-modeling、RL、unsupervised 均在合同入口 fail closed，直到专项 SDD 和 replay suite 通过。

达到上述门禁后，下一轮才可给出：

```text
CONTINUED_SECOND_REVIEW=APPROVED
DESIGN_GATE=PASS_FOR_IMPLEMENTATION
IMPLEMENTATION_AUTHORIZED=SUBJECT_TO_SDD_GATE
PRODUCTION_READY=NO
```

---

## 12. 最关键的待决策点

按优先级排序：

1. **Cycle 1 Owner 裁决：** 是否正式批准 partial metric 建立 provisional baseline；没有审批不能以测试或文档替代。
2. **baseline 状态迁移语义：** `BASELINE_ESTABLISHED` 是否授权写 champion；建议用统一 `state_transition` 取代仅 KEEP 才能 promotion 的布尔值。
3. **不可用 uncertainty 的唯一政策：** 首期是固定 `HUMAN_REVIEW`，还是允许经审批的 fallback bar 自动晋级；必须二选一并版本化。
4. **invalid metric 的唯一终态：** 区分 candidate 运行失败、champion 历史不可比和 policy 无效，分别固定为 DISCARD/INCOMPARABLE/BLOCKED，不能继续写“或”。
5. **test 隔离边界：** 必须确定“独立存储 + 独立服务身份/能力”，不能继续保留“独立存储或访问能力”的未决方案。
6. **首期多目标范围：** 建议只支持单 primary + 完整 hard constraints；复杂 soft/secondary/Pareto 自动晋级延后。

---

## 13. 最终裁决

V2.1 已经解决了 V2 最严重的“Comparator 冒充 Judge”和“配置改写 timeout 事实”的方向性问题，但仍未把所有安全不变量写成一致、确定、可验证的合同。

本轮最关键的四个阻断点是：

1. eligibility 错误 findings 可被忽略并返回 COMPARABLE；
2. CANCELLED、硬约束缺失/未评估仍可能到 KEEP；
3. baseline 建立状态不可达且与 `promotion_allowed` 冲突；
4. test 隔离尚未形成输入侧能力边界。

最终结论：

```text
BLOCKED_FOR_REMEDIATION
```

建议不要在 V2.1 上直接开始主链路编码。先提交 V2.2，完成确定性决策合同、baseline 状态迁移、双边 metric validation、硬约束 completeness 和 test 非干扰设计，再进入 SDD 实施门禁。
