# auto-deep-researcher-24x7 SDD 项目开发总契约

**契约编号：** ADR24X7-SDD-CONTRACT-V0.1  
**契约状态：** CONTRACT_CANDIDATE  
**生效条件：** HUMAN_OWNER 明确批准，并将 PROJECT_STATUS.yaml 中 owner_approved 改为 true  
**当前实施授权：** NO  

---

## 1. 契约目标

本契约定义 auto-deep-researcher-24x7 的规格驱动开发边界，使系统能够在不污染共享代码、不破坏评估独立性、不丢失实验制品的前提下，持续提出、执行、评估并晋级模型实验。

项目完成后应具备：

1. 每个 Study、每次 Experiment 都有机器可读且版本化的合同。
2. 同一 Study 内的候选只能在满足可比性门禁时排序。
3. Agent 只能在隔离 worktree 和批准的 change scope 内修改代码。
4. validation 指标用于候选选优，test 指标不进入逐轮反馈。
5. 代码、合同、数据、环境、指标、模型和决定具有端到端血缘。
6. KEEP、DISCARD、CRASH、TIMEOUT、INCOMPARABLE 和 STALE_CANDIDATE 都有确定状态和恢复路径。
7. 24x7 无人值守不是默认能力，只有 Gate 6 通过后才可授权。

## 2. 非目标

本阶段不承诺：

- 在不同任务之间用一个分数直接比较模型优劣。
- 在不同 GPU 代际、不同并行规模间把相同墙钟时间视为同等算力。
- 以 LLM 的叙述性反思替代机器评估和晋级策略。
- 将大型模型、checkpoint 或训练日志写入 Git 历史。
- 在首个试点中开放多候选并发晋级。
- 在未完成安全与恢复测试前进入生产或长期无人值守运行。

## 3. 权威输入与优先级

发生冲突时，按以下顺序裁决：

| 层级 | 权威材料 | 说明 |
|---|---|---|
| L0 | HUMAN_OWNER 明确决定、批准记录 | 最高业务与风险裁决 |
| L1 | 已批准的 SDD 总契约、约束规范、角色规范、Study Contract | 开发与运行的正式基线 |
| L2 | 已批准 HLD、ADR、接口合同、数据与状态模型 | 技术设计基线 |
| L3 | 已批准 Experiment Contract、Change Request | 单次实验和变更授权 |
| L4 | 代码、自动化测试、schema、策略配置 | 必须实现上层规格，不得反向覆盖 |
| L5 | 运行日志、实验台账、模型制品、QA 证据 | 证明实现和运行事实 |
| L6 | Agent 记忆、prompt、自述、临时笔记 | 非权威参考，不得单独驱动晋级 |

冲突处理规则：

- 低层材料与高层基线冲突时，低层材料必须停止使用并提交 Finding。
- 未批准的新需求不得以“实现方便”为由进入代码。
- Agent 不得静默修正合同；任何合同修改都必须生成 Change Request。
- 当前证据未闭合的事实必须标注 UNKNOWN 或 LIKELY，不得写成 CONFIRMED。

## 4. 项目范围

### 4.1 P0-EXP-VALIDITY：实验有效性合同

必须实现以下子合同：

| 子合同 | 必填内容 | 机器门禁 |
|---|---|---|
| Budget Contract | 预算类型、目标值、硬超时、热身与编译计时口径 | 超预算或计时字段缺失不得比较 |
| Evaluation Contract | 主指标、方向、单位、评估器、重复次数、最小有效改进 | 评估器 hash 或规则不一致时 INCOMPARABLE |
| Data Contract | 数据集、版本、split、预处理、tokenizer、指纹 | 数据或 split 指纹不一致时 INCOMPARABLE |
| Environment Contract | 硬件 cohort、GPU 数、驱动、CUDA、框架、镜像或依赖锁 | cohort 不一致时禁止自动排序 |
| Statistical Contract | seeds、聚合方法、噪声基线、置信规则 | 重复数不足时不得自动 KEEP |
| Resource Contract | 显存、参数量、磁盘、成本或时长上限 | 违反硬约束时自动 BLOCK |

### 4.2 P0-EXP-TRANSACTION：候选实验事务合同

必须实现：

- 冠军分支与候选分支分离。
- 每个候选使用独立 worktree 或等价隔离工作区。
- 候选提交前记录 champion_before_sha。
- 运行完成后先固化 Artifact Manifest，再进入判定。
- KEEP 只能在父冠军未变化时 fast-forward。
- 父冠军变化时标记 STALE_CANDIDATE，并在新冠军上重放和重测。
- DISCARD、CRASH、TIMEOUT 不得改变冠军分支。
- 共享工作区禁止破坏性 reset、clean 或 force push。
- 候选 worktree 清理后，ledger、代码差异和制品仍可复现实验。

