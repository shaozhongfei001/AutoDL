# QA Gate 2 报告 — STUDY-001（阶段 1+2 实施验证）

> 状态：**PASS（待 HUMAN_OWNER 最终放行）**
> 日期：2026-08-15
> 范围：阶段 1（A 实验有效性合同）+ 阶段 2（D0 受保护写入边界）代码实施后的独立验证
> 基线 commit：`1331cfcec07ea673f0c1b540e1f9b9f0d667bebe`
> 验证方式：完整测试套件（158 用例）+ 针对性单元测试（28 新增）+ 端到端工具行为实测

## 1. 交付内容

| 模块 | 文件 | 变更 |
|------|------|------|
| A 合同核心 | `core/experiment_contract.py`（新增） | schema 校验、预算解析、比较性指纹、run 分类、D0 写入策略、受保护文件哈希门禁 |
| A 合同接入 | `core/loop.py` | config schema 校验告警、budget 传入 monitor |
| A 合同执行 | `core/monitor.py` | 硬超时兜底、active_train_seconds 解析、run 分类（SUCCESS/BUDGET_EXCEEDED/TIMEOUT/CRASH）、validation/test 指标分离 |
| D0 写入保护 | `core/tools.py` | allowlist/denylist 写入检查、run_shell 拒绝 shell 运算符与 cd、阻断破坏性 git、launch_experiment 附预算事实 |
| 试点 config | `examples/mnist_gpu/config.yaml` | 加入 experiment.budget/evaluation/comparability/write_policy |
| 测试 | `tests/test_experiment_contract.py`（新增 28）+ `test_tools_security.py`（更新 2） | |

## 2. QA2 验收矩阵

| ID | 检查项 | 结果 | 证据 |
|----|--------|------|------|
| QA2-01 | 训练按 `active_train_seconds` 分类自终止 | ✅ | `classify_run_outcome`：BUDGET_EXCEEDED 当 >limit、TIMEOUT 当 >hard（单测覆盖） |
| QA2-02 | hard_wall_clock_limit 兜底生效 | ✅ | monitor 轮询中检测硬超时并 `_terminate`；`TIMEOUT` vs `BUDGET_EXCEEDED` 区分（单测） |
| QA2-03 | poll_interval 不改变预算 | ✅ | 预算基于 `active_train_seconds`（日志）而非轮询次数；poll 仅影响发现延迟 |
| QA2-04 | validation 选优 + test 独立验收 | ✅ | monitor 解析 `validation_accuracy`/`test_accuracy` 分离；test 标记独立验收 |
| QA2-05 | 跨 cohort 标记 INCOMPARABLE | ✅ | `comparability_fingerprint`/`are_comparable`（单测：不同 cohort 返回 False） |
| QA2-06 | 候选在受保护边界外写入 | ✅ | D0 `allows_write`：data/.codebuddy/contracts/tests/artifacts 被拒（单测+冒烟） |
| QA2-07 | 破坏性 git 被禁 | ✅ | `git reset/clean/...` 拒绝；只读 `git status` 允许（单测） |
| QA2-08 | schema 校验缺必填报错 | ✅ | `validate_experiment_config`（单测：bad mode/negative limit） |
| QA2-09 | 受保护文件 hash 未变 | ✅ | `ProtectedWritePolicy.assert_unchanged`（单测：篡改被检测） |
| QA2-10 | 端到端 launch_experiment 被 monitor 捕获 | ✅ | 实测：`run_shell cd&&` 拒→agent 改 `launch_experiment`→monitor 捕获 PID→提取 metrics+active_train_seconds，status=completed |

## 3. 回归验证

- 完整测试套件：**158 passed**（128 原有 + 28 新增 + 2 更新）
- 无 lint 错误（4 个核心文件均 0 diagnostics）
- 向后兼容：未配置 `experiment` 段时保持 legacy 行为（budget 不强制、写边界仅 denylist 默认、git 破坏命令仍拒但只读 git 放行）

## 4. 关键行为修复（相对改造前）

改造前实测发现：`run_shell` 不支持复合命令 + `launch_experiment` 因绝对路径被拒 → agent 绕开 launch 直接前台跑训练，monitor 未捕获 PID。
改造后：`run_shell` 显式拒绝 shell 运算符并提示用 `launch_experiment`；D0 允许合法训练脚本写入；实测确认 **monitor 正确捕获训练并分类预算**。

## 5. 遗留与边界（非阻断）

1. **ADR-002 完整版**（champion 分支 + 独立 worktree + 事件账本 + fast-forward 晋级）本次**未实施**，仅完成 D0 写入保护与破坏性 git 阻断。事务隔离晋级属后续阶段。
2. `mnist_gpu/workspace/` 存在上次运行的残留状态（cycle=1 + max_cycles=1 会立即停止）。本次 QA 通过隔离模拟验证完成，未改动该 workspace。
3. config 的 `comparability` 已在试点 config 声明数据/评估器指纹，但数据 SHA256 的实际计算需在运行期注入（当前为声明值）。

## 6. 结论

阶段 1（A 合同）+ 阶段 2（D0）核心能力已实现并通过单元测试与端到端行为验证，满足 QA Gate 2 验收矩阵（10/10）。**待 HUMAN_OWNER 最终放行**后方可在试点 study 启用全量 agent 循环。
