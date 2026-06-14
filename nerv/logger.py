"""Console logging system — console output or a sink callback (no log files)."""

import logging
import sys
from datetime import datetime
from typing import Callable, Optional


# ANSI color codes for console output
C_ORANGE = "\033[38;5;208m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_GRAY = "\033[90m"
C_WHITE = "\033[97m"
RESET = "\033[0m"


class ConsoleFormatter(logging.Formatter):
    """Colored, timestamped console formatter."""

    LEVEL_COLORS = {
        logging.DEBUG: C_GRAY,
        logging.INFO: C_ORANGE,
        logging.WARNING: C_YELLOW,
        logging.ERROR: C_RED,
        logging.CRITICAL: C_RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, C_WHITE)
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = record.levelname.ljust(7)
        return (
            f"{C_GRAY}[{timestamp}]{RESET} "
            f"{color}[{level}]{RESET} "
            f"{record.getMessage()}"
        )


class _SinkHandler(logging.Handler):
    """Routes plain (no-ANSI) formatted log lines to a callback."""

    def __init__(self, sink: Callable[[str], None]):
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord):
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = record.levelname.ljust(7)
        try:
            self.sink(f"[{timestamp}] [{level}] {record.getMessage()}")
        except Exception:
            pass


class NervLogger:
    """
    Console logger for EPUB Manager — console only, no log file.

    If `sink` is provided (e.g. the NERV dashboard log feed), log lines are sent
    there instead of stdout, so they don't corrupt a full-screen live window.
    """

    def __init__(self, verbose: bool = False, sink: Optional[Callable[[str], None]] = None):
        self.logger = logging.getLogger("EPUB")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        level = logging.DEBUG if verbose else logging.INFO

        if sink is not None:
            handler: logging.Handler = _SinkHandler(sink)
        else:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(ConsoleFormatter())

        handler.setLevel(level)
        self.logger.addHandler(handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def critical(self, msg: str):
        self.logger.critical(msg)
