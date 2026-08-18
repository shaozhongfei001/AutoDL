# EVD-G0-017 Runner Flow（终态 / clock / timeout / process-tree 现状）

- **Evidence ID**：EVD-G0-017
- **Owner**：DEV-RUN-01
- **Collected by**：CodeBuddy（Tech Lead / ARCH-01）
- **Collected at UTC**：2026-08-16T16:40:00Z
- **Gate**：G0_EVIDENCE_CLOSURE

## 现状事实

### 1. 运行器与终态（当前实现）
- `core/execution.py` 提供 `LocalExecutionBackend.launch_command`（Popen 启动，stdout→log_file）。
- `core/monitor.py::wait_for_completion` 轮询进程状态，返回 `status`（如 completed）+ `contract_status`（SUCCESS/CRASH/TIMEOUT/BUDGET_EXCEEDED/EARLY_STOPPED）。
- **当前没有 `ExecutionResult`（process_status × termination_reason）强类型**——用松散字符串。

### 2. 预算 / clock / timeout
- `resolve_budget`（core/experiment_contract.py）解析 active_wall_clock_seconds / hard_wall_clock_limit。
- `active_train_seconds` 由训练脚本自身计时并打印（monitor 解析）。
- `hard_wall_clock_limit` 由 monitor 硬超时终止。
- **当前 BUDGET_REACHED 与 HARD_TIMEOUT 区分不足**：Qwen 试点 C1 是 HARD_TIMEOUT（9000s），但判定时 contract 显示 SUCCESS 且被判 INCOMPARABLE——这正是 V3.0 R3/R4 要修正的（execution 保留 FAILED/HARD_TIMEOUT 事实）。

### 3. process-tree 行为
- 后台 nohup 启动，monitor 追踪单个 PID；未做完整进程树管理（V3.0 后续需要）。

## 关键差距（对齐 V3.0）
- 需要引入 `ExecutionResult`（process_status×termination_reason）强类型。
- HARD_TIMEOUT 必须保留为 FAILED 事实，不得被改写为 BUDGET_REACHED。

## 状态
- **CONFIRMED（现状）**：当前 runner 用松散字符串终态，无 process_status×termination_reason 双字段。
- **UNKNOWN（G1 冻结项）**：正式 clock 来源、timeout 语义、process-tree 合同尚未冻结。
