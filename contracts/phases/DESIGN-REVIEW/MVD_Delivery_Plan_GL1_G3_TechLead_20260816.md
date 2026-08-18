# MVD V3.0 交付执行方案 —— Tech Lead（ARCH-01 / Delivery Tech Lead）

> **文档类型**：交付规划（Gate 1-3）
> **作者**：CodeBuddy（Tech Lead / ARCH-01）
> **日期**：2026-08-16
> **唯一设计输入**：`ADR24X7-MVD-FINAL-V3.0`（`AutoResearch_Machine_Verdict_Diagnosis_Final_Architecture_V3.0_20260816.md`）
> **范围**：首轮仅交付规划，**禁止编码**（§25）
> **状态头**：
> ```
> DOCUMENT=ADR24X7-MVD-FINAL-V3.0
> CURRENT_GATE=G1_CONTRACT_BASELINE_PREPARATION
> DESIGN_ABSORBED=YES
> IMPLEMENTATION_AUTHORIZED=NO
> PILOT_AUTHORIZED=NO
> PRODUCTION_READY=NO
> OPEN_BLOCKERS=3
> ```

---

## 1. 状态纪律声明（§18.1 如实）

```text
DESIGN_ABSORBED=YES
TEST_SPEC_DEFINED=YES
TEST_EXECUTED=NO
RUNTIME_ACL_VERIFIED=NO
PROFILE_IMPLEMENTED=NONE
IMPLEMENTATION_AUTHORIZED=NO
```

本文是**规划**，不是实现完成声明。任何"P0 已闭合"仅指**设计吸收 + 测试规格定义**，不指测试已执行。

---

## 2. 设计吸收矩阵（映射 MVD-P0-001—020 → 当前代码 → WP）

> 列：`P0 ID` / `V3.0 不变量` / `当前代码位置（差距）` / `闭合 WP` / `测试 ID` / `证据位置`。

| P0 | V3.0 不变量 | 当前代码现状（差距） | 闭合 WP | 测试 ID | 证据 |
|---|---|---|---|---|---|
| 001 | 唯一 Judge 产 FinalDecision | `loop.py:456-470` 内联 decide_verdict+gate | WP-05 | JDG 系列 | `core/mvd/decision/promotion_judge.py` |
| 002 | 唯一 Committer 写 champion | `loop.py:486-488 _try_promote` + `git_vcs.py promote` | WP-06 | 恢复测试 | `core/mvd/commit/promotion_committer.py` |
| 003 | KEEP⇐formal+全门禁+IMPROVED | 现状无完整门禁链 | WP-05 | JDG-001..005 | 决策表合同测试 |
| 004 | 失败运行永不 KEEP | `gate_verdict_by_contract_status` 已有 TIMEOUT 拦截 | WP-05 | JDG-010 | execution gate |
| 005 | 无 champion 不构 comparison | `decide_verdict` 无 champion 返回 INCOMPARABLE | WP-05 | BSL-001..002 | champion_router |
| 006 | 方向唯一归一 | `decide_verdict` 内方向处理 | WP-03 | 性质测试 | comparison.py |
| 007 | 0/负合法，缺失不占位 | monitor 提取可能 NaN | WP-03 | JDG（0 值） | metric.py |
| 008 | 不可交换不排序 | 现状比较 cohort/fingerprint | WP-03 | JDG-008 | metric identity |
| 009 | 硬约束完整性 | **无 constraints 系统** | WP-05 | JDG-008/009 | constraints.py |
| 010 | Manifest 原子完成 | `git_vcs.py` 有 manifest 雏形 | WP-04 | 故障注入 | artifact.py |
| 011 | test 不入 iterative | **无 selection/test 隔离** | WP-07 | 非干扰测试 | namespace/ACL |
| 012 | provisional 仅 exact APPROVED | **无 OwnerDecisionRecord 系统** | WP-05 | BSL-003..004 | baseline_policy |
| 013 | provisional 不自动 KEEP | 现状无 provisional 概念 | WP-05 | BSL-005..006 | baseline_policy |
| 014 | uncertainty 不足→HUMAN_REVIEW | 现状无 uncertainty 计算 | WP-03 | JDG-007 | decision_bar |
| 015 | 非法 policy→BLOCKED | 现状无 policy bundle | WP-01 | Contract rejection | models.py |
| 016 | 诊断/建议不改历史 verdict | 现状无诊断层 | WP-08 | 性质测试 | publish |
| 017 | DISCARD/BLOCKED 不改 champion | `_try_promote` 仅 KEEP 时调 | WP-06 | 性质测试 | committer |
| 018 | parent SHA 过期→STALE | 现状无 parent SHA 检查 | WP-05 | 恢复测试 | champion_router |
| 019 | test/evaluator/合同等 agent 不可改 | `write_policy` denylist 有雏形 | WP-07 | ACL denial | SEC |
| 020 | 状态可重放恢复 | ledger 追加式已有 | WP-06 | 故障注入 | events/ledger |

