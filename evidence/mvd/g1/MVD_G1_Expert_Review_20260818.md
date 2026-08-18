# MVD-V3 G1 合同基线独立专家评审报告 V1.0

**评审编号：** MVD-G1-EXPERT-REVIEW-20260818-001  
**评审角色：** Independent MVD Contract & Architecture Audit Expert  
**评审独立性：** 非 TECH_LEAD、非 ARCH-01、非 QA-01，不继承项目自评或 QA-01 结论  
**评审日期：** 2026-08-18  
**评审对象声明：** 用户要求评审 `evidence/mvd/g1/G1_EXPERT_REVIEW_PROMPT.md`；本次实际收到的附件标题为《MVD-V3 G1 合同基线进展汇报》，汇报 ID 为 `G1-PROGRESS-REPORT-20260818-001`，文件 SHA-256 为 `99f2e80925e12150cc37101bb5deb777cf18a6fc5a2d252e291a650b2eea0d63`。附件不是所称评审提示词，也不包含 27 个 G1 原始交付物、复现脚本或 Git 对象。

---

## 1. 总体结论

```text
EXPERT_REVIEW_VERDICT=BLOCKED_FOR_REMEDIATION
G1_QA_REPORTED_STATUS=PASS
G1_INDEPENDENTLY_REPRODUCED=NO
G1_HUMAN_OWNER_FINAL_APPROVAL=NOT_EVIDENCED
G1_GATE_CLOSED_CLAIM=NOT_ACCEPTED_AS_MACHINE_FACT
G2_AUTHORIZATION_RECOMMENDATION=DO_NOT_AUTHORIZE
IMPLEMENTATION_AUTHORIZED=NO
PILOT_AUTHORIZED=NO
PRODUCTION_READY=NO
```

当前不能确认 `G1 PASS(CLOSED)`，也不能批准报告申请的 `G2_IMPLEMENTATION / F1 coding`。

本结论不是因为已证明全部 G1 合同内容错误，而是同时存在两类问题：

1. **确定存在的治理与合同矛盾：** G2 被错误解释为编码阶段；`evaluator_hash` 仍为 PENDING；D-01 依赖差异仍标记 OPEN；D-08 未见 HUMAN_OWNER 对七项具体约束的批准。
2. **独立复现输入缺失：** 提供的是 TECH_LEAD/QA-01 进展汇报，而非评审提示词及原始证据包；哈希、split、ACL、统计公式和基线差异均只能看到自述结论，无法独立重算。

即使后续证明所有哈希与数据 split 均正确，`G2_IMPLEMENTATION` 的授权倒置仍构成单独 BLOCKER。按照已批准的 V3.0 与交付计划 V1.1：

```text
G1 PASS → 允许完成 HLD、schema 示例和 Tool Policy
G2 PASS → 允许任务拆分、CI/fixture/开发隔离环境准备，仍禁止编码
G3 BUILD_READY PASS → 才允许开始 P0 编码和集成分支建设
```

---

## 2. 审计输入与证据等级

### 2.1 本次实际获得

| 输入 | 可用性 | 证据等级 | 说明 |
|---|---:|---|---|
| G1 进展汇报 | 有 | NARRATIVE_REPORT | TECH_LEAD＋QA-01 协作产物，不是独立机器证据 |
| 已批准 V3.0 架构文件 | 有 | NORMATIVE_BASELINE | 用于核对 Gate、统计、隔离和 Study 必填字段 |
| 交付计划 V1.1 | 有 | NORMATIVE_BASELINE | 明确 G3 才是编码授权门槛 |
| SDD 治理包 V0.1 | 有 | GOVERNANCE_INPUT | 存在早期措辞歧义，须由后批准、MVD 专用 V3.0/V1.1 规则收敛 |

### 2.2 本次未获得

