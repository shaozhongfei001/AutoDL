# 阶段 0 回应：P0 证据闭合报告与落地计划

> **文档性质**：对《AutoResearch 机制对比与改造方案_独立评审报告_V1.0》阶段 0（证据与基线闭合）的落地执行产物。
> **日期**：2026-08-15
> **依据**：对 `/home/szf/env/AutoDL` 全仓的实际代码检索（非文档节选），旨在将评审所述"高概率成立"的两个 P0 升级为"已确认"或"已否定"。
> **检索命令**：使用仓库内容检索工具对 `core/` 与全仓执行了 Git 关键字、时间预算关键字、指标关键字三类检索。

---

## 1. P0 证据闭合裁决

### 1.1 P0-2：是否缺少"git 驱动的改进保留 / 变差回退闭环" → **已确认（CONFIRMED）**

**检索范围**：全仓（含 `core/`、`apps/`、`agents/`、`skills/`、`examples/`），模式：
```
git\.(commit|reset|revert|checkout|worktree|branch|tag|merge|stash)
git\s+(commit|reset|revert|checkout|worktree|branch|tag|merge)
subprocess.*git
shutil.*git
```

**结果**：
- 全仓**唯一的 git 相关匹配**全部位于文档/证据文件（`docs/evidence/*`、`docs/handover_*.md`）和 `CONTRIBUTING.md`（人类开发者提交流程说明）。
- **`core/` 内 0 处调用 git**；`agents/`、`skills/`、`examples/` 亦无任何 git 自动化。
- `core/loop.py` 的 `_execute`（EXECUTE）→ `_monitor_experiment`（MONITOR）→ `_reflect`（REFLECT）→ `_record_to_ledger`（台账）完整链路中，**不存在任何 commit / reset / revert / branch / worktree 操作**。
- `core/ledger.py` 的 `ExperimentLedger.record()` 仅记录 `cycle/hypothesis/action/status/metrics/pid/log_file/conclusion`，**无 commit SHA、无父版本、无 candidate/champion、无 verdict(KEEP/DISCARD/CRASH)、无 artifact manifest**。

**结论**：交接报告 P0-② 与评审 4.2 的判断成立。该缺口不仅限于 `core/loop.py` 两段节选，而是**全项目在运行时代码层确实不存在任何 git 驱动的实验版本化闭环**。评级从"高概率成立"升级为"已确认"。

### 1.2 P0-1：是否缺少"显式、可执行、可审计的实验有效性合同（含时间预算）" → **已确认（CONFIRMED）**

**检索范围**：全仓，模式：
```
time_budget|TIME_BUDGET|deadline|hard_timeout|max_duration|wall_clock|budget
```

**结果**：
- `core/` 中所有 `budget` 命中均为**非训练时间预算**概念：
  - `core/agents.py:512` — `token budget`（LLM 输出 token 上限）
  - `core/memory.py:8` — `memory budget`（两级记忆 5000 字符上限）
  - `core/safety.py:10` — `cycle budget`（`max_cycles_per_hour` 防烧钱速率限制）
- `core/execution.py:56` 的 `"DEADLINE"` 是 Slurm `sacct` **作业状态枚举**（BOOT_FAIL/DEADLINE/REVOKED 等），非训练预算控制。
- **没有任何配置字段、CLI 参数、环境变量、训练脚本约定用于"按训练时长停止/公平比较"**。
- `core/loop.py:621-626` 与 `core/obsidian.py` 用 `yaml.safe_load` 加载配置，**无 schema 校验**（评审要求"机器权威值放有 schema 校验的 config"，当前无 schema 机制）。
- `core/monitor.py:74-104` 的 `wait_for_completion` 是纯轮询 `while _is_process_alive(pid)`，**无训练预算执行、无硬超时兜底**（仅 Slurm 后端借集群 `--time` 兜底，非公平比较预算）。
- 训练结束条件完全由 code agent 写的 `train.py` 决定（epoch/steps），指标为任务相关值。

**结论**：交接报告 P0-① 与评审 4.1 的判断成立。当前项目**既无固定时间预算归一化，也无更广义的"实验有效性合同"**（预算、评估器、数据版本/split、环境 cohort、种子、重复次数、指标方向、min_effect_size 均无机器可执行的定义）。评级从"高概率成立"升级为"已确认"。

---

## 2. 指标选优与 split 职责：**已确认存在 test 集泄漏风险**

**检索**：`core/monitor.py` 解析 loss/accuracy/FGD/FID（163-177 行），`examples/mnist_gpu/train.py:98-99` 直接 `test_accuracy=...` 作为最终输出。

**证据**：
- monitor 的指标解析器**不区分 validation 与 test**，也没有"validation 选优、test 仅独立验收"的职责划分。
- 示例训练脚本用 test 集作为唯一评估口径。
- `core/ledger.py` 的 `stagnation`（189-186 行）与 `phase_gate`（189-201 行）是 **advisory 判定**（仅输出建议），且基于单一 metric_key，**无 split 职责、无种子聚合、无噪声基线**。

**结论**：评审 1.1 第 4 点（逐轮用 test_accuracy 选优会造成自适应过拟合）**属实**。当前项目若开启多轮自动选优，确实可能把 test 集退化为训练反馈。

---

## 3. 评审相关技术点的实证佐证

### 3.1 写入保护现状（D0 相关）
- `core/tools.py:33` 存在 `_protected_files = {"state.json", "MEMORY_LOG.md", "PROJECT_BRIEF.md", ".lock"}`，`write_file` 会拒绝覆盖这些文件。
- 但**无 allowlist / denylist 目录级保护**，code agent 可写 workspace 内任意其他文件；`launch_experiment`/`read_file`/`list_tree` 因"路径必须相对 workspace"的约束反而误伤合法路径（见 3.2）。

