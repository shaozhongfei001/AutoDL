"""
AutoResearcher Tool Registry

Each agent gets a minimal tool set (3-5 tools) instead of all tools.
This reduces token overhead per API call significantly.
"""

import json
import logging
import shlex
from pathlib import Path

from .execution import ExecutionBackend, normalize_relative_path
from .experiment_contract import ProtectedWritePolicy

logger = logging.getLogger("autoresearcher.tools")


class ToolRegistry:
    """Manages tools available to agents.

    Design principle: minimal tool sets per agent.
    - Leader: log_memory, write_file, read_file
    - Idea Agent: search_papers, search_arxiv, get_paper, write_file, read_file
    - Code Agent: run_shell, launch_experiment, write_file, read_file, list_files,
      list_tree, search_code
    - Writing Agent: write_file, read_file, list_files, search_code

    Fewer tools = fewer tokens in each API call = lower cost.
    """

    def __init__(self, backend: ExecutionBackend, config: dict | None = None):
        self.backend = backend
        self._protected_files = {"state.json", "MEMORY_LOG.md", "PROJECT_BRIEF.md", ".lock"}
        # D0: protected write boundary. Config keys (all optional, backwards compatible):
        #   experiment.write_policy.allowlist / denylist_dirs / denylist_files
        cfg = (config or {}).get("experiment", {}) or {}
        wp = cfg.get("write_policy") or {}
        self.write_policy = ProtectedWritePolicy(
            allowlist=wp.get("allowlist"),
            denylist_dirs=wp.get("denylist_dirs"),
            denylist_files=wp.get("denylist_files"),
            protected_hashes=wp.get("protected_hashes"),
        )
        # A: experiment budget contract (used by launch_experiment), legacy-safe.
        from .experiment_contract import resolve_budget
        self.budget = resolve_budget(cfg)

    def get_tools_for(self, agent_type: str) -> list[dict]:
        """Get tool definitions for a specific agent type."""
        tool_map = {
            "leader": [self._tool_log_memory, self._tool_write_file, self._tool_read_file],
            "idea": [
                self._tool_search_papers,
                self._tool_search_arxiv,
                self._tool_get_paper,
                self._tool_write_file,
                self._tool_read_file,
            ],
            "code": [
                self._tool_run_shell,
                self._tool_launch_experiment,
                self._tool_write_file,
                self._tool_read_file,
                self._tool_list_files,
                self._tool_list_tree,
                self._tool_search_code,
            ],
            "writing": [
                self._tool_write_file,
                self._tool_read_file,
                self._tool_list_files,
                self._tool_search_code,
            ],
        }
        return tool_map.get(agent_type, [])

    def execute_tool(self, name: str, args: dict) -> str:
        """Execute a tool by name and return the result."""
        handlers = {
            "run_shell": self._exec_run_shell,
            "launch_experiment": self._exec_launch_experiment,
            "write_file": self._exec_write_file,
            "read_file": self._exec_read_file,
            "list_files": self._exec_list_files,
            "list_tree": self._exec_list_tree,
            "search_code": self._exec_search_code,
            "search_papers": self._exec_search_papers,
            "search_arxiv": self._exec_search_arxiv,
            "get_paper": self._exec_get_paper,
            "log_memory": self._exec_log_memory,
        }

        handler = handlers.get(name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            return handler(**args)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return json.dumps({"error": str(e)})

    # --- Tool Definitions (for API schema) ---

    @property
    def _tool_run_shell(self) -> dict:
        return {
            "name": "run_shell",
            "description": "Run a shell command and return output. Use for quick checks, file ops, git commands. For long-running training, use launch_experiment instead.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 120)", "default": 120},
                },
                "required": ["command"],
            },
        }

    @property
    def _tool_launch_experiment(self) -> dict:
        return {
            "name": "launch_experiment",
            "description": (
                "Launch a long-running training experiment via nohup. Returns PID for "
                "monitoring. Use this for training runs, NOT run_shell (which rejects "
                "shell operators and 'cd'). The command runs with the workspace as cwd."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Training command (no shell operators)"},
                    "log_file": {"type": "string", "description": "Path for stdout/stderr log"},
                    "gpu": {"type": "string", "description": "CUDA_VISIBLE_DEVICES value"},
                },
                "required": ["command", "log_file"],
            },
        }

    @property
    def _tool_write_file(self) -> dict:
        return {
            "name": "write_file",
            "description": "Write content to a file. Cannot overwrite protected files (state.json, MEMORY_LOG.md, PROJECT_BRIEF.md).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        }

    @property
    def _tool_read_file(self) -> dict:
        return {
            "name": "read_file",
            "description": (
                "Read a file's contents. For large files, pass start_line/end_line "
                "to read just a slice (1-indexed, inclusive) with line numbers, "
                "instead of being truncated at 10K chars."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace"},
                    "start_line": {"type": "integer", "description": "First line to read (1-indexed). Optional."},
                    "end_line": {"type": "integer", "description": "Last line to read (1-indexed, inclusive). Optional."},
                },
                "required": ["path"],
            },
        }

    @property
    def _tool_list_files(self) -> dict:
        return {
            "name": "list_files",
            "description": "List files in a single directory (non-recursive). Use list_tree for a recursive overview.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to workspace", "default": "."},
                },
            },
        }

    @property
    def _tool_list_tree(self) -> dict:
        return {
            "name": "list_tree",
            "description": (
                "Recursively list the directory tree (depth-limited) to understand repo "
                "structure in one call. Skips .git, __pycache__, node_modules and similar. "
                "Directories end with '/'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root directory relative to workspace", "default": "."},
                    "max_depth": {"type": "integer", "description": "Max recursion depth (default: 3)", "default": 3},
                    "max_entries": {"type": "integer", "description": "Max entries to return (default: 300)", "default": 300},
                },
            },
        }

    @property
    def _tool_search_code(self) -> dict:
        return {
            "name": "search_code",
            "description": (
                "Search file contents for a regular expression across the workspace "
                "(grep-style). Returns matching file path, line number, and line text. "
                "Use this to locate where something is defined or used before reading files."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for"},
                    "path": {"type": "string", "description": "Directory/file to search under (default: whole workspace)", "default": "."},
                    "max_results": {"type": "integer", "description": "Max matches to return (default: 50)", "default": 50},
                    "ignore_case": {"type": "boolean", "description": "Case-insensitive search (default: false)", "default": False},
                },
                "required": ["pattern"],
            },
        }

    @property
    def _tool_search_papers(self) -> dict:
        return {
            "name": "search_papers",
            "description": "Search for academic papers via Semantic Scholar API.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10},
                    "year": {"type": "string", "description": "Year filter, e.g. '2024-2026'"},
                },
                "required": ["query"],
            },
        }

    @property
    def _tool_search_arxiv(self) -> dict:
        return {
            "name": "search_arxiv",
            "description": (
                "Search arXiv directly for the most recent preprints (Semantic Scholar "
                "indexing lags by days). Returns title, arXiv id, authors, published date, "
                "and abstract. Prefer this for very recent work; use search_papers for "
                "citation counts and venue coverage."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10},
                    "category": {"type": "string", "description": "Optional arXiv category filter, e.g. 'cs.CV', 'cs.LG'"},
                },
                "required": ["query"],
            },
        }

    @property
    def _tool_get_paper(self) -> dict:
        return {
            "name": "get_paper",
            "description": (
                "Fetch full details for one paper by id: a Semantic Scholar paperId, "
                "'arXiv:2401.01234', 'DOI:...', or 'CorpusId:...'. Returns abstract plus "
                "the top references and citations, so you can snowball through the "
                "citation graph to find closely related work."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "Paper id, e.g. 'arXiv:2401.01234' or a Semantic Scholar paperId"},
                    "include_references": {"type": "boolean", "description": "Include outgoing references (default: true)", "default": True},
                    "include_citations": {"type": "boolean", "description": "Include incoming citations (default: true)", "default": True},
                },
                "required": ["paper_id"],
            },
        }

    @property
    def _tool_log_memory(self) -> dict:
        return {
            "name": "log_memory",
            "description": "Log an entry to the memory system. Use 'milestone' for key results, 'decision' for routine decisions.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["milestone", "decision"]},
                    "entry": {"type": "string", "description": "Content to log"},
                },
                "required": ["type", "entry"],
            },
        }

    # --- Tool Implementations ---

    def _normalize_path(self, path: str) -> str:
        """Validate a tool-visible path and keep it workspace-relative."""
        return normalize_relative_path(path)

    def _parse_command(self, command: str) -> list[str]:
        """Parse command text into argv without invoking a shell.

        Shell compound syntax (``&&``, ``;``, pipes, redirection, ``cd``) is
        rejected up-front with an actionable hint: agents must use
        ``launch_experiment`` for training and ``cd`` is not needed because
        every command already runs with the workspace as its cwd. This closes
        the failure seen when an agent passed ``cd x && python train.py``.
        """
        if not command or not command.strip():
            raise ValueError("Command cannot be empty")

        shell_ops = ("&&", "||", ";", "|", ">", "<", ">>", "2>")
        for op in shell_ops:
            if op in command:
                raise ValueError(
                    f"Shell operator '{op}' is not allowed in run_shell. "
                    "Commands already run with the workspace as cwd; for "
                    "training use launch_experiment instead of 'cd && python ...'."
                )
        if command.strip().startswith("cd "):
            raise ValueError(
                "'cd' is not needed (commands run in the workspace cwd). "
                "For training use launch_experiment."
            )

        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ValueError(f"Invalid command syntax: {exc}") from exc

        if not argv:
            raise ValueError("Command cannot be empty")

        dangerous_bins = {
            "rm",
            "sudo",
            "su",
            "mkfs",
            "dd",
            "shutdown",
            "reboot",
            "poweroff",
            "halt",
        }
        if Path(argv[0]).name in dangerous_bins:
            raise ValueError(f"Blocked executable: {argv[0]}")

        # D0 / ADR-002: block destructive git subcommands outright. Read-only
        # git (status/log/diff) stays allowed so agents can inspect state.
        if Path(argv[0]).name == "git" and len(argv) > 1:
            destructive = {"reset", "clean", "checkout", "revert", "merge", "rebase",
                           "push", "fetch", "pull", "branch", "commit", "rm", "mv"}
            if argv[1].lstrip("-") in destructive:
                raise ValueError(
                    f"Blocked destructive git subcommand: git {argv[1]}"
                )

        return argv

    def _exec_run_shell(self, command: str, timeout: int = 120) -> str:
        """Execute a shell command with timeout."""
        argv = self._parse_command(command)
        result = self.backend.run_command(argv=argv, timeout=timeout)
        return json.dumps(result)

    def _exec_launch_experiment(self, command: str, log_file: str, gpu: str = None) -> str:
        """Launch experiment via nohup, annotating the result with the active
        experiment-validity budget so monitor/reporting can stay consistent."""
        env = {}
        if gpu:
            env["CUDA_VISIBLE_DEVICES"] = gpu

        argv = self._parse_command(command)
        result = self.backend.launch_command(
            argv=argv,
            log_file=self._normalize_path(log_file),
            env=env,
        )
        # A contract: attach budget facts (advisory; monitor is the enforcer).
        result = dict(result)
        result["experiment_budget"] = {
            "mode": self.budget.get("mode"),
            "limit": self.budget.get("limit"),
            "hard_wall_clock_limit": self.budget.get("hard_wall_clock_limit"),
            "enforced": self.budget.get("enforced"),
        }
        return json.dumps(result)

    def _exec_write_file(self, path: str, content: str) -> str:
        """Write file with protection checks (D0)."""
        normalized = self._normalize_path(path)
        if normalized.split("/")[-1] in self._protected_files:
            return json.dumps({"error": f"Cannot overwrite protected file: {path}"})

        # D0: allowlist/denylist boundary check.
        allowed, reason = self.write_policy.allows_write(normalized)
        if not allowed:
            return json.dumps({
                "error": f"Write blocked by protected write boundary: {reason}",
                "hint": "You may only modify allowlisted files. Commit time-sliced "
                        "code changes into the allowlisted train.py or workspace/.",
            })

        result = self.backend.write_file(normalized, content)
        return json.dumps(result)

    def _exec_read_file(self, path: str, start_line: int = None, end_line: int = None) -> str:
        """Read file contents, optionally a 1-indexed inclusive line range."""
        normalized = self._normalize_path(path)
        if start_line is not None or end_line is not None:
            content = self.backend.read_file_range(
                normalized,
                start_line=int(start_line) if start_line is not None else 1,
                end_line=int(end_line) if end_line is not None else None,
            )
            return content[:20000]  # Ranged reads get a larger cap
        content = self.backend.read_file(normalized)
        return content[:10000]  # Cap at 10K chars

    def _exec_list_files(self, path: str = ".") -> str:
        """List directory contents."""
        files = self.backend.list_files(self._normalize_path(path))
        return json.dumps({"files": files[:100]})  # Cap at 100 entries

    def _exec_list_tree(self, path: str = ".", max_depth: int = 3, max_entries: int = 300) -> str:
        """List a depth-limited recursive directory tree."""
        entries = self.backend.list_tree(
            self._normalize_path(path),
            max_depth=int(max_depth),
            max_entries=int(max_entries),
        )
        return json.dumps({"tree": entries, "count": len(entries)})

    def _exec_search_code(self, pattern: str, path: str = ".", max_results: int = 50,
                          ignore_case: bool = False) -> str:
        """Grep file contents for a regex across the workspace."""
        hits = self.backend.grep_files(
            pattern,
            self._normalize_path(path),
            max_results=int(max_results),
            ignore_case=bool(ignore_case),
        )
        return json.dumps({"matches": hits, "count": len(hits)})

    def _exec_search_papers(self, query: str, limit: int = 10, year: str = None) -> str:
        """Search Semantic Scholar."""
        import urllib.request
        import urllib.parse

        limit = max(1, int(limit))  # tolerate string limits from the text tool-call protocol
        params = {"query": query, "limit": limit, "fields": "title,year,authors,abstract,citationCount,url"}
        if year:
            params["year"] = year

        url = f"https://api.semanticscholar.org/graph/v1/paper/search?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoResearcher/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                papers = data.get("data", [])
                return json.dumps({"papers": papers[:limit]}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"Search failed: {str(e)}"})

    def _exec_search_arxiv(self, query: str, limit: int = 10, category: str = None) -> str:
        """Search arXiv's Atom API for the latest preprints."""
        import urllib.request
        import urllib.parse
        import xml.etree.ElementTree as ET

        limit = max(1, int(limit))  # tolerate string limits from the text tool-call protocol
        search_query = f"all:{query}"
        if category:
            search_query = f"cat:{category} AND ({search_query})"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max(1, int(limit)),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"http://export.arxiv.org/api/query?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoResearcher/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                root = ET.fromstring(resp.read())
        except Exception as e:
            return json.dumps({"error": f"arXiv search failed: {str(e)}"})

        ns = {"a": "http://www.w3.org/2005/Atom"}
        papers = []
        for entry in root.findall("a:entry", ns):
            arxiv_url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
            arxiv_id = arxiv_url.rsplit("/", 1)[-1]
            papers.append({
                "arxiv_id": arxiv_id,
                "title": " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split()),
                "published": (entry.findtext("a:published", default="", namespaces=ns) or "").strip(),
                "authors": [
                    (a.findtext("a:name", default="", namespaces=ns) or "").strip()
                    for a in entry.findall("a:author", ns)
                ],
                "abstract": " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split()),
                "url": arxiv_url,
            })
        return json.dumps({"papers": papers[:limit]}, indent=2)

    def _exec_get_paper(self, paper_id: str, include_references: bool = True,
                        include_citations: bool = True) -> str:
        """Fetch one paper's details (incl. references/citations) from Semantic Scholar."""
        import urllib.request
        import urllib.parse

        if not paper_id or not str(paper_id).strip():
            return json.dumps({"error": "paper_id cannot be empty"})

        fields = ["title", "year", "authors", "abstract", "citationCount", "venue", "url"]
        if include_references:
            fields.append("references.title")
            fields.append("references.year")
            fields.append("references.externalIds")
        if include_citations:
            fields.append("citations.title")
            fields.append("citations.year")
            fields.append("citations.externalIds")

        quoted = urllib.parse.quote(str(paper_id).strip(), safe=":/")
        url = (
            f"https://api.semanticscholar.org/graph/v1/paper/{quoted}"
            f"?{urllib.parse.urlencode({'fields': ','.join(fields)})}"
        )

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoResearcher/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            return json.dumps({"error": f"get_paper failed: {str(e)}"})

        # Trim reference/citation lists so the result stays token-friendly.
        for key in ("references", "citations"):
            if isinstance(data.get(key), list):
                data[key] = data[key][:25]
        return json.dumps(data, indent=2)

    def _exec_log_memory(self, type: str, entry: str) -> str:
        """Log to memory (delegated to MemoryManager)."""
        return json.dumps({"status": "logged", "type": type, "entry": entry[:200]})
