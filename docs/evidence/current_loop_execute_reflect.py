# Evidence: AutoDL 当前 EXECUTE/MONITOR/REFLECT 流程
# Source: core/loop.py:248-301
# Supports: 确认"当前项目无 git 回退闭环"（P0 缺失项）

def _execute(self, plan: dict) -> dict:
    """EXECUTE phase: implement and run the planned experiment."""
    agent_type = plan.get("agent", "code")
    task_description = plan.get("task", "")
    # dispatch_worker: code agent 用 tool-use 写代码并尝试 launch 实验
    result = self.dispatcher.dispatch_worker(
        agent_type=agent_type,
        task=task_description,
        tool_registry=self.tools,
    )
    return result

def _monitor_experiment(self, execute_result: dict) -> dict:
    """Monitor running experiment with ZERO LLM calls."""
    pid = execute_result.get("pid")
    log_file = execute_result.get("log_file")
    if not pid:
        return {"status": "no_pid"}
    # 阻塞等待训练完成（零 LLM 成本轮询）
    return self.monitor.wait_for_completion(
        pid=pid,
        log_file=log_file,
        notify=self.config.get("monitor", {}).get("notify_on_complete", True),
    )

def _reflect(self, execute_result: dict) -> dict:
    """REFLECT phase: evaluate results and update memory."""
    context = {
        "brief": self.memory.get_brief(),
        "memory_log": self.memory.get_log(),
        "experiment_result": execute_result,
        "cycle": self.cycle_count,
    }
    result = self.dispatcher.dispatch_leader(task="reflect", context=context)
    # 只更新记忆/决策，无代码回退机制
    if result.get("milestone"):
        self.memory.log_milestone(result["milestone"])
    if result.get("decision"):
        self.memory.log_decision(result["decision"])
    return result

# 结论：REFLECT 只写记忆/决策，**没有任何 git commit/reset 来保留改进或回退坏改动**。
# 对比 autoresearch：指标变差时不会 git reset，迭代不形成"单调向优"轨迹。