### 3.2 实测工具边界问题（阶段 0 之外的补充发现）
实际执行 `light_demo` / `mnist_gpu` 时观察到：
- `run_shell` 用 `shlex.split` 解析，**不支持 shell 复合命令**（`cd ... && ...`），报 `[Errno 2] No such file or directory: 'cd'`。
- `launch_experiment` / `read_file` 因 agent 传绝对路径被"必须相对 workspace"拒绝。
- 结果：agent 绕开 `launch_experiment` 直接前台跑训练，**框架 monitor 未捕获 PID**，`experiments.jsonl` 出现 `pid:null, log_file:""`。

**含义**：这恰好印证评审第 7 节"工具边界/写入保护"的担忧——当前工具层的路径约束既**未实现评审要求的受保护边界（D0）**，又**阻碍了 `launch_experiment` 这一安全晋级路径的采用**。

---

## 4. 落地计划（按评审阶段顺序）

> 评审阶段顺序：**证据闭合 → A → D0 → B → C → 多后端/多 Agent 扩展**。阶段 0（证据闭合）已由本文档完成；后续阶段给出可执行设计。

### 阶段 1：A — 实验有效性合同（P0-1 落地）

**目标**：建立"预算 + 评估 + 数据 + 环境 + 种子 + 阈值"的机器可执行合同。

**改动点**：
1. **config schema**：新增 `experiment.schema_version` + `budget` + `evaluation` + `comparability` 段（对齐评审 6.3 推荐结构）；`loop.py` 配置加载处加最小 schema 校验（缺必填字段即报错）。
2. **预算执行**：训练脚本按 `active_train_seconds`（单调时钟）自终止；runner 设 `hard_wall_clock_limit` 硬超时兜底。支持预算模式枚举（active_wall_clock_seconds / optimizer_steps / samples_or_tokens）。
3. **split 职责**：指标解析区分 `validation_*`（选优）与 `test_*`（独立验收）。
4. **指纹**：记录 dataset/evaluator/environment hash，`comparability` 不满足 → 状态 `INCOMPARABLE`。

**验收**（评审 6.4）：预算达目标且误差可控；hard timeout 区分 CRASH/TIMEOUT/BUDGET_EXCEEDED；poll_interval 只影响完成发现延迟、不影响预算；指纹不同拒绝比较。

### 阶段 2：D0 — 最小安全写入边界（P0-1 的写入侧）

**改动点**：
1. 引入 **allowlist**（默认最小修改面：项目根 train.py + workspace/）与 **denylist**（评估器、数据、config、测试、制品目录）。
2. 受保护文件哈希门禁：执行前后验证数据/评估器边界 hash 未变。
3. 修复 3.2 的工具问题：`run_shell` 支持复合命令（或改为显式禁止 `&&`/`cd` 并提示用 `launch_experiment`）；`launch_experiment`/`read_file` 允许合理的 workspace 外路径（如项目根、logs/）。

**验收**：越界修改被执行前拒绝；受保护文件 hash 不变。

### 阶段 3：B — 隔离实验、制品与晋级（P0-2 落地）

**改动点**（评审 7.1/7.4）：
1. **champion 分支** + 每实验独立 worktree/候选分支（不共享目录 reset）。
2. code agent 仅在自己 worktree 内写。
3. 候选代码先 commit → 训练 → **制品先归档**（metrics/stdout/checkpoint/candidate.patch/environment/manifest + SHA-256）→ 再判定。
4. ledger 升级为**追加式事件账本**：`champion_before_sha/candidate_sha/champion_after_sha`、`verdict`(KEEP/DISCARD/CRASH/INCOMPARABLE)、`promotion_status`、`artifact_manifest_uri`。
5. 机器判定为权威，LLM 只提供 hypothesis/解释；KEEP 仅 fast-forward（parent SHA 乐观锁），过期候选重放重测。

**验收**（评审 7.6）：KEEP 只推进 champion 不丢制品；DISCARD/CRASH 不动 champion；崩溃后可从 ledger 恢复；并发 parent 过期不误晋级。

### 阶段 4：C — 复杂度治理

**改动点**：结构化采集 `changed_files/added_lines/deleted_lines/dependency_delta/params_delta/vram_delta`；晋级用词典序（先硬约束 → 主指标 min_effect_size → 同分选低复杂度 → 高复杂度微提升进 HUMAN_REVIEW）。

### 阶段 5：多后端 / 多 Agent 扩展

**改动点**：按 `hardware_cohort` 分组比较；并发候选重放、资源配额、故障恢复；跨 cohort 禁止自动排序。

---

## 5. 只做一项的选择（回应评审 1.2）

**选 A（完整实验有效性合同）**，理由与评审一致：B 决定"保存/回退"，A 决定"这个决定是否可信"。没有可信比较基础，自动 git 晋级只会把不可靠结论更快固化。唯一例外：若已存在多人/多 Agent 相互覆盖的现实风险，应先做 D0 最小写入保护止损。

---

## 6. 需要人工确认的决策点

1. **试点 study 选定**：建议用 `examples/mnist_gpu` 改造为固定预算（如 RTX 3060 上 300s active_train + validation 选优 + test 独立验收），作为阶段 1 试点。
2. **config vs brief 职责**：确认采纳评审 6.2 分层（config 存机器权威值、brief 只声明意图引用 profile）。
3. **落地深度**：本次仅完成阶段 0（证据闭合 + 计划）。是否授权继续实施阶段 1（A 合同）与阶段 2（D0）的具体代码改造？
