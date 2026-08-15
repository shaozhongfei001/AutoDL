# auto-deep-researcher-24x7 SDD 阶段门禁、状态机与独立 QA

**规范编号：** ADR24X7-SDD-GATES-QA-V0.1  
**状态：** CONTRACT_CANDIDATE  

## 1. Gate 总览

| Gate | 名称 | 核心问题 | 通过后允许动作 |
|---|---|---|---|
| G0 | Evidence Closure | 对现状的判断是否有完整源码和可复核证据？ | 编制正式 Study 与 HLD |
| G1 | Contract Baseline | 目标、预算、数据、评估、角色和约束是否冻结？ | 详细设计 |
| G2 | HLD Approval | 设计是否完整实现 P0 合同且无职责混淆？ | 任务拆分与编码 |
| G3 | Build Readiness | schema、测试、工具权限和开发环境是否可执行？ | P0 实现 |
| G4 | Integration & Recovery | 端到端闭环和故障恢复是否通过？ | 受控试点准备 |
| G5 | Controlled Pilot | 单任务、单并发试点是否安全、有效、可复现？ | 申请有限 24x7 |
| G6 | Unattended 24x7 | 熔断、资源、通知、恢复和人工撤销是否成熟？ | 有限无人值守运行 |

Gate 不允许跳跃。CONDITIONAL_PASS 只允许处理明示的非阻塞条件，不等于下一 Gate 自动通过。

## 2. Gate 0｜Evidence Closure

**责任：** MAIN-00  
**独立审阅：** QA-01  

必需输入：

- 当前项目仓库提交号、branch、git status 和目录清单。
- config schema/loader、PROJECT_BRIEF、runner、monitor、dispatcher、tools、agents、ledger 全文件。
- MNIST 试点的 train、validation evaluator、test evaluator、启动命令和完整日志。
- 全仓关键词检索原始命令与输出。
- autoresearch 对应版本的原始 prepare.py、train.py、program.md。

检查：

1. “没有 time budget”“没有 Git/版本闭环”等不存在性结论是否覆盖全仓。
2. 当前 test_accuracy 是否进入逐轮选优。
3. 多 backend、多 Agent、记忆和零 LLM 监控的真实边界。
4. 当前用户修改、分支和制品目录是否存在冲突风险。

退出标准：

- 所有关键事实为 CONFIRMED、REFUTED 或明确 UNKNOWN。
- 两项 P0 与现有实现的重叠范围已识别。
- QA_GATE 不存在 BLOCKER。

## 3. Gate 1｜Contract Baseline

**最终批准：** HUMAN_OWNER  
**组织：** MAIN-00  
**设计责任：** ARCH-01  
**独立审阅：** QA-01  

必需输入：

- 已填写 Study Contract。
- SDD 总契约、约束、角色和本 Gate 规范。
- 数据与 split 职责说明。
- Budget、Evaluation、Environment、Promotion Policy。
- Protected Paths 与 Agent Tool Policy。

退出标准：

1. 所有必填字段完成，hash 和版本规则明确。
2. validation 用于选优、test 用于独立验收。
3. 首个试点固定 hardware cohort、max_parallel=1。
4. change scope 与 protected boundaries 已批准。
5. HUMAN_OWNER_APPROVED=YES。
6. QA_GATE=PASS 或不影响实现边界的 CONDITIONAL_PASS。

## 4. Gate 2｜HLD Approval

HLD 必须覆盖：

- Contract Validator。
- Experiment 状态机与 Ledger 事件。
- Workspace Manager 与冠军/候选分支策略。
- Runner 双层预算与 backend adapter。
- Monitor 零 LLM 路径。
- validation Evaluator 与 test 隔离。
- Artifact Manager 与原子 manifest。
- Decision Engine 与 Promotion Manager。
- 崩溃恢复、幂等、并发和过期候选。
- 权限、安全、依赖和可观测性。

强制 ADR：