- 实际指定的 `G1_EXPERT_REVIEW_PROMPT.md`；
- commit `7dc0f71`、`ee5c667`、`548b8de` 的 Git 对象和完整 40 位 SHA；
- 27 个 G1 bundle 原文件和精确文件清单；
- bundle 归一化/重算脚本及其测试；
- `STUDY-MVD-SH-QWEN-001.yaml` 原文；
- G1-05/G1-06 统计与 metric identity 原文；
- C01–C07 七项 hard constraints 原文和 HUMAN_OWNER 签署；
- D01 dependency discrepancy 的最终状态记录；
- D12 原始 Arrow 文件、row manifest、split 公式和重算脚本；
- principals、ACL、目录权限和 state root 的机器检查输出；
- QA-01 签署全文及其审计命令原始输出。

依据“machine facts over narrative”，缺失上述材料时，不得把报告中的 `✅`、`ALL_MATCH=True` 或 `QA-G1=PASS` 自动提升为独立审计事实。

---

## 3. A–G 七维评审结果

| 维度 | 结论 | 关键证据/问题 | Gate 影响 |
|---|---|---|---|
| A. 门禁与授权 | **FAIL** | 附件第 103、105、131 行把 G2 定义为 implementation/F1 coding；V3.0/V1.1 明确编码必须等 G3 BUILD_READY | BLOCKER |
| B. 哈希可复现 | **FAIL（证据不足）** | 只给出两个结果哈希和文字规范；无 27 文件、精确 manifest、脚本、Git 对象；无法验证 548b8de→ee5c667→7dc0f71 是否改动基线 | BLOCKER |
| C. 统计政策 | **FAIL（证据不足）** | policy 名称符合 Owner 修订方向，但未提供 paired delta 公式、ddof、t 分位数、边界/缺失处理和测试向量 | MAJOR，阻止确认 G1 |
| D. 隔离与安全 | **FAIL（证据不足）** | “四独立 principal”“state root 外移”只是陈述；无真实 service identity、ACL、目录权限、symlink/TOCTOU 与 test 非干扰检查 | MAJOR，阻止确认 G1 |
| E. 数据 split | **FAIL（证据不足）** | 行数合计为 51,760，但未提供 split 公式、row IDs、canonicalization、重复/近重复检测输出；“无泄漏”不可复现 | BLOCKER |
| F. 基线纪律 | **FAIL（证据不足）** | C8/C9 纪律表述与 Owner 决策一致，但无 Study、ledger、diff；`main 未超 83e41c1` 仅为叙述 | MAJOR |
| G. 决策一致性 | **FAIL** | D01 仍 OPEN、D08 未见 Owner 对具体清单批准、evaluator_hash PENDING、QA-01 被用于替代 Gate Owner、G2 编码语义越权 | BLOCKER |

### 3.1 A｜门禁与授权

**结论：FAIL。**

进展报告申请：

```text
G2_IMPLEMENTATION
F1 coding
evaluator 实现
train_ft.py 优化
```

这与 MVD 专用、后批准的唯一授权模型冲突。交付计划 V1.1 明确：

- G1 后仍禁止编码；
- G2 后仍禁止编码和真实 loop 集成；
- `IMPLEMENTATION_AUTHORIZED=YES` 只能由 G3 `BUILD_READY` PASS 产生。

早期 SDD V0.1 中“Gate 1、Gate 2 通过后才允许编码”或 G2 表格里的“任务拆分与编码”与后续 V3.0/V1.1 存在措辞冲突。G1 的 ADR-MVD-009 本应消除该冲突，但进展报告反而采用了旧语义，说明 Gate crosswalk 未真正闭合。

**整改：**

1. 将申请改为 `G2_HLD_PREPARATION_ONLY`；
2. 删除 G2 范围中的 evaluator 实现、`train_ft.py` 修改和任何 F1 coding；
3. 在 SDD Gate 文档增加 supersession 标记：MVD 范围内以 V3.0/V1.1 Gate 模型为准；
4. `IMPLEMENTATION_AUTHORIZED` 在 G3 前必须保持 NO。

### 3.2 B｜哈希可复现

**结论：FAIL（EVIDENCE_NOT_AVAILABLE）。**

报告声称：

- `contract_bundle_sha256=9308b809...`；
- `policy_bundle_sha256=4587a4e1...`；
- 对 27 个文件剥离自指行，生成 `path|sha256`，锚定 548b8de；
- 独立重算、归档和合同字段三方一致。

但附件没有提供可供本专家执行的文件、manifest 和脚本。还存在三层提交需要核对：