**当前代码最大的 3 个差距**（决定交付工作量）：
1. **无 constraints 系统**（P0-009）——需全新建 `ConstraintEvaluator` + Study Contract 的 constraints 定义。
2. **无 selection/test 隔离**（P0-011/019）——需全新建 namespace + principal + ACL + 独立 DTO。
3. **无 uncertainty/决策 bar 统计**（P0-014）——需全新建 `MetricAggregator` + `UncertaintyEstimate` + `DecisionBar`。

---

## 3. 工作包（WP-01—10）拆分、依赖图、模块映射

### 3.1 依赖图（DAG）

```text
WP-01 Contracts ──► WP-02 Runner ──► WP-03 Evaluation ──► WP-05 Decision ──► WP-06 Commit ──► WP-09 Migration
      │                │                                   │                     │
      │                └────► WP-04 Workspace/Artifact ──────┘                     │
      │                                                                             │
      └───────────────► WP-07 Isolation/Security ◄────── WP-08 Diagnostics/Advice ─┘
      │                                                                             │
      └────────────────────────────────────────────────────────► WP-10 Independent QA
```

**关键路径**：WP-01 → WP-03 → WP-05 → WP-06 → WP-09（决定单写者 cutover）。
**并行分支**：WP-02/04 可与 WP-03 并行；WP-07/08 依赖 WP-01 但可与 WP-05/06 并行。
**WP-10** 全程独立，不依赖任何 WP 输出（独立 QA）。

### 3.2 工作包明细（每包：owner/输入/输出/代码模块/测试ID/证据/回滚）

#### WP-01 Contract Runtime｜DEV-CORE-01
- **输入**：V3.0 §5/§6 合同选型（Pydantic v2 strict + pyright strict）
- **输出**：`core/mvd/contracts/{enums,models}.py`、JSON Schema、`PolicyBundle`、registry
- **代码**：`core/mvd/contracts/`
- **测试**：Contract rejection（MVD-CTR-*：非法 union、MISSING+value=0、unknown direction、policy hash 不符）
- **证据**：rejection tests 全绿 + schema diff
- **回滚**：纯新增目录，不影响旧路径；未接 Judge 前可整体移除
- **退出条件**：非法构造/JSON 全部拒绝

#### WP-02 Runner/Budget｜DEV-RUN-01
- **输入**：V3.0 §7.1 双层预算 + §6.1 ExecutionResult
- **输出**：`ExecutionResult`（process_status×termination_reason）+ 双层预算计时
- **代码**：`core/mvd/contracts/enums.py`（ExecutionResult）+ `core/execution.py` 扩展
- **测试**：timeout/clock/backend（MVD-RUN-*：BUDGET_REACHED 不判 FAILED、HARD_TIMEOUT 判 FAILED）
- **证据**：runner 事件结构化输出
- **回滚**：ExecutionResult 枚举为新增，旧 contract_status 映射保留过渡
- **退出条件**：execution 事件完整、可区分 BUDGET_REACHED/EARLY_STOP/HARD_TIMEOUT

#### WP-03 Evaluation/Stats｜DEV-EVAL-01
- **输入**：V3.0 §6.2/§8（metric identity、paired delta、uncertainty、bar）
- **输出**：`MetricObservation`、`MetricAggregator`、`UncertaintyEstimate`、`DecisionBar`
- **代码**：`core/mvd/decision/{comparison,decision_bar}.py` + `metric.py`
- **测试**：minimize/maximize、多 seed（MVD-EVL-*：方向唯一归一、0/负值、不可交换、uncertainty unavailable）
- **证据**：统计正确性 + 性质测试
- **回滚**：纯新增，未接 Judge 前可移除
- **退出条件**：MetricComparison 构造正确，方向只归一一次

