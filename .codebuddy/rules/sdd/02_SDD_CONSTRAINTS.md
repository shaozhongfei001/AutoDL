# auto-deep-researcher-24x7 SDD 约束与护栏规范

**规范编号：** ADR24X7-SDD-CONSTRAINTS-V0.1  
**状态：** CONTRACT_CANDIDATE  
**适用对象：** 人类开发者、Leader Agent、Code Agent、Runner、Monitor、Evaluator、Decision Engine、Promotion Manager、CI 和运维脚本  

## 1. 规范用语

- MUST：必须满足；违反即门禁失败。
- MUST NOT：严禁；违反即门禁失败并停止相关动作。
- SHOULD：原则上应满足；偏离需要书面理由和批准。
- MAY：允许，但不得破坏 MUST/MUST NOT。

问题等级：

| 等级 | 含义 | 默认处置 |
|---|---|---|
| BLOCKER | 可能污染冠军、破坏评估独立性、丢失用户数据或造成不可恢复状态 | 立即停止、隔离、禁止晋级 |
| MAJOR | 影响可复现性、正确性、恢复或门禁可信度 | 修复并回归后才能继续 |
| MINOR | 不影响核心正确性，但影响维护、清晰度或效率 | 纳入整改计划 |
| NOTE | 建议或观察 | 不阻断 |

## 2. 代码库与工作区约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| VCS-P0-001 | BLOCKER | Agent MUST NOT 在用户共享工作树直接实施实验修改。 | 每个 experiment_id 对应独立 worktree 路径 |
| VCS-P0-002 | BLOCKER | MUST NOT 在共享工作树执行 git reset --hard、git clean -fd/ffdx、checkout 覆盖、force push 或等价破坏动作。 | 命令策略测试、审计日志 |
| VCS-P0-003 | BLOCKER | 候选必须从记录的 champion_before_sha 创建。 | Experiment Contract、Git 祖先校验 |
| VCS-P0-004 | BLOCKER | Promotion 前必须再次验证当前冠军 SHA 等于 champion_before_sha。 | 乐观锁测试 |
| VCS-P0-005 | BLOCKER | 过期候选 MUST 标记 STALE_CANDIDATE，重放并重测后才能晋级。 | 并发冲突测试 |
| VCS-P0-006 | BLOCKER | DISCARD、CRASH、TIMEOUT、INCOMPARABLE 不得改变冠军 SHA。 | 终态集成测试 |
| VCS-P1-007 | MAJOR | 只允许显式暂存任务文件；禁止 git add . 或等价宽泛暂存。 | 提交审计 |
| VCS-P1-008 | MAJOR | 未提交的用户修改 MUST NOT 被 Agent 暂存、修改、删除或移动。 | dirty-tree 保护测试 |
| VCS-P1-009 | MAJOR | 每个候选提交必须包含 experiment_id、spec IDs 和测试引用。 | commit policy |
| VCS-P1-010 | MAJOR | 失败候选分支清理前，必须保留 candidate SHA 或 patch、ledger 与 manifest。 | 清理测试 |

## 3. 规格与变更范围约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| SPC-P0-001 | BLOCKER | 没有 APPROVED Study Contract 的实验不得启动。 | Contract Validator 拒绝测试 |
| SPC-P0-002 | BLOCKER | 没有 Experiment Contract 或合同 hash 不匹配时不得写代码或运行。 | 启动前校验 |
| SPC-P0-003 | BLOCKER | Code Agent 只能修改 change_scope.allowlist 内的路径。 | 越界写入测试 |
| SPC-P0-004 | BLOCKER | 数据、评估器、治理规格、schema 基线、测试 oracle 必须列入 protected boundaries。 | 前后 hash 比较 |
| SPC-P0-005 | BLOCKER | Agent MUST NOT 为让测试通过而修改测试 oracle、评估数据或晋级阈值。 | 受保护路径和 diff 审计 |
| SPC-P1-006 | MAJOR | 超出 Experiment Contract 的变更必须先批准 Change Request。 | 追踪矩阵 |
| SPC-P1-007 | MAJOR | brief 不得维护与机器权威 config 可冲突的第二套预算或指标值。 | 单一来源检查 |
| SPC-P1-008 | MAJOR | 未知信息必须标识 UNKNOWN/PENDING，不得由 Agent 猜测成正式值。 | 文档审计 |
| SPC-P1-009 | MAJOR | 每个实现提交必须可追踪到规格 ID 和测试 ID。 | Traceability 检查 |

