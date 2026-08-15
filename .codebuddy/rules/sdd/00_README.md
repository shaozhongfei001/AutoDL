# auto-deep-researcher-24x7 SDD 开发治理包

**包版本：** V0.1  
**包状态：** CONTRACT_CANDIDATE  
**允许动作：** 审阅、补证、填写模板、详细设计  
**禁止动作：** 未经 Owner 批准直接实施、自动晋级代码、开启 24x7 无人值守循环  

## 1. 目的

本治理包将 AutoResearch 机制独立评审结论转化为 auto-deep-researcher-24x7 的规格驱动开发契约。它解决的不是“再增加几个功能”，而是建立一条受控主链：

**权威规格 → 隔离开发 → 固定合同实验 → 制品归档 → 独立评估 → 受控晋级 → 可恢复运行**

本包重点封闭两项 P0：

1. 实验有效性合同：预算、数据、split 职责、评估器、指标、环境、种子、重复次数和最小有效改进必须可执行、可验证、可审计。
2. 实验事务合同：候选代码、运行结果、晋级决定和失败恢复必须相互隔离，失败实验不得污染冠军版本或共享工作区。

## 2. 文件清单

| 文件 | 用途 |
|---|---|
| 01_SDD_PROJECT_DEVELOPMENT_CONTRACT.md | 项目总契约、权威层级、范围、合同体系和完成定义 |
| 02_SDD_CONSTRAINTS.md | P0/P1 强制约束、禁止行为、验证方法和违规处置 |
| 03_SDD_ROLES.md | 人类与 Agent 角色、权限边界、职责分离和 RACI |
| 04_SDD_GATES_AND_QA.md | Gate 0—6、实验状态机、独立 QA 测试和门禁报告格式 |
| PROJECT_STATUS.yaml | 当前治理状态和唯一权威入口 |
| templates/STUDY_CONTRACT_TEMPLATE.yaml | 一个研究专题的机器可读合同模板 |
| templates/EXPERIMENT_CONTRACT_TEMPLATE.yaml | 单次候选实验合同模板 |
| templates/ARTIFACT_MANIFEST_TEMPLATE.json | 实验制品与哈希清单模板 |

## 3. 使用顺序

1. Owner 审阅本包并对范围、角色和门禁作出批准或退回决定。
2. MAIN-00 执行 Gate 0，补齐源码提交号、全仓检索、配置 schema、runner、monitor、dispatcher、ledger 和试点基线证据。
3. ARCH-01 使用 Study Contract 模板定义第一个固定硬件、单任务、单并发试点。
4. QA-01 独立审查 Study Contract 与 HLD，Gate 1、Gate 2 通过后才允许编码。
5. 开发角色按合同拆分实现，任何需求变化必须走 Change Request。
6. Gate 4 通过后才允许执行受控试点；Gate 6 通过前不得开启 24x7 自动晋级。

## 4. 初始裁决

    PACKAGE=ADR24X7-SDD-GOVERNANCE-V0.1
    CONTRACT_STATUS=CONTRACT_CANDIDATE
    OWNER_APPROVED=NO
    IMPLEMENTATION_AUTHORIZED=NO
    PILOT_AUTHORIZED=NO
    UNATTENDED_24X7_AUTHORIZED=NO
    PRODUCTION_READY=NO
    FROZEN=NO

## 5. 核心原则

- Spec first：代码不得反向定义需求或实验规则。
- One source of truth：机器运行只读取一份已批准合同，brief 不得维护第二份可冲突数值。
- Validation selects, test accepts：验证集用于循环选优，测试集只用于独立验收。
- Isolate before mutate：Agent 写代码前必须先获得隔离 worktree。
- Archive before decide：制品清单完成前不得进入 KEEP/DISCARD 判定。
- Champion never regresses：失败候选不得修改冠军分支。
- Machine facts over narrative：结构化指标与策略引擎高于 LLM 自述。
- No silent repair：发现基线或合同问题必须退回对应 Owner，不得静默补写后宣布通过。

## 6. 批准记录

| 决策项 | 当前值 | 决策人 | 日期 |
|---|---|---|---|
| SDD 总契约 | PENDING | HUMAN_OWNER | PENDING |
| 约束规范 | PENDING | HUMAN_OWNER | PENDING |
| 角色与权限 | PENDING | HUMAN_OWNER | PENDING |
| 首个试点 Study | NOT_CREATED | HUMAN_OWNER | PENDING |