#### WP-04 Workspace/Artifact｜DEV-VCS-01
- **输入**：V3.0 §7.2 Artifact Manifest + §4.3 分支架构
- **输出**：独立 worktree、`ArtifactManifest`（原子）、protected refs
- **代码**：`core/mvd/commit/`（manifest）+ `core/git_vcs.py` 扩展
- **测试**：dirty tree、atomic artifact、manifest 半写恢复（MVD-ART-*）
- **证据**：故障注入测试
- **回滚**：manifest 为新增字段，旧 git_vcs 保留
- **退出条件**：Manifest 未原子完成不得进入判定

#### WP-05 Decision｜DEV-CORE-01 + ARCH-01
- **输入**：V3.0 §9/§10（ChampionRouter、BaselinePolicy、PromotionJudge）
- **输出**：`ChampionRouter`、`BaselinePolicy`、`PromotionJudge`（纯函数）
- **代码**：`core/mvd/decision/{champion_router,baseline_policy,promotion_judge}.py`
- **测试**：JDG-001..012 + BSL-001..006 + 性质测试 + 枚举穷尽
- **证据**：exhaustive decision report
- **回滚**：纯新增，未接 loop 前可移除
- **退出条件**：P0 单元/性质/golden 全绿，唯一 FinalDecision 无分叉

#### WP-06 Commit｜DEV-VCS-01
- **输入**：V3.0 §10.5 + §17.6 故障
- **输出**：`PromotionCommitter`、CAS（optimistic lock）、idempotency、ledger 事务
- **代码**：`core/mvd/commit/{promotion_committer,optimistic_lock}.py`
- **测试**：stale/recovery（manifest 半写、ledger 写前后崩溃、CAS 前后崩溃、duplicate key）
- **证据**：故障注入全绿 + single-writer 证明
- **回滚**：未切 single writer 前纯新增
- **退出条件**：PromotionCommitter 唯一能写 champion/ledger

#### WP-07 Isolation/Security｜SEC-01 + DEV-EVAL-01
- **输入**：V3.0 §4.1 两平面 + §10.5 + P0-011/019
- **输出**：selection/test namespace、principals、ACL、独立 DTO、no-mount
- **代码**：`core/mvd/publish/views.py` + security 层
- **测试**：denial、noninterference（仅 test 变化→iterative 输出不变）、越权拒绝（MVD-SEC-*）
- **证据**：ACL denial + 非干扰测试全绿
- **回滚**：新增隔离层，旧单 workspace 保留过渡（F4 前）
- **退出条件**：test 对 iterative 容器完全不可见，非授权 principal 无法写 champion

#### WP-08 Diagnostics/Advice｜独立功能开发角色
- **输入**：V3.0 §11（findings、policy、views、memory）
- **输出**：`DiagnosticEngine`、`AdvicePolicy`、typed views、memory 分层
- **代码**：`core/mvd/diagnostics/` + `core/mvd/advice/` + `core/mvd/publish/`
- **测试**：no-verdict-write、no-test（MVD-DIA-*）、policy 不追溯历史
- **证据**：诊断不改 FinalDecision、不读 test
- **回滚**：纯新增
- **退出条件**：诊断/建议不改 verdict、不读 test、风险动作门禁

#### WP-09 Migration｜DEV-CORE-01 + DEV-VCS-01
- **输入**：V3.0 §16（shadow/replay/cutover/retire）
- **输出**：C1-C4 replay、shadow diff、single-writer cutover、legacy adapter
- **代码**：`core/mvd/migration/` + `loop.py` 的 `_machine_judge` 改造为 orchestration shell
- **测试**：C1-C4 真实回放、shadow diff 全归因（MVD-MIG-*）
- **证据**：diff report、single-writer proof
- **回滚**：cutover 有 feature flag 回切；legacy adapter 有删除版本
- **退出条件**：shadow 无未解释差异，新路径唯一写者

#### WP-10 Independent QA｜QA-01
- **输入**：全部 WP 输出 + V3.0 §20 门禁
- **输出**：合同/架构/负向/E2E 测试、Gate 报告、finding matrix
- **代码**：`tests/qa/mvd/`（独立，不参与迭代）
- **测试**：全部门禁 + 独立 E2E
- **证据**：QA report/finding matrix
- **回滚**：QA 不签名则不进入下一 Gate
- **退出条件**：QA-01 独立签署，不依赖开发 Agent 自证

