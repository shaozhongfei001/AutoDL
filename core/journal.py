"""
研究日志（Journal）—— 只追加、永不删除的 DEAD_ENDS.md 与 INSIGHTS.md。

与两层 MEMORY_LOG（会自动压缩并静默丢弃旧内容）不同，这里的日志是
“只追加”的：它们永远不会被压缩；当某个文件超过大小上限时，会被轮转
（rotate）到一个带日期的 ``.bak`` 归档文件中，然后新建一个空白文件继续写，
因此历史不会丢失，只是被挪到了一边。

- DEAD_ENDS.md：记录失败过的思路，禁止再次尝试，避免重复踩坑。
- INSIGHTS.md：记录值得跨周期保留的、经得起时间检验的观察结论。

主循环（loop）会把这两个文件的尾部注入到 THINK（思考）上下文中，让智能体
不再重复已知的死路，同时把来之不易的洞察始终放在视野内。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger("autodl.journal")


class _AppendOnlyDoc:
    """一个只追加的文档：负责单类日志（死路或洞察）的写入与轮转。"""

    def __init__(self, path: Path, title: str, max_chars: int):
        # 日志文件路径
        self.path = Path(path)
        # 文档标题（写入文件头）
        self.title = title
        # 单个文件允许的最大字符数，超过则触发轮转
        self.max_chars = max_chars
        # 确保父目录存在
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 若文件不存在则初始化
        if not self.path.exists():
            self._init()

    def _init(self):
        # 写入带标题的空文档头
        self.path.write_text(f"# {self.title}\n\n", encoding="utf-8")

    def append(self, entry: str, ts: str = None) -> None:
        """追加一条带时间戳的记录。任何异常都不会向上抛出。"""
        entry = (entry or "").strip()
        if not entry:
            return
        # 没有显式时间戳时，使用当前本地时间
        stamp = ts if ts is not None else time.strftime("%Y-%m-%d %H:%M")
        try:
            if not self.path.exists():
                self._init()
            # 以追加模式写入一行带时间戳的记录
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(f"- [{stamp}] {entry}\n")
            # 文件体积超限则轮转
            if self.path.stat().st_size > self.max_chars:
                self._rotate(stamp)
        except OSError as exc:  # pragma: no cover - 磁盘故障分支
            logger.warning(f"Failed to append to {self.path.name}: {exc}")

    def _rotate(self, stamp: str) -> None:
        """把整个文件归档成带日期的备份，然后仅保留尾部内容重新开始。"""
        try:
            content = self.path.read_text(encoding="utf-8")
            # 时间戳中的空格与冒号在文件名中不友好，替换掉
            safe_stamp = stamp.replace(" ", "_").replace(":", "")
            backup = self.path.with_name(f"{self.path.stem}.{safe_stamp}.bak")
            # 若备份已存在，追加序号避免覆盖
            n = 0
            while backup.exists():
                n += 1
                backup = self.path.with_name(f"{self.path.stem}.{safe_stamp}.{n}.bak")
            # 写一份完整归档
            backup.write_text(content, encoding="utf-8")
            # 重新开始时只保留最近一半的内容，并在头部注明完整历史位置
            tail = content[-(self.max_chars // 2):]
            self.path.write_text(
                f"# {self.title}\n\n_(rotated; full history in {backup.name})_\n{tail}",
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - 磁盘故障分支
            logger.warning(f"Failed to rotate {self.path.name}: {exc}")

    def tail(self, max_chars: int) -> str:
        """返回文件最后 ``max_chars`` 个字符。任何异常都返回空字符串。"""
        try:
            max_chars = int(max_chars)
        except (TypeError, ValueError):
            max_chars = self.max_chars
        try:
            if not self.path.exists():
                return ""
            content = self.path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - 磁盘故障分支
            logger.warning(f"Failed to read {self.path.name}: {exc}")
            return ""
        # 内容比上限短则全返回，否则只返回尾部
        return content[-max_chars:] if len(content) > max_chars else content


class ResearchJournal:
    """管理 DEAD_ENDS 与 INSIGHTS 两份只追加日志。"""

    def __init__(self, workspace: Path, max_chars: int = 4000):
        workspace = Path(workspace)
        # 死路日志：记录失败思路，禁止重试
        self.dead_ends = _AppendOnlyDoc(workspace / "DEAD_ENDS.md", "Dead Ends", max_chars)
        # 洞察日志：记录可跨周期复用的观察结论
        self.insights = _AppendOnlyDoc(workspace / "INSIGHTS.md", "Insights", max_chars)

    def append_dead_end(self, entry: str, ts: str = None) -> None:
        # 追加一条死路记录
        self.dead_ends.append(entry, ts=ts)

    def append_insight(self, entry: str, ts: str = None) -> None:
        # 追加一条洞察记录
        self.insights.append(entry, ts=ts)

    def dead_ends_tail(self, max_chars: int = 1500) -> str:
        # 返回死路日志尾部，供主循环注入上下文
        return self.dead_ends.tail(max_chars)

    def insights_tail(self, max_chars: int = 1500) -> str:
        # 返回洞察日志尾部，供主循环注入上下文
        return self.insights.tail(max_chars)
