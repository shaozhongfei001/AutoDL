# MVD-V3 G1 合同基线进展汇报（待 Owner 申请内容详细汇报）

- **汇报 ID**：G1-PROGRESS-REPORT-20260818-001
- **汇报人**：TECH_LEAD（ARCH-01）+ QA-01 协作
- **汇报时间 UTC**：2026-08-18T01:30:00Z
- **覆盖区间**：自最近一次 Owner 评审通过（CONDITIONAL_PASS_FOR_DESIGN，基线 commit `83e41c1`）并下发任务起，至 G1 合同基线闭合（HEAD `ee5c667`）止
- **治理分支**：`governance/mvd-v3-baseline`
- **当前门禁**：G0 PASS(CLOSED) → **G1 PASS(CLOSED)** → 待 Owner 授权 G2

---

## 一、阶段总览

| 阶段 | 关键动作 | 提交 | 状态 |
|------|----------|------|------|
| Owner 评审通过 | 设计评审 CONDITIONAL_PASS_FOR_DESIGN，下发 G1 合同基线任务 | 83e41c1 | 已完成 |
| G1 基线草案 | 生成 G1-01~13 全部交付物 + Owner 决策包（DRAFT） | f1f3565 | 已完成 |
| Owner 裁决 | PARTIAL_APPROVAL + 定向整改 D-01~D-12 | — | 已裁决 |
| 增量整改 | 应用 Owner 决策 delta + 闭合附录 | ce1750d | 已完成 |
| 状态记录 | PROJECT_STATUS 记录完整 40 位 SHA | db5248c | 已完成 |
| 数据指纹闭合 | D-12 数据指纹 + 独立 final-test split + D-04 硬件 manifest | 548b8de | 已完成 |
| **G1 闭合** | **合同/政策 bundle hash 归档 + QA-01 独立 QA-G1=PASS** | **ee5c667** | **已完成** |

---

## 二、G1 交付物清单（13 项 + 哈希归档 + QA 签署）

| 编号 | 交付物 | 内容要点 | 状态 |
|------|--------|----------|------|
| G1-01 | canonical-runtime-manifest | .venv 3.10.12 / torch 2.5.0+cu124 冻结 | ✅ |
| G1-02 | environment-selection-report | 双环境对照（anaconda base 3.11.7 vs .venv 3.10.12）选型依据 | ✅ |
| G1-03 | STUDY-MVD-SH-QWEN-001.yaml | 主合同，D-01~D-12 决策全回填，status=G1_CLOSED_APPROVED | ✅ |
| G1-04 | profile-baseline | 仅 supervised_holdout，禁用 RL/TS/CV/无监督/多目标 | ✅ |
| G1-05 | metric-identity | 主指标 validation_loss MINIMIZE，单位 NLL_NAT_PER_TOKEN_V1 | ✅ |
| G1-06 | statistical-policy | PAIRED_STUDENT_T_ONE_SIDED_95_V1；pooled_se=false；2x=false | ✅ |
| G1-07 | budget-contract | active 600s / wall 900s / cohort RTX3060L-6G-V1 | ✅ |
| G1-08 | constraint-contract | 7 项硬约束 C01–C07，ids_match_expected=true | ✅ |
| G1-09 | isolation-contract + change-scope-amended | allowlist=train_ft.py，默认 DENY，max_files=1，max_diff≤200 | ✅ |
| G1-10 | artifact-ledger-contract + principals-amended | 四独立 principal；state_root 外移 | ✅ |
| G1-11 | state-root-amended | /home/szf/mvd-state（移出 Git worktree） | ✅ |
| G1-12 | traceability-matrix | 决策↔交付物可追溯 | ✅ |
| G1-13 | Owner Decision Pack + 闭合附录 | ODP-G1-20260817-001 + REMEDIATION ADDENDUM | ✅ |
| — | **合同哈希归档** | contract_bundle `9308b8...` / policy_bundle `4587a4...` | ✅ |
| — | **QA-G1 独立签署** | EVD-G1-001-QA01-Signoff.md = PASS | ✅ |

---

## 三、Owner 决策（D-01~D-12）回填与闭合明细

| 决策 | Owner 裁决 | 关键值 | 闭合证据 |
|------|-----------|--------|----------|
| D-01 | 有条件批准 .venv | Python 3.10.12 / torch 2.5.0+cu124；torch 差异以透明更正记录（DEPENDENCY_BASELINE_DISCREPANCY=OPEN），未覆盖原证据 | D01-torch-discrepancy-closure.md |
| D-02 | 批准 600s | active_train_seconds=600 | G1-07 / STUDY.budget |
| D-03 | 批准 900s | hard_wall_clock=900 | G1-07 / STUDY.budget |
| D-04 | 修订后批准 | COHORT-RTX3060L-6G-V1 + manifest hash `1b35c321...` | D04-hardware-manifest.json |
| D-05 | 批准 | repeats=3, seeds=[17,29,43] | G1-06 / STUDY.statistics |
| D-06 | 替换政策 | PAIRED_STUDENT_T_ONE_SIDED_95_V1（拒绝原 2x pooled SE） | G1-06.statistics |
| D-07 | 有条件批准 | min_practical_delta=0.02 NLL_NAT_PER_TOKEN_V1，source NOT_FROM_C8_C9 | G1-05 / G1-06 |
| D-08 | 暂不批准→七项全文后批准 | C01–C07 硬约束，machine_verifiable=true | G1-08 |
| D-09 | 修订后批准 | allowlist=train_ft.py，默认 DENY，max_diff≤200，含 anti_bypass | G1-09-amended |
| D-10 | 修订后批准 | 四独立 principal：iterative/final-eval/committer/qa | G1-10-amended |
| D-11 | 修订后批准 | state_root=/home/szf/mvd-state，移出 Git worktree | G1-11-amended |
| D-12 | 原则批准→数据证据闭合 | revision 12567cab；行摘要 58174bbb；独立 final-test 5228 行；无跨 split 泄漏 | D12-dataset-snapshot-evidence.md v2 |

