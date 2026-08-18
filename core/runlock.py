"""
==========================================================
One reader of the Telegram session at a time
==========================================================

    "shall i run this py tools/nightly.py now? in one terminal
     py tools/telegram_catchup.py --apply is running right now"
                                    -- operator, 2 August 2026

He asked before doing it, which is why nothing broke. The next person
to ask will be him at 22:00 on a Thursday, having forgotten what is
open in the other window.

WHAT WOULD HAVE HAPPENED
------------------------
tools/nightly.py opens with the same telegram_catchup. Telethon keeps
its session in a SQLite file and so does the message store, and two
processes writing both at once gives "database is locked" -- but not
reliably, and not immediately. The failure mode is a half-read backlog
and a session file that has to be regenerated, discovered at 08:45.

WHAT THIS IS NOT
----------------
Not a general lock. It guards ONE thing: the Telegram reader. Every
other tool in the nightly run is safe to overlap and is left alone.

A stale lock -- laptop closed mid-run, process killed -- is detected
by age and ignored with a warning rather than blocking the night. A
lock that outlives its process must never be able to stop work
happening; that turns a convenience into an outage.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import time

from core.logger import diagnostic, warn

LOCK_PATH = os.path.join("data", "telegram_reader.lock")


def _path(path):
    """Resolve the lock location at CALL time, not at import.

    Every public function below takes path=None rather than
    path=LOCK_PATH. A default argument is bound once, when the def
    runs, so

        monkeypatch.setattr(runlock, "LOCK_PATH", tmp)

    would change the module attribute and change nothing about what
    these functions actually open.

    That matters because this lock is not decoration: tools/collector
    .py REFUSES TO START while another process holds it, so a test run
    that took the real one could lock him out of his own collector.
    The full suite did exactly that on 18 August and the data-folder
    guard caught it. Identical fix to core/single_instance.py, two
    days earlier, for identical reasons.
    """
    return LOCK_PATH if path is None else path

# Beyond this a lock is assumed to belong to a process that is gone.
# A weekend backlog is 40-60 minutes of real work, so the window has to
# be comfortably longer than the longest honest run.
STALE_AFTER_SECONDS = 2 * 60 * 60


_PID = re.compile(r"\bpid=(\d+)\b")


def _is_me(who):
    """True when the lock text names THIS process.

    Fails to False on anything unparseable: a lock we cannot attribute
    must be treated as somebody else's, because the cost of running two
    readers is a corrupted session and the cost of one false wait is a
    minute.
    """
    hit = _PID.search(str(who or ""))
    if not hit:
        return False
    try:
        return int(hit.group(1)) == os.getpid()
    except (TypeError, ValueError):
        return False


def _age(path):
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def release_if_mine(path=None):
    path = _path(path)
    """Drop the lock, but only if this process is the one holding it.

    ---- 3 August 2026 ----
    Added for the collector's second-Ctrl+C exit. os._exit() skips every
    `with` block, so the reader lock would survive the process and the
    next run would be refused by a pid that no longer exists -- the same
    outage the self-detection bug caused, arriving by a different road.

    Only removes a lock this process wrote. A lock belonging to a real
    second reader is left exactly where it is.

    Returns True if a lock was removed. Never raises.
    """
    try:
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8") as handle:
            who = handle.read().strip()
        if not _is_me(who):
            diagnostic("[LOCK] Leaving the lock alone -- it belongs to "
                       f"{who or 'another process'}.")
            return False
        os.remove(path)
        diagnostic("[LOCK] Released on the way out.")
        return True
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[LOCK] Could not release {path}: {exc}")
        return False


def held_by_another(path=None):
    path = _path(path)
    """(True, description) when a live reader is already running.

    Fails OPEN. If the lock cannot be read for any reason the answer is
    "no", because a filesystem oddity must not stop the night's work.
    """
    try:
        if not os.path.exists(path):
            return False, ""
        age = _age(path)
        if age is None:
            return False, ""
        if age > STALE_AFTER_SECONDS:
            warn(f"[LOCK] A Telegram reader lock is {age / 60:.0f} minutes "
                 f"old -- older than any honest run. Assuming the process "
                 f"is gone and carrying on.")
            return False, ""
        try:
            with open(path, encoding="utf-8") as handle:
                who = handle.read().strip()
        except OSError:
            who = "unknown"

        # ---- A PROCESS IS NOT ANOTHER PROCESS. 3 August 2026. ----
        #
        #   "but just now i opened laptop & started runs. only 1
        #    terminal using, why it gets locked?"    -- operator
        #
        # He was right and this was the whole bug. tools/telegram_catchup
        # takes the lock in __main__ and THEN calls main(), which asks
        # held_by_another() -- so it found the lock IT had just written,
        # one line earlier, and refused:
        #
        #     ALREADY RUNNING: telegram_catchup pid=30928 (started 0 min ago)
        #
        # Same pid, same second. Every run since the lock shipped on
        # 2 August did this: took the lock, refused itself, exited 0.
        # tools/nightly.py reported it as "ok telegram 0.0 min" and moved
        # on, so the Monday it was supposed to protect opened with
        # nothing read since Sunday night -- the exact outage this file's
        # own docstring says a lock must never cause.
        #
        # The lock names its owner. Reading it costs nothing.
        if _is_me(who):
            diagnostic("[LOCK] The lock on file belongs to this process. "
                       "Not a second reader.")
            return False, ""

        return True, f"{who} (started {age / 60:.0f} min ago)"
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[LOCK] Could not check {path}: {exc}")
        return False, ""


class TelegramReaderLock:
    """with TelegramReaderLock("telegram_catchup"): ...

    Best-effort throughout. Failing to WRITE a lock is never a reason
    to refuse to read Telegram -- the lock exists to stop a second
    reader, not to become a third way the first one can fail.
    """

    def __init__(self, who, path=None):
        path = _path(path)
        self.who = who
        self.path = path
        self.taken = False

    def __enter__(self):
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(f"{self.who} pid={os.getpid()} "
                             f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.taken = True
        except Exception as exc:                            # noqa: BLE001
            diagnostic(f"[LOCK] Could not write {self.path}: {exc}")
        return self

    def __exit__(self, *exc):
        if not self.taken:
            return False
        try:
            os.remove(self.path)
        except OSError:
            pass
        return False