```text
548b8de  被声称为 bundle 锚点
ee5c667  被声称为 G1 CLOSED
7dc0f71  被用户声明为当前治理分支 HEAD
```

必须证明从 548b8de 到后续两个 HEAD，27 个合同/策略文件字节未发生变化；否则旧 bundle hash 不能代表当前权威 HEAD。

当前“删除包含 `contract_hash:`/`policy_bundle_hash:` 的行”还缺少精确定义：匹配正则、缩进、CRLF/LF、Unicode、路径排序、symlink、重复路径、空文件和文件集合闭包均未见证据。更稳妥的长期方案是：合同文件不内嵌自身 bundle hash，由独立、签名的 manifest 对原始字节直接哈希，避免自指归一化。

### 3.3 C｜统计政策

**结论：FAIL（EVIDENCE_NOT_AVAILABLE）。**

`PAIRED_STUDENT_T_ONE_SIDED_95_V1`、`pooled_se=false`、`2x=false` 在方向上符合 Owner 修订。但独立审计还必须确认：

```text
d_i = normalized_pair_delta(candidate_i, champion_i)
SE = sample_std(d_i, ddof=1) / sqrt(n)
margin = t_quantile(df=n-1, p=0.95) * SE
decision_bar = max(0.02, margin)
```

以及：

- candidate/champion 是否使用完全相同的 seed 集合；
- n<3、非有限值、seed 缺失、重复 seed 如何映射；
- `normalized_delta == ±bar` 的等号归属；
- `NLL_NAT_PER_TOKEN_V1` 是否确实是自然对数、按有效 token 加权；
- 全部 delta 相同时 SE=0 的处理；
- 无 fallback 时 `InsufficientEvidence → HUMAN_REVIEW` 是否唯一。

没有政策原文和 golden vectors，不能给 PASS。

### 3.4 D｜隔离与安全

**结论：FAIL（EVIDENCE_NOT_AVAILABLE）。**

逻辑上区分 iterative/final-eval/committer/qa 是必要条件，但 principal 名称不等于身份认证或 ACL。至少需要：

- 每个 principal 的真实 OS/service identity 映射；
- selection/test/artifact/ledger/champion 的 read/write/append/rename 权限矩阵；
- `/home/szf/mvd-state` 的 owner/group/mode、mount、realpath、symlink 和原子 rename 证据；
- iterative principal 读取 final-test 的拒绝证据；
- final-test 内容变化不影响 verdict/diagnostic/advice/memory 的非干扰测试设计；
- committer 只接收已签名 FinalDecision、不能读取 raw test/metric 的合同约束。

G1 可以冻结“应当如何隔离”的合同；运行时 ACL 验证可在 G3/G4 完成，但 G1 必须提供完整、无歧义的权限模型，而非仅列四个名称。

### 3.5 E｜数据 split

**结论：FAIL（EVIDENCE_NOT_AVAILABLE）。**

报告中的 train/val/test 数量之和为 51,760，算术一致。但数量一致不证明：

- 每行只进入一个 split；
- 相同或近重复样本未跨 split；
- split 由冻结 revision 和确定性公式派生；
- row canonicalization 稳定；
- final-test 没有被 iterative principal 读取；
- tokenizer/preprocess 变化不会静默改变样本身份。

必须提供 row-level manifest、split 公式、duplicate/near-duplicate 报告、最终集合哈希和可执行重算脚本。

### 3.6 F｜基线纪律

**结论：FAIL（EVIDENCE_NOT_AVAILABLE）。**

报告关于 C8/C9 的政策表述是正确的：只能用于 diagnostics/replay，不能作为 V3 baseline，也不能反推 practical delta 或 fallback bar。但没有以下机器证据：

- Study baseline 节点是否引用 C8/C9；
- champion ledger 是否引用 C8/C9；
- D-07 的来源字段及审计链；
- 83e41c1 到当前 main HEAD 的完整 diff/status；
- 548b8de 到 7dc0f71 的合同文件 diff。

因此只能认定“叙述符合政策”，不能认定“运行与合同事实已遵守政策”。

### 3.7 G｜决策一致性

**结论：FAIL。**

存在四项直接矛盾：

