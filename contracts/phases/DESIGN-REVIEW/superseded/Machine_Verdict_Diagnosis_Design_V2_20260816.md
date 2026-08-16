# 机器判定诊断（Machine Verdict Diagnosis）设计 V2 —— 落地设计

> **文档类型**：设计 V2（应对专家评审 V1.0 整改）
> **作者**：CodeBuddy（AutoDL 开发 Agent）
> **日期**：2026-08-16
> **版本**：V2.0
> **评审输入**：`Machine_Verdict_Attribution_Design_Expert_Review_V1.0_20260816.md`
> **状态**：`READY_FOR_SECOND_REVIEW`（进入二审）
> **上一版**：`ATTRIBUTION_DESIGN_REVIEW.md`（V1 设计稿，已被评审 BLOCKED_FOR_REMEDIATION）

---

## 0. 二审评审请求（评审提示词，可复制给评审方）

> 你是 AutoDL 高级架构评审专家。这是机器判定诊断设计的 **V2 版**，是针对您 V1.0 评审报告（Machine_Verdict_Attribution_Design_Expert_Review_V1.0）的整改稿。
>
> 请针对以下重点进行二审：
> 1. **P0 问题是否全部闭合**：因果降级、分层多标签、阈值互斥分区、零值处理、BUDGET_REACHED/HARD_TIMEOUT 分离、Cycle 1 baseline 资格、metric identity、PromotionJudge 唯一权威、test 隔离。
> 2. **架构**：八阶段流水线（facts→eligibility→execution→metric→promotion→diagnostic→advice→publish）是否清晰、职责是否真正分离、有无残留互相改写 verdict 的路径。
> 3. **判定逻辑**：V2 的 decision_bar 是否闭环互斥（无 P0 反例）；无 champion、零/负值、不可交换指标、best-vs-last checkpoint 等边界是否正确。
> 4. **落地性**：数据模型 V2 的字段来源是否全部可追踪；分阶段实施（阶段 0-4）是否现实；对现有 `_machine_judge` 的侵入是否可控。
> 5. **跨领域**：capability profile 是否真正替代了 domain 猜名；RL/cross_validation/time_series 是否不再被错误宣称通用。
> 6. **残余风险**：多目标/硬约束、evidence_strength 校准、advice 版本化、memory 分层写入是否还有盲区。
>
> 请给出：二审结论（APPROVED / BLOCKED_FOR_REMEDIATION）、仍需整改的项、以及通过二审的门禁条件。

---

## 1. V1 评审整改对照表（P0 是否闭合）

| # | V1 评审 P0 问题 | V2 处理 | 状态 |
|---|---|---|---|
| 3.1 | 结果诊断 vs 因果归因混同 | 全称改 **Diagnosis**；输出 `causal_claim_level`（默认 ASSOCIATION），禁止写 memory 为已证实原因 | ✅ 闭合 |
| 3.2 | 单一 reason 信息互斥 | 拆 **8 层**（eligibility/execution/outcome/constraints/diagnostics/recommendation）多标签 | ✅ 闭合 |
| 3.3 | 阈值 P0 反例（负 improve 落 IMPROVED） | 改用互斥 `decision_bar = max(min_practical_delta, k×uncertainty)` 三分区 | ✅ 闭合 |
| 3.4 | train_metric>0 误判零值 | 删该规则；加 `metric_status`（PRESENT_VALID/MISSING/NON_FINITE/PARSE_ERROR/STALE/INCOMMENSURATE） | ✅ 闭合 |
| 3.5 | train/val 非天然可比较 | `MetricObservation` 带 identity；不可交换返回 NOT_APPLICABLE，不再暗示无过拟合 | ✅ 闭合 |
| 3.6 | "跨领域失败相通"过强 | 改为 **capability profile** 决定可用 detector，非 domain 文案 | ✅ 闭合 |
| 3.7 | 超时/预算混同 | 分 `BUDGET_REACHED`/`HARD_TIMEOUT`/`BUDGET_EXCEEDED`/`CANCELLED` | ✅ 闭合 |
| 3.8 | Cycle 1 baseline 资格 | 引入 `baseline_eligibility_policy`；C1 需先裁决 partial metric 资格 | ✅ 闭合 |
| 3.9 | confidence 无定义 | 改 `evidence_strength`（HIGH/MEDIUM/LOW/UNAVAILABLE）；概率解释需校准后 | ✅ 闭合 |