| ADR | 决策主题 |
|---|---|
| ADR-001 | Budget mode、计时口径与 hard timeout |
| ADR-002 | validation/test 数据职责 |
| ADR-003 | hardware cohort 与跨后端可比性 |
| ADR-004 | worktree、champion、candidate 与 stale policy |
| ADR-005 | Artifact 存储、hash、原子发布与保留 |
| ADR-006 | Ledger 事件、幂等与恢复 |
| ADR-007 | Promotion Policy、统计阈值与 simplicity |
| ADR-008 | Agent 最小权限和 protected boundaries |

退出标准：

- 每条 P0 约束可追踪到设计对象和测试。
- 设计不存在共享 reset、test 回流、LLM 直接晋级。
- 数据模型支持全部终态与恢复。
- QA_GATE=PASS。

## 5. Gate 3｜Build Readiness

必需输入：

- 已批准 HLD/ADR。
- 版本化 schema 与示例。
- 开发任务分解和 Traceability Matrix。
- 测试计划、fixtures、故障注入计划。
- Agent 工具权限和隔离环境。

退出标准：

1. 每个任务具有 spec IDs、owner、输入、输出、测试和回滚。
2. schema 能拒绝缺失或非法合同。
3. protected paths 在工具层可执行，不只是 prompt。
4. CI 能运行单元、合同、集成、secret 与依赖检查。
5. 工作树基线干净，用户未提交修改得到保护。
6. QA-01 确认 BUILD_READY。

## 6. Gate 4｜Integration & Recovery

必须通过的端到端场景：

1. KEEP：候选在 manifest 完成后成为新冠军。
2. DISCARD：冠军不变，死胡同证据保留。
3. CRASH：无有效指标，不得误判为变差或 KEEP。
4. TIMEOUT：硬超时终止，终态和制品完整。
5. INCOMPARABLE：hash/cohort 不一致，禁止排序。
6. STALE_CANDIDATE：父冠军变化，必须重放重测。
7. dirty shared tree：实验仍隔离，用户修改不受影响。
8. artifact interruption：半成品不得进入 verdict。
9. ledger interruption：重启后恢复到唯一状态。
10. test access attempt：逐轮 Agent 被拒绝。

退出标准：

- 所有 BLOCKER 测试通过。
- 无开放 MAJOR。
- 端到端血缘可从 Study 重放到 champion_after_sha。
- QA_GATE=PASS_FOR_PILOT_CANDIDATE。

## 7. Gate 5｜Controlled Pilot

试点限制：

- 一个 Study。
- 一个固定 hardware cohort。
- max_parallel=1。
- 明确资源预算和运行时段。
- test 集只在 Owner/QA 批准的里程碑使用。
- HUMAN_OWNER 保留停止和撤销权限。

必须完成：

- baseline 按 Statistical Contract 重复。
- 至少一个 KEEP。
- 至少一个 DISCARD。
- 至少一个 CRASH 或 TIMEOUT 演练。
- 至少一次从 ledger 恢复。
- 未发生 test 泄漏、冠军污染、用户修改丢失或制品丢失。

Gate 5 通过只表示可申请 Gate 6，不表示生产就绪。

## 8. Gate 6｜Unattended 24x7

必需能力：

- Study 总资源、日资源和单实验资源上限。
- 连续失败、重复假设和无提升熔断。
- kill switch、暂停、排空和恢复。
- 运行完成、熔断、安全异常和容量异常通知。
- Ledger/Artifact 容量、保留与归档。
- 过期候选并发策略。
- test 集访问隔离。
- 人工撤销冠军和恢复上一冠军演练。
- 安全扫描、依赖锁和凭证隔离。

退出标准：

- SEC-01=PASS。
- QA-01=PASS。
- HUMAN_OWNER 明确授权运行范围和期限。
- PROJECT_STATUS.unattended_24x7_authorized=true。

## 9. 实验状态机

### 9.1 正常主路径

