# PHASE PLAN — PILOT-P0 环境准备

```yaml
phase_id: "PILOT-P0"
task_id: "PILOT-MNIST-GPU"
objective: >-
  准备 mnist_gpu 真实 GPU 无人值守试运行环境：备份上次运行成果、重置干扰状态、
  确认预算/受控基线/GPU/数据就绪，使多轮候选实验由机器判定晋级。
dependencies: []
scope:
  allow:
    - "examples/mnist_gpu/workspace/"   # 重置干扰状态（先备份）
    - "examples/mnist_gpu/config.yaml"  # 确认预算配置
  deny: []
acceptance:
  - "workspace 残留已备份且干扰状态（cycle_counter/state/MEMORY_LOG/experiments）已重置"
  - "预算 300s/hard 420s 生效；受控基线 train.py 在项目根"
  - "GPU 空闲、数据完整（4 个正式 .ubyte）"
  - "无 lint 错误"
budget:
  max_cycles: 2
  max_api_calls: 5
  max_wall_seconds: 300
subagents:
  enabled: false
  ownership: {}
exit_on_fail: "retry_up_to_2_then_ask_human"
```

## 执行
1. 备份 `examples/mnist_gpu/workspace/` 到 `contracts/phases/PILOT-MNIST-GPU/backup_run_prev/`。
2. 重置试运行状态：`.cycle_counter=0`，删除 `state.json`/`MEMORY_LOG.md`/`experiments.jsonl`/`INSIGHTS.md`/`DEAD_ENDS.md`。
3. 更新 PROJECT_BRIEF 为"固定预算 + 机器判定晋级"的试运行目标（若与当前一致则跳过）。
4. 确认 config 预算、GPU、数据。