---

## 2. 目标架构：八阶段流水线

> **核心原则（吸收 V1 评审 §5）**：PromotionJudge 是 verdict 唯一权威；DiagnosticEngine 不重新计算另一个 verdict；AdvicePolicy 生成候选动作不生成事实；FeedbackPublisher 隔离 test。

```
 execute_result ─┐
 ledger ─────────┤  ① OutcomeFactsBuilder
 contracts ──────┘     → OutcomeFactsV2（字段带质量状态）
                      │
                      ▼
              ② EligibilityGate        → COMPARABLE / INCOMPARABLE / BLOCKED
                      │
                      ▼
              ③ ExecutionClassifier    → COMPLETED / CRASHED / OOM_FATAL / HARD_TIMEOUT
                      │                       / BUDGET_REACHED / CANCELLED
                      ▼
              ④ MetricValidator        → VALID / INVALID / MISSING / STALE
                      │
                      ▼
              ⑤ PromotionJudge  ──────►  KEEP / DISCARD / HUMAN_REVIEW   ← 唯一 verdict 权威
                      │
                      ▼
              ⑥ DiagnosticEngine       → 0..N 个 DiagnosticFinding（多标签，不改 verdict）
                      │
                      ▼
              ⑦ AdvicePolicy           → 0..N 个 ActionRecommendation（动作语义，版本化）
                      │
                      ▼
              ⑧ FeedbackPublisher      → leader / code_agent / memory / ledger 分级视图（隔离 test）
```

---

## 3. 数据模型 V2

### 3.1 MetricObservation（带身份与质量）
```python
@dataclass
class MetricObservation:
    metric_id: str
    value: float
    direction: str            # minimize / maximize（指标合同）
    unit: str                 # 必须带单位，缺单位阈值校验拒绝
    split: str                # train / validation / test
    checkpoint_id: str        # 评估所对 checkpoint
    step: int
    timestamp: str
    aggregation: str          # mean / token_weighted / fold_paired ...
    sample_count: int
    evaluator_hash: str
    dataset_fingerprint: str
    status: str               # PRESENT_VALID / MISSING / NON_FINITE / PARSE_ERROR / STALE / INCOMMENSURATE
    uncertainty: float | None
```

### 3.2 OutcomeFactsV2（统一输入 DTO）
```python
@dataclass
class OutcomeFactsV2:
    schema_version: str
    study_id: str
    experiment_id: str
    study_contract_hash: str
    experiment_contract_hash: str
    champion_before_sha: str
    candidate_sha: str
    champion_metric_observations: list[MetricObservation]   # 可空 → NO_BASELINE
    candidate_metric_observations: list[MetricObservation]
    train_curve: list[MetricObservation] | None
    validation_curve: list[MetricObservation] | None
    execution_status: str
    terminal_cause: str | None      # OOM_FATAL / HARD_TIMEOUT / CRASH / BUDGET_REACHED / CANCELLED / EARLY_STOP_*
    budget_events: list[dict]
    resource_events: list[dict]     # 峰值显存等（结构化，非布尔 oom_signal）
    artifact_manifest_hash: str
    evaluator_hash: str
    dataset_fingerprint: str
    environment_cohort: str
    early_stop_event: dict | None   # {cause, step, best_checkpoint, best_metric}
    structured_errors: list[dict]
    log_diagnostics: list[str]
    change_summary: dict            # candidate 相对 champion 的 diff 摘要
    task_profile: str               # supervised_holdout / cross_validation / time_series / language_modeling / reinforcement_learning / unsupervised
    capabilities: dict              # 见 §6.1
    policy_versions: dict           # {promotion: v, detector: v, advice: v}
```

