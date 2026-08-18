"""
AutoResearcher 智能体调度器（Agent Dispatcher）

采用 Leader-Worker（领导-工人）架构，以高效利用 token：
- Leader（领导）：中央决策者，在一个周期内保持连续对话上下文。
- Worker（工人）：专用智能体（idea 构思 / code 编码 / writing 写作），按需派生。

同一时刻**只有一个** worker 在运行，其余处于空闲，零 token 消耗。

工具调用采用「与具体 provider 无关的文本协议」：大模型输出
``<tool_call>{...}</tool_call>`` 文本块，调度器通过工具注册表执行每个调用，
再把结果以 ``<tool_result name="...">...</tool_result>`` 文本块回填到下一轮
用户消息中。循环持续，直到 worker 产出「不再含工具调用的回复」（即最终答案）
或达到最大轮数。该协议在全部四种 provider 上一致可用——SDK 不依赖各自原生的
工具协议，CLI provider 则纯粹当作文本预言机（text oracle）使用。
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autodl.agents")


# 智能体提示词目录（agents/）
AGENTS_DIR = Path(__file__).parent.parent / "agents"


# 工具调用文本协议的正则：匹配 <tool_call>{...}</tool_call> 块
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
# 位于三反引号代码围栏内的内容在解析前会被整体剥离，这样大模型可以在代码块里
# “演示”该协议而不会触发真实工具执行。匹配从 ``` 到下一个 ``` 的整块。
_FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


class AgentDispatcher:
    """把任务分派给专用智能体。

    Leader 决定做什么，再把任务派给 worker：
    - idea_agent：文献检索、假设生成
    - code_agent：实验实现与执行
    - writing_agent：报告与论文撰写

    每个 worker 只配备极简工具集（3-5 个），以降低 token 开销。
    """

    # 各 worker 的配置：提示词文件、最大轮数、可用工具清单
    WORKER_CONFIGS = {
        "idea": {
            "prompt_file": "idea_agent.md",
            "max_turns": 12,
            "tools": ["search_papers", "search_arxiv", "get_paper", "write_file", "read_file"],
        },
        "code": {
            "prompt_file": "code_agent.md",
            "max_turns": 40,
            "tools": [
                "run_shell", "launch_experiment", "write_file",
                "read_file", "list_files", "list_tree", "search_code",
            ],
        },
        "writing": {
            "prompt_file": "writing_agent.md",
            "max_turns": 30,
            "tools": ["write_file", "read_file", "list_files", "search_code"],
        },
    }

    # 各 provider 之间的模型名映射
    MODEL_MAP = {
        # Anthropic ↔ OpenAI 等价表
        "claude-sonnet-4-6": "codex-5.3",     # 快速档
        "claude-opus-4-6": "gpt-5.4",          # 最强档
        "codex-5.3": "claude-sonnet-4-6",
        "gpt-5.4": "claude-opus-4-6",
    }

    # 支持的 provider：
    #   "anthropic"  —— Anthropic 兼容 SDK 接口（默认鉴权环境变量：ANTHROPIC_API_KEY）
    #   "openai"     —— OpenAI 兼容 SDK 接口（默认鉴权环境变量：OPENAI_API_KEY）
    #   "claude_cli" —— `claude -p` 子进程，使用 Claude Code / Pro / Max 订阅
    #   "codex_cli"  —— `codex exec` 子进程，使用 ChatGPT Plus / Pro 订阅
    SUPPORTED_PROVIDERS = ("anthropic", "openai", "claude_cli", "codex_cli")

    # 国内 / OpenAI 兼容 API 预设。把 `provider` 设为下列之一即可改用国产 LLM
    # （而非 Claude/Codex 订阅）——预设只是填好 OpenAI 兼容的 base_url 与默认
    # key 环境变量（二者仍可在 config 中覆盖），并经由 "openai" 路径路由。
    #   名称 -> (base_url, 默认 api-key 环境变量)
    PROVIDER_PRESETS = {
        "deepseek":  ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
        "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "qwen":      ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "moonshot":  ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
        "kimi":      ("https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
        "zhipu":     ("https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_KEY"),
        "glm":       ("https://open.bigmodel.cn/api/paas/v4", "ZHIPUAI_API_KEY"),
    }

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        provider: str = "anthropic",
        max_steps: int = 3,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: str = "",
        auth_token: Optional[str] = None,
        auth_token_env: str = "",
        max_tokens: int = 8192,
    ):
        # 把国产预设（deepseek / qwen / kimi / glm / ...）展开为 OpenAI 兼容路径。
        # base_url / port 仍可覆盖：config 中的显式值优先于预设默认值。
        self.provider_label = provider
        preset = self.PROVIDER_PRESETS.get(provider)
        if preset:
            preset_base_url, preset_key_env = preset
            base_url = (base_url or "").strip() or preset_base_url
            api_key_env = (api_key_env or "").strip() or preset_key_env
            provider = "openai"
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}'. Supported: {self.SUPPORTED_PROVIDERS} "
                f"or a domestic preset {tuple(self.PROVIDER_PRESETS)}"
            )
        self.model = model
        self.provider = provider
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.base_url = (base_url or "").strip() or None
        self.api_key = api_key or self._resolve_secret(api_key_env)
        self.auth_token = auth_token or self._resolve_secret(auth_token_env)
        self._leader_history = []  # Leader 在本周期内的对话历史

    @staticmethod
    def _resolve_secret(env_name: str) -> Optional[str]:
        # 从环境变量读取密钥（为空则返回 None）
        env_name = (env_name or "").strip()
        if not env_name:
            return None
        return os.environ.get(env_name)

    def dispatch_leader(self, task: str, context: dict) -> dict:
        """向 Leader 智能体派发任务。

        Leader 在一个周期内部保持对话历史，以进行连贯的多步推理；周期之间清空历史。

        参数：
            task: "think"（思考）或 "reflect"（反思）
            context: 当前状态（简报、记忆、结果等）

        返回：
            Leader 的决策（dict）
        """
        system_prompt = self._load_prompt("leader.md")

        messages = list(self._leader_history)
        messages.append({
            "role": "user",
            "content": self._format_leader_input(task, context),
        })

        response = self._call_llm(system=system_prompt, messages=messages)

        # 持久化对话，保证本周期内的连贯性
        self._leader_history = messages + [{"role": "assistant", "content": response}]

        return self._parse_leader_response(response)

    def dispatch_worker(self, agent_type: str, task: str, tool_registry) -> dict:
        """向 worker 智能体派发任务并运行其工具调用循环。

        worker 在多次派发之间**无状态**——每次调用都从全新的对话开始。但在单次
        派发内部对话是多轮的：worker 可发出工具调用、接收结果，并持续推理，直到
        产出最终答案（一个不再含 ``<tool_call>`` 块的回复）。

        参数：
            agent_type: "idea" / "code" / "writing"
            task: 来自 Leader 的任务描述
            tool_registry: 提供 `get_tools_for` 与 `execute_tool` 的工具注册表。
                注册表被显式传入，因此本模块无需硬依赖 tools.py。

        返回：
            至少含 `agent` 与 `response` 的 dict。若 worker 调用了
            `launch_experiment`，则该工具结果中的 PID 与 log_file 也会被提到顶层，
            以保持 loop 的 EXECUTE → MONITOR 衔接正常。
        """
        if agent_type not in self.WORKER_CONFIGS:
            raise ValueError(f"Unknown agent type: {agent_type}")
        if tool_registry is None:
            raise TypeError(
                "dispatch_worker requires a tool_registry with "
                "`get_tools_for(agent_type)` and `execute_tool(name, args)` "
                "methods. Pass a ToolRegistry configured with an empty tool "
                "list if you want a tool-less worker."
            )

        config = self.WORKER_CONFIGS[agent_type]
        base_prompt = self._load_prompt(config["prompt_file"])
        tool_defs = tool_registry.get_tools_for(agent_type)
        system_prompt = base_prompt + "\n\n" + self._render_tools_section(tool_defs)
        max_turns = config["max_turns"]

        # codex_cli 内部自带 agentic 工具循环，会无视本 <tool_call> 协议自行其是，
        # 从而破坏 EXECUTE → MONITOR 衔接（拿不到 PID / log_file）。Leader/think
        # 派发不受影响（它们不用工具），但 worker 派发很可能只返回非权威的摘要。
        # 每次派发只警告一次，避免日志噪声。
        if self.provider == "codex_cli" and tool_defs:
            logger.warning(
                "codex_cli is being used as a worker provider; its CLI does "
                "not support disabling built-in tools, so it may bypass the "
                "ToolRegistry and the resulting PID/log_file cannot be "
                "recovered. For worker dispatches prefer claude_cli, "
                "anthropic, or openai."
            )

        logger.info(f"Dispatching {agent_type} agent: {task[:100]}...")

        messages = [{"role": "user", "content": task}]
        last_response = ""
        tool_results_log: list[dict] = []

        # 由工具定义推导出的原生 OpenAI tools schema，使模型能返回结构化的
        # tool_calls，而非手写不可靠的 <tool_call> 文本协议。
        native_tools = None
        if tool_defs:
            native_tools = self._to_native_tools(tool_defs)

        for turn in range(1, max_turns + 1):
            last_response = self._call_llm(
                system=system_prompt, messages=messages, tools=native_tools
            )

            tool_calls = self._parse_tool_calls(last_response)
            if not tool_calls:
                # 无工具调用 -> worker 已产出最终答案，结束循环
                break

            # 回显 assistant 轮，使下一轮 LLM 调用能看到历史
            messages.append({"role": "assistant", "content": last_response})

            # 执行每个调用，并把所有结果拼成一个 user 轮
            result_blocks = []
            for call in tool_calls:
                name = call.get("name", "")
                args = call.get("args", {}) or {}
                if not isinstance(args, dict):
                    tool_output = json.dumps({"error": "`args` must be a JSON object"})
                else:
                    tool_output = tool_registry.execute_tool(name, args)
                tool_results_log.append({"name": name, "args": args, "output": tool_output})

                block = f'<tool_result name="{name}">\n{tool_output}\n</tool_result>'
                # D：当某工具持续失败时，显著提示 worker 改变策略，而非一遍遍重试
                # 同一个非法调用。
                if tool_output.startswith("{") and '"escalation"' in tool_output:
                    try:
                        payload = json.loads(tool_output)
                        note = payload.get("escalation") or ""
                        if note:
                            block += (
                                "\n<escalation>\n"
                                f"{note}\n"
                                "</escalation>"
                            )
                    except (json.JSONDecodeError, TypeError):
                        pass
                result_blocks.append(block)

            messages.append({
                "role": "user",
                "content": "\n\n".join(result_blocks),
            })
        else:
            # for/else：仅当循环耗尽 max_turns 而未 break 时执行
            logger.warning(
                f"Worker {agent_type} hit max_turns={max_turns} "
                f"with tool calls still pending; returning last response."
            )

        result = self._parse_worker_response(last_response, agent_type, tool_results_log)
        logger.info(f"Worker {agent_type} completed: {str(result)[:200]}")
        return result

    def reset_leader_history(self):
        """在周期之间清空 Leader 对话历史。"""
        self._leader_history = []

    @staticmethod
    def _parse_tool_calls(text: str) -> list[dict]:
        """从 LLM 回复中提取 ``<tool_call>{...}</tool_call>`` 块。

        静默跳过 JSON 体损坏的块。返回空列表意味着回复是最终答案（未请求工具调用）。

        位于三反引号代码围栏内的工具调用块会被刻意忽略：大模型在解释“将要做什么”
        时常常在围栏里演示该协议，把这些演示当成真实的有副作用调用执行，曾在实践中
        导致意外的写入。
        """
        stripped = _FENCED_BLOCK_RE.sub("", text or "")
        calls: list[dict] = []
        for match in _TOOL_CALL_RE.finditer(stripped):
            body = match.group(1)
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                logger.warning(f"Skipping malformed tool_call block: {exc}")
                continue
            if isinstance(parsed, dict) and parsed.get("name"):
                calls.append(parsed)
            else:
                logger.warning(
                    "Skipping tool_call without a string `name` field: "
                    f"{str(parsed)[:120]}"
                )
        return calls

    @staticmethod
    def _to_native_tools(tool_defs: list[dict]) -> list[dict]:
        """把项目工具定义转换为 OpenAI 原生 `tools` schema。

        项目定义采用 {"name", "description", "input_schema"}；OpenAI API 期望
        {"type": "function", "function": {"name", "description", "parameters"}}，
        其中 `parameters` == `input_schema`。
        """
        native = []
        for t in tool_defs or []:
            name = t.get("name", "")
            if not name:
                continue
            native.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return native or None

    @staticmethod
    def _render_tools_section(tool_defs: list[dict]) -> str:
        """把工具 schema 渲染成追加到 system prompt 的纯文本块。

        worker 自身的提示词已含简短的“可用工具”列表；本自动生成段落提供精确的
        机器可读 schema 与协议说明，使 LLM 能以调度器可解析的格式发出调用。
        """
        if not tool_defs:
            return ""

        lines = []
        for tool in tool_defs:
            name = tool.get("name", "<unnamed>")
            desc = tool.get("description", "")
            schema = tool.get("input_schema", {})
            lines.append(f"- `{name}` — {desc}")
            props = schema.get("properties", {}) or {}
            required = set(schema.get("required", []) or [])
            for pname, pspec in props.items():
                ptype = pspec.get("type", "any")
                pdesc = pspec.get("description", "")
                flag = "required" if pname in required else "optional"
                lines.append(f"    - `{pname}` ({ptype}, {flag}): {pdesc}")
        header = [
            "## Tool-Use Protocol",
            "",
            "You have NO direct access to the filesystem, shell, or network.",
            "To act on the environment you MUST emit `<tool_call>` blocks and",
            "wait for the framework to return `<tool_result>` blocks in the",
            "next user turn. Example:",
            "",
            "    <tool_call>",
            '    {"name": "read_file", "args": {"path": "config.yaml"}}',
            "    </tool_call>",
            "",
            "You may emit multiple `<tool_call>` blocks in one message; each",
            "will be executed and its result returned. When you are finished,",
            "produce a plain-text message with NO `<tool_call>` blocks — that",
            "is how the framework knows you are done.",
            "",
            "Emit `<tool_call>` blocks at the top level of the message. Do NOT",
            "wrap them in triple-backtick code fences — fenced blocks are",
            "treated as illustration, not as real calls.",
            "",
            "### Available tools",
            "",
        ]
        return "\n".join(header + lines)

    def _call_llm(self, system: str, messages: list, tools: list | None = None) -> str:
        """调用 LLM。支持四种 provider。

        - "anthropic":  Anthropic 兼容 Messages API，按 token 计费
        - "openai":     OpenAI 兼容 Chat Completions API，按 token 计费
        - "claude_cli": `claude -p` 子进程，使用 Claude Code / Pro / Max 订阅
        - "codex_cli":  `codex exec` 子进程，使用 ChatGPT Plus / Pro 订阅

        CLI provider 让你复用已有订阅，而非按 token 付费；在并行大量智能体或重
        负载 Think/Reflect 周期时便宜得多。代价：无原生 prompt 缓存、无原生工具
        协议——LLM 被纯粹当作“文本进/文本出”预言机，工具调用通过 <tool_call>
        文本协议叠加在其上（见 dispatch_worker）。
        """
        if self.provider == "claude_cli":
            return self._call_claude_cli(system, messages)
        if self.provider == "codex_cli":
            return self._call_codex_cli(system, messages)
        if self.provider == "openai":
            return self._call_openai(system, messages, tools)
        return self._call_anthropic(system, messages, tools)

    def _call_anthropic(self, system: str, messages: list, tools: list | None = None) -> str:
        """调用 Anthropic 兼容 Messages API。"""
        try:
            import anthropic

            client_kwargs = {}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            if self.auth_token:
                client_kwargs["auth_token"] = self.auth_token
            client = anthropic.Anthropic(**client_kwargs)

            api_messages = [
                {"role": msg["role"], "content": msg["content"]} for msg in messages
            ]

            kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": api_messages,
            }

            response = client.messages.create(**kwargs)
            return response.content[0].text

        except ImportError:
            logger.warning("anthropic package not installed. Trying openai fallback.")
            return self._call_openai(system, messages)

    def _call_openai(self, system: str, messages: list, tools: list | None = None) -> str:
        """调用 OpenAI 兼容 Chat Completions API。

        若提供了 `tools`，则使用原生 `tools` 参数，让模型返回结构化的 `tool_calls`。
        这些调用会被转译回项目的 `<tool_call>` 文本协议，从而下游解析器不变。
        这使工具调用在那些不能稳定输出自定义 `<tool_call>` 文本的模型（例如
        DeepSeek 官方 API）上也能可靠工作。
        """
        try:
            import openai

            client_kwargs = {}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.api_key:
                client_kwargs["api_key"] = self.api_key
            client = openai.OpenAI(**client_kwargs)

            # 若模型名是 Anthropic 名称则做映射
            model = self.MODEL_MAP.get(self.model, self.model) if self.provider != "openai" else self.model

            api_messages = [{"role": "system", "content": system}]
            for msg in messages:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

            call_kwargs: dict = {
                "model": model,
                "max_tokens": self.max_tokens,
                "messages": api_messages,
            }
            if tools:
                call_kwargs["tools"] = tools

            response = client.chat.completions.create(**call_kwargs)

            message = response.choices[0].message

            # 若模型返回了原生 tool_calls，转译回项目 <tool_call> 文本协议
            native_calls = getattr(message, "tool_calls", None)
            if native_calls:
                blocks = []
                for call in native_calls:
                    fn = getattr(call, "function", None)
                    if fn is None:
                        continue
                    try:
                        args = json.loads(fn.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append(
                        f"<tool_call>\n{json.dumps({'name': fn.name, 'args': args})}\n</tool_call>"
                    )
                if blocks:
                    return "\n".join(blocks)

            text = getattr(message, "content", None)
            # 推理型模型（如 Qwen3.6-27B / deepseek-r1）可能在 `reasoning` 字段中
            # 输出思维链，而 `content` 因 token 预算被思维链占满而为 None。降级
            # 使用 reasoning，避免向下游解析器返回 None。
            if not text and getattr(message, "reasoning", None):
                text = message.reasoning
            if not text:
                # 最后兜底：返回一段安全的降级动作，而非让 None 传播并导致解析崩溃
                logger.warning("openai chat completion returned empty content; using fallback.")
                return json.dumps(
                    {"action": "wait", "reason": "LLM returned no content (token budget may be exhausted)."}
                )
            return text

        except ImportError:
            logger.warning("openai package not installed. Using mock response.")
            return json.dumps({"action": "wait", "reason": "LLM not available"})

    @staticmethod
    def _flatten_for_cli(system: str, messages: list) -> str:
        """把 (system + 对话历史) 序列化为供 CLI 子进程使用的单一提示词。

        无头 CLI 工具（claude -p / codex exec）只接受一个文本块并返回 assistant 回复。
        我们用简单的分段标记重建对话，而非结构化 role schema——对单轮派发足够好，
        而 loop 本就如此使用 LLM。
        """
        parts = [f"===== SYSTEM =====\n{system.strip()}\n"]
        for msg in messages:
            role = str(msg.get("role", "user")).upper()
            content = str(msg.get("content", "")).strip()
            parts.append(f"===== {role} =====\n{content}\n")
        parts.append("===== ASSISTANT =====\n")
        return "\n".join(parts)

    def _run_cli(self, argv: list, prompt: str, tool_label: str, install_hint: str,
                 use_stdin: bool = False) -> str:
        """调用无头 CLI 工具，把其 stdout 作为 assistant 回复返回。"""
        import subprocess

        try:
            if use_stdin:
                result = subprocess.run(
                    argv,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
            else:
                result = subprocess.run(
                    argv + [prompt],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
        except FileNotFoundError:
            logger.warning(
                f"{tool_label} CLI not found on PATH. "
                f"Install: {install_hint}. Falling back to mock response."
            )
            return json.dumps({"action": "wait", "reason": f"{tool_label} CLI missing"})
        except subprocess.TimeoutExpired:
            logger.error(f"{tool_label} CLI timed out after 600s")
            return json.dumps({"action": "wait", "reason": f"{tool_label} CLI timeout"})
        except OSError as e:
            # argv 过大（E2BIG）——改用 stdin 重试
            if not use_stdin and getattr(e, "errno", None) == 7:
                logger.info(f"{tool_label} argv exceeded OS limit; retrying via stdin.")
                return self._run_cli(argv, prompt, tool_label, install_hint, use_stdin=True)
            raise

        if result.returncode != 0:
            stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
            logger.error(
                f"{tool_label} CLI exited {result.returncode}. "
                f"Stderr tail: {' | '.join(stderr_tail)}"
            )
            return json.dumps({"action": "wait", "reason": f"{tool_label} CLI error"})

        return (result.stdout or "").strip()

    def _call_claude_cli(self, system: str, messages: list) -> str:
        """通过 `claude` CLI 无头派发，按 Pro / Max 订阅计费。

        `--tools ""` 禁用所有内置工具，使 CLI 降级为纯文本预言机。这是我们的
        <tool_call> 协议工作所必需的：CLI 必须无法自行其是，否则会绕过 ToolRegistry
        （loop 将失去对实际发生之事的可见性，尤其是 launch_experiment 的 PID）。

        提示词通过 stdin 传入，以规避大对话历史的 argv 长度限制。
        """
        prompt = self._flatten_for_cli(system, messages)
        return self._run_cli(
            argv=["claude", "-p", "--output-format", "text", "--tools", ""],
            prompt=prompt,
            tool_label="claude",
            install_hint="npm i -g @anthropic-ai/claude-code && run `claude` once to sign in",
            use_stdin=True,
        )

    def _call_codex_cli(self, system: str, messages: list) -> str:
        """通过 `codex` CLI 无头派发，按 ChatGPT 订阅计费。

        与 `claude -p` 不同，`codex exec` 默认是完全 agentic 的——它运行自己的内部
        工具循环，且没有任何 CLI 标志能禁用内置工具。这意味着在本 provider 下框架
        的 <tool_call> 协议不可靠：codex 会常常自行其是并返回一段最终摘要。因此
        需要启动实验（并从 ToolRegistry 回收 PID）的 worker 应优先选用
        claude_cli / anthropic / openai；codex_cli 最好只用于 leader/think 路径
        （那里我们只需要自由文本输出）。

        标志：
          - `-o <tempfile>`       只捕获最终的 assistant 消息而非完整 agentic trace
          - `--skip-git-repo-check` 允许 codex 在任意目录下运行（工作区通常不是仓库）
        """
        import subprocess
        import tempfile

        prompt = self._flatten_for_cli(system, messages)

        try:
            with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as out:
                out_path = out.name
            try:
                result = subprocess.run(
                    [
                        "codex", "exec",
                        "--skip-git-repo-check",
                        "-o", out_path,
                        prompt,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
            except FileNotFoundError:
                logger.warning(
                    "codex CLI not found on PATH. "
                    "Install: brew install codex (or see upstream) then `codex login`. "
                    "Falling back to mock response."
                )
                return json.dumps({"action": "wait", "reason": "codex CLI missing"})
            except subprocess.TimeoutExpired:
                logger.error("codex CLI timed out after 600s")
                return json.dumps({"action": "wait", "reason": "codex CLI timeout"})

            if result.returncode != 0:
                stderr_tail = (result.stderr or "").strip().splitlines()[-5:]
                logger.error(
                    f"codex CLI exited {result.returncode}. "
                    f"Stderr tail: {' | '.join(stderr_tail)}"
                )
                return json.dumps({"action": "wait", "reason": "codex CLI error"})

            try:
                with open(out_path, "r") as f:
                    return f.read().strip()
            except OSError:
                # 若 --output-last-message 没产出文件，则降级用 stdout
                return (result.stdout or "").strip()
        finally:
            try:
                Path(out_path).unlink(missing_ok=True)
            except OSError:
                pass

    def _load_prompt(self, filename: str) -> str:
        """从 agents/ 目录加载智能体提示词。"""
        prompt_path = AGENTS_DIR / filename
        if prompt_path.exists():
            return prompt_path.read_text()
        logger.warning(f"Prompt file not found: {prompt_path}")
        return f"You are the {filename.replace('.md', '')} agent."

    def _format_leader_input(self, task: str, context: dict) -> str:
        """把上下文格式化为 Leader 的结构化输入。"""
        parts = [f"## Task: {task.upper()}\n"]

        if context.get("directive"):
            parts.append(f"## Human Directive (HIGHEST PRIORITY)\n{context['directive']}\n")

        parts.append(f"## Project Brief\n{context.get('brief', 'N/A')}\n")
        parts.append(f"## Memory Log\n{context.get('memory_log', 'N/A')}\n")

        # 由 loop 的 _enrich_context 注入的可选 v2 建议性信号。仅当存在时才渲染，
        # 以兼容旧的调用点。
        for label, key in (
            ("Active Violations", "active_violations"),
            ("Phase Gate", "phase_gate"),
            ("Progress Signal", "progress_signal"),
            ("Recent Experiments", "recent_experiments"),
            ("Dead Ends (do NOT retry these)", "dead_ends"),
            ("Durable Insights", "insights"),
            ("Empty-Metric Feedback (fix these)", "metrics_feedback"),
        ):
            if context.get(key):
                parts.append(f"## {label}\n{context[key]}\n")

        parts.append(f"## Cycle: {context.get('cycle', 'N/A')}\n")

        if context.get("experiment_result"):
            parts.append(f"## Experiment Result\n{json.dumps(context['experiment_result'], indent=2)}\n")

        return "\n".join(parts)

    def _parse_leader_response(self, response: str) -> dict:
        """把 Leader 的回复解析为结构化动作。"""
        try:
            # 尝试从回复中找到 JSON
            import re
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        # 兜底：从文本中提取动作
        response_lower = response.lower()
        if "wait" in response_lower or "no experiment" in response_lower:
            return {"action": "wait", "reason": response[:200]}

        return {
            "action": "experiment",
            "agent": "code",
            "task": response,
        }

    def _parse_worker_response(self, response: str, agent_type: str,
                               tool_results: Optional[list] = None) -> dict:
        """把 worker 回复解析为结构化结果字典。

        当 worker 使用了 `launch_experiment` 工具时，PID 与 log_file 直接来自该工具
        的 JSON 结果——这是权威来源。对纯散文报告实验启动的回复（或早于工具调用
        循环的旧提示词），保留基于正则从自由文本解析的兜底路径。
        """
        result = {"agent": agent_type, "response": response}
        if tool_results:
            result["tool_calls"] = len(tool_results)

        if agent_type == "code":
            # 优先采用权威的工具结果数据，而非文本解析
            launch_result = None
            if tool_results:
                for entry in reversed(tool_results):
                    if entry.get("name") == "launch_experiment":
                        launch_result = entry
                        break
            if launch_result is not None:
                try:
                    payload = json.loads(launch_result.get("output", "{}"))
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                if isinstance(payload, dict) and payload.get("pid") is not None:
                    result["experiment_launched"] = True
                    result["pid"] = int(payload["pid"])
                    if payload.get("log_file"):
                        result["log_file"] = payload["log_file"]

            # 兜底：从自由文本回复中抓取 PID
            if "pid" not in result and ("PID" in response or "launched" in response.lower()):
                result["experiment_launched"] = True
                pid_match = re.search(r"PID[=:\s]+(\d+)", response)
                if pid_match:
                    result["pid"] = int(pid_match.group(1))

        return result
