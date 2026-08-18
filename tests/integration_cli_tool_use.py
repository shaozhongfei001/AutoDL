"""实时集成检查：端到端驱动一个真实的 CLI 供应商 worker。

手动运行：  python -m tests.integration_cli_tool_use

每个供应商会消耗一次订阅往返（round-trip）。若对应 CLI 不在 PATH 上，
则自动跳过。该脚本并未接入常规的 unittest 测试套件。
"""

import shutil
import tempfile
from pathlib import Path

from core.agents import AgentDispatcher
from core.execution import LocalExecutionBackend
from core.tools import ToolRegistry


TASK = (
    "Your one job: create a file named hello.txt in the workspace "
    "containing exactly the three-word sentence 'integration test ok', "
    "then confirm by listing the files. Once done, reply with a short "
    "success message and no further tool calls."
)


def _run(provider: str) -> dict:
    # 根据供应商选择要执行的 CLI 可执行文件。
    binary = {"claude_cli": "claude", "codex_cli": "codex"}[provider]
    if shutil.which(binary) is None:
        return {"provider": provider, "skipped": f"{binary} not on PATH"}

    dispatcher = AgentDispatcher(provider=provider)
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        registry = ToolRegistry(LocalExecutionBackend(workspace))
        try:
            result = dispatcher.dispatch_worker("writing", TASK, registry)
        except Exception as exc:
            return {"provider": provider, "error": repr(exc)}

        hello = workspace / "hello.txt"
        return {
            "provider": provider,
            "tool_calls": result.get("tool_calls", 0),
            "file_created": hello.exists(),
            "file_content": hello.read_text() if hello.exists() else None,
            "response_tail": (result.get("response", "") or "")[-200:],
        }


def main():
    # 逐个供应商跑一遍集成检查并打印结果。
    for provider in ("claude_cli", "codex_cli"):
        print(f"\n=== {provider} ===")
        outcome = _run(provider)
        for k, v in outcome.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()