1. **D-01 条件未闭合：** 报告第 52 行仍写 `DEPENDENCY_BASELINE_DISCREPANCY=OPEN`，却同时宣称 G1 CLOSED。应同时记录 `ORIGINAL_STATUS=OPEN` 与 `CURRENT_STATUS=CLOSED`，并给出 resolution hash；若当前仍 OPEN，则 G1 不能关闭。
2. **D-08 Owner 权威缺失：** Owner 之前只批准“提交七项全文后再审”，未知内容不能被预先批准。TECH_LEAD 生成 C01–C07、QA-01 判定 PASS，均不能替代 HUMAN_OWNER 对具体 hard constraints 的批准。
3. **evaluator_hash 必填但仍 PENDING：** V3.0 Study Contract 将 evaluator hash 定义为 REQUIRED。报告第 97、105 行把它推迟到所谓 G2/F1 coding，既违反 G1 必填字段，又触发编码 Gate 循环。
4. **QA 不能替代 Owner：** QA-G1 PASS 是独立审查意见，不等于 HUMAN_OWNER 的 Gate 1 最终批准。SDD Gate 1 明确最终批准角色为 HUMAN_OWNER。

关于 evaluator hash，建议采用双哈希模型消除设计—实现循环：

```yaml
evaluation:
  evaluator_contract_hash: REQUIRED_AT_G1
  evaluator_implementation_hash: REQUIRED_BEFORE_ANY_RUNTIME_EXECUTION
```

- G1 冻结 evaluator 接口、算法、reduction、单位和测试向量的 contract hash；
- G3 BUILD_READY 前形成实现候选和 implementation hash；
- 任何真实 replay/shadow/pilot 前，Study 通过受控 amendment 绑定 implementation hash；
- implementation hash 未绑定时 fail-closed，禁止运行与比较。

如果不修改 schema，则必须在 G1 使用一个已经存在、可复核的 evaluator 实现 hash，不能保留 PENDING。

---

## 4. 风险 TOP 5

| 排名 | 风险 | 严重度 | 后果 |
|---:|---|---|---|
| 1 | G2 被误授权为 coding 阶段 | CRITICAL | 绕过 G2 HLD 与 G3 BUILD_READY，直接修改 evaluator/`train_ft.py` |
| 2 | QA-01/TECH_LEAD 实际替代 HUMAN_OWNER 关闭 D-08 与 G1 | CRITICAL | hard constraints 和 Study 风险值未经人类责任人批准 |
| 3 | evaluator hash PENDING 却宣称合同冻结 | CRITICAL | 运行时 evaluator 可漂移，metric identity 与 baseline 不可复现 |
| 4 | bundle/split 只有自述、无法独立重算 | HIGH | 当前哈希可能不对应 HEAD，数据泄漏或文件漂移不能被发现 |
| 5 | D-01 discrepancy 仍 OPEN | HIGH | canonical runtime 与 G0 依赖基线冲突，后续构建和测试不可复现 |

---

## 5. BLOCKER 清单与闭合条件

| ID | BLOCKER | 闭合条件 |
|---|---|---|
| EXP-G1-BLK-001 | 实际附件不是指定的专家评审提示词/证据包 | 提供正确 `G1_EXPERT_REVIEW_PROMPT.md` 及只读证据包 |
| EXP-G1-BLK-002 | G2_IMPLEMENTATION 越权 | 改为 G2_HLD_PREPARATION_ONLY；G3 前实现授权为 NO |
| EXP-G1-BLK-003 | G1 HUMAN_OWNER 最终批准未证实 | Owner 对完整 Study、D08 七项原文和 G1 bundle hash 显式签署 |
| EXP-G1-BLK-004 | evaluator_hash PENDING | 使用双哈希 schema 或在 G1 绑定已有 evaluator 实现 hash |
| EXP-G1-BLK-005 | D01 discrepancy OPEN | 追加闭合记录、锁文件/环境一致性证据和 QA 复核 |
| EXP-G1-BLK-006 | bundle hash 无法复现 | 提供 27 文件、固定 manifest、版本化脚本、Git commit 和重算输出 |
| EXP-G1-BLK-007 | split/无泄漏无法复现 | 提供 row manifest、公式、脚本、重复检测和 ACL 证据 |