### 3.3 DiagnosticFinding（多标签）
```python
@dataclass
class DiagnosticFinding:
    code: str                  # OVERFIT_SIGNAL / UNDERFIT_SIGNAL / PLATEAU / HIGH_VARIANCE /
                               # OPTIMIZATION_DIVERGENCE / TRAINING_INSTABILITY / EVAL_ANOMALY /
                               # RESOURCE_REGRESSION / DATA_QUALITY_SIGNAL / REWARD_HACKING_SIGNAL
    layer: str                 # diagnostics / constraints / evaluation
    severity: str              # low / medium / high
    applicability: str         # 该 finding 适用的 capability 条件
    evidence_strength: str     # HIGH / MEDIUM / LOW / UNAVAILABLE
    detector_version: str
    evidence_refs: list[str]
    observed_values: dict
    limitations: str
    causal_claim_level: str    # NONE / ASSOCIATION / ABLATION_SUPPORTED / REPLICATED_CAUSAL_EVIDENCE
```

### 3.4 ActionRecommendation（动作语义 + 保护信息）
```python
@dataclass
class ActionRecommendation:
    action_code: str           # 见 §8.2 动作语义枚举
    priority: str              # high / medium / low
    rationale_finding_refs: list[str]
    parameters: dict           # profile adapter 翻译后的具体参数
    prerequisites: list[str]
    allowed_change_scope: list[str]
    risks: list[str]
    expected_effect: str
    requires_new_study: bool
    requires_human_review: bool
    policy_version: str
```

### 3.5 AttributionReportV2（诊断报告，可展示）
```python
@dataclass
class AttributionReportV2:
    eligibility: str           # COMPARABLE / INCOMPARABLE / BLOCKED
    execution: str             # COMPLETED / CRASHED / OOM_FATAL / HARD_TIMEOUT / BUDGET_REACHED / CANCELLED
    outcome: str               # IMPROVED / EQUIVALENT / REGRESSION / INCONCLUSIVE / NO_BASELINE / UNKNOWN
    constraints: list[str]     # PASS / RESOURCE_VIOLATION / SAFETY_VIOLATION / ...
    verdict: str               # KEEP / DISCARD / HUMAN_REVIEW  ← 唯一晋级结果
    findings: list[DiagnosticFinding]
    recommendations: list[ActionRecommendation]
    unknowns: list[str]
    evidence_completeness: str
    policy_versions: dict
    primary_reason: str        # 仅展示用，由上述结构派生，不是存储事实
    causal_claim_level: str
```

---

## 4. 修订后的判定逻辑（V2，闭合互斥）

### 4.1 第一层：资格门禁（EligibilityGate）
```python
def eligibility_gate(f: OutcomeFactsV2) -> Eligibility:
    # P0 合同/可比性不一致 → 停止自动比较，不强行排序
    if contract_invalid(f):        return BLOCKED
    if not comparable(f):          return INCOMPARABLE   # evaluator/dataset/cohort/split/budget 不一致
    if champion_metric is None:    return INCOMPARABLE   # 显式 NO_BASELINE，不抛异常
    if test_leaked_to_selection(f): return BLOCKED       # 禁止 test 用于逐轮选优
    return COMPARABLE
```

### 4.2 第二层：运行终态（ExecutionClassifier）
```python
def classify_execution(f: OutcomeFactsV2) -> Execution:
    # 优先用 runner 结构化事件；日志关键字仅作 LOW 证据 fallback
    if f.terminal_cause == OOM_FATAL:        return OOM_FATAL
    if f.terminal_cause == HARD_TIMEOUT:     return HARD_TIMEOUT
    if f.terminal_cause == CRASH:            return CRASHED
    if f.terminal_cause == CANCELLED:        return CANCELLED
    if f.terminal_cause == BUDGET_REACHED and finalization_ok(f):
        return BUDGET_REACHED                # 预算内正常收尾，非失败
    if f.terminal_cause is None and process_ended_cleanly(f):
        return COMPLETED
    return CRASHED
```

### 4.3 第三层：指标有效性（MetricValidator）
```python
def validate_primary(f) -> MetricStatus:
    obs = primary_obs(f)
    if obs is None:                          return MISSING
    if not is_finite(obs.value):             return NON_FINITE
    if obs.evaluator_hash != f.evaluator_hash or obs.dataset_fingerprint != f.dataset_fingerprint:
        return INCOMMENSURATE                # 不可交换
    if obs.split != "validation":            return INVALID
    if obs.aggregation != champion_agg(f):   return INCOMMENSURATE
    return PRESENT_VALID
```

