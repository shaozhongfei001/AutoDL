# auto-deep-researcher-24x7 SDD 角色、权限与交接规范

**规范编号：** ADR24X7-SDD-ROLES-V0.1  
**状态：** CONTRACT_CANDIDATE  

## 1. 角色设计原则

1. 规格批准、代码实现、实验评估、代码晋级和独立 QA 必须逻辑分离。
2. 小型试点中一个人可兼任多个开发角色，但 HUMAN_OWNER、Promotion 权限和 QA 独立性不得被 Code Agent 合并。
3. Agent 角色按最小权限运行；没有明确授权即禁止。
4. LLM 负责提出假设、实现和解释；确定性组件负责校验、计时、评估、判定与晋级。
5. 任何角色发现上游规格问题都必须退回，不得静默补写后自签通过。

## 2. 治理角色

### 2.1 HUMAN_OWNER｜项目 Owner／研究目标与风险责任人

**使命**

- 决定项目目标、风险容忍度、试点范围和 24x7 授权。

**拥有权限**

- 批准或退回 SDD 总契约。
- 批准 C3 变更、首个 Study、Pilot 和 Unattended 运行。
- 撤销自动晋级授权和冻结冠军版本。

**必须输出**

- Owner Decision Record。
- 试点边界、资源上限、人工介入条件。
- Gate 1、Gate 5、Gate 6 的最终批准。

**禁止事项**

- 不以口头偏好替代版本化合同。
- 不绕过 QA 直接声明生产就绪。

### 2.2 MAIN-00｜SDD Baseline Owner／Change Control Lead

**使命**

- 维护项目唯一权威入口、规格基线、状态和变更控制。

**拥有权限**

- 接收角色交付。
- 判定材料是否具备进入下一 Gate 的形式条件。
- 批准 C0，组织 C1/C2/C3 裁决。

**必须输出**

- PROJECT_STATUS 更新。
- 基线索引、变更台账、开放问题清单。
- Gate 0 证据闭合包。

**禁止事项**

- 不替代 ARCH-01 设计技术实现。
- 不替代 QA-01 自签合并门禁。
- 不把未确认事实写成已确认基线。

### 2.3 ARCH-01｜Experiment Contract & Platform Architecture Lead

**使命**

- 将总契约转化为可实现的 HLD、ADR、schema、接口和状态模型。

**拥有权限**

- 定义组件边界、合同校验、计时模型、worktree 策略、制品与 ledger 设计。
- 审核 C1/C2 技术影响。

**必须输出**

- HLD 总册。
- Budget/Evaluation/Data/Environment/Promotion ADR。
- Study、Experiment、Manifest、Ledger schema。
- 需求—设计—测试追踪矩阵。

**禁止事项**

- 不修改 Owner 批准的研究目标。
- 不用“Git reset 更简单”等理由放宽共享工作区保护。
- 不把设计完整度写成真实系统已实现。

### 2.4 SEC-01｜Security, Tooling & Supply-chain Review Lead

**使命**

- 控制 Agent 工具权限、命令、网络、密钥、依赖和制品访问。

**拥有权限**

- 阻断密钥风险、危险命令、未批准依赖和越界网络访问。

**必须输出**

- Tool Policy、Protected Paths、Dependency Policy。
- secret scan、依赖扫描、命令策略和 sandbox 测试报告。

**禁止事项**

- 不以安全名义修改评估业务规则。
- 不静默接受长期例外。

### 2.5 QA-01｜Independent QA／Architecture Review／Merge Gate

**使命**

- 独立审计规格覆盖、实现一致性、负向路径、证据链和可合并性。

**拥有权限**

- 输出 PASS、CONDITIONAL_PASS 或 BLOCKED。
- 提交 BLOCKER/MAJOR/MINOR/NOTE Finding。
- 要求开发角色补证、整改和回归。

**必须输出**

- Gate Review Report。
- Finding Matrix。
- Contract-to-Test Traceability。
- 残余风险与 Owner 决策项。

**禁止事项**

- 不用大段补写源码或规格掩盖结构性问题。
- 不在发现问题后自行修复并宣布通过。
- 不承担被审实现的主要作者角色。

## 3. 开发角色

### 3.1 DEV-CORE-01｜Orchestrator, State & Ledger Lead

**负责**

