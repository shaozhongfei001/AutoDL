"""
为本框架提供稳定的第三方结构化日志（基于 loguru）。

为什么用 loguru（而不是自己手写日志层）：
  - 默认线程安全：框架会派发多个 worker 智能体、监控子进程、并发调用多个
    工具；手写日志配置很容易出现竞争（日志行交错/损坏），而 loguru 会串行化写入。
  - ``RESULT {...}`` 这类结构化实验指标仍然属于训练子进程的“纯标准输出”
    （见 monitor._extract_metrics）——它们**不**经过本模块。训练进程是独立的
    子进程，Python logging 无法捕获它的 stdout。本模块只负责整理框架“自身”
    的日志流。

设计要点：
  - 拦截标准库 ``logging`` 中 ``autodl.*`` 日志树产生的记录，并通过 loguru 重新
    发出，因此已有的 ``logging`` 调用点无需任何改动即可继续工作，项目的测试
    （它们驱动的是标准库 logging）也不受影响。
  - ``configure_logging`` 是幂等的，可以安全地多次调用。
  - ``install_autodl_loggers`` 是唯一需要显式调用的入口；它把 ``autodl`` 日志器的
    处理器替换为一个 loguru 桥接器。请在进程启动时（loop.py 的 ``main`` 中）、
    标准库 ``basicConfig`` 之后调用一次即可。
"""

import logging
import sys

try:
    # 尝试导入 loguru；若环境中未安装则降级到标准库 logging
    from loguru import logger as _loguru_logger
    _HAS_LOGURU = True
except Exception:  # pragma: no cover - 可选依赖
    _HAS_LOGURU = False

# 标准库日志级别 -> loguru 级别名称 的映射表
_LEVEL_MAP = {
    "CRITICAL": "CRITICAL",
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
}

# 人类可读的彩色日志格式
_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class _LoguruHandler(logging.Handler):
    """一个标准库 Handler，把日志记录转发给 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        # 没有 loguru 时直接跳过
        if not _HAS_LOGURU:
            return
        try:
            # 把标准库级别名映射到 loguru 级别
            level = _LEVEL_MAP.get(record.levelname, record.levelname)
            message = self.format(record)
            frame = None  # 保留占位，避免 loguru 把本桥接帧计入 traceback
            if record.exc_info and record.exc_info[0] is not None:
                # 带异常信息时，连同异常对象一起交给 loguru
                _loguru_logger.opt(exception=record.exc_info, colors=True).log(
                    level, message
                )
            else:
                _loguru_logger.opt(depth=1).log(level, message)
        except Exception:  # pragma: no cover - 日志绝不能让一次运行崩溃
            self.handleError(record)


def _bridge_to_loguru() -> None:
    """把标准库 ``autodl`` 日志器（及其子日志器）的日志路由到 loguru。"""
    if not _HAS_LOGURU:
        return
    root = logging.getLogger("autodl")
    root.handlers = []  # 清空已有处理器，避免重复记录
    handler = _LoguruHandler()
    # 默认与 loguru 的 INFO 级别对齐，除非另有配置
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    # 关闭标准库向上传播，避免根处理器再记录一次
    root.propagate = False


def configure_logging(level: str = "INFO", serialize: bool = False) -> None:
    """幂等地配置框架的 loguru 日志。

    参数：
        level: 框架输出的最低严重级别（默认 INFO）。
        serialize: 为 True 时输出 JSON 行（供机器消费），否则输出人类可读的
            彩色格式。
    """
    if not _HAS_LOGURU:
        # 优雅降级：loguru 未安装时（例如极简测试环境）退回标准库 logging
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
        )
        return

    _loguru_logger.remove()
    # 根据是否序列化选择不同格式
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        if not serialize
        else "{time} | {level} | {name} | {message}"
    )
    _loguru_logger.add(
        sys.stderr,
        format=fmt,
        level=level.upper(),
        serialize=bool(serialize),
        colorize=not serialize,
        backtrace=False,
        diagnose=False,
        enqueue=True,  # 线程安全的后台写入
    )
    _bridge_to_loguru()


def get_framework_logger(name: str = "autodl"):
    """返回一个绑定了框架子模块名称的 loguru 日志器。

    新代码优先使用本函数，从而直接获得 loguru 的结构化、线程安全日志。
    已有的标准库 ``logging.getLogger('autodl.X')`` 调用点则继续通过桥接器工作。
    """
    return _loguru_logger.bind(name=name)