所有 BLOCKER 关闭后，才能重新申请独立专家结论；QA-01 无权豁免这些项。

---

## 6. 要求项目方执行的只读复现命令

以下命令不得修改 main、不得 checkout 到共享脏工作树。`REPO` 应指向保留的治理 worktree。

### 6.1 Git 与基线链

```bash
REPO=/absolute/path/to/governance-worktree

git -C "$REPO" status --short
git -C "$REPO" branch --show-current
git -C "$REPO" rev-parse HEAD
git -C "$REPO" rev-parse 83e41c1^{commit}
git -C "$REPO" rev-parse 548b8de^{commit}
git -C "$REPO" rev-parse ee5c667^{commit}
git -C "$REPO" rev-parse 7dc0f71^{commit}
git -C "$REPO" log --oneline --decorate 83e41c1..7dc0f71
```

必须保存完整 40 位输出，不能只保存短 SHA。

### 6.2 当前 HEAD 是否仍对应被冻结 bundle

项目方应从 bundle manifest 读取精确路径集合，不得手工拼写：

```bash
python evidence/mvd/g1/recompute-g1-bundle.py \
  --repo "$REPO" \
  --commit 548b8de \
  --manifest evidence/mvd/g1/g1-bundle-input-manifest.txt \
  --verify-archive evidence/mvd/g1/g1-bundle-hash-archive.json

git -C "$REPO" diff --exit-code 548b8de..7dc0f71 -- \
  $(cut -d '|' -f 1 "$REPO/evidence/mvd/g1/g1-bundle-input-manifest.txt")
```

如果仓库不存在上述版本化脚本或 manifest，`B_HASH_REPRODUCIBILITY=FAIL`。项目方应使用实际受控路径修正命令，不得仅复制本报告中的示意文件名后制造空 PASS。

### 6.3 统计 golden vectors

```bash
"$REPO/.venv/bin/python" -m pytest -q \
  tests/mvd/test_paired_student_t_policy.py \
  tests/mvd/test_decision_bar_boundaries.py \
  tests/mvd/test_insufficient_evidence.py
```

至少覆盖：正/负/零 delta、等于 ±bar、SE=0、n=2、缺 seed、重复 seed、NaN/Inf、minimize/maximize。

### 6.4 数据 split 重算

```bash
"$REPO/.venv/bin/python" evidence/mvd/g1/reproduce-d12-split.py \
  --dataset-revision 12567cabf869d7c92e573c7c783905fc160e9639 \
  --expected-arrow-sha256 e0b8d2a4fd14442983201e182c15ab2c82175064128920839408ea57dc04015e \
  --expected-row-digest 58174bbb6f7f80ac7cb12555dbbff2a4a5e1731424369ab62850446082afb555 \
  --expected-train 41567 \
  --expected-validation 4965 \
  --expected-final-test 5228
```

脚本必须输出：集合互斥、并集完整、exact duplicate=0、near-duplicate 检查策略和三个 split 的独立 SHA-256。若脚本不存在或需访问浮动远端数据，E 维度继续 FAIL。

### 6.5 环境差异闭合

```bash
"$REPO/.venv/bin/python" -V
"$REPO/.venv/bin/python" -m pip show torch pydantic loguru
"$REPO/.venv/bin/python" -c \
  'import sys,torch; print(sys.executable); print(torch.__version__); print(torch.version.cuda)'
"$REPO/.venv/bin/python" -m pip freeze --all
"$REPO/.venv/bin/python" -m pytest -q
```

输出必须与 canonical runtime manifest、dependency correction 和 lock hash 一致。

### 6.6 权限与 state root

```bash
realpath /home/szf/mvd-state
stat -c '%n|%U|%G|%a|%F|%d' /home/szf/mvd-state
findmnt -T /home/szf/mvd-state
namei -l /home/szf/mvd-state
```

ACL 负向测试须分别以 iterative、final-eval、committer 身份执行；仅由同一用户改变环境变量或字符串 principal 不算权限隔离。

---

## 7. 最小整改提交包

项目方无需重做全部 G1，只需提交一个 append-only 专家复核包：

