# EVD-G1-001 — QA-01 独立签署：G1 合同基线（QA-G1）

- **artifact_id**: EVD-G1-001-QA01-Signoff
- **gate**: G1_CONTRACT_BASELINE
- **role**: QA-01（独立验收，readonly-review，不兼任 final-eval 运行主体）
- **signoff_utc**: 2026-08-18T01:10:00Z
- **head_commit_under_review**: 548b8de
- **trigger_authorization**: HUMAN_OWNER 于 2026-08-18 授权触发独立 QA-G1 签署
- **verdict**: **PASS**

---

## 1. 验收范围与方法论

依据 SDD 04（`04_SDD_GATES_AND_QA.md`）Gate 1 验收矩阵，QA-01 对 G1 合同基线执行**独立机器事实核验**，不依赖 TECH_LEAD / ARCH-01 自述。所有判定基于可复现哈希与文件内容交叉验证。

验收对象：G1-01~G1-12 共 13 项交付物（含 1 主合同、9 ADR、Traceability Matrix、Owner Decision Pack、6 项增量闭合证据）。

---

## 2. 机器事实核验记录（Machine Facts）

### 2.1 合同哈希归档（closure pending 项已闭合）
| 项 | 值 | 核验 |
|----|----|------|
| contract_bundle_sha256 | `9308b809877e7c65f734f415240be4569a71e4e623ff2bca144e5020c607bce0` | 独立重算 == 归档 == 合同字段（三方一致 PASS）|
| policy_bundle_sha256 | `4587a4e1be18f0b88b49fb668965d9352b2f84370c364a0996aed5375a9e756d` | 同上 PASS |
| 归一化规范 | 27 个 G1 交付物；每文件 sha256 先剥离自指 `contract_hash:`/`policy_bundle_hash:` 行；行格式 `path\|sha256`；排除自指归档/清单文件；锚定 commit 548b8de | 可复现 PASS |
| 归档位置 | `evidence/mvd/g1/G1-CONTRACT-HASH-ARCHIVE.json` | 存在 PASS |

### 2.2 数据指纹（D-12 闭合）
| 项 | 值 |
|----|----|
| dataset_revision | 12567cabf869d7c92e573c7c783905fc160e9639 |
| dataset_fingerprint (row digest) | 58174bbb6f7f80ac7cb12555dbbff2a4a5e1731424369ab62850446082afb555 |
| dataset_arrow_sha256 | e0b8d2a4fd14442983201e182c15ab2c82175064128920839408ea57dc04015e |
| split | SPLIT-MVD-V1：train 41567 / val 4965 / test 5228（独立 final-test，无跨 split 泄漏）|
| tokenizer_hash | a8506e7111b80c6d8635951a02eab0f4e1a8e4e5772da83846579e97b16f61bf |

### 2.3 硬件 Manifest（D-04 闭合）
- hardware_manifest_hash: `1b35c32145103c84146f062a261e738b9324c996c48c56aaad151d27c22e6657`
- cohort: COHORT-RTX3060L-6G-V1（已绑定于 STUDY 与 G1-05）

### 2.4 运行环境（D-01 闭合）
- canonical_runtime: `/home/szf/env/AutoDL/.venv/bin/python` (3.10.12, torch 2.5.0+cu124)
- torch 差异（G0 EVD-G0-012 误记）：以透明更正 `DEPENDENCY_BASELINE_DISCREPANCY=OPEN` 记录，未覆盖原证据，符合 No Silent Repair。

### 2.5 约束 / 变更范围 / 主体 / 状态根（D-08/D-09/D-10/D-11）
- G1-08 硬约束 7 项（C01–C07），ids_match_expected=true，machine_verifiable=true。
- G1-09 allowlist=['train_ft.py']，default DENY，max_changed_files=1，max_diff≤200 行，含 anti_bypass。
- G1-10 四独立 principal：svc-mvd-iterative-v1 / svc-mvd-final-eval-v1 / svc-mvd-committer-v1 / qa-01-readonly-review。
- G1-11 state_root=`/home/szf/mvd-state`（移出 Git worktree，ext4，247G）。

