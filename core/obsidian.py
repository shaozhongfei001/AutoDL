"""
把研究状态桥接到 Obsidian 知识库。

提供一个轻量适配器，把当前的“研究状态”（周期、最佳指标、假设、结论）写入
Obsidian 风格的 Markdown 笔记（带 YAML frontmatter），这样研究者可以在
Obsidian 中浏览、打标签、建立双向链接，而不必打开原始 JSONL 账本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class ObsidianBridge:
    """把研究状态快照成 Obsidian 笔记。"""

    def __init__(self, vault_dir: Path):
        # Obsidian 库目录（笔记将被写入此目录）
        self.vault_dir = Path(vault_dir)
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    def _frontmatter(self, state: dict) -> str:
        # 把状态中的标量字段写成 YAML frontmatter；非标量则序列化为 JSON 字符串
        fm: dict = {}
        for key, value in state.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                fm[key] = value
            else:
                fm[key] = json.dumps(value, ensure_ascii=False)
        lines = ["---"]
        for k, v in fm.items():
            lines.append(f"{k}: {v}")
        lines.append("---")
        return "\n".join(lines)

    def write_note(
        self,
        note_name: str,
        state: dict,
        body: str = "",
        ts: Optional[float] = None,
    ) -> Path:
        """写出一个带 frontmatter 的研究状态笔记，返回其路径。"""
        note_name = note_name or "research_state"
        if not note_name.endswith(".md"):
            note_name += ".md"
        # frontmatter 中无法表达的值（列表/字典）放进正文供阅读
        extra: list[str] = []
        for key, value in state.items():
            if not isinstance(value, (str, int, float, bool)) and value is not None:
                extra.append(f"- **{key}**: `{json.dumps(value, ensure_ascii=False)}`")
        front = self._frontmatter(state)
        content = f"{front}\n\n# Research State\n\n{body}\n"
        if extra:
            content += "\n## Structured\n" + "\n".join(extra) + "\n"
        path = self.vault_dir / note_name
        path.write_text(content, encoding="utf-8")
        return path
