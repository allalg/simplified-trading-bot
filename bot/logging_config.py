"""
logging_config.py — Configures structured logging for the trading bot.

Logs go to both:
  - Console (INFO level, human-readable)
  - File    (DEBUG level, structured with timestamps)
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path


LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "trading_bot.log"

LOG_FORMAT_FILE = (
    "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s"
)
LOG_FORMAT_CONSOLE = (
    "%(levelname)-8s | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(console_level: int = logging.INFO, file_level: int = logging.DEBUG) -> None:
    """
    Call once at application startup to configure all handlers.
    Safe to call multiple times — handlers are not duplicated.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()

    # Avoid adding duplicate handlers on re-import
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.DEBUG)

    # ── File handler (rotating, max 5 MB × 3 backups) ──────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT_FILE, datefmt=DATE_FORMAT))

    # ── Console handler ─────────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT_CONSOLE))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ── Silence noisy third-party loggers ───────────────────────────────────────
    # These flood the log with internal HTTP connection pool details
    # that are not useful for auditing bot activity.
    for noisy_lib in ("urllib3", "requests", "charset_normalizer", "urllib3.connectionpool"):
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. setup_logging() must be called first."""
    return logging.getLogger(name)