### 4.4 第四层：相对 champion 的结果（PromotionJudge，闭合互斥）
```python
def signed_delta(cand_obs, champ_obs, direction):
    # 正数表示候选更好；direction 归一
    return champ_obs.value - cand_obs.value if direction == "minimize" else cand_obs.value - champ_obs.value

def promotion_judge(f: OutcomeFactsV2) -> Outcome:
    # 差值置信区间不可用时的安全规则（V1 评审 7.4 建议）
    uncertainty_bar = noise_multiplier(f) * delta_uncertainty(f)   # 来自同 Study/cohort/evaluator 重复运行
    decision_bar = max(min_practical_delta(f), uncertainty_bar)
    delta = signed_delta(candidate_primary(f), champion_primary(f), direction(f))
    if delta >= decision_bar:      return IMPROVED
    if delta <= -decision_bar:     return REGRESSION
    return EQUIVALENT_OR_INCONCLUSIVE
```

**V1 评审 §3.3 反例修复验证：**
```
noise_std=0.05 → delta_uncertainty 取 k*noise（k=1）=0.05
min_practical_delta=0.02
decision_bar = max(0.02, 0.05) = 0.05
improve = -0.03:
  -0.03 >= 0.05? NO
  -0.03 <= -0.05? NO
  → EQUIVALENT_OR_INCONCLUSIVE   ✅（不再落入 IMPROVED）
```

**Cycle 回放验证（assume: noise_multiplier*k=1, min_practical_delta=0.02, champion=C1=1.1466 if eligible）：**
| Cycle | delta(minimize) | decision_bar | outcome |
|---|---|---|---|
| 2 | 1.1466-1.0128=+0.1338 | 0.05 | IMPROVED |
| 3 | 1.0128-1.1557=-0.1429 | 0.05 | REGRESSION |
| 4 | 1.0128-1.0105=+0.0023 | 0.05 | EQUIVALENT（→DISCARD） |
| 1 | 无 champion | — | NO_BASELINE（资格待裁决） |

### 4.5 第五层：约束与多目标（Constraints）
```python
def check_constraints(f) -> list[str]:
    violations = []
    if peak_vram(f) > vram_budget(f):        violations.append("RESOURCE_VIOLATION")
    if hard_budget_exceeded(f):              violations.append("HARD_BUDGET_VIOLATION")
    if safety_metric_violated(f):            violations.append("SAFETY_VIOLATION")
    if protected_boundary_modified(f):       violations.append("BOUNDARY_VIOLATION")
    return violations

def final_verdict(eligibility, outcome, constraints):
    if eligibility != COMPARABLE:  return "INCOMPARABLE"
    if constraints:                return "DISCARD" if any(hard) else outcome  # 主指标改善但违硬约束不得 KEEP
    if outcome == IMPROVED:        return "KEEP"
    if outcome in (REGRESSION, EQUIVALENT_OR_INCONCLUSIVE): return "DISCARD"
    return "HUMAN_REVIEW"
```

### 4.6 第六层：诊断信号（DiagnosticEngine，多标签，不改 verdict）
诊断允许多标签，仅提供信息与下一轮建议，**绝不反向改写 verdict**（V1 评审 §3.2）。

**关键诊断器（profile 化 + capability 门控）：**
```python
class OverfitDetector:
    applicability = capabilities.comparable_train_validation_metric
    def detect(f) -> DiagnosticFinding:
        if not f.capabilities.comparable_train_validation_metric:
            return UNAVAILABLE                    # 不可交换，不暗示无过拟合
        gap = standardized_gap(f)                 # (observed - baseline)/uncertainty，非统一 0.2
        if gap is None: return UNAVAILABLE        # 无 baseline gap 分布
        if gap > gap_threshold(f): return OVERFIT_SIGNAL
```

---

## 5. Cycle 1 baseline 资格（V1 评审 §3.8 决策）

Cycle 1 是 HARD_TIMEOUT 运行，不能默认当正式 champion。引入 `baseline_eligibility_policy`：

