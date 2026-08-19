# AutoDL 架构与训练优化流程说明

> 配套图：`architecture.html`（系统架构图）、`training_flow.html`（训练优化流程图）。
> 基于源码 `core/loop.py`、`core/agents.py`、`core/execution.py`、`core/monitor.py`、
> `core/ledger.py`、`core/memory.py`、`core/experiment_contract.py`、`gpu/detect.py` 梳理。

---

## 一、架构图配套说明

### 1.1 分层结构
系统分为四个平面，形成"编排—执行—治理"的闭环：

| 平面 | 主要模块 | 职责 |
|------|----------|------|
| **控制面** | `loop.py` + `agents.py` | 读账本→Leader 生成 THINK→Dispatcher 调度三类 Agent |
| **执行面** | `execution.py` + `gpu/*` + `monitor.py` | 多后端运行训练、GPU 选卡、进度与停滞检测 |
| **数据/治理面** | `workspace/`、`experiment_contract.py`、Git、快照 | 预算契约、写保护、版本化升级、知识沉淀 |

### 1.2 控制面（多智能体编排）
- **Leader（编排者）**：每轮读取 `experiments.jsonl` 账本（`recent`/`best_metric`/`detect_stagnation`），
  生成 `THINK`（下一步假设与计划），再调度 **Code Agent** 执行。
- **Dispatcher**：管理 `max_parallel` 并行度、任务队列与 **PID 追踪**（保障实验可观测、可收割）。
- **三类 Worker Agent**（按最小工具集隔离，降低 token 成本）：
  - Idea Agent：文献检索（`search_papers`/`search_arxiv`/`get_paper`）生成假设；
  - Code Agent：`run_shell` / `launch_experiment` / 文件读写，负责改代码与启动实验；
  - Writing Agent：产出论文/报告。
- **ToolRegistry**：每个 Agent 只拿到 3–5 个工具（而非全部），并在 `state.json`/`MEMORY_LOG` 等
  受保护文件上施加 **ProtectedWritePolicy** 写边界。

### 1.3 执行面（多后端 + GPU）
- **ExecutionBackend** 三态：`local`（本机 subprocess + nohup 日志重定向）、`ssh`（远程训练节点）、
  `slurm`（sbatch 提交 + sacct 探针，按 `--gres` 分配 GPU，并带 anti-hang 的 unknown_grace_polls 与
  time_buffer 兜底）。
- **GPU 子系统**（`gpu/detect.py` + `gpu/keeper.py`）：通过 `nvidia-smi -L` 探测卡列表，
  `gpu_status()` 取显存/利用率/温度，`get_free_gpus(reserve_last=True)` 选空闲卡并**保留最后一张做保活**，
  避免 keep-alive 被训练任务挤占。
- **Monitor**：轮询实验进度，识别停滞（`detect_stagnation`），为 Leader 的"无进展衰减"提供依据。

### 1.4 数据面与治理（持久化 + 安全升级）
- **workspace/**：`state.json`（周期状态）、`experiments.jsonl`（只追加账本）、`candidate/` 与
  `champion/` 分支隔离。
- **ExperimentContract**：预算契约 + 写保护策略，所有实验启动前受约束（D0 受保护边界、A 预算契约）。
- **Git 仓库**：升级时记录 `champion_before_sha` / `candidate_sha` / `champion_after_sha`，实现可溯源的
  冠军分支锁定（"Champion never regresses"）。
- **快照/知识沉淀**：`snapshots.py` 导出每实验周期快照，`evidence/`、`contracts/` 沉淀经验。

---

## 二、训练优化流程图配套说明

### 2.1 主研究循环（8 步）
1. **读账本**：从 `experiments.jsonl` 取近期结果、最优指标、停滞信号。
2. **Leader THINK**：基于账本产出下一轮假设/计划。
3. **调度 Code Agent**：在 `ExperimentContract` 预算约束下派发任务。
4. **launch_experiment**：GPU 子系统选空闲卡 → 后台 nohup 拉起训练 → 重定向日志到 `training_logs/`。
5. **Monitor**：轮询进度，识别停滞。
6. **评估/判别**：读日志提取指标，对照目标给出 `verdict`（达标 / 不达标）。
7. **冠军升级**：达标时以 Git SHA 锁版冠军，并写入账本（含 `champion_after_sha`）。
8. **无进展衰减**：连续无进展则进入 `cooldown_interval` 或降低并行度，防止空转烧钱。

> 闭环：步骤 8 / 7 回流到下一轮"读账本"，形成持续自我优化。

### 2.2 三类模型的训练优化差异（步骤 4 内展开）
同一套循环框架，但不同模型在**超参搜索维度、资源策略、判别指标**上有差异：

| 维度 | 计算机视觉 (CNN/ViT) | 自然语言 (Transformer/LLM) | 推荐/序列 (Embedding) |
|------|----------------------|----------------------------|------------------------|
| 主要调参 | batch / LR / scheduler | 层数 / 隐藏维 / 注意力 | embedding 维 / 采样策略 |
| 优化手段 | 数据增强 + AMP + DDP 多卡 | 梯度累积 + 序列长度优化 | 负采样 + 稀疏特征 |
| 资源策略 | 单机多卡为主 | 显存受限，常走 ssh/slurm | 轻量单机训练 |
| 判别指标 | 验证集 top-1 + 早停 | 困惑度 / 下游任务指标 | AUC / NDCG |

三类路径最终在"收敛"处汇合：写回 `experiments.jsonl`（metrics + verdict + champion SHA），
若达标则经步骤 7 升级冠军并回流主循环。

### 2.3 关键设计原则（来自治理契约）
- **Isolate before mutate**：Code Agent 在 `workspace/` 沙盒改代码，不污染冠军分支。
- **Champion never regresses**：失败候选绝不修改冠军分支，仅当 `verdict=达标` 且 Git SHA 锁版才升级。
- **Machine facts over narrative**：升级决策基于账本中的结构化指标，而非 LLM 自评叙述。
- **持久账本零 LLM 成本**：`experiments.jsonl` 只追加，崩溃可恢复，细节不随 MEMORY_LOG 压缩而丢失。
