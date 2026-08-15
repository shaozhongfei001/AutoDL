"""
A: Stable third-party structured logging for the AutoDL framework.

Why loguru (not a hand-rolled logging layer):
  - Thread-safe by default: the framework dispatches worker agents, monitors
    subprocesses and runs multiple tool calls; a hand-rolled logging config
    is easy to race on (interleaved/corrupt lines). loguru serializes writes.
  - ``RESULT {...}`` structured experiment metrics remain pure stdout of the
    training subprocess (see monitor._extract_metrics) — they are NOT routed
    through this module. The training process is an independent subprocess;
    Python logging cannot capture its stdout. This module only structures the
    *framework's own* log stream.

Design:
  - Intercepts the stdlib ``logging`` records produced by the ``autodl.*``
    logger tree and re-emits them through loguru, so existing ``logging``
    call sites keep working with zero edits and the project's tests (which
    drive stdlib logging) are unaffected.
  - ``configure_logging`` is idempotent and safe to call multiple times.
  - ``install_autodl_loggers`` is the only required entry point; it replaces
    the ``autodl`` logger's handler with a loguru bridge. Call it once at
    process start (loop.py ``main``), after stdlib ``basicConfig``.
"""

import logging
import sys

try:
    from loguru import logger as _loguru_logger
    _HAS_LOGURU = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_LOGURU = False

# Map stdlib levels -> loguru level names.
_LEVEL_MAP = {
    "CRITICAL": "CRITICAL",
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "INFO": "INFO",
    "DEBUG": "DEBUG",
}

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class _LoguruHandler(logging.Handler):
    """A stdlib handler that forwards records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        if not _HAS_LOGURU:
            return
        try:
            level = _LEVEL_MAP.get(record.levelname, record.levelname)
            # Keep the loguru frame out of the traceback.
            message = self.format(record)
            frame = None
            if record.exc_info and record.exc_info[0] is not None:
                _loguru_logger.opt(exception=record.exc_info, colors=True).log(
                    level, message
                )
            else:
                _loguru_logger.opt(depth=1).log(level, message)
        except Exception:  # pragma: no cover - logging must never crash a run
            self.handleError(record)


def _bridge_to_loguru() -> None:
    """Route the stdlib 'autodl' logger (and children) through loguru."""
    if not _HAS_LOGURU:
        return
    root = logging.getLogger("autodl")
    root.handlers = []  # drop any prior handlers so we don't double-log
    handler = _LoguruHandler()
    # Match loguru's default level (INFO) unless explicitly configured.
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    # Prevent stdlib propagation from ALSO logging via the root handler.
    root.propagate = False


def configure_logging(level: str = "INFO", serialize: bool = False) -> None:
    """Idempotent framework loguru configuration.

    Args:
        level: minimum severity emitted by the framework (default INFO).
        serialize: if True, emit JSON lines (for machine consumption) instead
            of the human-readable colored format.
    """
    if not _HAS_LOGURU:
        # Graceful fallback: plain stdlib logging so the framework still works
        # when loguru is not installed (e.g. minimal test environments).
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
        )
        return

    _loguru_logger.remove()
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
        enqueue=True,  # thread-safe background writer
    )
    _bridge_to_loguru()


def get_framework_logger(name: str = "autodl"):
    """Return a loguru logger bound to a framework submodule name.

    Prefer this for NEW code so call sites get loguru's structured, thread-safe
    logging directly. Existing stdlib ``logging.getLogger('autodl.X')`` call
    sites keep working through the bridge.
    """
    return _loguru_logger.bind(name=name)
