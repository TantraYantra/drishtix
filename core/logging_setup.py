"""Logging setup for the windowed PeopleLens application.

A PyInstaller ``console=False`` build has nowhere to print tracebacks, so every
important error is written to ``%LOCALAPPDATA%\\TantraYantra\\PeopleLens\\peoplelens.log``.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app_paths import LOG_PATH, ensure_user_data

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("peoplelens")
    if _CONFIGURED:
        return logger
    _CONFIGURED = True
    ensure_user_data()
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        file_handler = RotatingFileHandler(
            LOG_PATH, maxBytes=1_500_000, backupCount=4, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    logging.captureWarnings(True)
    return logger