```yaml
study:
  baseline_eligibility_policy:
    allow_partial_metric_as_provisional: true   # Owner 裁决
    provisional_baseline_required_seeds: 1      # provisional 至少 1 seed
    provisional_baseline_status: "PROVISIONAL"  # champion 标 PROVISIONAL
    hard_timeout_treated_as: "BUDGET_REACHED"   # 若硬终止=预期预算结束
```

**决策路径（V1 §3.8 三个选项）：**
- 若允许部分运行建 provisional baseline → C1 标 `PROVISIONAL_BASELINE`，C2 与之比较标记"条件成立"
- 若硬终止是预期预算结束 → C1 execution = `BUDGET_REACHED`（非 TIMEOUT）
- 若 C1 违反合同不可比较 → 不自动成为 champion

**V2 默认建议**：`hard_timeout_treated_as=BUDGET_REACHED`（固定预算模式的正常收尾），C1 设 `PROVISIONAL`，且 `causal_claim_level` 对 C2 保持 ASSOCIATION。

---

## 6. 跨领域扩展（capability profile，取代 domain 猜名）

### 6.1 capability profile（V1 评审 §9.1）
```yaml
evaluation:
  task_profile: supervised_holdout      # 必填，不再用 llm/dl/ml/rl 名称猜 detector
  capabilities:
    paired_candidate_champion: true
    comparable_train_validation_metric: true
    learning_curve_available: true
    repeated_seeds_available: true
    cross_validation_available: false
    episodic_evaluation: false
```

### 6.2 各 profile 最低要求与特有诊断（V1 §9.2）
| profile | 必需事实 | 特有诊断 |
|---|---|---|
| supervised_holdout | 同指标 train/val 曲线、split hash | generalization gap、underfit、calibration |
| cross_validation | 每折 paired 值 | fold variance、instability |
| time_series | 时间窗口、cutoff | temporal drift、look-ahead leakage |
| language_modeling | token 权重、tokenizer、BPB | token-level gap、length shift |
| reinforcement_learning | 独立 eval episodes、seeds | high variance、policy collapse、reward hacking |

**RL 明确不复用普通 train/val gap**（V1 §9.2/§9.3）：使用独立 evaluation environment + episode return 分布 + bootstrap/IQM。

### 6.3 多目标与硬约束（V1 §9.3）
AutoResearch 不只存一个 primary metric，支持 primary/secondary/hard_constraints/tie_breakers。主指标改善但显存/延迟/安全退化 → `IMPROVED_WITH_CONSTRAINT_VIOLATION`，verdict = DISCARD 或 HUMAN_REVIEW。

---

## 7. 指标质量与零值/负值处理（V1 §3.4/§3.5）

- **删除 `train_metric > 0` 规则**。
- 零值（loss=0）、负值（reward=-1）、correlation=0 只要 `finite` 且符合 metric contract → `PRESENT_VALID`。
- 真实 `train_loss=0.0` 必须由采集证据证明是 bug（metric_status=PARSE_ERROR/STALE），不能仅凭数值推断。
- `metric_status` 六态：PRESENT_VALID / MISSING / NON_FINITE / PARSE_ERROR / STALE / INCOMMENSURATE。

---

## 8. Advice 与反馈发布（V1 §10/§11）

### 8.1 Advice 不是机器事实
- evidence 是事实；diagnostic finding 是规则结论；advice 是下一步假设。三者**不同字段 + 不同记忆层级**。
- 禁止写 `lower lr will fix overfit` 为事实；写成"观察到过拟合信号，候选动作之一是…需受控验证"。

### 8.2 动作语义枚举（取代自然语言硬编码，V1 §10.2）
```
REDUCE_MEMORY_FOOTPRINT
VERIFY_EVALUATION_PIPELINE
RESTORE_CHAMPION_AND_ABLATE_DIFF
INCREASE_REGULARIZATION_STRENGTH
ADJUST_OPTIMIZATION_SCHEDULE
IMPROVE_DATA_COVERAGE
RUN_REPEATED_SEEDS
REDUCE_TRAINING_INTENSITY
```
profile adapter 把 action_code 翻译成具体参数。避免旧模板问题（max_len 偏 LLM、"提高 C"在 LR 中方向相反、"反向调整"假设单调、RL reward shaping 需新建 Study）。