## 4. 数据、评估与统计约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| EVAL-P0-001 | BLOCKER | validation split 用于逐轮选优；test split 只用于预先约定的独立验收。 | 调用日志、数据访问审计 |
| EVAL-P0-002 | BLOCKER | test 结果 MUST NOT 进入 Leader/Code Agent 的逐轮上下文或实验假设生成。 | 上下文过滤测试 |
| EVAL-P0-003 | BLOCKER | evaluator、dataset、split、preprocess、tokenizer 的 hash 必须记录且匹配 Study。 | Comparability Gate |
| EVAL-P0-004 | BLOCKER | 任一关键 hash 或 hardware cohort 不一致，终态必须为 INCOMPARABLE。 | 负向测试 |
| EVAL-P0-005 | BLOCKER | 结构化指标缺失、NaN、无单位或方向未知时不得 KEEP。 | 指标 parser 测试 |
| EVAL-P0-006 | BLOCKER | LLM 反思不得覆盖机器计算的 verdict。 | 权限和接口测试 |
| EVAL-P1-007 | MAJOR | 自动 KEEP 必须满足 repeats、seeds、聚合和 min_effect_size。 | 多种子测试 |
| EVAL-P1-008 | MAJOR | baseline 必须按相同合同重复运行并建立噪声范围。 | baseline evidence |
| EVAL-P1-009 | MAJOR | accuracy 等高分区指标应配置次指标与并列规则。 | Study Contract 审查 |
| EVAL-P1-010 | MAJOR | 任何阈值调整必须版本化 promotion policy；不得对已运行结果追溯改阈值。 | policy version 检查 |

## 5. 预算、运行与后端约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| RUN-P0-001 | BLOCKER | Budget Contract 必须定义 mode、limit、hard_wall_clock_limit 和计时口径。 | schema 校验 |
| RUN-P0-002 | BLOCKER | 训练程序负责预算自终止，runner 负责硬超时兜底；二者不可互相替代。 | 双层超时测试 |
| RUN-P0-003 | BLOCKER | 必须使用单调时钟统计主动训练时间。 | 单元测试、代码审查 |
| RUN-P0-004 | BLOCKER | queue、setup、compile、warmup、active_train、eval 和 total wall time 应分项记录。 | ledger 事件 |
| RUN-P0-005 | BLOCKER | 异构硬件、GPU 数量、功耗或关键软件栈不同的实验不得自动排序。 | cohort mismatch 测试 |
| RUN-P1-006 | MAJOR | monitor.poll_interval 不得承担精确预算终止职责。 | 架构与集成测试 |
| RUN-P1-007 | MAJOR | poll interval 应显著小于典型预算，并设置配置上限。 | 配置 validator |
| RUN-P1-008 | MAJOR | 首个试点 max_parallel 必须为 1。 | PROJECT_STATUS 与运行配置 |
| RUN-P1-009 | MAJOR | 24x7 模式必须有总资源配额、连续失败熔断、停止开关和通知。 | Gate 6 故障测试 |
| RUN-P1-010 | MAJOR | backend 排队时间不得计入主动训练预算，但必须记录。 | Slurm/SSH adapter 测试 |

