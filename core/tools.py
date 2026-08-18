"""
工具注册表（Tool Registry）—— 把可供智能体调用的工具集中管理。

目前只暴露一个底层工具：``run_command``（在隔离目录中执行 shell 命令并捕获
输出）。更多工具（文件读写、网络搜索等）可在此注册，保持统一的调用接口。
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("autodl.tools")


class ToolRegistry:
    """集中管理智能体可用工具的注册表。"""

    def __init__(self):
        # 工具名 -> 可调用对象的映射
        self._tools: Dict[str, Callable] = {}
        self.register("run_command", self.run_command)

    def register(self, name: str, func: Callable):
        # 注册一个工具
        self._tools[name] = func

    def get(self, name: str) -> Optional[Callable]:
        # 取出一个工具（不存在则返回 None）
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        # 列出所有已注册工具名
        return list(self._tools.keys())

    @staticmethod
    def run_command(command: str, cwd: Optional[str] = None, timeout: int = 300) -> str:
        """在指定目录执行 shell 命令，返回合并后的标准输出/错误。

        参数：
            command: 要执行的命令字符串
            cwd: 工作目录（默认当前目录）
            timeout: 超时秒数（默认 300）
        """
        try:
            # 通过 shell 执行；cwd 决定命令运行位置
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd or os.getcwd(),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            # 合并 stdout 与 stderr
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return output
        except subprocess.TimeoutExpired:
            logger.warning(f"Command timed out after {timeout}s: {command[:80]}")
            return f"ERROR: Command timed out after {timeout}s"
        except Exception as exc:  # noqa: BLE001 - 工具调用应总是返回文本而非崩溃
            logger.warning(f"Command failed: {exc}")
            return f"ERROR: {exc}"