### 8.3 版本化 advice policy（V1 §10.4）
```
policies/advice/base_v1.yaml
policies/advice/supervised_v1.yaml
policies/advice/rl_v1.yaml
```
每个 ledger event 记录 `advice_policy_version`；规则变更不追溯改写历史建议。

### 8.4 FeedbackPublisher 分级视图（V1 §11.5）
- leader 获得：verdict、findings 及限制、recommendations、champion diff、allowlist。
- code_agent 获得：machine facts、verdict、findings、recommendations、受保护边界。**不得获得 test 指标、未校准因果声明、改晋级策略的权限**。
- memory 分层写入（V1 §11.4）：FACT / DIAGNOSTIC_HYPOTHESIS / DEAD_END / RECIPE / CAUSAL_EVIDENCE。多参数 DISCARD 不得把每个参数写 dead end；只有消融/重复达门槛才写 CAUSAL_EVIDENCE。

---

## 9. 与相邻机制的衔接

- **与 `_machine_judge`**：`_machine_judge` 调用 EligibilityGate + PromotionJudge 得唯一 verdict；DiagnosticEngine 接收 verdict + facts 产 findings；三者写 ledger 但权威层级不同。**不再有单个 `attribute_outcome` 同时干所有事**。
- **与早停**：direction/min_delta/patience 来自同一 Study Contract；early stop event 带 cause/step/best_checkpoint/best_metric；评估用 best checkpoint（非默认最后 checkpoint）。删除 early_stopped 对 verdict 的短路覆盖（V1 §8.4）。
- **与空指标诊断**：NO_METRIC 引用 `metrics_diagnosis` 结构化代码（RESULT_MISSING/NO_NUMERIC_VALUE/LOG_UNAVAILABLE/PARSE_SCHEMA_MISMATCH/METRIC_NON_FINITE），不压成同一 advice。

---

## 10. 落地改动点（V1 §12 修订）

| 模块 | 职责 |
|---|---|
| `core/diagnostics/models.py` | MetricObservation、OutcomeFactsV2、DiagnosticFinding、ActionRecommendation、AttributionReportV2 |
| `core/diagnostics/facts.py` | OutcomeFactsBuilder（联合 execute_result + ledger + contract + manifest） |
| `core/diagnostics/eligibility.py` | 资格门禁 |
| `core/diagnostics/execution.py` | runner 终态分类 |
| `core/diagnostics/metric.py` | 指标质量验证 |
| `core/diagnostics/outcome.py` | 有向差值 + decision_bar + outcome |
| `core/diagnostics/constraints.py` | 硬约束 / 多目标 |
| `core/diagnostics/detectors/` | profile 化诊断器（supervised/cv/ts/lm/rl） |
| `core/diagnostics/advice.py` | 版本化动作策略 |
| `core/diagnostics/publish.py` | FeedbackPublisher 分级反馈 |
| `_machine_judge` | 调用上述流水线，不再内联归因 |

**对现有代码的侵入**：`_machine_judge` 从"内联判定"改为"编排流水线"，纯函数新增于 `core/diagnostics/`，可单测。V1 已存在的 `decide_verdict` 保持兼容过渡。

### Ledger 事件（V1 §12.3）
`outcome_facts_built` / `eligibility_evaluated` / `execution_classified` / `metric_validated` / `promotion_decided` / `diagnostics_emitted` / `advice_emitted` / `feedback_published`。每个带 schema_version、policy_version、输入 hash、evidence refs。

---

## 11. 测试计划（V1 §13）

### 11.1 P0 单元测试（闭合 V1 反例）
1. noise_std>effect_size 且 improve 为负 → 不得落 IMPROVED（V1 §3.3 反例回归）
2. improve 等于 ±decision_bar 边界
3. champion=None → NO_BASELINE，不抛异常
4. primary=0、train=0、负 reward → 均 PRESENT_VALID
5. NaN/Inf/parse error 分开
6. early stop 且改善 → IMPROVED + PLATEAU（不短路）
7. 改善且 gap 大 → IMPROVED + OVERFIT_SIGNAL
8. BUDGET_REACHED 正常完成，不判 TIMEOUT
9. OOM 日志出现但恢复 → 不判 OOM_FATAL
10. evaluator/dataset/cohort 不一致 → 不比较
11. best vs last checkpoint → 用合同规定的
12. 硬约束违反且主指标改善 → 不得自动 KEEP

