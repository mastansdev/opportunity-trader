"""
==========================================================
One main.py, proven by a live pid -- not by a port
==========================================================

    "i'm having 2 terminals only  1 - main.py & 2- py tools/collector.py"
                                -- operator, 13 August 2026

He had two terminals and THREE processes. A main.py started at 07:30
had outlived the window it was launched from, and was still running an
hour later: heartbeat, circuit monitor across 1,314 symbols, ranker
every few seconds. A second complete bot on his Dhan account, with no
window and no way to notice it.

main.py already had a guard against exactly this, and its own comment
is right about why it matters:

    both are wired to Dhan, so a manual BUY on the wrong tab is a
    second real order
    whichever exits LAST silently overwrites the other's book

WHY THE OLD GUARD DID NOT FIRE
------------------------------
It asked "is something listening on port 8000?" -- and on Windows a
second socket CAN bind over a listening one. Unlike Linux, the bind
succeeds, the newer process takes the port, and the probe that ran a
moment earlier saw nothing wrong. So the check passed, the second bot
started, and it even ended up owning the dashboard the operator was
looking at while the first one traded invisibly.

A port is a poor proxy for "is a bot alive" on this platform. It also
answers the wrong question: the dashboard may be down while the engine
runs, which is precisely the state the 07:30 process was in.

WHY NOT core/runlock.py
-----------------------
It solves the same shape of problem for the Telegram reader and it
solves it correctly THERE, but its staleness rule is AGE:

    STALE_AFTER_SECONDS = 2 * 60 * 60

A catch-up runs for minutes, so two hours means "certainly dead". A
trading session runs from 09:15 to 15:30 and beyond -- six hours plus
the after-close review hold. Age would declare a healthy bot stale
halfway through the morning and wave a second one through.

So this asks the only question that is actually decisive: IS THAT PID
STILL RUNNING, and is it still this bot?

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

LOCK_PATH = os.path.join("data", "main_bot.lock")


def _path(path):
    """Resolve the lock location at CALL time, not at import time.

    Every function below takes path=None rather than path=LOCK_PATH.
    That looks like a needless indirection and is not: a default
    argument is bound once, when the def is executed, so

        monkeypatch.setattr(single_instance, "LOCK_PATH", tmp)

    would change the module attribute and change nothing about what
    held_by_another() actually opens. The test would pass while the
    real data/main_bot.lock was still being written.

    That is the same silent no-op that let a test boot a live bot on
    14 August -- a patch that succeeds and covers nothing. Once was
    enough. tests/conftest.py redirects this for the whole suite, and
    it has to bite.
    """
    return LOCK_PATH if path is None else path


def _alive(pid):
    """Is this pid a running process? Never raises.

    Unknown reads as ALIVE. A guard that cannot tell must not be the
    reason a second bot starts -- refusing costs one restart, allowing
    costs a duplicated order.
    """
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process, but it exists.
        return True
    except Exception:                                       # noqa: BLE001
        return True


def _is_this_bot(pid):
    """Is that pid actually a main.py, or has the number been reused?

    Pids are recycled. A stale lock naming 12376 must not block a
    session six hours later because an unrelated program now holds
    that number.

    Without psutil this cannot be checked, and the answer is then YES
    -- see _alive(): unknown must refuse, not allow.
    """
    try:
        import psutil
    except ImportError:
        return True
    try:
        line = " ".join(psutil.Process(pid).cmdline()).lower()
    except Exception:                                       # noqa: BLE001
        return True
    if not line:
        return True
    return "main.py" in line


def read(path=None):
    """{"pid", "since", "alive", "is_bot"} for the lock on disk, or None."""
    path = _path(path)
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read().strip()
    except OSError:
        return None
    pid, since = None, ""
    for part in raw.split():
        if part.startswith("pid="):
            try:
                pid = int(part[4:])
            except ValueError:
                pid = None
        elif part.startswith("since="):
            since = part[6:]
    if pid is None:
        return None
    return {"pid": pid, "since": since, "alive": _alive(pid),
            "is_bot": _is_this_bot(pid)}


def held_by_another(path=None):
    """(True, description) when another LIVE main.py holds the lock.

    False for: no lock, a lock this process wrote, a dead pid, or a pid
    that has been recycled by something that is not this bot.
    """
    held = read(_path(path))
    if held is None:
        return False, ""
    if held["pid"] == os.getpid():
        return False, ""
    if not held["alive"]:
        return False, ""
    if not held["is_bot"]:
        return False, ""
    since = f" since {held['since']}" if held["since"] else ""
    return True, f"pid {held['pid']}{since}"


def claim(path=None):
    """Write this process into the lock. Returns True.

    Best effort: a lock that cannot be written must not stop a session
    starting. The cost is that the NEXT start will not see this one,
    which is the behaviour before this module existed.
    """
    path = _path(path)
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()} "
                         f"since={datetime.now():%Y-%m-%dT%H:%M:%S} "
                         f"argv={os.path.basename(sys.argv[0] or 'main.py')}")
        return True
    except Exception:                                       # noqa: BLE001
        return False


def release(path=None):
    """Drop the lock, but only if this process owns it.

    A lock belonging to a genuinely running second bot is left exactly
    where it is -- removing it would be handing out permission this
    process does not have.
    """
    path = _path(path)
    held = read(path)
    if held is None or held["pid"] != os.getpid():
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False
