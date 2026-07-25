"""
Two log destinations, always:

    console -- clean, only real decisions/results (unless
               VERBOSE_CONSOLE=True)
    file    -- everything, always, for later review

Nothing is ever silently dropped. If it's not on console,
it's in the file.
"""

import logging
import os

from config import LOG_DIR, DIAGNOSTIC_LOG_PATH, VERBOSE_CONSOLE

os.makedirs(LOG_DIR, exist_ok=True)


def _build_logger():
    logger = logging.getLogger("opportunity_trader")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger

    file_handler = logging.FileHandler(
        DIAGNOSTIC_LOG_PATH, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )
    )
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        logging.DEBUG if VERBOSE_CONSOLE else logging.INFO
    )
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    return logger


log = _build_logger()


def decision(message):
    """A real decision or result -- always shown live."""
    log.info(message)


def diagnostic(message):
    """Detail -- file only, unless VERBOSE_CONSOLE is on."""
    log.debug(message)


def warn(message):
    """Something is wrong or missing -- always shown live."""
    log.warning(f"WARNING: {message}")