### 2.6 统计政策（D-05/D-06/D-07）
- seeds=[17,29,43]，min_repeats=3。
- confidence_policy: PAIRED_STUDENT_T_ONE_SIDED_95_V1；pooled_se_allowed=false；fixed_2x_multiplier_allowed=false。
- min_practical_delta=0.02，单位 NLL_NAT_PER_TOKEN_V1，source NOT_FROM_C8_C9。

### 2.7 基线来源纪律（C8/C9）
- cycle8/cycle9 validation_loss 仅 DIAGNOSTIC_AND_REPLAY_ONLY；c8_v3_baseline_authority=NO；不得回填 C1 provisional、不得建立 V3 champion、不得从 C8 派生 practical_delta/fallback_bar。符合 Owner 裁决。

### 2.8 BASELINE_DRIFT 检查
- repository_base_commit: 83e41c13e1032b02548d445dd3234ae127d03311（main 未超此基线，无漂移）。

---

## 3. Gate 1 验收矩阵判定

| 验收项 | 期望 | 实测 | 结果 |
|--------|------|------|------|
| G1-01 运行环境冻结 | 单一 canonical runtime | .venv 3.10.12 / torch 2.5.0+cu124 | PASS |
| G1-02 环境选型报告 | 双环境对照 + 选型依据 | D01 报告 + freeze | PASS |
| G1-03 Study Contract 主合同 | 决策全回填 | D-01~D-12 已回填 | PASS |
| G1-04 Profile Baseline | 仅 supervised_holdout | 已限定 | PASS |
| G1-05 Metric Identity | 单位/方向/evaluator 冻结 | NLL_NAT_PER_TOKEN_V1 等 | PASS |
| G1-06 Statistical Policy | 配对 t / POOLED_SE=false | PAIRED_STUDENT_T_ONE_SIDED_95_V1 | PASS |
| G1-07 Budget Contract | 600s/900s cohort | 已批准值 | PASS |
| G1-08 Constraint Contract | 7 硬约束 machine-verifiable | C01–C07 match=true | PASS |
| G1-09 Isolation/Change Scope | allowlist + DENY default | train_ft.py 单文件 | PASS |
| G1-10 Artifact/Ledger | state_root 外移 | /home/szf/mvd-state | PASS |
| G1-11 State Root | 非 Git worktree | 已外移 + 权限分离 | PASS |
| G1-12 Traceability Matrix | 决策↔交付物可追溯 | 已生成 | PASS |
| Owner Decision Pack | 集中决策 + 增量闭合 | D-01~D-12 全闭合 | PASS |
| contract_hash / policy_bundle_hash | 机器可复现归档 | 三方一致 `9308b8...` / `4587a4...` | PASS |

> 注：evaluator_hash 仍 `PENDING_EVALUATOR_HASH`，属 F1 coding 阶段（G2 实施期），不阻塞 G1 闭合——其身份已在 G1-05 中冻结（evaluator_identity_frozen=true）。

---

## 4. 独立结论

QA-01 独立核验确认：G1 全部 13 项交付物齐备、Owner D-01~D-12 裁决均已增量闭合、合同哈希可复现且三方一致、无 BASELINE_DRIFT、C8/C9 来源纪律成立、四主体与状态根隔离合规。

**QA-G1 = PASS**。授权进入下一阶段（G2 实现）前置条件已满足。

---

## 5. 签署

- **QA-01**: signoff=PASS, timestamp=2026-08-18T01:10:00Z, evidence=EVD-G1-001-QA01-Signoff.md
- **next_gate**: G2_IMPLEMENTATION（待 HUMAN_OWNER 授权 pilot/implementation 晋级）
- **archive_commit_pending**: 本签署文件 + 哈希归档需随 G1 闭合一并提交
