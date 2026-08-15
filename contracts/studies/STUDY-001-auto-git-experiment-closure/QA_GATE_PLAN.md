# QA 门禁计划 — STUDY-001（Gate 1 / Gate 2）

> 状态：**DRAFT**（QA-01 尚未执行）
> 关联：SDD `04_SDD_GATES_AND_QA.md`
> 作用：对 STUDY-001 及其落地代码的独立 QA 验收矩阵（Gate 1 = 概要与合同评审，Gate 2 = 关键路径实现评审）

## Gate 1：概要与合同评审（QA-01 对合同/ADR 的静态审阅）

| ID | 检查项 | 期望 | 方法 | 结果 |
|----|--------|------|------|------|
| QA1-01 | Study Contract 字段完整且 schema 合法 | 必填字段无 `<PENDING>` | YAML 校验 | ⬜ |
| QA1-02 | baseline_commit 存在且匹配 | 指向真实 HEAD | `git rev-parse` | ⬜ |
| QA1-03 | 数据指纹与受保护边界声明一致 | 4 项 SHA256 与 data/ 一致 | `sha256sum` | ⬜ |
| QA1-04 | validation/test split 职责正确 | validation=iterative_selection, test=independent_acceptance, feedback=false | 字段审阅 | ⬜ |
| QA1-05 | budget 模式/limit/hard 一致且可达 | active_wall_clock=300, hard=420 | 字段审阅 | ⬜ |
| QA1-06 | 评审 4 项 must-fix 全部在 ADR 中覆盖 | A/D0/B/C 均有对应 ADR/设计 | 交叉核对 | ⬜ |
| QA1-07 | ADR-001 验收标准可度量 | 5 项均有可执行判据 | 审阅 | ⬜ |
| QA1-08 | ADR-002 验收标准可度量 | 6 项均有可执行判据 | 审阅 | ⬜ |
| QA1-09 | 无 test 回流 / 无破坏性 reset 风险 | 机制文本明确禁止 | 审阅 | ⬜ |
| QA1-10 | approvals 状态为 PENDING，未越权声称已批准 | 所有 approval=PENDING | 字段审阅 | ⬜ |

**Gate 1 出口判据**：所有 ⬜ 必须为 ✅ 或标记为已记录的豁免，且 HUMAN_OWNER 未批准前**不得声称合同有效**。

## Gate 2：关键路径实现评审（对落地代码的独立验证）

> 前置：Owner 批准实施 + 落地代码已提交。此表为待实施后执行的检查表。

| ID | 检查项 | 期望 | 方法 |
|----|--------|------|------|
| QA2-01 | 训练按 `active_train_seconds` 自终止 | 达预算即停，误差≤5% | 计时复测 |
| QA2-02 | hard_wall_clock_limit 兜底生效 | TIMEOUT/BUDGET_EXCEEDED 区分 | 注入测试 |
| QA2-03 | poll_interval 不改变预算 | 改 interval 预算不变 | 对比测试 |
| QA2-04 | validation 选优 + test 独立验收 | 晋级只用 validation | 日志审计 |
| QA2-05 | 跨 cohort 标记 INCOMPARABLE | 拒绝比较 | 构造差异 |
| QA2-06 | 候选在独立 worktree 内写 | 越界写入被拒 | 越权测试 |
| QA2-07 | champion fast-forward + parent 乐观锁 | 过期 parent 重放 | 并发注入 |
| QA2-08 | 破坏性 git 被禁 | reset/clean -fd/force 拒绝 | 命令注入 |
| QA2-09 | ledger 追加式、可重放 | 崩溃恢复不丢 | 中断重放 |
| QA2-10 | 受保护文件 hash 未变 | 执行前后一致 | 前后 sha256 |

## 报告输出
- Gate 1 报告文件：`artifacts/STUDY-001/qa/gate1_report.md`
- Gate 2 报告文件：`artifacts/STUDY-001/qa/gate2_report.md`
- 所有报告由 QA-01 独立出具，HUMAN_OWNER 最终放行。

## 当前状态
- 本轮（G0 允许动作）仅产出合同 + ADR + 本 QA 计划，**未实施代码、未执行 QA 验证**。
- 需 HUMAN_OWNER 批准后：实施 → 提交 → QA Gate 2。
