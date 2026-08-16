# G1 Owner 决策包（集中决策申请）

- **决策包 ID**：ODP-G1-20260817-001
- **申请人**：TECH_LEAD（ARCH-01）
- **目标**：申请 Owner 对 G1 合同基线中全部业务/风险值做一次集中决策
- **决策依据**：G0 证据（EVD-G0-010~020）+ G1 环境实测（G1-01/02）
- **提交时间 UTC**：2026-08-17T04:05:00Z
- **说明**：Tech Lead 不替 Owner 猜测以下值，仅提交推荐值、依据、替代方案、风险。

---

## 决策项汇总

| # | 决策项 | 推荐值 | 最终决定人 | 状态 |
|---|---|---|---|---|
| D-01 | canonical Python/runtime | .venv (3.10.12) | HUMAN_OWNER | 待决 |
| D-02 | active budget | 推荐 600s（见下） | HUMAN_OWNER + ARCH-01 | 待决 |
| D-03 | hard wall-clock timeout | 推荐 900s | HUMAN_OWNER + ARCH-01 | 待决 |
| D-04 | hardware cohort | COHORT-RTX3060L-6G | HUMAN_OWNER | 待决 |
| D-05 | repeats & seeds | 3 repeats, seeds [17,29,43] | HUMAN_OWNER + DEV-EVAL-01 | 待决 |
| D-06 | uncertainty/confidence policy | PAIRED_SE_V1, 2x pooled SE | HUMAN_OWNER | 待决 |
| D-07 | minimum practical delta | 正且有限，DEV-EVAL 校准（建议 0.02 nats） | HUMAN_OWNER + DEV-EVAL-01 | 待决 |
| D-08 | hard constraints | 7 项候选（见下） | HUMAN_OWNER + ARCH-01 | 待决 |
| D-09 | protected paths / 变更文件数 / diff 上限 | allowlist=train_ft.py, max_files=1, max_diff=200 | SEC-01 + HUMAN_OWNER | 待决 |
| D-10 | selection/test/committer principals | DEV-ITERATIVE / QA-01 / DEV-VCS-01 | HUMAN_OWNER | 待决 |
| D-11 | artifact root & ledger path | artifacts/mvd/ + specs/mvd/ledger/ledger.jsonl | HUMAN_OWNER | 待决 |
| D-12 | dataset/metric identity 指纹 | 需 Owner 确认数据源（alpaca-cleaned 快照） | HUMAN_OWNER | 待决 |

---

## D-01 canonical Python/runtime

- **推荐**：`.venv`（/home/szf/env/AutoDL/.venv/bin/python, Python 3.10.12）
- **依据**：唯一完整可运行环境。loguru 硬依赖齐全；torch 2.5.0+cu124 与 G0 基线一致；288 测试通过。anaconda base 缺 loguru 无法运行。
- **替代方案**：
  - A. anaconda base（3.11.7）——需补装 loguru + 重建 torch 2.5.0 基线 + 重跑 288 测试，成本高，不建议。
  - B. 双环境并用——违反"单一运行环境"要求，不可行。
- **风险**：若选 anaconda base，需额外安装与验证，G1 延迟。

## D-02 active budget

- **推荐**：**600s**（active_train_seconds）
- **依据**：G1 环境实测：历史 300s 在 RTX3060L-6G 上对 Qwen-0.5B 训练偏紧。600s 提供 3 seed 配对训练余量。C8/C9 试点实际训练量佐证 300s 不足以完成多 seed。
- **替代方案**：A. 300s（沿用历史，但 Owner 决策约束禁止直接沿用）；B. 900s（更宽裕但延迟）。
- **风险**：600s 若仍不足需 HUMAN_REVIEW 扩展；过长则资源浪费。

## D-03 hard wall-clock timeout

- **推荐**：**900s**
- **依据**：含 queue/setup/compile/eval/artifact 全流程，为 active budget 的 1.5x，保证不被悬挂拖死。
- **替代方案**：A. 720s（更紧）；B. 1800s（更宽）。
- **风险**：过短可能误杀正常训练，过长浪费资源。

## D-04 hardware cohort

- **推荐**：**COHORT-RTX3060L-6G**（NVIDIA GeForce RTX 3060 Laptop GPU, 6GB, driver 555.42.02）
- **依据**：与 G0 基线一致，固定 cohort 保证公平比较。
- **替代**：无（唯一可用 GPU）。
- **风险**：若 GPU 型号/驱动变更需重新冻结 cohort。

