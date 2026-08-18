"""
AutoResearcher 两层记忆系统

无论智能体运行多久，都把记忆总量控制在固定大小：
- 第一层（PROJECT_BRIEF.md）：冻结的参考信息，智能体永远不能修改
- 第二层（MEMORY_LOG.md）：滚动日志，会自动压缩（compaction）

记忆总预算：约 5000 字符（约 1500 token）——始终保持恒定。
"""

import time
from pathlib import Path
from typing import Optional


class MemoryManager:
    """带自动压缩的两层记忆管理器。

    核心思路：长时间运行的智能体会不断积累上下文，导致性能下降、成本飙升。
    本系统通过以下方式把记忆限制在固定预算内：
    - 把关键里程碑（重要结果）放进优先队列，最旧的优先丢弃
    - 只保留最近 N 条决策记录
    - 永不修改冻结的项目简报（brief）
    """

    def __init__(
        self,
        project_dir: Path,
        brief_max: int = 3000,
        log_max: int = 2000,
        milestone_max: int = 1200,
        max_recent: int = 15,
    ):
        # 项目根目录
        self.project_dir = Path(project_dir)
        # 第一层（冻结简报）路径
        self.brief_path = self.project_dir / "PROJECT_BRIEF.md"
        # 第二层（滚动日志）路径
        self.log_path = self.project_dir / "workspace" / "MEMORY_LOG.md"
        # 简报字符上限
        self.brief_max = brief_max
        # 日志字符上限
        self.log_max = log_max
        # 里程碑字符上限
        self.milestone_max = milestone_max
        # 保留的最近决策条数
        self.max_recent = max_recent

        # 确保日志文件存在
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self._init_log()

    def get_brief(self) -> str:
        """返回冻结的项目简报（第一层）。"""
        if self.brief_path.exists():
            content = self.brief_path.read_text()
            return content[: self.brief_max]
        return ""

    def get_log(self) -> str:
        """返回滚动记忆日志（第二层）。"""
        if self.log_path.exists():
            return self.log_path.read_text()
        return ""

    def get_full_context(self) -> str:
        """返回供智能体使用的合并记忆上下文。"""
        brief = self.get_brief()
        log = self.get_log()
        return f"## Project Brief\n{brief}\n\n## Memory Log\n{log}"

    def log_milestone(self, entry: str):
        """记录一条关键结果里程碑。超出预算时自动压缩。"""
        sections = self._parse_log()
        timestamp = time.strftime("%m-%d %H:%M")
        sections["milestones"].append(f"[{timestamp}] {entry}")

        # 压缩：若里程碑字符超限，则从最旧开始丢弃
        while self._section_size(sections["milestones"]) > self.milestone_max and len(sections["milestones"]) > 1:
            sections["milestones"].pop(0)

        self._write_log(sections)

    def log_decision(self, entry: str):
        """记录一条最近决策。自动压缩，只保留最近 N 条。"""
        sections = self._parse_log()
        timestamp = time.strftime("%m-%d %H:%M")
        sections["decisions"].append(f"[{timestamp}] {entry}")

        # 压缩：只保留最近 max_recent 条
        if len(sections["decisions"]) > self.max_recent:
            sections["decisions"] = sections["decisions"][-self.max_recent :]

        self._write_log(sections)

    def _init_log(self):
        """创建初始的空记忆日志。"""
        content = "# Memory Log\n\n## Key Results\n\n## Recent Decisions\n"
        self.log_path.write_text(content)

    def _parse_log(self) -> dict:
        """把 MEMORY_LOG.md 解析为分段字典。"""
        content = self.get_log()
        sections = {"milestones": [], "decisions": []}

        current_section = None
        for line in content.split("\n"):
            line_stripped = line.strip()
            if line_stripped == "## Key Results":
                current_section = "milestones"
            elif line_stripped == "## Recent Decisions":
                current_section = "decisions"
            elif line_stripped.startswith("[") and current_section:
                sections[current_section].append(line_stripped)

        return sections

    def _write_log(self, sections: dict):
        """把分段写回 MEMORY_LOG.md。"""
        lines = ["# Memory Log", "", "## Key Results"]
        for entry in sections["milestones"]:
            lines.append(entry)
        lines.append("")
        lines.append("## Recent Decisions")
        for entry in sections["decisions"]:
            lines.append(entry)
        lines.append("")

        content = "\n".join(lines)

        # 最终安全检查：日志总字符必须落在预算内
        if len(content) > self.log_max:
            # 激进压缩：先砍里程碑，再砍决策
            while len(content) > self.log_max and len(sections["milestones"]) > 1:
                sections["milestones"].pop(0)
                content = self._build_content(sections)
            while len(content) > self.log_max and len(sections["decisions"]) > 1:
                sections["decisions"].pop(0)
                content = self._build_content(sections)

        self.log_path.write_text(content)

    def _build_content(self, sections: dict) -> str:
        # 根据分段重新拼装日志文本
        lines = ["# Memory Log", "", "## Key Results"]
        lines.extend(sections["milestones"])
        lines.append("")
        lines.append("## Recent Decisions")
        lines.extend(sections["decisions"])
        lines.append("")
        return "\n".join(lines)

    def _section_size(self, entries: list) -> int:
        # 计算一段记录的总字符数
        return sum(len(e) for e in entries)