## 6. 制品、账本与恢复约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| ART-P0-001 | BLOCKER | Artifact Manifest 完整固化前不得进入 REFLECT 的晋级判定。 | 故障注入测试 |
| ART-P0-002 | BLOCKER | checkpoint、模型、日志和大型二进制 MUST NOT 写入 Git 历史。 | repository size、ignore policy |
| ART-P0-003 | BLOCKER | 关键制品和 manifest 必须有 SHA-256。 | manifest validator |
| ART-P0-004 | BLOCKER | 账本采用只追加事件；不得覆盖、删除或静默重写历史事件。 | append-only 测试 |
| ART-P0-005 | BLOCKER | 每次 verdict 必须引用 candidate SHA、合同 hash、环境 hash、manifest hash 和 policy version。 | ledger schema |
| ART-P0-006 | BLOCKER | 任何崩溃点恢复后，实验必须进入唯一、可解释的状态。 | crash matrix |
| ART-P1-007 | MAJOR | 清理策略必须区分代码 refs、模型、日志和元数据的保留期限。 | retention policy |
| ART-P1-008 | MAJOR | 制品写入应采用临时文件加原子发布，避免半成品被判为完整。 | 原子性测试 |
| ART-P1-009 | MAJOR | Ledger 与 Artifact Manifest 的交叉引用必须可双向校验。 | integrity scan |

## 7. Agent、工具与依赖约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| AGT-P0-001 | BLOCKER | Code Agent 不得拥有 Promotion Manager 的权限。 | 角色权限测试 |
| AGT-P0-002 | BLOCKER | Reflect Agent 只可建议，不得直接移动冠军分支。 | API 授权测试 |
| AGT-P0-003 | BLOCKER | Monitor 必须保持零 LLM 运行路径；异常时不得自行生成代码修复。 | 调用计数、接口测试 |
| AGT-P0-004 | BLOCKER | Agent 不得读取、打印、写入或提交密钥、令牌及凭证。 | secret scan |
| AGT-P1-005 | MAJOR | 新增依赖必须有批准、来源、版本锁定和安全扫描。 | lockfile、Change Request |
| AGT-P1-006 | MAJOR | Study 可禁止新增依赖；禁止时 Code Agent 必须遵守。 | dependency diff check |
| AGT-P1-007 | MAJOR | Prompt、策略和工具清单必须版本化并记录 hash。 | environment/ledger |
| AGT-P1-008 | MAJOR | Agent 运行必须限制写路径、命令类别、网络域和资源上限。 | sandbox policy |
| AGT-P1-009 | MAJOR | 连续出现相同失败时必须触发 dead-end 规则，不得无限重试同一方案。 | 熔断测试 |

## 8. 复杂度与代码质量约束

| ID | 等级 | 约束 | 验证证据 |
|---|---|---|---|
| QLT-P1-001 | MAJOR | 每个候选记录 changed_files、added_lines、deleted_lines 和 dependency delta。 | diff metrics |
| QLT-P1-002 | MAJOR | 微小指标提升但显著增加复杂度的候选进入 HUMAN_REVIEW。 | promotion policy test |
| QLT-P1-003 | MAJOR | 指标近似相等时，优先更简单、更低资源方案。 | tie-break test |
| QLT-P1-004 | MAJOR | 新状态、新终态或新字段必须有单元、合同和迁移测试。 | coverage matrix |
| QLT-P1-005 | MAJOR | 每项 bug fix 必须先有可失败的回归测试。 | commit/test trace |
| QLT-P1-006 | MAJOR | 不得用捕获所有异常、吞掉错误或伪造默认指标来让流程继续。 | code review、negative tests |
| QLT-P1-007 | MAJOR | 日志必须结构化、可解析，并避免把整份训练日志注入 LLM 上下文。 | parser、context budget test |

## 9. 例外机制

任何 BLOCKER 约束不得由 Agent 自行豁免。例外请求必须包含：

1. 约束 ID。
2. 业务和技术原因。
3. 影响范围与持续时间。
4. 替代控制。
5. 回滚计划。
6. HUMAN_OWNER、MAIN-00、ARCH-01、SEC-01 和 QA-01 的适用批准。

涉及 test 泄漏、共享工作区破坏、评估器篡改、密钥暴露或制品丢失的约束，不得批准常态化豁免。

## 10. 违规状态

- 违反 BLOCKER：实验进入 QUARANTINED；冠军禁止变化；QA_GATE=BLOCKED。
- 违反 MAJOR：实验进入 BLOCKED；整改并完整回归。
- 违反 MINOR：可继续当前非破坏性工作，但不得关闭 Gate 前遗留。
- 同一 BLOCKER 重复发生：暂停 24x7 权限申请并启动根因审查。

