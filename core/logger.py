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
import time
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


class _SayItOnce(logging.Filter):
    """The same line, once -- then a count, not a flood.

    ==========================================================
        "why can't we stop this printing continously ... print only
         one time at starting & do not make this print every second"
                                -- the operator, 3 September 2026
    ==========================================================

    dhanhq logs its own failures to the ROOT logger, which is why it
    reads ERROR:root: and not like anything this bot writes. With the
    static IP expired, every poll of /v2/positions and /v2/holdings
    comes back "Tunnel connection failed: 403" and prints in full,
    once a cycle, all day -- burying the lines that matter on the one
    screen he watches.

    This does not hide it. The first occurrence prints in full, and
    every 15 minutes it prints again WITH the number of times it
    happened in between, so a fault that is getting worse still looks
    like it is getting worse. A message that scrolls past 400 times an
    hour is not more visible than one that prints five times; it is
    less.

    Keyed on the message text, so a DIFFERENT error is never
    suppressed by a noisy neighbour.
    """

    def __init__(self, every_seconds=900):
        super().__init__()
        self._every = float(every_seconds)
        self._seen = {}

    def filter(self, record):                              # noqa: A003
        try:
            key = record.getMessage()[:200]
        except Exception:                                  # noqa: BLE001
            return True
        now = time.time()
        seen = self._seen.get(key)
        if seen is None:
            self._seen[key] = [now, 0]
            return True
        last, repeats = seen
        if now - last >= self._every:
            seen[0], seen[1] = now, 0
            if repeats:
                record.msg = (f"{record.getMessage()}   "
                              f"[and {repeats} more like it in the last "
                              f"{int(self._every // 60)} minutes]")
                record.args = ()
            return True
        seen[1] = repeats + 1
        return False


def quieten_repeats(every_seconds=900):
    """Install the filter on the ROOT logger -- where third-party
    libraries write. The bot's own logger sets propagate=False and is
    untouched by this."""
    root = logging.getLogger()
    if any(isinstance(f, _SayItOnce) for f in root.filters):
        return
    root.addFilter(_SayItOnce(every_seconds))


log = _build_logger()
quieten_repeats()


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


# ==========================================================
#  SAY IT WHEN IT CHANGES, NOT WHEN IT IS TRUE.  1 Sept 2026
# ==========================================================
#
#     "why main.py needs to print every thing ? is it mandatory"
#
# Measured on his own log, 1 September, eight minutes before the open
# with no trading happening at all:
#
#     6,167 lines
#     77% of them repeats
#
#     913x  [FLOWS] fii_cr differs between the two sources
#     912x  [RANK] 262 stock(s) added by reason
#     457x  [GL] No live prices -- showing the 2026-08-31 close
#     456x  [RANK] refused: no event x169, not moving enough x73
#     456x  [RULES] 1 pick(s) removed
#     288x  [BRAIN] 8 candidate(s) -> would back [...]
#
# Not one of those is a decision, a trade, or a fault. They are the
# refresh loop narrating a state that has not changed. "No live prices"
# before 09:15 is true and unchanging for ninety minutes.
#
# WHY IT IS NOT JUST UNTIDY. The log rotates at 25 MB and pre-flight
# reported the largest already at 20 MB. At this rate the one line that
# matters -- an order refused, the feed dropping, BUYING DRIED UP -- is
# buried in five thousand identical ones. He would never find it, and
# neither would I.
#
# NOT a rate limit and NOT a "say once". Both of those hide a change.
# This says the message the FIRST time and every time it DIFFERS from
# the last one under the same key, so "refused: 169 no-event" prints
# when 169 becomes 170 and stays quiet while it stays 169.
_LAST_SAID = {}


def when_it_changes(key, message, how=None):
    """Log `message` only if it differs from the last one for `key`.

    `how` is the log function to use -- diagnostic by default, so a
    caller has to opt in to anything louder.
    """
    if _LAST_SAID.get(key) == message:
        return False
    _LAST_SAID[key] = message
    (how or diagnostic)(message)
    return True


def forget_what_was_said(key=None):
    """Test hook, and the way to force a repeat after a restart."""
    if key is None:
        _LAST_SAID.clear()
    else:
        _LAST_SAID.pop(key, None)