- 主状态机、Contract Validator 集成、事件账本、恢复和幂等。

**交付**

- 状态转换实现、ledger append-only、replay/recovery、接口测试。

**不得**

- 自行决定评估指标。
- 直接执行冠军分支晋级。

### 3.2 DEV-RUN-01｜Runner, Backend & Budget Lead

**负责**

- local/SSH/Slurm adapter、预算注入、单调计时、硬超时、进程终态。

**交付**

- Runner 接口、Budget Adapter、计时分项、backend 合同测试。

**不得**

- 将 poll_interval 当预算。
- 在 backend 间绕过 hardware cohort。
- 判断 KEEP/DISCARD。

### 3.3 DEV-EVAL-01｜Evaluation & Statistics Lead

**负责**

- validation evaluator、指标 schema、多种子聚合、噪声基线和 comparability gate。

**交付**

- 评估器 hash、指标 parser、统计晋级输入、test 隔离机制。

**不得**

- 修改候选训练代码。
- 把 test 指标反馈给逐轮 Agent。
- 为提升通过率修改阈值。

### 3.4 DEV-VCS-01｜Workspace, Artifact & Promotion Lead

**负责**

- worktree 生命周期、候选提交、制品清单、乐观锁和冠军推进。

**交付**

- Workspace Manager、Artifact Manager、Promotion Manager、清理与恢复测试。

**不得**

- 在共享工作区做破坏性操作。
- 在 manifest 不完整时晋级。
- 合并 STALE_CANDIDATE。

### 3.5 DEV-OBS-01｜Monitor & Observability Lead

**负责**

- 零 LLM 监控、资源采集、结构化日志、通知和连续失败熔断。

**交付**

- Monitor、事件/轮询策略、指标与日志 schema、告警测试。

**不得**

- 修改代码。
- 用 LLM 参与正常监控循环。
- 自行修复或晋级。

> 首个试点中 DEV-CORE-01、DEV-RUN-01、DEV-VCS-01 可由同一人负责，但代码必须分模块、权限必须在运行时保持分离；DEV-EVAL-01 与 QA-01 不应由被审代码的同一 Agent 会话承担。

## 4. 运行时 Agent 角色

### 4.1 LEADER-AGENT｜Hypothesis & Planning Agent

**输入**

- 已批准 Study Contract、冠军摘要、允许暴露的 validation 结果、dead-end 记忆和资源余量。

**输出**

- 结构化 hypothesis、预期机制、实验风险、请求的 change scope。

**允许**

- 提出实验。
- 请求 HUMAN_REVIEW。

**禁止**

- 直接写代码。
- 查看 test 结果。
- 修改 Study Contract 或 promotion policy。
- 直接执行 Git 晋级。

### 4.2 CODE-AGENT｜Isolated Implementation Agent

**输入**

- 已批准 Experiment Contract、隔离 worktree、allowlist、测试命令。

**输出**

- 候选代码、显式提交、diff metrics、单元/合同测试结果。

**允许**

- 修改 allowlist 内的文件。
- 运行批准的开发测试。

**禁止**

- 修改 protected boundaries。
- 扩大依赖或网络权限。
- 在共享树写入。
- 启动 test 集评估。
- 决定 KEEP/DISCARD。

### 4.3 MONITOR-AGENT｜Deterministic Monitor

此角色名称保留 Agent 语义，但实现必须是确定性程序，正常路径不调用 LLM。

**输入**

- pid/job_id、log_file、hard deadline、resource limits。

**输出**

- process events、resource events、terminal state、日志引用。

**禁止**

- 生成或修改代码。
- 改变 budget。
- 解释指标并晋级。

### 4.4 REFLECT-AGENT｜Advisory Reflection Agent

**输入**

- 结构化 validation 指标、diff 摘要、约束结果、历史 dead ends。

**输出**

- 原因解释、后续假设、复杂度分析、是否建议人工审阅。

**禁止**

- 修改机器 verdict。
- 读取 test 结果。
- 调用 Promotion Manager。

### 4.5 DECISION-ENGINE｜Deterministic Policy Actor

它不是自由推理 Agent，而是批准策略的确定性执行者。

**负责**

- comparability、约束、统计阈值、复杂度和人工复核规则。

**输出**