## D-05 repeats & seeds

- **推荐**：**repeats=3, seeds=[17,29,43]**
- **依据**：3 个配对 seed 满足最小配对统计要求；与 G0 基线噪声研究 seed 一致（可复用噪声证据）。
- **替代**：A. repeats=5（更稳健但资源×1.67）；B. seeds=[17,29]（不足 3，违反最小配对要求）。
- **风险**：seed 不足 3 时配不齐 → HUMAN_REVIEW。

## D-06 uncertainty/confidence policy

- **推荐**：**PAIRED_SE_V1 + 差值超过 2x pooled SE**
- **依据**：配对实验减小 seed 方差；2x pooled SE 作为置信门槛，与 G0 基线 noise 研究一致。
- **替代**：A. 独立样本 SE（不配对，方差更大）；B. 1x SE（置信过松）。
- **风险**：若 paired 假设不成立需重估。

## D-07 minimum practical delta

- **推荐**：**0.02 nats**（validation_loss, 正且有限）
- **依据**：由 DEV-EVAL 基于 G0 噪声研究（validation 噪声 std~0.18pp 对应 loss 尺度）校准；需显著大于配对 SE 且具实践意义。
- **替代**：A. 0.01 nats（更敏感但噪声风险高）；B. 0.05 nats（更保守但难达成）。
- **风险**：C8/C9 数据不得反推此值（仅诊断）。

## D-08 hard constraints

- **推荐（候选完整集）**：
  1. `resource_quota_1xRTX3060L`
  2. `dependency_change_forbidden`
  3. `data_readonly`
  4. `governance_contracts_readonly`
  5. `tests_oracle_readonly`
  6. `destructive_git_forbidden`
  7. `no_test_feedback_to_iterative_agent`
- **替代**：A. 显式空集合（不推荐，有隔离/安全底线风险）；B. 减少为 5 项（风险提升）。
- **风险**：遗漏关键项（如 data 只读）可能导致破坏性操作。

## D-09 protected paths / 变更文件数 / diff 上限

- **推荐**：allowlist=`examples/llm_finetune/train_ft.py`；max_changed_files=1；max_diff_lines=200
- **依据**：强隔离，不按成本降级（SEC-01 建议）。
- **替代**：A. 放宽 allowlist（不推荐）；B. 更严 max_diff=100（更稳但束缚开发）。
- **风险**：过严束缚 agent 优化，过宽有破坏风险。

## D-10 principals

- **推荐**：iterative=`DEV-ITERATIVE`；final_eval=`QA-01`；committer=`DEV-VCS-01`
- **依据**：职责分离，test 平面与迭代平面 ACL 分离。
- **替代**：A. 单一 principal（违反隔离）；B. 仅 namespace 分离（ACL 不完整）。
- **风险**：principal 若无法在工具层强制需 VCS/artifact ACL 兜底。

## D-11 artifact root & ledger path

- **推荐**：artifact_root=`artifacts/mvd/`；ledger_path=`specs/mvd/ledger/ledger.jsonl`
- **依据**：集中管理，append-only，可重放。
- **替代**：A. 按 study 分目录（artifacts/mvd/STUDY-MVD-SH-QWEN-001/）；B. 放 workspace/。
- **风险**：路径不一致导致追溯断裂。

## D-12 dataset/metric identity 指纹

- **推荐**：`alpaca-cleaned` 固定快照；指纹需 Owner 确认数据源后由 DEV-EVAL 计算。
- **依据**：metric identity 需 dataset/split/preprocess/evaluator 全部固化。
- **替代**：A. 使用 hf-mirror 拉取的最新快照（需锁哈希）；B. 本地缓存（需验证完整性）。
- **风险**：指纹未锁导致不可复现。

---

## 决策生效后动作

Owner 批准本决策包（或调整个别项）后，Tech Lead 将：
1. 用决策值回填 `STUDY-MVD-SH-QWEN-001.yaml` 的所有 `PENDING_OWNER_DECISION`。
2. 计算 contract_hash 与 policy_bundle_hash。
3. 更新各策略文件（G1-04~G1-10）为正式冻结态。
4. 生成 G1-13 QA 独立签署（QA-01）。
5. 更新 PROJECT_STATUS.yaml（完整 40 位 SHA）。
6. 若 G1 门禁全满足 → G1_STATUS=PASS。

> 本决策包不重新开放 OB-2、OB-3（除非 Owner 显式修改原决定）。
