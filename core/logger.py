"""
==========================================================
Logging -- readable, rotated, and honest about what it drops
==========================================================

    console  -- decisions and warnings only (unless VERBOSE_CONSOLE)
    file     -- everything at DEBUG, but rotated and per-process

WHY THIS WAS REWRITTEN, 2026-07-28
----------------------------------
The old version was a plain FileHandler on one path, DEBUG to disk,
never rotated. By the audit that evening:

    369 MB, 3,586,389 lines, one file
    131,238 lines CORRUPTED (3.7%) by interleaved writes
    ~4,000 lines a minute during a session, 99.97% of them DEBUG
    2,446 of those per minute were "SYM stale: 24.0s old"

Three separate faults, all of them making the log unusable as evidence
-- which matters more than disk space, because the whole plan rests on
producing ONE clean session whose log can be trusted.

1. NO ROTATION. It only grew.

2. INTERLEAVED WRITES. Several PROCESSES appended to the same path --
   main.py, the dashboard preview, pytest runs. Python's logging is
   thread-safe, not process-safe, so writes tore into each other:

       2026-02026-07-23 11:29:29,307 [DEBUG] [CANDLE] LICI closed ...
       7-23 11:29:29,582 [DEBUG] [ORB] TCS range complete ...

   That is why three of the audit's own findings were wrong: I was
   reading a corrupted file and could not tell.

3. TEST OUTPUT IN THE LIVE LOG. A pytest run emitted lines
   indistinguishable from real alarms -- [DAILY HALT] Realized P&L
   -8500, [BAD_TICK] TCS rejected 105.00. None of it real. (Fixed
   separately in tests/conftest.py; the per-process filename below is
   the belt to that braces.)

WHAT CHANGED
------------
- RotatingFileHandler, 25 MB x 5 files. A session is ~15 MB after the
  staleness fix, so a full day fits in one file and a week is kept.
- One file PER PROCESS (pid in the name), so two processes can never
  tear into each other's lines again.
- DEBUG can be kept off disk entirely (LOG_DEBUG_TO_FILE=False), which
  removes ~84% of the volume. Default is ON, because a quiet log that
  cannot answer "what happened at 09:47" is a false economy -- but the
  switch exists for a day when it matters.

NOTHING IS EVER SILENTLY DROPPED. If it is not on the console, it is
in the file -- unless LOG_DEBUG_TO_FILE is off, and then the startup
banner says so out loud.

Author : H&M Opportunity Trader
==========================================================
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from config import LOG_DIR, DIAGNOSTIC_LOG_PATH, VERBOSE_CONSOLE

try:
    from config import (
        LOG_MAX_BYTES, LOG_BACKUP_COUNT, LOG_DEBUG_TO_FILE,
        LOG_ONE_FILE_PER_PROCESS,
    )
except ImportError:      # pragma: no cover -- older config, keep working
    LOG_MAX_BYTES = 25 * 1024 * 1024
    LOG_BACKUP_COUNT = 5
    LOG_DEBUG_TO_FILE = True
    LOG_ONE_FILE_PER_PROCESS = True

os.makedirs(LOG_DIR, exist_ok=True)


def _log_path():
    """One file per process, so two processes cannot interleave.

    2026-07-28: 131,238 lines of the shared log were torn in half by
    concurrent writers. The pid in the name makes that impossible
    rather than unlikely.
    """
    if not LOG_ONE_FILE_PER_PROCESS:
        return DIAGNOSTIC_LOG_PATH
    stem, ext = os.path.splitext(DIAGNOSTIC_LOG_PATH)
    return f"{stem}_{os.getpid()}{ext or '.log'}"


def _build_logger():
    logger = logging.getLogger("opportunity_trader")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        return logger

    file_handler = RotatingFileHandler(
        _log_path(), maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setLevel(
        logging.DEBUG if LOG_DEBUG_TO_FILE else logging.INFO
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
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


def log_file_path():
    """Where this process is actually writing. Printed at startup so
    there is never a question of which file to read."""
    for handler in log.handlers:
        if isinstance(handler, logging.FileHandler):
            return handler.baseFilename
    return DIAGNOSTIC_LOG_PATH


def decision(message):
    """A real decision or result -- always shown live."""
    log.info(message)


def diagnostic(message):
    """Detail -- file only, unless VERBOSE_CONSOLE is on."""
    log.debug(message)


def warn(message):
    """Something is wrong or missing -- always shown live."""
    log.warning(f"WARNING: {message}")