- KEEP、DISCARD、HUMAN_REVIEW、INCOMPARABLE 或 BLOCKED。

### 4.6 PROMOTION-MANAGER｜Controlled Git Actor

**输入**

- 已固化 manifest、机器 verdict、candidate SHA、champion_before_sha。

**唯一允许动作**

- 校验全部 Gate 后，以批准方式推进冠军引用。

**禁止**

- force push。
- 处理 dirty shared tree。
- 合并过期候选。

## 5. RACI 矩阵

R=负责执行，A=最终负责/批准，C=协商，I=知会。

| 活动 | OWNER | MAIN | ARCH | DEV | SEC | QA | Runtime Agents |
|---|---|---|---|---|---|---|---|
| 批准 SDD 总契约 | A | R | C | I | C | C | I |
| Gate 0 证据闭合 | I | A/R | C | C | C | C | I |
| 创建 Study Contract | A | C | R | C | C | C | I |
| HLD/ADR | I | C | A/R | C | C | C | I |
| 实现 P0 | I | I | A | R | C | C | I |
| Tool/安全策略 | I | C | C | C | A/R | C | I |
| Experiment hypothesis | I | I | A | I | I | I | R |
| 候选代码实现 | I | I | A | C | I | I | R |
| validation 评估 | I | I | A | R | I | C | C |
| 机器 verdict | I | I | A | C | I | C | R |
| 冠军晋级 | I | I | A | R | I | C | C |
| 独立合并门禁 | I | I | C | I | C | A/R | I |
| Pilot 授权 | A | R | C | I | C | C | I |
| 24x7 授权 | A | R | C | I | C | C | I |

## 6. 职责分离硬规则

| 规则 | 要求 |
|---|---|
| SOD-001 | Code Agent 不得同时拥有 Promotion Manager 凭证或接口权限。 |
| SOD-002 | Reflect Agent 的建议不得直接写入冠军引用。 |
| SOD-003 | Evaluator 不得修改候选代码或 Study 指标。 |
| SOD-004 | QA-01 不得作为被审 P0 实现的主要作者。 |
| SOD-005 | HUMAN_OWNER 的批准不得由 Agent 模拟或代签。 |
| SOD-006 | test 评估结果不得进入 Leader、Code 或 Reflect 的逐轮上下文。 |
| SOD-007 | MAIN-00、ARCH-01、QA-01 的 Gate 状态必须分别记录，不得用一个 PASS 替代。 |

## 7. 角色交接包

每个角色向下游交接时至少提供：

1. handoff_id、角色、版本、日期。
2. 权威输入和对应 hash/版本。
3. 已完成范围与未完成范围。
4. 交付文件索引。
5. 测试与证据。
6. Finding、风险、开放问题。
7. 当前 Gate 和允许的下一动作。
8. 明确禁止下游假设的事项。

推荐状态头：

    HANDOFF_ID=<ID>
    SOURCE_ROLE=<ROLE>
    TARGET_ROLE=<ROLE>
    BASELINE_VERSION=<VERSION>
    CURRENT_GATE=<GATE>
    STATUS=<READY|PARTIAL|BLOCKED>
    IMPLEMENTATION_AUTHORIZED=<YES|NO>
    OPEN_BLOCKERS=<COUNT>

## 8. 人类必须介入点

| 时点 | 必须介入的人类角色 | 不可委托给 Agent 的决定 |
|---|---|---|
| SDD 契约批准 | HUMAN_OWNER | 是否接受风险、范围和角色边界 |
| 首个 Study 冻结 | HUMAN_OWNER＋ARCH-01 | 研究目标、数据职责、预算和指标 |
| test 集首次启用 | HUMAN_OWNER＋QA-01 | 是否允许独立验收及结果使用范围 |
| 高复杂度微小收益 | HUMAN_OWNER 或授权专家 | 是否接受复杂度债务 |
| 依赖/网络/密钥例外 | SEC-01＋HUMAN_OWNER | 是否接受供应链与数据风险 |
| Gate 5 Pilot | HUMAN_OWNER＋QA-01 | 是否进入真实受控运行 |
| Gate 6 24x7 | HUMAN_OWNER＋QA-01＋SEC-01 | 是否开启无人值守晋级 |
| 任何 BLOCKER 豁免 | HUMAN_OWNER | 是否允许一次性替代控制 |