---

## 4. Gate 1—3 交付计划

### 4.1 Gate 1：合同基线准备（CURRENT_GATE）

**产出物**：
1. 本设计吸收矩阵（§2）✅ 已完成
2. WP 依赖图（§3.1）✅ 已完成
3. **Study Contract 模板冻结**（V3.0 §6）：需含 budget/metric/seeds/bar/constraints/protected paths
4. **首个 Study Contract 草案**：supervised_holdout + Qwen 微调回归
5. **ADR**：V3.0 吸收 ADR、C1 Owner 决策 ADR（DRAFT）
6. **Traceability Matrix**：P0 → WP → 测试 ID → 代码模块

**Gate 1 PASS 条件**：
- Owner 批准 V3.0（`OWNER_DECISION=APPROVE_FINAL_ARCHITECTURE_V3_0`）
- Study Contract 模板冻结且 Owner 批准
- Pydantic v2 + pyright strict 技术选型确认
- C1 provisional 决策保持 DRAFT（不默认生效）

### 4.2 Gate 2：合同/运行/评估基线

**前置**：Gate 1 PASS

**产出物**：
- WP-01 完成：Pydantic strict models + JSON Schema + PolicyBundle
- WP-02 完成：ExecutionResult 双层预算
- WP-03 完成：MetricObservation/paired delta/uncertainty/bar
- Contract rejection + golden cases 测试全绿

**Gate 2 PASS 条件**：
- 非法构造/JSON 全部拒绝
- minimize/maximize/多 seed 统计测试全绿
- pyright strict 全绿
- 追踪矩阵无悬挂 P0

### 4.3 Gate 3：决策核心（BUILD_READY）

**前置**：Gate 2 PASS

**产出物**：
- WP-04（artifact）、WP-05（Decision）、WP-06（Commit）完成
- WP-07（isolation）、WP-08（diagnostics/advice）完成
- 全部 P0 单元/性质/golden/枚举穷尽/故障注入测试通过
- `_machine_judge` 仍为旧路径（未接新路径），但新模块已就绪

**Gate 3 PASS 条件（=BUILD_READY）**：
- schemas/Enums/unions + JSON Schema 已版本化
- pyright strict、unit、contract、property tests 全绿
- requirements→design→code→test 追踪矩阵完整
- protected paths/tool policy 可执行
- **QA-01=BUILD_READY**（独立签署，非开发自证）

> **Gate 3 是编码授权门槛**。Gate 3 PASS 前不修改 `_machine_judge` 主判定写路径，不接新路径到真实 loop，不开启自动 KEEP/pilot。

---

## 5. 开放问题 + 需 Human Owner 决策项

| # | 问题 | 类型 | 需要决策 | 当前状态 |
|---|---|---|---|---|
| OB-1 | **V3.0 是否批准为唯一技术设计输入？** | Owner | `APPROVE_FINAL_ARCHITECTURE_V3_0` | PENDING |
| OB-2 | **C1 provisional 决策**（允许 exact APPROVED 建 provisional？） | Owner | 默认 DRAFT 不生效，需显式批准 | DRAFT/NOT_EFFECTIVE |
| OB-3 | **首期 fallback bar 是否预批**？ | Owner | 单次/低重复比较；不得看结果后批准 | PENDING |
| OB-4 | Pydantic v2 + pyright strict 是否加入依赖/CI | 架构 | 引入依赖的代价 vs 合同保障 | PENDING |
| OB-5 | test 独立 namespace/principal 的实现代价（新存储/挂载） | 架构+SEC | 隔离强度 vs 部署复杂度 | PENDING |
| OB-6 | 现有试点（Qwen 微调已跑 7 cycle）是否作为 F5 replay 数据源 | Owner | 用真实 C1-C7 回放 | PENDING |

---

## 6. 风险与回滚计划

### 6.1 风险登记（V3.0 §21 补充交付侧风险）