### 4.3 P1 范围

- 任务级 change scope 和受保护路径。
- simplicity 的结构化判定。
- 多 backend 的 hardware cohort 管理。
- 多 Agent 并发和乐观锁。
- 连续失败熔断、资源配额和通知。
- 账本重放、崩溃恢复和制品保留策略。

## 5. 规格对象

### 5.1 Project Contract

定义整个项目不变量、权威层级、角色、门禁和完成条件。本文件即项目总契约。

### 5.2 Study Contract

定义一个连续研究专题的稳定比较边界。Study 一旦进入 BASELINED，以下字段不得由普通实验修改：

- research_objective
- dataset 与 split
- evaluator
- primary metric 与 direction
- budget mode
- hardware cohort
- promotion policy
- protected paths

Study 变更必须升级版本；影响可比性的变更应创建新 Study，不得与旧 Study 直接排序。

### 5.3 Experiment Contract

定义单个候选的：

- hypothesis 与预期机制
- champion_before_sha
- 允许修改范围
- 预算与评估合同引用
- seeds 与重复计划
- 风险、复杂度预估
- 终态、制品和判定

### 5.4 Change Request

任何超出已批准 Experiment Contract 的变更必须先提交 Change Request。至少包含：

- 变更原因与范围
- 受影响规格、代码和测试
- 是否破坏历史可比性
- 数据、评估、安全和回滚影响
- Owner 或相应基线责任人的决定

### 5.5 Artifact Manifest

制品清单必须列出文件、大小、SHA-256、类型、生成阶段、保留期限和访问位置。清单自身也必须有哈希。

### 5.6 Ledger Event

实验账本采用只追加事件。不得覆盖历史事件以伪装状态变化。每个事件至少包含：

- schema_version、event_id、event_type、timestamp
- study_id、experiment_id、cycle
- actor 与 policy_version
- champion_before_sha、candidate_sha、champion_after_sha
- contract hashes、environment hash、artifact manifest hash
- process status、terminal state、verdict、promotion status

## 6. 逻辑组件责任边界

| 组件 | 允许职责 | 禁止职责 |
|---|---|---|
| Contract Validator | 校验 Study/Experiment 合同、指纹、必填字段 | 修改合同以让校验通过 |
| Workspace Manager | 创建隔离 worktree、保护共享工作区、清理已归档候选 | 在共享树执行破坏性回退 |
| Code Worker | 在 allowlist 内实现一个已批准假设 | 修改评估器、数据、治理规格或自行扩大范围 |
| Runner | 注入预算、启动进程、执行硬超时、采集退出状态 | 判断 KEEP/DISCARD |
| Monitor | 零 LLM 等待、健康检查、日志与资源采集 | 修改代码、指标或晋级状态 |
| Evaluator | 在固定 validation 数据和评估器上产生结构化指标 | 读取 test 结果后反馈给逐轮开发 |
| Artifact Manager | 固化日志、模型、环境、diff 和 manifest | 在 manifest 完成前删除临时结果 |
| Decision Engine | 依据批准策略计算 KEEP/DISCARD/REVIEW/INCOMPARABLE | 依据 LLM 自述绕过结构化规则 |
| Promotion Manager | 校验父 SHA 并推进冠军分支 | merge 过期候选或 force push |
| Ledger | 追加状态事件、支持恢复和审计 | 覆盖或删除已提交事件 |

## 7. 项目不变量

以下条件在任何阶段都必须为真：

1. 只有一份机器权威 Study Contract。
2. 每个运行中的实验都能解析到一个已批准的 Study 和一个 Experiment Contract。
3. 候选工作区与共享工作区隔离。
4. 评估器、数据和治理规格在实验前后 hash 相同。
5. validation 与 test 的职责不可互换。
6. 任何自动晋级都有结构化指标、合同 hash、制品 manifest 和策略版本。
7. 任何失败或不可比较实验都不改变冠军 SHA。
8. 大型制品不进入 Git。
9. 未提交用户修改不得被 Agent 覆盖、暂存或删除。
10. 任何状态都可以通过 ledger 和制品恢复或解释。

违反任一不变量时：

- 当前实验立即进入 BLOCKED 或 QUARANTINED。
- 禁止执行晋级。
- 生成 BLOCKER Finding。
- 由 MAIN-00、ARCH-01 或 QA-01 按责任边界处理。

## 8. 开发流程契约

### 8.1 Spec

- 先完成 Study Contract、接口合同、状态模型和验收矩阵。
- 每条需求必须有 ID、责任角色、验收方法和证据位置。
- 未明确字段不得由开发者或 Agent 自行猜测为正式值。

### 8.2 Design

