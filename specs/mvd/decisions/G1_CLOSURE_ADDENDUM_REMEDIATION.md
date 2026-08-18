# G1 增量闭合包（REMEDIATION ADDENDUM）

- **Addendum ID**：G1-CLOSURE-ADDENDUM-20260817-001
- **Owner**：TECH_LEAD（ARCH-01）
- **依据**：`OWNER_DECISION=PARTIAL_APPROVAL_G1_DECISION_PACK_WITH_TARGETED_REMEDIATION`
- **Next authorized action**：`APPLY_G1_OWNER_DECISION_DELTA_AND_SUBMIT_CLOSURE_ADDENDUM`
- **生成时间 UTC**：2026-08-17T05:30:00Z
- **状态**：待 QA-G1 触发（`QA_G1_TRIGGER_AUTHORIZED=NO`）

## 六项整改交付（Owner 要求）

| # | 整改项 | 交付物 | 状态 |
|---|---|---|---|
| 1 | torch 版本差异闭合 | `specs/mvd/runtime/D01-torch-discrepancy-closure.md` + `D01-canonical-freeze.txt` | ✅ |
| 2 | D-06 新统计政策 | `specs/mvd/contracts/G1-06-statistical-policy.yaml` | ✅ |
| 3 | D-08 七项约束全文 | `specs/mvd/contracts/G1-08-constraint-contract.yaml` | ✅ |
| 4 | D-09—D-11 修订合同片段 | `G1-09-change-scope-amended.md`, `G1-10-principals-amended.md`, `G1-11-state-root-amended.md` + 主合同回填 | ✅ |
| 5 | D-12 数据快照证据 | `specs/mvd/decisions/D12-dataset-snapshot-evidence.md` | ✅ |
| 6 | 完整 40 位 SHA + 治理分支 HEAD | 见下方 SHA 表 | ✅ |

## Owner 决策回填汇总

| 决策 | Owner 裁决 | 已回填到 |
|---|---|---|
| D-01 | 有条件批准 .venv + torch 差异闭合 | STUDY-MVD-SH-QWEN-001.yaml + D01-closure |
| D-02 | 600s active-train | budget + STUDY contract |
| D-03 | 900s wall-clock | budget + STUDY contract |
| D-04 | COHORT-RTX3060L-6G-V1 + manifest hash | budget + STUDY contract |
| D-05 | repeats=3, seeds=[17,29,43] | STUDY contract + G1-06 |
| D-06 | PAIRED_STUDENT_T_ONE_SIDED_95_V1 | G1-06 + STUDY contract |
| D-07 | 0.02 nats/token（条件） | G1-05 + G1-06 + STUDY contract |
| D-08 | 七项约束全文 | G1-08 + STUDY contract |
| D-09 | allowlist=train_ft.py, 默认 DENY | G1-09a + STUDY contract |
| D-10 | 四独立 service principals | G1-10a + G1-09 + STUDY contract |
| D-11 | state root 移出 Git worktree | G1-11a + G1-10 + STUDY contract |
| D-12 | 原则批准，数据证据待闭合 | D12 evidence + STUDY contract |

## 完整 40 位 SHA 表

| 对象 | SHA-256 / commit |
|---|---|
| 治理分支 HEAD（提交本包前） | `f1f35652848c1b0ee4c5f0a1c8cce7d0fd2b03e6` |
| main base commit | `83e41c13e1032b02548d445dd3234ae127d03311` |
| requirements.txt | `8c390592e17a5589bc80be465a43fdff850e975bb667de698bb5e3e0eb78c943` |
| canonical freeze | `ade58b5661416172832f0de5bbd13fefa4e36171c374775ae1d938bd6ced7893` |
| 288 测试报告 | `d94a0247f3b84c743804f217bfbc5c1227e5d32d669aa9604acc976b60a3dba2` |

## 待闭合项（QA-G1 触发前必须闭合）

1. **D-04** hardware manifest hash —— **已闭合**（`1b35c321...`，见 D04-hardware-manifest.json，2026-08-18）。
2. **D-12** dataset 指纹、tokenizer/preprocess hash、**独立 final-test split** —— **已闭合**（见 D12-dataset-snapshot-evidence.md v2，2026-08-18）。
3. **D-08** 约束阈值已冻结（无需再改），但需机器验证 expected==actual。
4. **D-10** G2 需把逻辑 principal 映射到 OS/service identity + ACL。
5. contract_hash / policy_bundle_hash 需在合同最终批准后计算。
6. 所有基线文件需版本化 + SHA-256 + 生效时间 + Owner（归档后计算）。
7. **evaluator hash** —— 待 F1 编码阶段确定（非 G1 阻塞）。

## QA-G1 触发条件

以下全部闭合后才授权触发独立 QA-G1（`QA_G1_TRIGGER_AUTHORIZED=YES`）：
- [x] 六项整改交付全部提交（本包）
- [x] 数据指纹/独立 final-test split 闭合（D-12，2026-08-18）
- [x] hardware manifest hash 绑定（D-04，2026-08-18）
- [x] PROJECT_STATUS.yaml 记录完整 40 位 SHA
- [ ] 合同正式冻结 + SHA-256 归档（contract_hash/policy_bundle_hash）
- [ ] QA-01 独立签署 QA-G1=PASS
