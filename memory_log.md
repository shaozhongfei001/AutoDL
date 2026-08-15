[machine:INCOMPARABLE] no metrics in log

---

## E2E 验证归档 — 稳定性加固 (A+B+D+E) RESULT 协议端到端生效
**日期**: 2026-08-15 20:xx（当前会话）
**提交前**: core HEAD 3b95f10 + 本次 A/B/D/E 加固

### 背景
用户要求验证 RESULT 协议在完整 Agent 循环中端到端生效。检测到旧 STUDY-001 循环进程 PID 2793940（已运行约5h，处于反复确认 CLOSED 状态），经用户确认后终止，并重置 mnist_gpu workspace 至干净基线。

### 验证方式
- 环境: DeepSeek 官方 API (`provider=openai`, `base_url=https://api.deepseek.com`, model=deepseek-chat) + loguru 结构化日志 + anaconda PATH（含 torch 2.3.0 + CUDA）
- 启动: `PYTHONPATH=项目根 .venv/bin/python -m core.loop --project examples/mnist_gpu --gpu 0` 无人值守
- 进程: PID 3736849，推进至 Cycle 9 后手动停止（用户授权）

### E2E 证据 — RESULT 协议在 3 个真实 GPU 训练 cycle 全部解析成功
| Cycle | 实验 | RESULT 解析指标 | 机器判定 |
|-------|------|----------------|---------|
| 1 | dry-run 合规审查 | val=0.9852, test=0.9851, loss=0.2529 | INCOMPARABLE（无基线） |
| 2 | 改 CNN 架构 (32→64通道, 更深) | val=0.9858, test=0.9847, loss=0.0633 | DISCARD（未超 champion 0.99） |
| 3 | 加正则化 | val=0.9458, test=0.9459, loss=0.4585 | DISCARD（退化） |
| 4+ | leader 判断 pilot 收敛，转 writing agent 出报告 | — | 收尾 |

### A/B/D/E 全部生效确认
- **A loguru 框架日志**: 全程彩色结构化 `2026-08-15 20:17:51.798 | INFO | logging:968`
- **A RESULT 结构化指标**: 每个训练 cycle 精确解析 `validation_accuracy/test_accuracy/validation_loss` 三键，替代旧正则零散提取
- **B launch_experiment 落盘**: `logs/round2_train.log` 等，无 run_shell 跑训练，无路径不一致
- **E 空指标归零**: 本轮 **0 次空指标**（旧试运行曾有 4 次），INCOMPARABLE 仅因无基线
- **机器判定闭环**: 3 轮全部正确判定，champion 保护正常，预算契约 SUCCESS

### 附带修复
E2E 中发现并修复 E 类边界 bug: `_diagnose_empty_metrics` 在有可解析指标时仍误报 `result_no_numeric`；已加"有指标则返回空诊断"守卫并补测试，全套 274 测试通过。

### 遗留观察
- 循环在 Cycle 4 后 leader 即判断 pilot 收敛转入报告，未继续多轮 CNN 搜索——MNIST 已饱和（champion ~0.99），改进空间有限，属合理收敛。
- launch_experiment 默认 `python` 解析到 `/usr/bin/python`（无 torch）；训练需显式用含 torch 的 anaconda python 或前置 PATH。已在启动时前置 `PATH=/home/szf/anaconda3/bin:$PATH`。

---

## 早停机制验证归档 — 循环级自动收敛 + 训练进程早停
**日期**: 2026-08-15 22:0x（当前会话）

### 背景
用户提出：模型效果不会在收敛就应该早停，而不是无限循环 loop 还要杀进程。针对 E2E 观察到的 leader 饱和后空转 report（旧 STUDY-001 跑 233-297 cycle 需手动杀）问题，实现两层面早停。

### 实现（两层面）
**层面 1 训练运行内 epoch 级早停（core/monitor.py）**：
- `_extract_epoch_metrics`：从实时日志解析每 epoch 验证指标序列（RESULT 快照 + 正则）
- `_check_in_run_early_stop`：验证指标连续 `patience` 个 epoch 无提升（超 `improvement_tol`）→ `_terminate` 提前终止训练进程
- 结果标记 `early_stopped=true`，contract 保持 SUCCESS（干净运行，非 crash）
- 配置：`experiment.budget.early_stop.{enabled,metric,patience,improvement_tol,min_epochs}`

**层面 2 循环级主动早停（core/loop.py `_early_stop_reason`）**：
- Trigger A 停滞：leader 连续 `max_consecutive_no_experiment` 轮未真正 launch 实验（report/wait 空转）→ 收敛
- Trigger B 饱和：连续 `saturation_rounds` 轮机器 DISCARD 且 delta 在噪声平台带（`|delta| <= plateau_band*noise_std`）→ 收敛
- 配置：`experiment.loop_engineering.early_stop.{enabled,saturation_rounds,plateau_band,max_consecutive_no_experiment}`

### 验证证据（完整 Agent 循环 PID 4063772，自动收敛，无需手动杀进程）
| Cycle | 架构 | 指标 | 判定 |
|-------|------|------|------|
| 1 | baseline 2-conv | val=0.9878 | INCOMPARABLE（建基线） |
| 2 | 改结构 | val=0.9868 | DISCARD |
| 3 | 改结构 | val=0.9902 | DISCARD |
| 4 | 宽度增广 | val=0.9906, test=0.9918 | DISCARD |
| **收敛** | — | — | **`converged (early-stop): 3 consecutive DISCARD within noise plateau; champion saturated`** |

- **循环在 Cycle 4 后自动收敛退出**（`AutoResearcher stopped.`，state.json: cycle=4, status=completed），不再空转、不需手动杀进程
- 训练进程早停另经真实 GPU 直接验证（PID 4025868 在平台期被 `terminating to save GPU` 提前终止）+ 单测 `test_monitor_terminates_plateaued_run`
- 收敛判定合理：champion 0.9906 已达 MNIST 饱和区，后续 DISCARD delta 均在噪声带，继续搜索浪费资源

### 配置要点
- `improvement_tol` 需匹配指标噪声（MNIST val 噪声 ±0.002，设 0.001 更稳；0.0005 过严导致波动上升序列不触发）
- train.py 默认 epochs 3→8（提供足够平台期供早停观察）；每 epoch 打印 `validation_accuracy=X`（早停解析前提）
- 早停 Trigger B 要求 champion 已建立 + delta 严格在噪声带，避免误杀仍在探索的任务；disabled=false 时完全向后兼容

### 测试
新增 `tests/test_early_stop.py`（12 个用例），全套 286 测试通过（原 274 + 12）。

