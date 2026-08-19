"""
==========================================================
The same stock, announced again at a worse price
==========================================================

    "6 total alerts recvd as of now . & all were given at random
     prices as today multiple restarts happened & the 1st time alerts
     may be gives opportunity rather than raise - fall back & random
     entry."
                                -- operator, 19 August 2026

He is exactly right, and the log proves it. 19 August, one session:

    MGL         09:31 at 1156.30   and again 11:01 at 1151.90
    IGL         09:33 at  154.62   and again 11:01 at  155.20
    BLACKBUCK   10:20 at  606.50   and again 11:01 at  614.40
    KIRLOSBROS  10:27 at 1954.50   and again 11:01 at 1952.40
    RAILTEL     09:30              and again 11:02, and 11:06

THE FIRST ALERT IS THE OPPORTUNITY. A re-announcement an hour later
is the same idea at a price the move has already left behind, and
nothing on the card said it was a repeat -- so six alerts looked like
six findings.

WHY IT HAPPENED
Engine._manual_alerts_seen is the set that stops a stock being
announced twice. export_session_counters() has carried it since
29 July and the PERIODIC save never passed it -- only the shutdown
save did. So every kill, every crash and every restart lost it, and
data/session_state.json proved it: "session_counters": {}.

A hard kill skips the shutdown save entirely, which is exactly how
today's restarts were done.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.engine import Engine

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _engine():
    eng = Engine.__new__(Engine)
    eng.manual_alerts = []
    eng._manual_alerts_seen = set()
    eng._rotations_today = 0
    eng._news_alerted = set()
    eng.on_alert = None
    return eng


# ---------------------------------------------------------------
# THE SET HAS TO CROSS A RESTART
# ---------------------------------------------------------------

def test_a_stock_announced_before_the_restart_is_not_announced_after():
    """THE WHOLE BUG. MGL at 09:31 and again at 11:01 was one idea
    presented as two."""
    morning = _engine()
    morning._manual_alert("MGL", "ranked-buy", "MGL BUY 35 @ 1156.30")
    saved = morning.export_session_counters()

    after = _engine()
    after.load_session_counters(saved)
    after._manual_alert("MGL", "ranked-buy", "MGL BUY 34 @ 1151.90")
    assert after.manual_alerts == [], (
        "the restart announced MGL a second time, at a worse price")


def test_a_stock_it_had_not_reached_yet_still_gets_through():
    """The control. A dedupe that silences everything would pass the
    test above and take the whole alert lane down with it."""
    morning = _engine()
    morning._manual_alert("MGL", "ranked-buy", "MGL BUY 35 @ 1156.30")

    after = _engine()
    after.load_session_counters(morning.export_session_counters())
    after._manual_alert("RAILTEL", "ranked-buy", "RAILTEL BUY 208 @ 288.50")
    assert len(after.manual_alerts) == 1


def test_the_same_stock_on_a_DIFFERENT_kind_is_a_different_thing():
    """A ranked buy and a trailing-stop warning about the same stock
    are two different messages and both are his to see."""
    after = _engine()
    after._manual_alert("MGL", "ranked-buy", "MGL BUY 35")
    after._manual_alert("MGL", "TRAIL", "MGL has fallen back")
    assert len(after.manual_alerts) == 2


def test_a_broken_saved_set_never_stops_the_restart():
    """Bad state must mean a fresh start, not a bot that will not
    boot."""
    eng = _engine()
    for junk in (None, {}, {"manual_alerts_seen": None},
                 {"manual_alerts_seen": "not-a-list"}):
        eng.load_session_counters(junk)
    eng._manual_alert("MGL", "ranked-buy", "MGL BUY 35")
    assert len(eng.manual_alerts) == 1


# ---------------------------------------------------------------
# AND IT HAS TO BE WRITTEN OFTEN ENOUGH TO SURVIVE A KILL
# ---------------------------------------------------------------

def test_the_heartbeat_save_carries_the_alert_set():
    """It was written ONLY by the shutdown save, and a hard kill skips
    that -- which is how every restart on 19 August lost it."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert code.count("session_counters=engine.export_session_counters()") >= 2, (
        "only one save passes the alert set -- the periodic one is "
        "missing it again and a kill will re-announce the morning")


def test_the_restore_is_reported_out_loud():
    """If this line ever reads 0 after a mid-session restart, the
    persistence is broken and he should not have to find that out
    from a duplicate alert on his phone."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "already announced today" in src


def test_the_set_cannot_leak_into_tomorrow():
    """A stock announced today must be announceable again tomorrow.
    core/state_store.py's load() refuses any file not dated today."""
    src = (ROOT / "core" / "state_store.py").read_text(encoding="utf-8")
    assert "saved_date == today" in src
