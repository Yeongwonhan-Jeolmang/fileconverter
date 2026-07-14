"""Central logging configuration shared by the CLI and GUI."""

from __future__ import annotations

import logging
import sys

from .config import CONFIG_DIR

LOG_FILE = CONFIG_DIR / "fileconverter.log"


def setup_logging(verbose: bool = False) -> logging.Logger:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fileconverter")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.addHandler(stream_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("fileconverter")