1. 正确的 `G1_EXPERT_REVIEW_PROMPT.md`；
2. `G1_EXPERT_REVIEW_INPUT_MANIFEST.json`，列出每个输入的 path、SHA-256、Git blob SHA；
3. 548b8de、ee5c667、7dc0f71 的完整 SHA 和 bundle 文件差异报告；
4. D01 `CURRENT_STATUS=CLOSED` 的 resolution evidence；
5. D08 七项 hard constraints 原文及 HUMAN_OWNER 显式批准；
6. evaluator 双哈希 ADR/schema amendment，或现有实现 hash；
7. bundle/split 的版本化重算脚本及原始输出；
8. 修订后的 Gate crosswalk，明确 G3 才授权编码；
9. QA-01 对整改包的复核，但 QA 结论仍不得替代 Owner；
10. 更新后的 `PROJECT_STATUS.yaml`，在复核完成前不得写 G1 CLOSED。

整改期间建议状态：

```text
CURRENT_GATE=G1_CONTRACT_BASELINE_REMEDIATION
G0_STATUS=PASS_CLOSED
QA_G1_STATUS=PASS_REPORTED_UNDER_EXPERT_CHALLENGE
G1_STATUS=REMEDIATION_REQUIRED
HUMAN_OWNER_G1_APPROVAL=PENDING
NEXT_AUTHORIZED_ACTION=SUBMIT_G1_EXPERT_REVIEW_EVIDENCE_PACKAGE
IMPLEMENTATION_AUTHORIZED=NO
PILOT_AUTHORIZED=NO
UNATTENDED_24X7_AUTHORIZED=NO
PRODUCTION_READY=NO
```

---

## 8. 对 `G1_EXPERT_REVIEW_PROMPT` 设计的意见

根据用户对提示词的描述，A–G 七维、machine facts 优先、允许推翻 QA-01、要求复现命令的方向正确。但由于实际提示词未提供，不能做逐行 PASS。正式版本还应明确加入：

1. 权威输入及冲突优先级，尤其说明 MVD V3.0/V1.1 对早期 SDD Gate 措辞的 supersession；
2. 缺失证据必须判 `FAIL(EVIDENCE_NOT_AVAILABLE)`，不能用 WARN 规避；
3. HUMAN_OWNER、QA-01、独立专家三种结论分别记录，禁止互相替代；
4. 评审只读，不得由专家静默修复后自签 PASS；
5. 必须审核 Gate 授权语义，不仅审核合同内容；
6. 必须验证当前 HEAD 与 bundle 锚点间的目标文件零差异；
7. 必须检查必填字段是否存在 PENDING、OPEN、TBD 或未授权默认值；
8. 输出结论应包含 `PASS / BLOCKED_FOR_REMEDIATION` 总门禁，不只给逐项评分。

---

## 9. 给 HUMAN_OWNER 的建议决定

```text
OWNER_DECISION=DO_NOT_AUTHORIZE_G2_AT_THIS_TIME

G0_STATUS=PASS_CLOSED
G1_REPORTED_QA_STATUS=PASS
G1_EXPERT_REVIEW_STATUS=BLOCKED_FOR_REMEDIATION
G1_OWNER_CONFIRMATION=WITHHELD
G2_START_AUTHORIZED=NO
G2_IMPLEMENTATION_AUTHORIZED=NO
IMPLEMENTATION_AUTHORIZED=NO

REQUIRED_REMEDIATION=EXP-G1-BLK-001_TO_007
NEXT_AUTHORIZED_ACTION=SUBMIT_READ_ONLY_G1_EXPERT_REVIEW_EVIDENCE_PACKAGE

WHEN_REMEDIATED_NEXT_GATE=G2_HLD_PREPARATION_ONLY
CODING_GATE=G3_BUILD_READY
PILOT_GATE=G5_CONTROLLED_PILOT
```

Owner 不应批准“G2 implementation”。在本报告 BLOCKER 全部闭合、独立复现通过并由 HUMAN_OWNER 正式确认 G1 后，下一项授权只能是 **G2 HLD 编制与评审**；任何 evaluator 实现或 `train_ft.py` 修改必须等待 G3 BUILD_READY。
