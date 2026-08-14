# 交接文档：autoresearch 提升机制对比分析 & AutoDL 改造建议

> **文档性质**：交接文档（供其他 AI 智能体审阅，无需重读两个项目全部源码）
> **日期**：2026-08-15
> **作者**：Tech Lead
> **审阅指引**：本文档已自包含核心结论与关键证据。若需交叉验证，请参阅随附的 `evidence/` 代码证据包。

---

## 1. 任务背景

对两个自动化深度学习研究项目做机制对比，判断当前项目 `AutoDL` 是否完全吸收了 `autoresearch` 项目的设计优点，并识别提升空间。

- **autoresearch**：`/home/szf/env/autoresearch`（极简、单文件可改、固定时间预算）
- **当前项目**：`/home/szf/env/AutoDL`（多 agent、多后端、零成本监控）

---

## 2. autoresearch 提升机制深度解析

### 2.1 核心设计哲学

autoresearch 是**单文件可改的自主实验系统**，目标：让 agent 在无人干预下反复改进模型、逼近最优。其核心是 **"固定时间预算 + 归一化指标 + git 回退闭环"** 三件套。

### 2.2 六大机制（按重要性）

| # | 机制 | 代码位置 | 本质作用 |
|---|------|----------|----------|
| 1 | **固定时间预算** | `prepare.py:31` `TIME_BUDGET=300`；`train.py:516-604` | 训练按**时长**而非 epoch 停止，所有调度基于 `progress=training_time/TIME_BUDGET`。**使任意架构改动在相同计算预算下可公平比较** |
| 2 | **BPB 归一化指标** | `prepare.py:340-365` `evaluate_bpb` | bits-per-byte，按 token 字节长度归一化，**与 vocab size 无关**，跨架构可比 |
| 3 | **git 驱动实验闭环** | `program.md` 协议 | 每实验一 commit；改进→`git commit` KEEP；变差→`git reset` DISCARD；崩溃→CRASH。git 历史=实验记忆 |
| 4 | **simplicity criterion** | `program.md` | 显式约束 agent 权衡"复杂度成本 vs 改进幅度"，防过度工程 |
| 5 | **指标可解析** | `grep "^val_bpb:" run.log` | 防日志刷爆上下文 |
| 6 | **NEVER STOP** | `program.md` | 无限迭代到被打断 |

---

## 3. 两项目提升机制对比表

| 维度 | autoresearch | AutoDL | 判定 |
|------|-------------|---------------------------|------|
| 固定时间预算归一化 | ✅ `TIME_BUDGET=300s` | ❌ 无，按 epoch 跑 | 🔴 当前缺失 |
| 指标归一化可比性 | ✅ `val_bpb`（vocab 无关）| ⚠️ `test_accuracy`/`metric`（任务相关）| 🟡 当前较弱 |
| git 驱动的改进/回退闭环 | ✅ commit/KEEP/reset/DISCARD | ❌ 仅写台账，无代码回退 | 🔴 当前缺失 |
| simplicity criterion | ✅ 显式约束 | ❌ 无 | 🟡 当前缺失 |
| 单文件聚焦修改 | ✅ 只改 `train.py` | ⚠️ code agent 可任意写文件 | 🟡 当前较弱 |
| NEVER STOP 自主性 | ✅ 无限迭代 | ⚠️ `max_cycles` 受限（可配置）| ⚪ 取向不同 |
| 训练期零 LLM 成本 | ❌ 无概念 | ✅ `core/monitor.py` 零成本监控 | 🟢 当前更强 |
| 多后端执行 | ❌ 单 GPU | ✅ local/ssh/slurm | 🟢 当前更强 |
| 多 agent 编排 | ❌ 单 agent | ✅ Leader-Worker | 🟢 当前更强 |
| 记忆系统 | ⚠️ 仅 git+tsv | ✅ 台账+记忆+洞察+死胡同 | 🟢 当前更强 |

---

## 4. 核心结论

### 4.1 是否完全吸收？—— **否**

当前项目在**工程架构**上全面超越 autoresearch（多后端、多 agent、零成本监控、记忆系统），但在**"提升模型训练效果"的核心闭环**上缺失 autoresearch 最精华的机制：

| 优先级 | 缺失机制 | 缺失影响 |
|--------|---------|----------|
| 🔴 P0 | 固定时间预算归一化 | agent 无法公平比较"相同预算下哪个改动最优"，找不到平台最优模型 |
| 🔴 P0 | git 驱动的改进保留/变差回退 | 坏的改动不回退，迭代不形成"单调向优"轨迹 |
| 🟡 P1 | simplicity criterion | 可能接受"微小改进+高复杂度"的次优改动 |
| 🟡 P1 | 单文件聚焦修改 | code agent 改动范围不可控，diffs 难审查 |