- HLD 必须覆盖合同验证、工作区隔离、预算执行、评估、制品、ledger、判定和晋级。
- 关键选择必须记录 ADR，包括计时口径、Git 策略、制品存储和统计晋级规则。
- HLD 不得反向放宽 SDD 约束。

### 8.3 Develop

- 每个开发任务绑定一个规格 ID 和测试 ID。
- 每次提交只实现已批准范围。
- 禁止使用宽泛暂存；只允许显式暂存本任务文件。
- 依赖变化必须单独审批并更新 lockfile。

### 8.4 Verify

- 单元测试验证局部逻辑。
- 合同测试验证 schema 与拒绝路径。
- 集成测试验证状态与组件协作。
- 故障注入验证 crash、timeout、账本恢复和制品保全。
- 独立 QA 验证不可由开发角色自签通过。

### 8.5 Promote

- 开发代码合并与实验冠军晋级是两种不同动作，必须分别留痕。
- 代码合并要求 QA merge gate。
- 实验晋级要求 comparability gate、artifact gate 和 promotion gate。

## 9. 状态语义

项目状态：

- CONTRACT_CANDIDATE：契约待 Owner 审批。
- BASELINE_APPROVED：规格可用于设计。
- DESIGN_APPROVED：允许编码。
- PILOT_READY：允许单任务受控试点。
- UNATTENDED_READY：允许有限 24x7 运行。
- PRODUCTION_READY：通过生产级安全、运维和容量门禁。
- FROZEN：对应版本不得无变更请求修改。

实验终态：

- PROMOTED：候选成为新冠军。
- DISCARDED：可比较但未满足晋级规则。
- INCOMPARABLE：关键合同或 cohort 不一致。
- CRASHED：程序异常或无有效指标。
- TIMED_OUT：触发硬超时。
- BLOCKED：合同、权限、安全或证据门禁失败。
- QUARANTINED：出现可能污染评估或制品的严重异常。

“没有提升”不能写成 CRASH；“运行成功”也不能自动写成 KEEP。

## 10. 可追踪性契约

每条实现必须形成以下链路：

**需求 ID → 设计对象 → 代码提交 → 测试 ID → 测试结果 → QA Finding/结论 → Gate 决定**

每个实验必须形成：

**Study hash → Experiment hash → champion_before_sha → candidate_sha → environment hash → metric events → artifact manifest hash → verdict → champion_after_sha**

缺少任一关键环节时，不得声明可复现或可审计。

## 11. 完成定义

### 11.1 P0 开发完成

只有同时满足以下条件，P0 才可标记 DONE：

1. Study/Experiment/Artifact/Ledger schema 已版本化并有拒绝测试。
2. 预算自终止和 runner 硬超时均通过。
3. validation/test 隔离通过污染测试。
4. 独立 worktree、冠军分支和过期候选策略通过。
5. KEEP、DISCARD、CRASH、TIMEOUT、INCOMPARABLE 均有集成测试。
6. 制品先归档、后判定的不变量通过故障注入。
7. ledger 可从中断状态恢复并重放。
8. QA-01 给出 PASS，HUMAN_OWNER 批准进入试点。

### 11.2 首个试点完成

- 固定 hardware cohort，max_parallel=1。
- baseline 至少按批准的重复策略运行。
- 至少完成一个 KEEP、一个 DISCARD 和一个故障场景。
- 未发生共享工作区污染、test 泄漏或制品丢失。
- 结果不外推到其他任务或其他硬件 cohort。

### 11.3 24x7 授权完成

- Gate 6 全部通过。
- 有资源上限、连续失败熔断、停止开关和通知。
- 有账本与制品容量策略。
- 有人工撤销授权和恢复冠军的演练证据。

## 12. 变更控制

变更分级：

| 等级 | 示例 | 批准人 |
|---|---|---|
| C0 | 文案、非语义格式调整 | MAIN-00 |
| C1 | 不改变合同语义的实现修复 | ARCH-01＋QA-01 |
| C2 | schema、状态机、组件接口或保护范围变化 | MAIN-00＋ARCH-01＋QA-01 |
| C3 | 数据 split、评估器、主指标、预算模式、晋级策略变化 | HUMAN_OWNER；通常创建新 Study |

任何影响历史可比性的 C3 变更，不允许用覆盖旧合同的方式处理。

## 13. 生效与签署

在以下记录完成前，本契约仅为候选：

| 角色 | 决定 | 签署标识 | 日期 |
|---|---|---|---|
| HUMAN_OWNER | PENDING | PENDING | PENDING |
| MAIN-00 | REVIEW_PENDING | PENDING | PENDING |
| ARCH-01 | REVIEW_PENDING | PENDING | PENDING |
| QA-01 | INDEPENDENT_REVIEW_PENDING | PENDING | PENDING |

