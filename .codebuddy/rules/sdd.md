---
alwaysApply: true
globs: "**/*"
---

# SDD 开发治理契约 — 激活入口

> 本规则是 auto-deep-researcher-24x7 的 **SDD（Specification-Driven Development）开发治理契约**入口。
> 依据 CodeBuddy `rules` 脚手架规范，所有 SDD 契约文件存放于 `.codebuddy/rules/sdd/`。
> **状态：`CONTRACT_CANDIDATE`**。在执行任何 AutoDL 改造前，必须遵循本契约。

## 契约文件索引

| 文件 | 内容 | 优先级 |
|------|------|--------|
| `00_README.md` | 治理包说明、文件清单、使用顺序、核心原则 | 入口 |
| `01_SDD_PROJECT_DEVELOPMENT_CONTRACT.md` | 项目总契约、权威层级（L0-L6）、P0 范围、组件边界、不变量、完成定义 | 总纲 |
| `02_SDD_CONSTRAINTS.md` | P0/P1 强制约束（VCS/SPC/EVAL/RUN/ART/AGT/QLT）、禁止行为、违规处置 | 硬约束 |
| `03_SDD_ROLES.md` | HUMAN_OWNER / MAIN-00 / ARCH-01 / SEC-01 / QA-01 治理角色、开发角色、运行时 Agent 角色、RACI、职责分离 | 权限 |
| `04_SDD_GATES_AND_QA.md` | Gate 0—6、实验状态机、独立 QA 验收矩阵、门禁报告格式 | 门禁 |
| `PROJECT_STATUS.yaml` | 当前治理状态、唯一权威入口、被阻止动作、下一步产出 | 状态 |
| `templates/STUDY_CONTRACT_TEMPLATE.yaml` | 研究专题机器可读合同模板 | 模板 |
| `templates/EXPERIMENT_CONTRACT_TEMPLATE.yaml` | 单次候选实验合同模板 | 模板 |
| `templates/ARTIFACT_MANIFEST_TEMPLATE.json` | 实验制品与哈希清单模板 | 模板 |

## 强制遵循的核心原则（Spec First）

1. **Spec first**：代码不得反向定义需求或实验规则；先写 Study/Experiment 合同，再编码。
2. **One source of truth**：机器运行只读取一份已批准合同（config/合同 schema），brief 不得维护第二份可冲突数值。
3. **Validation selects, test accepts**：validation 用于逐轮选优，test 只用于独立验收，严禁 test 回流到逐轮 Agent。
4. **Isolate before mutate**：Agent 写代码前必须先获得隔离 worktree。
5. **Archive before decide**：Artifact Manifest 固化前不得进入 KEEP/DISCARD 判定。
6. **Champion never regresses**：失败候选不得修改冠军分支。
7. **Machine facts over narrative**：结构化指标与 Decision Engine 高于 LLM 自述。
8. **No silent repair**：发现基线或合同问题必须退回对应 Owner，不得静默补写后宣布通过。

## 禁止动作（当前阶段）

- 未经 HUMAN_OWNER 批准直接实施改造、自动晋级代码。
- 在共享工作区执行破坏性 Git 回退（reset --hard / clean -fd / force push）。
- 使用 test 集逐轮选优。
- 未归档制品即作出 KEEP/DISCARD。
- 未通过 Gate 6 即开启 24x7 无人值守自动晋级。

## 当前门禁状态

- 当前 Gate：`G0_EVIDENCE_CLOSURE`
- `owner_approved=false`、`implementation_authorized=false`、`pilot_authorized=false`
- 下一步产出：首个 Study Contract、P0 概要设计与 ADR、独立 QA Gate 1/Gate 2 报告

## 操作指引

当进行 AutoDL 改造时，AI 必须：
1. 先读取 `00_README.md` + `PROJECT_STATUS.yaml` 确认当前 Gate 与允许动作。
2. 按 `01` 总契约确定权威层级与范围，按 `02` 约束执行（MUST/MUST NOT）。
3. 涉及角色/权限遵守 `03`，涉及门禁遵守 `04`。
4. 任何合同/规格变更走 Change Request，不静默修改契约文件。
5. 首个试点固定 hardware cohort、`max_parallel=1`、validation 选优 + test 独立验收。
