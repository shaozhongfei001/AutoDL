# EVD-G0-016 Evaluation Flow（selection/test 数据链路现状）

- **Evidence ID**：EVD-G0-016
- **Owner**：DEV-EVAL-01
- **Collected by**：CodeBuddy（Tech Lead / ARCH-01）
- **Collected at UTC**：2026-08-16T16:40:00Z
- **Gate**：G0_EVIDENCE_CLOSURE

## 现状事实

### 1. 指标来源与可见性（当前实现）
- 训练脚本通过 stdout 输出 `validation_loss=<float>`（每 epoch）和 `RESULT {json}`（末尾）。
- `core/monitor.py::_extract_metrics` 从 `log_tail` 解析这些行得到 `metrics` dict。
- 当前 **没有独立 selection/test 命名空间**：训练脚本在一个 stdout 里同时打印 `validation_loss` 与 `test_loss`（见 Qwen 试点 `train_ft.py` 的 RESULT 含 test_loss）。
- 当前 **没有 service principal / ACL**：所有 agent（leader/code agent）共享同一 workspace，读写无身份隔离。

### 2. selection 指标 vs test 指标（现状差距）
- 现状把 `validation_*` 用于逐轮选优（decide_verdict），`test_*` 作为独立验收（gate）。
- **没有"test 指标对 iterative 容器不可见"的机制**——这是 V3.0 P0-011/019 要求、当前缺失的。

### 3. evaluator / metric 输出链路
- evaluator 是训练脚本内的函数（如 `evaluate()`），输出写入 stdout 由 monitor 解析。
- **没有 evaluator_hash / dataset_fingerprint / MetricObservation 身份**——当前用原始 dict。

## 状态
- **CONFIRMED（现状）**：当前无 selection/test 隔离、无 metric identity、无 evaluator hash。
- **UNKNOWN（G1 冻结项）**：正式 evaluator_hash、dataset_fingerprint、unit、direction 合同尚未冻结。