---

## 四、机器事实核验（Machine Facts，非叙述）

### 4.1 合同哈希归档（可复现，三方一致）
- **contract_bundle_sha256**: `9308b809877e7c65f734f415240be4569a71e4e623ff2bca144e5020c607bce0`
- **policy_bundle_sha256**: `4587a4e1be18f0b88b49fb668965d9352b2f84370c364a0996aed5375a9e756d`
- 归一化规范：27 个 G1 交付物；每文件 sha256 先剥离自指 `contract_hash:`/`policy_bundle_hash:` 行；行格式 `path|sha256`；排除自指归档/清单文件；锚定 commit 548b8de。
- 校验：独立重算 == 归档 == 合同字段（ALL_MATCH=True）。

### 4.2 数据指纹（D-12）
- dataset_revision: `12567cabf869d7c92e573c7c783905fc160e9639`
- arrow_sha256: `e0b8d2a4fd14442983201e182c15ab2c82175064128920839408ea57dc04015e`
- row digest: `58174bbb6f7f80ac7cb12555dbbff2a4a5e1731424369ab62850446082afb555`
- split: train 41567 / val 4965 / **test 5228（独立，无泄漏）**
- tokenizer_hash: `a8506e7111b80c6d8635951a02eab0f4e1a8e4e5772da83846579e97b16f61bf`

### 4.3 硬件 / 环境
- hardware_manifest_hash: `1b35c32145103c84146f062a261e738b9324c996c48c56aaad151d27c22e6657`
- canonical_runtime: .venv 3.10.12 / torch 2.5.0+cu124
- BASELINE_DRIFT: 无（main 未超 83e41c1）

### 4.4 基线来源纪律（C8/C9）
- cycle8/9 validation_loss 仅 DIAGNOSTIC_AND_REPLAY_ONLY；c8_v3_baseline_authority=NO；不从 C8 派生 practical_delta/fallback_bar。符合 Owner 裁决。

---

## 五、QA-01 独立验收结论

- 签署文件：`evidence/mvd/g1/EVD-G1-001-QA01-Signoff.md`
-  verdict：**QA-G1 = PASS**
- 覆盖：G1-01~12 全验收矩阵 + D-01~D-12 增量闭合核验 + BASELINE_DRIFT 检查 + C8/C9 来源纪律。
- 不阻塞项：evaluator_hash 仍 PENDING，但已在 G1-05 冻结身份，属 G2/F1 coding 阶段。

---

## 六、当前待 Owner 决策 / 授权事项

1. **G2 晋级授权**：是否授权进入 G2_IMPLEMENTATION（F1 coding 阶段：evaluator 实现 + train_ft.py 优化）。当前 `pilot_enabled=false`、`unattended_24x7_authorized=false`。
2. **首试点参数确认**：固定 hardware cohort、max_parallel=1、validation 选优 + test 独立验收（按 05/06 契约）。
3. **evaluator_hash 生成**：G2 期由 DEV-EVAL 实现 evaluator 后回填（F1 编码阶段），不回溯影响 G1 闭合。
4. **G1 闭合提交归档**：本汇报 + ee5c667 提交是否纳入主仓库（或保持治理分支）。

---

## 七、完整提交链（SHA）

```
ee5c667  G1 CLOSE: hash archive + QA-G1 PASS + PROJECT_STATUS G1_CLOSED
548b8de  G1 close D-12 dataset fingerprints + final-test split + D-04 hw manifest
db5248c  PROJECT_STATUS -> G1 owner decision remediation required + 40-char SHAs
ce1750d  G1 TARGETED_REMEDIATION - apply Owner decision delta D01-D12 + closure addendum
f1f3565  G1 contract baseline - contracts, ADRs, traceability, owner decision pack (DRAFT)
a3c414e  PROJECT_STATUS -> G0_EVIDENCE_CLOSURE_CLOSED
19b7e8f  G0 CLOSED - QA-01 signoff PASS + four-role review archive
cda2de9  correct EVD-G0-012 dependency baseline after SEC-01 review
65ba4fb  G0 evidence closure artifacts
... (基线 83e41c1 docs: machine-verdict-diagnosis design review chain)
```

---

## 八、申请内容（供 Owner 审批）

> 基于上述进展，向 HUMAN_OWNER 申请：
> 1. 确认 G1 合同基线闭合有效（QA-G1=PASS），接受 contract_bundle / policy_bundle 哈希归档。
> 2. 授权进入下一阶段 G2_IMPLEMENTATION（含首试点参数与 evaluator 实现任务下发）。
> 3. 确认治理分支 ee5c667 作为 G1 闭合权威基线。
