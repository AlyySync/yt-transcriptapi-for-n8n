"""
Logging setup for the transcript service.

Controlled entirely by environment variables:

    LOG_LEVEL           INFO (normal) or DEBUG (very detailed). Default: INFO
    LOG_RETENTION_DAYS  How many days of logs to keep. Older ones auto-delete.
                        Default: 7
    LOG_DIR             Folder where log files are written. Default: logs

Two log files are produced (both rotate daily at midnight):
    app.log     everything at the chosen level (INFO or DEBUG)
    error.log   errors only (ERROR level and above, with full tracebacks)

Rotation + retention = old files delete themselves automatically. With
LOG_RETENTION_DAYS=7 the handler keeps 7 rotated files and drops anything older.
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOGGER_NAME = "yt_transcript"


def setup_logging() -> logging.Logger:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    retention_days = int(os.getenv("LOG_RETENTION_DAYS", "7"))
    log_dir = os.getenv("LOG_DIR", "logs")

    level = getattr(logging, log_level_name, logging.INFO)

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()  # avoid duplicate handlers if called more than once

    # 1) Main log file — INFO or DEBUG depending on LOG_LEVEL
    app_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "app.log"),
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    app_handler.setLevel(level)
    app_handler.setFormatter(formatter)
    logger.addHandler(app_handler)

    # 2) Error-only log file — always ERROR and above
    error_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "error.log"),
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    # 3) Console — so you also see logs in the terminal
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    logger.info(
        "Logging ready | level=%s | retention=%s days | dir=%s",
        log_level_name,
        retention_days,
        log_dir,
    )
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)