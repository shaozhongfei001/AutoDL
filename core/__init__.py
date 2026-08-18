"""AutoResearcher 核心模块 —— 一个自主机器学习实验智能体框架。

该模块把各个子模块的核心类与工厂函数统一对外暴露，
方便上层代码以 `from core import ResearchLoop` 等方式直接引用。
"""

# 导入任务执行后端相关类与工厂函数（本地 / SSH / Slurm 等多种执行环境）
from .execution import (
    ExecutionBackend,
    LocalExecutionBackend,
    SSHExecutionBackend,
    SlurmExecutionBackend,
    build_execution_backend,
)
# 研究主循环：负责驱动"规划→执行→检查→反思"的自主实验流程
from .loop import ResearchLoop
# 记忆管理器：维护智能体的长期记忆与上下文
from .memory import MemoryManager
# 实验监控器：实时采集指标、判断早期停止等
from .monitor import ExperimentMonitor
# 智能体调度器：分发并协调多个子智能体的工作
from .agents import AgentDispatcher
# 工具注册表：集中管理可供智能体调用的各类工具
from .tools import ToolRegistry

# 当前框架版本号
__version__ = "0.1.1"
# 定义本模块对外公开、可被 `from core import *` 导入的所有名称列表
__all__ = [
    "AgentDispatcher",
    "ExecutionBackend",
    "ExperimentMonitor",
    "LocalExecutionBackend",
    "MemoryManager",
    "ResearchLoop",
    "SSHExecutionBackend",
    "SlurmExecutionBackend",
    "ToolRegistry",
    "build_execution_backend",
]
