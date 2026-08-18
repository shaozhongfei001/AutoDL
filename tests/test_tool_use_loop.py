"""针对 core/agents.py 中 worker 工具调用循环的测试。

该循环必须：
  - 多轮运行，直到模型不再发出 <tool_call> 代码块；
  - 把每个工具的输出以 <tool_result> 形式回填到下一轮用户消息中；
  - 把 max_turns 作为硬性上限遵守；
  - 从 launch_experiment 工具调用中读取 pid / log_file，保证 core/loop.py
    的 EXECUTE → MONITOR 交接仍然成立；
  - 忽略格式错误的 <tool_call> JSON 体而不崩溃。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.agents import AgentDispatcher
from core.execution import LocalExecutionBackend
from core.tools import ToolRegistry


def _make_dispatcher():
    # 供应商选择无关紧要，因为所有测试都会桩掉 _call_llm。
    return AgentDispatcher(provider="anthropic")


class ParseToolCallsTests(unittest.TestCase):
    """对 _parse_tool_calls 的解析测试：块提取、忽略含代码围栏的示例、容错。"""

    def test_extracts_multiple_blocks_in_order(self):
        text = """
        I will take two actions.
        <tool_call>
        {"name": "read_file", "args": {"path": "a.txt"}}
        </tool_call>
        Some prose in between.
        <tool_call>
        {"name": "write_file", "args": {"path": "b.txt", "content": "hi"}}
        </tool_call>
        """
        calls = AgentDispatcher._parse_tool_calls(text)
        self.assertEqual([c["name"] for c in calls], ["read_file", "write_file"])
        self.assertEqual(calls[1]["args"]["path"], "b.txt")

    def test_empty_when_no_blocks(self):
        # 无任何工具调用块 -> 空列表。
        self.assertEqual(AgentDispatcher._parse_tool_calls("final answer"), [])

    def test_skips_malformed_json(self):
        # 格式错误的 JSON 体应被跳过，仅保留可解析的调用。
        text = """
        <tool_call>{"name": "ok", "args": {}}</tool_call>
        <tool_call>{not valid json</tool_call>
        <tool_call>"just a string"</tool_call>
        """
        calls = AgentDispatcher._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "ok")

    def test_ignores_tool_calls_inside_code_fences(self):
        """LLM 在解释时会用围栏代码块示意协议；这些示意图绝不应当被执行。"""
        text = '''
        Here is how you would call the tool:

        ```
        <tool_call>
        {"name": "write_file", "args": {"path": "DANGER.txt", "content": "pwned"}}
        </tool_call>
        ```

        But for this task I do not need any tools.
        '''
        self.assertEqual(AgentDispatcher._parse_tool_calls(text), [])

    def test_mix_of_fenced_illustration_and_real_call(self):
        """即使消息中包含一个示意性的围栏示例，真实的顶层调用仍应被识别。"""
        text = '''
        For reference, the general form looks like:

        ```
        <tool_call>
        {"name": "write_file", "args": {"path": "EXAMPLE.txt", "content": "x"}}
        </tool_call>
        ```

        Now I will do the real call:

        <tool_call>
        {"name": "read_file", "args": {"path": "actual.txt"}}
        </tool_call>
        '''
        calls = AgentDispatcher._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "read_file")
        self.assertEqual(calls[0]["args"]["path"], "actual.txt")

    def test_tolerates_missing_args_key(self):
        """无 `args` 字段的 tool_call 也合法；args 缺省为 {}。"""
        text = '<tool_call>{"name": "list_files"}</tool_call>'
        calls = AgentDispatcher._parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "list_files")

    def test_rejects_args_that_is_not_a_dict(self):
        """当 LLM 以字符串或列表形式给出 args 时，dispatcher 必须返回结构化错误，
        而不是在 **kwargs 解包时崩溃。"""
        dispatcher = _make_dispatcher()
        registry = _FakeRegistry(
            tools=[{"name": "read_file", "description": "", "input_schema": {}}],
            outputs={},
        )
        turns = [
            '<tool_call>{"name": "read_file", "args": "not-a-dict"}</tool_call>',
            "giving up",
        ]
        with patch.object(dispatcher, "_call_llm", side_effect=turns):
            dispatcher.dispatch_worker("writing", "t", registry)
        # The registry must NOT have been called with a non-dict args payload.
        self.assertEqual(registry.calls, [])


class RenderToolsSectionTests(unittest.TestCase):
    def test_renders_schema_properties(self):
        tool = {
            "name": "search_papers",
            "description": "Search Semantic Scholar.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        }
        rendered = AgentDispatcher._render_tools_section([tool])
        self.assertIn("search_papers", rendered)
        self.assertIn("<tool_call>", rendered)
        self.assertIn("query", rendered)
        self.assertIn("required", rendered)
        self.assertIn("Max results", rendered)

    def test_empty_when_no_tools(self):
        # 无工具时渲染结果应为空字符串。
        self.assertEqual(AgentDispatcher._render_tools_section([]), "")


class _FakeRegistry:
    """最小化的 ToolRegistry 桩：记录每次调用并按预置内容返回结果。"""

    def __init__(self, tools, outputs):
        self._tools = tools
        self._outputs = outputs  # 字典：tool_name -> json 字符串
        self.calls: list[tuple[str, dict]] = []

    def get_tools_for(self, agent_type):
        return self._tools

    def execute_tool(self, name, args):
        self.calls.append((name, args))
        return self._outputs.get(name, json.dumps({"ok": True}))


class DispatchWorkerLoopTests(unittest.TestCase):
    """对 dispatch_worker 工具调用循环主流程的测试。"""

    def test_none_registry_raises_clear_typeerror(self):
        """传入 tool_registry=None 必须在边界处以清晰的 TypeError 失败，
        而不是在循环深处抛出晦涩的 AttributeError。dispatch_worker 的外部调用者
        会触碰到这个边界情况。"""
        dispatcher = _make_dispatcher()
        with self.assertRaises(TypeError) as ctx:
            dispatcher.dispatch_worker("writing", "task", None)
        self.assertIn("tool_registry", str(ctx.exception))
        self.assertIn("get_tools_for", str(ctx.exception))

    def test_unknown_agent_type_raises_before_touching_registry(self):
        """Agent 类型校验应先行发生，这样无论 registry 处于何种状态，
        非法的 agent_type 都会得到 ValueError。"""
        dispatcher = _make_dispatcher()
        with self.assertRaises(ValueError):
            dispatcher.dispatch_worker("bogus_agent", "task", None)

    def test_terminates_when_response_has_no_tool_calls(self):
        # 模型回答里没有工具调用块 -> 直接终止，不执行任何工具。
        dispatcher = _make_dispatcher()
        registry = _FakeRegistry(tools=[], outputs={})

        with patch.object(dispatcher, "_call_llm", return_value="all done, no tools"):
            result = dispatcher.dispatch_worker("writing", "task", registry)

        self.assertEqual(registry.calls, [])
        self.assertEqual(result["agent"], "writing")
        self.assertIn("all done", result["response"])

    def test_executes_tools_and_feeds_results_back(self):
        # 工具会被真正执行，其输出会以 tool_result 形式回填到下一轮。
        dispatcher = _make_dispatcher()
        fake_tools = [{"name": "read_file", "description": "read",
                       "input_schema": {"type": "object", "properties": {}}}]
        registry = _FakeRegistry(
            tools=fake_tools,
            outputs={"read_file": json.dumps({"content": "file body"})},
        )

        turns = [
            '<tool_call>{"name": "read_file", "args": {"path": "a.txt"}}</tool_call>',
            "Done reading, here is my summary.",
        ]
        call_log: list[list] = []

        def fake_call(system, messages, tools=None):
            call_log.append(list(messages))
            return turns.pop(0)

        with patch.object(dispatcher, "_call_llm", side_effect=fake_call):
            result = dispatcher.dispatch_worker("writing", "task", registry)

        # 正好执行了一次工具调用且参数正确。
        self.assertEqual(registry.calls, [("read_file", {"path": "a.txt"})])
        # 第二轮 LLM 同时看到了 assistant 的 tool_call 与 user 的 tool_result。
        self.assertEqual(len(call_log), 2)
        second_turn_messages = call_log[1]
        self.assertEqual(second_turn_messages[0]["role"], "user")  # 原始任务
        self.assertEqual(second_turn_messages[1]["role"], "assistant")  # 工具调用回显
        self.assertEqual(second_turn_messages[2]["role"], "user")  # tool_result 内容
        self.assertIn("<tool_result", second_turn_messages[2]["content"])
        self.assertIn("file body", second_turn_messages[2]["content"])
        # 最终结果捕获了摘要响应与工具调用次数。
        self.assertEqual(result["tool_calls"], 1)
        self.assertIn("summary", result["response"])

    def test_max_turns_hard_ceiling(self):
        # max_turns 是硬性上限：即使模型持续请求工具调用也不会无限循环。
        dispatcher = _make_dispatcher()
        registry = _FakeRegistry(
            tools=[{"name": "read_file", "description": "", "input_schema": {}}],
            outputs={},
        )

        # 每轮都继续请求下一个工具调用 -> 若不设上限会无限循环。
        infinite = '<tool_call>{"name": "read_file", "args": {"path": "x"}}</tool_call>'

        with patch.object(dispatcher, "_call_llm", return_value=infinite):
            # 为测试把 'writing' worker 的 max_turns 改得足够小。
            with patch.dict(AgentDispatcher.WORKER_CONFIGS["writing"], {"max_turns": 3}):
                result = dispatcher.dispatch_worker("writing", "task", registry)

        # 恰好执行 3 次工具调用，不再增多。
        self.assertEqual(len(registry.calls), 3)
        self.assertEqual(result["response"], infinite)

    def test_surfaces_pid_from_launch_experiment_tool_result(self):
        """core/loop.py 中的 EXECUTE → MONITOR 交接会读取 result['pid'] 与
        result['log_file']。它们必须来自工具结果（这是权威来源），而不是
        从模型的自然语言回复中做正则抽取。"""
        dispatcher = _make_dispatcher()
        launch_output = json.dumps({"pid": 4321, "log_file": "/tmp/exp.log", "status": "launched"})
        registry = _FakeRegistry(
            tools=[{"name": "launch_experiment", "description": "", "input_schema": {}}],
            outputs={"launch_experiment": launch_output},
        )

        turns = [
            '<tool_call>{"name": "launch_experiment", '
            '"args": {"command": "python train.py", "log_file": "exp.log"}}'
            '</tool_call>',
            # 故意给出一个谎报 PID 的自然语言回复——工具结果必须胜出。
            "Training started, PID=99999 (this number is wrong).",
        ]

        with patch.object(dispatcher, "_call_llm", side_effect=turns):
            result = dispatcher.dispatch_worker("code", "launch it", registry)

        self.assertTrue(result["experiment_launched"])
        self.assertEqual(result["pid"], 4321)
        self.assertEqual(result["log_file"], "/tmp/exp.log")

    def test_end_to_end_with_real_registry(self):
        """使用真实 ToolRegistry 与临时工作区的冒烟测试。"""
        dispatcher = _make_dispatcher()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            registry = ToolRegistry(LocalExecutionBackend(workspace))

            turns = [
                '<tool_call>{"name": "write_file", '
                '"args": {"path": "note.txt", "content": "hello"}}</tool_call>',
                '<tool_call>{"name": "read_file", '
                '"args": {"path": "note.txt"}}</tool_call>',
                "I wrote and read the file successfully.",
            ]

            with patch.object(dispatcher, "_call_llm", side_effect=turns):
                result = dispatcher.dispatch_worker("writing", "do it", registry)

            self.assertEqual(result["tool_calls"], 2)
            self.assertTrue((workspace / "note.txt").exists())
            self.assertEqual((workspace / "note.txt").read_text(), "hello")


if __name__ == "__main__":
    unittest.main()