| 当前状态 | 触发条件 | 下一状态 | 必需证据 |
|---|---|---|---|
| PROPOSED | Leader 输出假设 | CONTRACT_PENDING | hypothesis event |
| CONTRACT_PENDING | Experiment Contract 校验通过 | CONTRACT_VALIDATED | contract hash |
| CONTRACT_VALIDATED | worktree 创建、父 SHA 锁定 | ISOLATED | worktree event |
| ISOLATED | Code Agent 提交候选 | PATCH_COMMITTED | candidate SHA、diff hash |
| PATCH_COMMITTED | dry-run 与安全检查通过 | READY_TO_RUN | test events |
| READY_TO_RUN | Runner 启动 | RUNNING | pid/job_id、budget |
| RUNNING | 进程正常结束 | EVALUATING | terminal event |
| EVALUATING | validation 评估完成 | ARCHIVING | metrics event |
| ARCHIVING | manifest 原子发布 | DECIDING | manifest hash |
| DECIDING | Policy 计算 verdict | KEEP/DISCARD/REVIEW | policy version |
| KEEP | Promotion 乐观锁通过 | PROMOTED | champion_after_sha |
| DISCARD | 记录死胡同 | DISCARDED | conclusion event |

### 9.2 异常路径

| 触发 | 终态/中间态 | 处理 |
|---|---|---|
| 合同缺失/非法 | BLOCKED | 返回 ARCH/MAIN 修订 |
| protected path 被修改 | QUARANTINED | 禁止运行和晋级，SEC/QA 审查 |
| 进程异常 | CRASHED | 归档日志和 traceback，冠军不变 |
| 硬超时 | TIMED_OUT | 终止子进程树，归档制品，冠军不变 |
| 关键 hash/cohort 不一致 | INCOMPARABLE | 不排序，可创建新 Study |
| 父冠军已变化 | STALE_CANDIDATE | 在新冠军上重放、重测 |
| manifest 不完整 | ARCHIVE_FAILED | 不得进入 DECIDING |
| ledger 写入失败 | RECOVERY_REQUIRED | 暂停动作，恢复后重放事件 |
| test 泄漏 | QUARANTINED | 作废受影响结果，重建干净 Study |

### 9.3 禁止转换

- RUNNING → PROMOTED
- EVALUATING → PROMOTED
- CRASHED/TIMED_OUT/INCOMPARABLE → PROMOTED
- STALE_CANDIDATE → PROMOTED
- ARCHIVE_FAILED → DECIDING
- 任一状态在缺少 Experiment Contract 时 → RUNNING

## 10. 独立 QA 验收矩阵

