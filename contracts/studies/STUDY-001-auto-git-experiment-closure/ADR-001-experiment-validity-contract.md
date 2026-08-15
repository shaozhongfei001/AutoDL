# ADR-001 — 实验有效性合同（Experiment Validity Contract）

> 状态：**APPROVED_BY_OWNER**（设计已批准，未实施）
> 审批：HUMAN_OWNER via conversation 2026-08-15（`OWNER-APPROVAL-20260815-01`）
> 关联：SDD P0-1（评审 4.1 / 6.3 / 6.4）、Study CONTRACT `STUDY-001`
> 基线 commit：`1331cfcec07ea673f0c1b540e1f9b9f0d667bebe`
> 作者：MAIN-00（起草）；ARCH-01/SEC-01/QA-01 评审待实施前完成

## 1. 背景与动机

阶段 0 证据闭合（`docs/phase0_evidence_closure_response.md`）确认：
- 当前项目**无任何训练时间预算执行**（所有 `budget` 均为 token/memory/cycle 预算）。
- `monitor.wait_for_completion` 纯轮询、无硬超时、无预算感知。
- 配置 `yaml.safe_load` 加载、**无 schema 校验**。
- 训练结束条件完全由 agent 写的 `train.py` 决定（epoch/steps）。
- 指标解析不区分 validation/test，存在 test 回流风险。

没有"预算 + 评估 + 数据 + 环境 + 阈值"的机器可执行合同，则候选实验**不可公平比较**，任何自动晋级/回退都是对不可靠结论的固化。故 P0-1 优先于 P0-2。

## 2. 决策

采纳评审 6.1-6.4 的设计，为 AutoDL 引入**机器可读、schema 校验、单源权威**的实验有效性合同：

### 2.1 配置分层（评审 6.2）
- **权威值**放机器可读 config（`experiment.budget` / `experiment.evaluation` / `experiment.comparability`），由 **schema 校验**约束。
- `PROJECT_BRIEF` 只声明**意图**（引用 profile 名），**不得**维护第二份可冲突数值。
- 冲突时以 config（schema 校验通过者）为唯一权威。

### 2.2 预算执行（评审 6.3.1 / 6.4）
- 训练脚本按 `active_train_seconds`（单调时钟，排除 queue/setup/compile/warmup）自终止。
- runner 设 `hard_wall_clock_limit` 硬超时兜底（区分 `CRASH`/`TIMEOUT`/`BUDGET_EXCEEDED`）。
- `poll_interval` 只影响"完成发现延迟"，**不参与预算计算**（monitor 不充当预算执行器）。
- 预算权威模式：`active_wall_clock_seconds`（pilot 采用），支持扩展 `optimizer_steps` / `samples_or_tokens`。

### 2.3 评估合同与 split 职责（评审 6.3.2）
- **validation 用于逐轮选优**（maximize primary_metric）。
- **test 仅独立验收**（`access_policy: gated_milestone_or_final_only`，`feedback_to_iterative_agents: false`）。
- 多种子聚合（seeds + repeats），`min_effect_size` + 置信规则（difference_must_exceed_2x_pooled_std）。
- 记录 `baseline_noise_evidence` 作为噪声基线。

### 2.4 比较性指纹（评审 6.4）
- 记录 dataset / evaluator / environment(cohort) / seed / 预算 指纹。
- `comparability` 不满足（跨 cohort / 预算不一致 / 评估器变化）→ 状态 `INCOMPARABLE`，拒绝自动比较。

### 2.5 状态机（对齐 04_SDD 实验状态机）
`SCHEDULED → RUNNING → FINISHED{SUCCESS/TIMEOUT/BUDGET_EXCEEDED/CRASH/INCOMPARABLE}`

## 3. 配置 schema 草案（草案字段）

```yaml
experiment:
  schema_version: "1.0"
  budget:
    mode: "active_wall_clock_seconds"
    limit: 300            # 训练预算（排除 setup/compile/warmup）
    hard_wall_clock_limit: 420
    timer: "monotonic"
    required_time_events: [...]
  evaluation:
    primary_metric: { name: "validation_accuracy", direction: "maximize", unit: "pp" }
    secondary_metrics: [...]
    evaluator: { entrypoint: ..., fingerprint: ... }
    test_evaluator: { entrypoint: ..., fingerprint: ..., result_visibility: "owner_and_qa_only" }
    statistics: { seeds: [17,29,43], repeats: 3, min_effect_size: "0.5pp", confidence_rule: ... }
  comparability:
    hardware_cohort_id: "COHORT-RTX3060L-6G"
    requires_exact_cohort: true
    dataset_fingerprint: ...
    evaluator_fingerprint: ...
```

## 4. 落地范围（待 Owner 批准后实施）

- `core/config_loader.py`（新增）：加载 + schema 校验（缺必填即报错）。
- `core/monitor.py`：增加预算感知（`active_train_seconds` 上报 + 硬超时状态判定）。
- `core/execution.py`：runner 层 `hard_wall_clock_limit` 兜底（local 与 Slurm）。
- `core/tools.py`：`launch_experiment` 接受预算参数；`run_shell` 修复复合命令 / 明确拒绝并提示用 launch。
- 指标解析：区分 `validation_*`（选优）与 `test_*`（验收）。

## 5. 验收标准（对齐评审 6.4）

1. 预算达 limit 时训练自终止，`active_train_seconds` 误差可控（≤ limit × 1.05）。
2. `hard_wall_clock_limit` 触发区分 `TIMEOUT`/`BUDGET_EXCEEDED`。
3. `poll_interval` 改变不影响预算数值。
4. 指纹不匹配拒绝比较，状态置 `INCOMPARABLE`。
5. test 结果不回流到逐轮 Agent（审计日志可证）。

## 6. 相关与待办

- 依赖 ADR-002（事务隔离与晋级）共用状态机与指标。
- `minimum_effect_size` 数值待基线噪声研究（pilot 候选实验）校准。
- 本 ADR 为 DRAFT，未经 4 方 approval 不进入实施。