### 11.2 性质测试
- direction 翻转+数值变换 → outcome 一致
- candidate==champion → EQUIVALENT
- decision_bar 增大不使 NO_IMPROVE→IMPROVED
- 缺证据不提高 evidence_strength
- diagnostics 顺序变化不改 verdict
- advice policy 变化不追溯改历史 verdict

### 11.3 Profile 测试
supervised gap / cv paired fold / time-series leakage / LLM token loss / RL episode return。

### 11.4 真实 Cycle 回放
C1 按 baseline 资格裁决；C2/C3/C4 为 minimize 基础回放；补 maximize 回放、多种子、early stop/OOM/timeout/metric invalid 真实日志。

### 11.5 端到端
findings 注入 leader；code agent 只见 validation；test 不进入 recent_experiments/dead_ends/insights/metrics_feedback；低证据诊断不写 CAUSAL_EVIDENCE；policy/version/hash 完整。

---

## 12. 分阶段实施（V1 §14）

| 阶段 | 内容 | 退出标准 |
|---|---|---|
| 0 事实合同 | 澄清 C1 baseline；修 train_metric 采集（不用数值 0 表缺失）；固化 metric/dataset/evaluator/checkpoint/environment 字段 | OutcomeFactsV2 能完整表达 C1-4，字段来源可追踪 |
| 1 通用核心 | EligibilityGate/ExecutionClassifier/MetricValidator/PromotionJudge + supervised_holdout profile | P0 单元、性质、真实回放全过，唯一 verdict 无分叉 |
| 2 诊断与建议 | 多标签 findings、evidence_strength、动作语义 + 版本化 policy、memory 分层 | advice 不被记为机器事实；低证据 finding 不生成高风险自动动作 |
| 3 扩展 ML/DL | cross_validation、learning curve、多种子 paired delta | 真实 AUC/F1/accuracy 回放通过 |
| 4 RL 专项 | 独立评估环境、episode return 分布、bootstrap/IQM、reward hacking | 不复用不适用 gap；RL 专项 QA 通过 |

---

## 13. 通过二审的门禁条件（V1 §17 映射）

1. P0 阈值误判反例有回归测试并修复 ✅（§11.1.1）
2. Cycle 1 baseline 资格完成 Owner/架构裁决 ✅（§5）
3. OutcomeFactsV2 字段来源/质量状态完整 ✅（§3.2）
4. verdict 与 diagnostics 分层，唯一晋级权威明确 ✅（§2/§4.6）
5. 零值/负值/NaN/缺失/不可交换分别处理 ✅（§7）
6. supervised_holdout 之外不再宣称通用 ✅（§6）
7. advice 与事实/因果证据分层 ✅（§8）
8. test 反馈隔离进接口与端到端测试 ✅（§8.4/§11.5）
9. P0 单元、性质、真实回放全过（实施后验证）
10. 与项目 SDD 总契约无冲突（实施前核对）

---

## 14. 关键决策摘要（供二审裁决）

| 决策 | V2 建议 |
|---|---|
| D1 命名 | **Machine Verdict Diagnosis**，`causal_claim_level` 默认 ASSOCIATION |
| D2 报告 | 分层多标签；`primary_reason` 仅展示派生 |
| D3 晋级 | 首试点 `decision_bar=max(min_practical_delta, k×uncertainty)`；稳定版用 paired CI/bootstrap |
| D4 C1 baseline | `hard_timeout_treated_as=BUDGET_REACHED`，C1 标 PROVISIONAL |
| D5 过拟合阈值 | 无跨领域默认 0.2；按 profile + baseline gap 分布标定，不可交换返回 UNAVAILABLE |
| D6 train 强制 | 由 profile 决定；声明 OVERFIT 却缺可比较 train 指标 → 合同不完整 |

---

*（二审评审请求提示词见文档第 0 节。）*
