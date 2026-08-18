# QA-G0 Report —— TECH LEAD SELF-CHECK（非 QA-01 正式签署）

- **Evidence ID**：EVD-G0-020（正式版由 QA-01 独立生成；本文件为 Tech Lead self-check）
- **Owner**：QA-01（独立签署；本稿为 ARCH-01 自检，**未经 QA-01 签署**）
- **Prepared by**：CodeBuddy（Tech Lead / ARCH-01）
- **Prepared at UTC**：2026-08-16T16:42:25Z（后更新至 2026-08-17T02:30:28Z 试点停止后）
- **Gate**：G0_EVIDENCE_CLOSURE
- **按 Owner 决策**：`TECH_LEAD_SELF_SIGN_AUTHORIZED=NO`、`EVD_G0_020_FINAL_OWNER=QA_01`

> **声明**：本文件是 Tech Lead 的 **self-check 草稿**，**不构成 QA-01 独立通过结论**。按 Owner 决策与 WP-10、SDD 职责分离，正式 EVD-G0-020 必须由**独立 QA-01 新会话**直接检查原文件后独立生成 PASS/CONDITIONAL_PASS/BLOCKED。本 self-check 已改名保存，不作为正式证据，仅作 Tech Lead 自检留档。

## G0 退出条件对照

```text
REPOSITORY_BASE_COMMIT=83e41c13e1032b02548d445dd3234ae127d03311
DEPENDENCY_BASELINE=8c390592e17a5589bc80be465a43fdff850e975bb667de698bb5e3e0eb78c943
BASELINE_TEST_RESULT=288 passed (0 failed, 0 skipped) in 6.25s
CURRENT_CODE_FACTS=CONFIRMED per item (see EVD-G0-014/015/016/017/018)
REPLAY_FIXTURE_CUTOFF=2026-08-16T16:42:25Z
QA_G0=PENDING (independent QA-01 sign-off required)
```

## 证据清单核验

| Evidence | 已采集 | 位置 | 状态 |
|---|---|---|---|
| EVD-G0-010 repository-baseline | ✅ | evidence/mvd/g0/repository-baseline.json | CONFIRMED |
| EVD-G0-011 worktree-baseline | ✅ | evidence/mvd/g0/worktree-baseline.txt | CONFIRMED（7 个未跟踪文件） |
| EVD-G0-012 dependency-baseline | ✅ | evidence/mvd/g0/dependency-baseline.json | CONFIRMED |
| EVD-G0-013 test-baseline | ✅ | evidence/mvd/g0/test-baseline.json | CONFIRMED（288 pass） |
| EVD-G0-014 source-index | ✅ | evidence/mvd/g0/source-index.json | CONFIRMED |
| EVD-G0-015 repository-search | ✅ | evidence/mvd/g0/repository-search.log | CONFIRMED |
| EVD-G0-016 evaluation-flow | ✅ | evidence/mvd/g0/evaluation-flow.md | CONFIRMED（selection/test 隔离缺失） |
| EVD-G0-017 runner-flow | ✅ | evidence/mvd/g0/runner-flow.md | CONFIRMED（无 process_status×termination_reason） |
| EVD-G0-018 mutation-map | ✅ | evidence/mvd/g0/mutation-map.md | CONFIRMED（无独立 Committer） |
| EVD-G0-019 replay-fixture-manifest | ✅ | evidence/mvd/g0/replay-fixture-manifest.json | CONFIRMED_AS_OF_CUTOFF |
| EVD-G0-020 QA-G0-report | ✅（草案） | evidence/mvd/g0/QA-G0-report.md | **PENDING 独立签署** |

## 试点停止后更新（2026-08-17T02:30:28Z）

- **试点已优雅停止**：C9（PID 263475）完成终态归档（validation_loss=0.9188, DISCARD），主循环（PID 1658788）因 SIGTERM（`_running=False`）在 C9 后退出，**未启动 C10**，无残留进程。见 `stop-state-capture.json`。
- **C8 addendum 已创建**：`cycle8-addendum.json`（LEGACY_VERDICT=KEEP, VALIDATION_LOSS=0.7723, V3_NORMATIVE_DECISION=PENDING_G1, V3_CHAMPION_AUTHORITY=NO）。
- **288 测试停止后重跑通过**（2.64s），EVD-G0-013 已更新。

## 已知开放项（G0 未闭合，不得宣称通过）

1. **QA_G0=PENDING**：需**独立 QA-01 新会话**签署，本 self-check 不能替代。正式 EVD-G0-020 由 QA-01 生成。
2. **治理分支已建立**（2026-08-17T02:45Z）：`governance/mvd-v3-baseline`（GIT_WORKTREE_ADD_NEW_BRANCH），NORMATIVE 提交 5866d20（V3.0/V1.1/ODR/manifest），EVIDENCE 提交 962f332（reviews/superseded 分类）。提交后 288 测试通过。批准文档仅提交到治理分支，main 未变。见 `worktree-baseline-poststop.txt`。
3. **C8 的 0.7723 不得成为 V3 正式 baseline**：metric identity/重复实验/uncertainty/Study Contract/hard constraints 未冻结（G1 待办）。
4. **中文名重复文件标记 WITHDRAWN**：`完整交付计划 V1.1-用于替代原 Tech Lead V1.0提示词.md`（重复上传）不纳入权威基线，未提交。已在 manifest 标记 WITHDRAWN。
5. **C9 训练日志显示 train_loss=0.0**：印证了 metric identity + train 指标契约需在 G1 冻结（V3.0 差距）。

## 结论（self-check，非 QA-01 结论）

- **G0 证据采集完成**（EVD-G0-010—020 + addendum + stop-state 均已落盘到 `evidence/mvd/g0/`）。
- **G0 PASS 未达成**：①QA-01 独立签署未完成；②治理分支提交被阻塞。
- 在 QA-01 独立签署 + 治理分支问题解决前，G0 状态保持 `REMEDIATION_IN_PROGRESS`，不进入 G1。

## G0 闭合更新（2026-08-17T03:20:00Z，governance 分支并入）

- **QA-01 独立签署完成**：PASS（正式版见 `EVD-G0-020-QA01-Signoff.md`）。
- **四角色审查全部 PASS**：QA-01（最终签署人）、SEC-01、DEV-VCS-01、DEV-EVAL-01。
- **EVD-G0-012 已更正**（commit `cda2de9`）：pydantic NOT_PRESENT → PRESENT 2.13.4，经 SEC-01 发现 + QA-01 独立复核确认，留存为"已识别并更正的证据偏差"。
- **G0_STATUS = PASS（CLOSED）**。G0 退出条件已全部满足（见上方对照表），QA_G0=PASS。
- 治理分支 `governance/mvd-v3-baseline` @ HEAD `cda2de9` 保留，供 G1 使用。