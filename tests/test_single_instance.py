"""
==========================================================
One bot at a time -- and the suite may never start one
==========================================================

31 July 2026, after a restart, the operator pasted this:

    [EVENTS] Results and orders are now filed as they arrive...
    [EVENTS] Results and orders are now filed as they arrive...

That line is printed once, on a straight path through main(), with no
loop and no retry. A single process cannot produce it twice. So either
it was pasted twice or two bots were running -- and there was no way
to tell which.

"No way to tell" is not acceptable when the answer decides whether
real orders can be doubled.

WHY TWO BOTS IS A SERIOUS CONDITION
-----------------------------------
Both are wired to the same Dhan account with the same static IP, so
both can place real orders. Worse and quieter: both hold
data/session_state.json in memory and both write it out on shutdown,
so whichever exits LAST silently overwrites the other's book. A
position taken by one can simply disappear.

REFUSES, DOES NOT WARN. A warning at 09:00 scrolls off the screen in
seconds and the thing it precedes is two processes trading one
account.

---- AND THEN THIS FILE STARTED THE SECOND BOT. 14 August 2026. ----

Every test below used to patch main._another_bot_is_already_running,
the port probe that core/single_instance.py replaced on 13 August. The
probe was left in the file, called by nothing. So:

    monkeypatch.setattr(main, "_another_bot_is_already_running", ...)

succeeded -- setattr does not care whether anything calls the name --
main() consulted the REAL guard, found no other bot, and started one.
Inside pytest. The suite sat at 82% for twenty minutes with a live
tick worker and the ranker walking 1,314 symbols, until py-spy showed
main.py:1685 on the stack.

It had passed the day before for the worst possible reason: his
main.py was running, so held_by_another() said True by accident. The
test's result depended on what else was open on the machine.

Two rules come out of that, and they are what this file now enforces:

  1. PATCH THE GUARD THAT main() ACTUALLY CALLS.
  2. A TEST THAT CALLS main() CARRIES A TRIPWIRE, so if the refusal
     ever fails to happen it fails in milliseconds instead of booting
     a bot. See the a_bot_may_not_boot fixture -- and note that every
     patch in it uses raising=True, the default, so a rename fails
     loudly rather than guarding nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

import main
from core import single_instance

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# THE TRIPWIRE
# ---------------------------------------------------------------

@pytest.fixture
def a_bot_may_not_boot(monkeypatch):
    """Mine the path main() takes AFTER the guard.

    Each of these is a module-level name in main.py that a real start
    reaches within a few lines of the refusal point. If the guard does
    not fire, one of them is hit immediately and the test fails with a
    sentence saying so -- instead of pytest running a live bot on his
    Dhan account for as long as the suite lasts.

    raising=True is the default and is deliberate here. If somebody
    renames MasterLoader, this fixture must break at once; a tripwire
    that has quietly stopped covering anything is precisely the fault
    of 14 August.
    """
    def _forbidden(name):
        def _boom(*a, **k):                                # pragma: no cover
            raise AssertionError(
                f"main() reached {name} -- it did NOT refuse. Without "
                f"this tripwire the test suite would now be running a "
                f"live bot.")
        return _boom

    monkeypatch.setattr(main, "MasterLoader", _forbidden("MasterLoader"))
    monkeypatch.setattr(main.dhan_auth, "access_token",
                        _forbidden("dhan_auth.access_token"))


@pytest.fixture
def another_bot_is_up(monkeypatch):
    """The guard main() actually calls, answering yes."""
    monkeypatch.setattr(single_instance, "held_by_another",
                        lambda *a, **k: (True, "pid 4242 since 07:30:11"))


# ---------------------------------------------------------------
# THE REFUSAL
# ---------------------------------------------------------------

def test_it_refuses_rather_than_warning(another_bot_is_up, a_bot_may_not_boot):
    """A second bot must not get past this line."""
    with pytest.raises(SystemExit) as raised:
        main.main()
    assert raised.value.code == 1


def test_it_refuses_before_it_asks_dhan_for_a_token(another_bot_is_up,
                                                    a_bot_may_not_boot):
    """THE ONE THAT WAS NEVER TRUE.

    This file has claimed since it was written that main() does not
    touch Dhan on the way to refusing. It did: the token block was
    ABOVE the guard, so a second bot minted a token it had no right
    to -- and Dhan allows one mint every two minutes, so the process
    being turned away could spend the quota of the one starting
    legitimately. That is the rate-limit refusal he pasted on 13
    August.

    a_bot_may_not_boot mines dhan_auth.access_token, so a token asked
    for at any point in a refused start fails this test by name.
    """
    with pytest.raises(SystemExit) as raised:
        main.main()
    assert raised.value.code == 1


def test_the_guard_is_the_first_thing_main_does():
    """The mechanical half of the test above, read off the source, so
    it holds even for a path the tripwire does not cover."""
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    body = src[src.index("def main():"):]
    code = "\n".join(l for l in body.splitlines()
                     if l.strip() and not l.strip().startswith("#"))

    guard = code.index("single_instance.held_by_another()")
    for later in ("dhan_auth.access_token()", "MasterLoader()",
                  "_preflight()"):
        assert guard < code.index(later), (
            f"{later} runs before the single-bot guard. A bot that is "
            f"about to be refused must do nothing first.")

    first = code.splitlines()[1].strip()
    assert first.startswith("busy, who = single_instance.held_by_another"), (
        f"the first statement in main() is {first!r}, not the guard")


# ---------------------------------------------------------------
# THE TRAP THAT MADE IT POSSIBLE
# ---------------------------------------------------------------

def test_the_dead_port_probe_is_really_gone():
    """Not "unused" -- GONE.

    While _another_bot_is_already_running existed, monkeypatching it
    succeeded and did nothing, and the test that did so booted a bot.
    Deleting it turns that same patch into an AttributeError: loud,
    instant, and impossible to sit at 82% for twenty minutes.
    """
    assert not hasattr(main, "_another_bot_is_already_running"), (
        "the port probe is back. It cannot see a second bot on Windows "
        "(a socket binds over a listening one) and its presence lets a "
        "stale monkeypatch silently guard nothing.")


def test_a_patch_of_the_old_name_now_fails_loudly(monkeypatch):
    """Prove the AttributeError above is what a stale test would get,
    rather than assuming it."""
    with pytest.raises(AttributeError):
        monkeypatch.setattr(main, "_another_bot_is_already_running",
                            lambda *a, **k: True)


def test_the_tripwire_actually_covers_something():
    """a_bot_may_not_boot is only worth having if these names exist and
    are still on the boot path."""
    assert hasattr(main, "MasterLoader")
    assert hasattr(main.dhan_auth, "access_token")

    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "MasterLoader()" in code
    assert "dhan_auth.access_token()" in code


# ---------------------------------------------------------------
# THE STARTUP LINE
# ---------------------------------------------------------------

def test_the_startup_line_carries_the_pid():
    """Seeing the line twice must answer its own question: two
    different pids means two processes, the same pid twice means a
    duplicated paste."""
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    # The phrase also appears in the docstring above, quoting what the
    # operator saw. Match the CALL, not the prose about it.
    assert 'decision(f"[EVENTS] (pid {os.getpid()})' in src, (
        "the one-shot startup line must identify its process, or "
        "seeing it twice is ambiguous again")

    # ---- AND NOW THERE ARE GENUINELY TWO PROCESSES. 3 August 2026 ----
    #
    #   "KEEPING MAIN.PY AS STANDALONE RUN + REMAINING RUN IN OTHER
    #    TERMINALS ...... PLS DO NOT COMBINE MAIN.PY"
    #
    # Telegram now runs in tools/collector.py, in its own terminal. So
    # two pids on two lines is the CORRECT picture rather than the
    # symptom it used to be -- and the collector has to say which one
    # it is for the same reason main.py does.
    collector = (ROOT / "tools" / "collector.py").read_text(
        encoding="utf-8", errors="replace")
    assert "os.getpid()" in collector, (
        "the collector must name its process too -- two terminals is "
        "now the intended layout, and neither line means anything if "
        "you cannot tell which process wrote it")