| Test ID | 关联约束 | 场景 | 预期结果 |
|---|---|---|---|
| QA-CTR-001 | SPC-P0-001, SPC-P0-002 | Study 或 Experiment 合同缺失 | 启动被拒绝 |
| QA-CTR-002 | SPC-P1-007 | brief 与 config 预算冲突 | Validator 报冲突，不猜测优先值 |
| QA-CTR-003 | SPC-P0-003, SPC-P0-004, SPC-P0-005 | Code Agent 修改 protected path 或测试 oracle | 写入被拒绝或实验隔离 |
| QA-EVL-001 | EVAL-P0-001, EVAL-P0-002 | Code/Leader 请求 test 结果 | 权限拒绝且记录安全事件 |
| QA-EVL-002 | EVAL-P0-003, EVAL-P0-004 | evaluator hash 改变 | INCOMPARABLE |
| QA-EVL-003 | EVAL-P0-005 | 指标为空/NaN | CRASHED 或 BLOCKED，不得 KEEP |
| QA-EVL-004 | EVAL-P1-007/008 | 单种子微小提升 | 不得自动 KEEP |
| QA-EVL-005 | EVAL-P1-010 | 运行后降低晋级阈值 | 旧结果不得按新阈值追溯晋级 |
| QA-EVL-006 | EVAL-P0-006 | Reflect Agent 建议覆盖机器 verdict | 建议被拒绝，机器 verdict 保持不变 |
| QA-RUN-001 | RUN-P0-001, RUN-P0-002 | 预算到期 | train 自终止；runner 记录合规 |
| QA-RUN-002 | RUN-P0-002 | 训练拒绝退出 | hard timeout 终止进程树 |
| QA-RUN-003 | RUN-P0-003, RUN-P0-004 | 系统时钟变化 | 单调计时不倒退；分项完整 |
| QA-RUN-004 | RUN-P0-005 | RTX 3060 与 2080 Ti 直接比较 | INCOMPARABLE 或分 cohort |
| QA-RUN-005 | RUN-P1-006/007 | 改变 poll interval | 不改变训练预算，只改变发现延迟 |
| QA-VCS-001 | VCS-P0-001, VCS-P1-008 | shared tree 有用户修改 | 候选隔离，用户修改 hash 不变 |
| QA-VCS-002 | VCS-P0-002 | 尝试共享 reset/clean | 命令被拒绝并告警 |
| QA-VCS-003 | VCS-P0-003, VCS-P0-004, VCS-P0-005 | 候选父 SHA 非冠军或运行期间冠军变化 | 创建或晋级被拒绝，旧候选标记 STALE |
| QA-VCS-004 | VCS-P0-006 | DISCARD/CRASH/TIMEOUT | champion SHA 不变 |
| QA-ART-001 | ART-P0-001 | manifest 前触发 reflect | 判定被拒绝 |
| QA-ART-001A | ART-P0-002 | 尝试把 checkpoint 或大型日志提交到 Git | 提交被阻断 |
| QA-ART-002 | ART-P0-003 | 制品 hash 错误 | manifest 校验失败 |
| QA-ART-003 | ART-P0-004, ART-P0-006 | ledger 写一半崩溃 | 重启后恢复唯一状态 |
| QA-ART-004 | ART-P1-008 | manifest 半写 | 不可见或标记不完整 |
| QA-ART-005 | ART-P0-005 | verdict 缺少代码、合同、环境、manifest 或策略引用 | verdict 事件被拒绝 |
| QA-AGT-001 | AGT-P0-001, AGT-P0-002 | Code/Reflect 调用 promotion | 权限拒绝 |
| QA-AGT-002 | AGT-P0-003 | Monitor 正常轮询 | LLM 调用计数为 0 |
| QA-AGT-003 | AGT-P0-004 | 提交中含假密钥 | secret scan 阻断 |
| QA-QLT-001 | QLT-P1-001/002 | 微小提升＋大幅复杂度 | HUMAN_REVIEW |
| QA-E2E-001 | 多项 | 完整 KEEP | manifest 完成后冠军推进 |
| QA-E2E-002 | 多项 | 完整 DISCARD | 冠军不变，死胡同可检索 |
| QA-E2E-003 | 多项 | 进程在各阶段中断 | 每个阶段均可恢复或明确隔离 |

## 11. QA Finding 格式

每个 Finding 必须包含：

- finding_id
- severity
- violated_contract_ids
- affected_files/components
- evidence
- risk
- required_remediation
- owner
- retest_ids
- status

QA 不得只写“建议优化”；必须指明违反的合同和可验证整改。

## 12. Gate 报告格式

    GATE_ID=<G0..G6>
    REVIEW_OBJECT=<PACKAGE_OR_COMMIT>
    BASELINE_VERSION=<VERSION>
    QA_GATE=<PASS|CONDITIONAL_PASS|BLOCKED>
    BLOCKER_COUNT=<N>
    MAJOR_COUNT=<N>
    MINOR_COUNT=<N>
    RESIDUAL_RISK=<LOW|MEDIUM|HIGH>
    NEXT_AUTHORIZED_ACTION=<ACTION>
    PRODUCTION_READY=<YES|NO>
    FROZEN=<YES|NO>

## 13. 独立 QA 合并规则

- 任一开放 BLOCKER：BLOCKED。
- 任何影响 P0 的开放 MAJOR：BLOCKED。
- 仅有不影响安全、不影响可比性且有 Owner/期限的 MAJOR：可考虑 CONDITIONAL_PASS。
- 文档通过不代表代码通过；代码通过不代表 Pilot 通过。
- QA_PASS 与 DEV_SELF_CHECK_PASS 必须分开记录。
- 未通过 Gate 6 不得把系统描述为 24x7 自动晋级就绪。