### 4.2 根因判断

当前项目设计重心在**工程扩展性**（怎么跑得远），弱化了 autoresearch 赖以成功的**实验闭环设计**（怎么跑得好）——即"固定预算 + 归一化指标 + git 回溯"这套让 agent 可靠单调逼近最优的引擎。

---

## 5. 改造建议

### 建议 A（P0）：引入固定时间预算归一化
- 在 `config.yaml`/`PROJECT_BRIEF.md` 声明 `TIME_BUDGET`
- 让训练脚本按"训练时长"而非 epoch 停止
- 用统一指标（val_loss/自定义归一化指标）评估
- 改造点：brief 规范 + 监控指标解析适配

### 建议 B（P0）：建立 git 驱动的实验闭环
- REFLECT 阶段增强：指标改进→`git commit` 保留；变差→`git reset` 回退
- `experiments.jsonl` 记录 commit hash 与 keep/discard 状态
- 改造点：`core/loop.py` REFLECT 后处理 + `core/ledger.py`

### 建议 C（P1）：加入 simplicity criterion
- 在 leader/code agent prompt 显式加入"权衡复杂度成本 vs 改进幅度"约束
- 改造点：`agents/*.md` prompt

### 建议 D（P1）：收敛 code agent 修改范围
- 约束 code agent 聚焦修改单个训练文件
- 改造点：code agent prompt + tool 权限

---

## 6. 证据索引

随附 `evidence/` 目录包含支撑本报告的关键代码段落：

| 证据文件 | 来源 | 支撑结论 |
|----------|------|----------|
| `evidence/ar_train_time_budget.py` | `autoresearch/train.py:513-604` | autoresearch 固定时间预算机制 |
| `evidence/ar_prepare_bpb.py` | `autoresearch/prepare.py:340-365` | autoresearch BPB 归一化指标 |
| `evidence/current_loop_execute_reflect.py` | `AutoDL/core/loop.py:248-301` | 当前项目按 pid 监控，REFLECT 仅写记忆 |
| `evidence/current_loop_ledger.py` | `AutoDL/core/loop.py:466-499` | 当前项目仅写台账，无 git 回退 |
| `evidence/current_config_no_time_budget.yaml` | `AutoDL/config.yaml` + `examples/mnist_gpu/config.yaml` | 当前项目配置**无 time_budget 归一化**（佐证 P0 缺失项①）|
| `evidence/ar_program_md.md` | `autoresearch/program.md` | git 闭环 + simplicity criterion + NEVER STOP |

> **补充佐证**：对 `AutoDL/core/` 全目录搜索 `git.commit/reset/revert`，**0 处匹配**——证实当前项目核心代码无任何 git 驱动的实验回退机制。

---

## 7. 审阅请求

请审阅以下关键问题（按优先级）：

### 7.1 判断核实（请逐条给出一致/异议 + 理由）
1. **对比表是否有误**？尤其两处 P0 判断：
   - P0-①：当前项目"无固定时间预算归一化"是否准确？（证据：`current_config_no_time_budget.yaml`）
   - P0-②：当前项目"无 git 驱动的改进/回退闭环"是否准确？（证据：`current_loop_ledger.py` + 0 处 git 匹配佐证）
2. **指标可比性判断**：当前项目的 `test_accuracy`/`metric` 是否真的弱于 autoresearch 的 `val_bpb`？有无当前项目已具备的归一化手段被遗漏？

### 7.2 改造方案评审（建议 A/B）
3. **建议 A（固定时间预算）**：改造点在"brief 规范 + 监控指标解析"。请评估：
   - 是否与当前项目 `poll_interval`/`wait_for_completion` 机制冲突？
   - `TIME_BUDGET` 应放在 config 还是 brief？如何被监控层感知？
4. **建议 B（git 回退闭环）**：改造点在 REFLECT 后处理。请评估：
   - 如何在 `experiments.jsonl` 中记录 commit hash 与 keep/discard 状态？
   - 回退时如何保证不丢失已训练的模型/结果（git 回退会删 commit，需先归档结果）？
   - 是否需要 git branch 策略（如 autoresearch 的 `autoresearch/<tag>` 分支）？

### 7.3 遗漏与补充
5. 是否有 autoresearch 的**其他优点**被本报告遗漏（如数据并行、checkpoint、日志管理）？
6. 当前项目的**独有优势**（零成本监控、多后端、多 agent）是否足够弥补 P0 缺失，还是 P0 缺失是决定性短板？

### 7.4 落地顺序与风险
7. 建议落地顺序（A→B→C→D？）与每步的风险提示。
8. 若只做一项，选 A 还是 B？为什么？