| 风险 | 等级 | 交付侧控制 |
|---|---|---|
| 迁移工作量大、周期长 | HIGH | 严格 F0-F9 分阶段；每阶段有独立退出条件；禁止跨越 |
| 新模块与旧 `_machine_judge` 并存造成双语义 | HIGH | F6 前新路径只 shadow；cutover 有 feature flag；CI 禁旧业务分支 |
| Pydantic/pyright 引入破坏现有 288 测试 | MEDIUM | 新模块独立目录，不触碰旧路径；回归测试守门 |
| constraint/uncertainty 标定不准 | HIGH | 用试点 C1-C7 真实数据标定；Study 预批 policy；HUMAN_REVIEW fallback |
| 交付过程中试点继续跑（无人值守）产生新 champion | MEDIUM | 试点数据仅作 replay fixture，不作为实现输入；cutover 前冻结 |

### 6.2 回滚策略

| 层 | 回滚方式 |
|---|---|
| 代码 | 新模块纯新增（`core/mvd/`），不触碰旧路径；可整体 git revert |
| 判定 | cutover 前旧 `_machine_judge` 保留；feature flag 切换唯一 writer |
| 数据 | ledger 追加式，可重放；provisional 未批准前不产生 champion mutation |
| 依赖 | Pydantic 为新增依赖，失败可移除 |

---

## 7. 交付节奏与里程碑（建议）

| 里程碑 | 内容 | 依赖 |
|---|---|---|
| M1 | Gate 1 PASS：Owner 批准 + Study 模板冻结 | OB-1..3 决策 |
| M2 | Gate 2 PASS：contracts/runner/eval 全绿 | M1 |
| M3 | Gate 3 PASS（BUILD_READY）：决策核心 + QA-01 签署 | M2 |
| M4 | F3-F5：transaction/isolation/replay/shadow | M3 |
| M5 | F6 cutover：single writer | M4 |
| M6 | F7-F8：diagnostics + pilot | M5 |
| M7 | F9 / Gate 5-6：受控 24x7（需单独授权） | M6 |

**当前处于 M1（Gate 1 准备）**。

---

## 8. 对技术经理执行清单（V3.0 §22）的回应状态

| §22 问题 | 回应 |
|---|---|
| 1. 哪个 commit/包实现每个 P0？ | 见 §2 吸收矩阵 → WP 映射 |
| 2. Pydantic/pyright/JSON Schema CI 强制？ | WP-01 + CI gate（Gate 2） |
| 3. 完整 union variant 代数 + 未知 fail-closed？ | WP-05 + 枚举穷尽测试 |
| 4. minimize/maximize 唯一归一？ | WP-03，比较器只归一一次 |
| 5. 无 champion 为何不构 comparison？ | ChampionRouter（P0-005） |
| 6. C1 DRAFT/APPROVED/EXPIRED 测试？ | WP-05 BSL-003/004 + 三态 |
| 7. provisional 为何不自动 KEEP？ | BaselinePolicy（P0-013） |
| 8. 硬约束完整性防 missing/duplicate/extra？ | ConstraintEvaluator complete 校验 |
| 9. uncertainty unavailable vs policy invalid？ | DecisionBar 区分 |
| 10. 谁写 champion？其他不能？ | PromotionCommitter + ACL |
| 11. test namespace 对 iterative 不可见？ | WP-07 非干扰测试 |
| 12. manifest/ledger/CAS 崩溃恢复？ | WP-04/06 故障注入 |
| 13. legacy 何时删 + 不双写？ | WP-09，F6 cutover |
| 14. 历史 C1-C4 replay golden bundle？ | WP-09 + 试点 fixture |
| 15. 独立 QA 位置？ | WP-10，QA-01 |

---

## 9. 本轮交付结论

**交付规划已产出，未编码。** 当前状态：
- `DESIGN_ABSORBED=YES`
- `IMPLEMENTATION_AUTHORIZED=NO`
- `OPEN_BLOCKERS=3`（OB-1 V3.0 批准、OB-2 C1 决策、OB-3 fallback bar 预批）

**下一步（需 Human Owner 决策后推进）**：
1. 批准 V3.0（OB-1）
2. 决策 C1 provisional（OB-2，默认 DRAFT）
3. 预批 fallback bar（OB-3）
4. 批准进入 Gate 1 冻结 Study Contract

在获得上述授权前，不进入编码、不改 `_machine_judge`、不开启任何 pilot/KEEP/24x7。

（试点后台继续无人值守运行，数据仅作为 F5 replay fixture，不作为实现输入。）
