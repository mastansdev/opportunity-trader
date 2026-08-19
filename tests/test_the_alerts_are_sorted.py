"""
==========================================================
Random alerts
==========================================================

    "whats the status of bot? alerts are recving but random alerts
     i'm getting , u need to check how the stock alerts are sorting to
     mobile/telegram alerts"
                                -- operator, 19 August 2026

He was right, and "sorting" turned out to be the smaller half. Three
faults, found by reading the live board against what his phone got.

1. THE BEST SETUPS WERE THE ONES BEING FILTERED OUT
   core/position_plan.py refused any trade whose structural stop sat
   closer than MIN_STOP_DISTANCE_PCT. On 19 August:

       RAILTEL     score 30.68   struct stop 0.10%   daily ATR 2.08%
       KIRLOSBROS  score 17.95   struct stop 0.14%   daily ATR 3.72%

   RAILTEL was up 4.0% while its sector FELL 0.7%, on 28.4x its
   normal volume, on a Rs 166.80 crore EPFO work order. Highest score
   of the day by a distance. It never alerted. KTKBANK at 5.5 did,
   because KTKBANK's day low happened to sit far enough away.

   So what reached his phone was filtered by WHERE THE DAY'S LOW
   HAPPENED TO BE. And a stock making highs on a real event is
   exactly the shape whose day low ends up too close -- the filter
   was strongest against the setups it should have been weakest
   against.

   The stop_for() docstring says it takes the tighter of the
   structural and the ATR level. NEITHER CALLER EVER PASSED AN ATR,
   so that half had never run.

2. THE SCORE NEVER REACHED THE PHONE
   core/auto_entry.take() sorts rows by score and then built a
   sentence that dropped it. RAILTEL at 30.7 and KTKBANK at 5.5
   arrived looking identical.

3. WHY A PICK DID NOT ALERT WAS COMPUTED AND BINNED
   take() returns {"symbol","taken","why"} -- its own docstring calls
   it "for the record" -- and main.py discarded the return. The gap
   between "7 kept by the ranker" and "5 buzzed his phone" was
   invisible.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import pathlib

import pytest

from core.position_plan import plan
from core.rules import MAX_STOP_DISTANCE_PCT, MIN_STOP_DISTANCE_PCT

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# 1. A BAD STOP LEVEL IS NOT A BAD TRADE
# ---------------------------------------------------------------

def test_the_railtel_case(monkeypatch):
    """THE EXACT PICK HE LOST. Entry 288.10, day low 287.80 -- a stop
    a tenth of a percent away, which is noise, not a stop."""
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 2.08)
    got = plan(288.1, "BUY", day_low=287.8, symbol="RAILTEL")
    assert got["ok"] is True, "the best setup of the day is still dropped"
    assert got["stop_pct"] == pytest.approx(2.496, abs=0.01)
    assert got["qty"] >= 1


def test_without_a_symbol_it_still_refuses_rather_than_inventing():
    """No symbol means no daily range, and a stop derived from a
    volatility nobody measured is worse than an honest refusal."""
    got = plan(288.1, "BUY", day_low=287.8)
    assert got["ok"] is False
    assert "widen" in got["why"]


def test_a_wild_stock_gets_a_wider_stop_than_a_calm_one(monkeypatch):
    reading = {"CALM": 1.2, "WILD": 4.0}
    monkeypatch.setattr("core.atr.daily_atr_pct",
                        lambda s, **kw: reading.get(s))
    calm = plan(100.0, "BUY", day_low=99.95, symbol="CALM")
    wild = plan(100.0, "BUY", day_low=99.95, symbol="WILD")
    assert wild["stop_pct"] > calm["stop_pct"]


def test_a_stop_that_is_TOO_FAR_still_refuses(monkeypatch):
    """That refusal is a real statement about the trade -- the loss
    would not be small -- and must survive this change."""
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 2.0)
    got = plan(100.0, "BUY", day_low=80.0, symbol="X")
    assert got["ok"] is False
    assert "too far" in got["why"]


def test_the_widened_stop_stays_inside_the_bounds(monkeypatch):
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 40.0)
    got = plan(100.0, "BUY", day_low=99.99, symbol="X")
    if got["ok"]:
        assert got["stop_pct"] <= MAX_STOP_DISTANCE_PCT
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 0.05)
    got = plan(100.0, "BUY", day_low=99.99, symbol="X")
    if got["ok"]:
        assert got["stop_pct"] >= MIN_STOP_DISTANCE_PCT


def test_a_normal_structural_stop_is_left_completely_alone(monkeypatch):
    """The widening is a FALLBACK. A stock whose day low is a real
    level away must keep that level."""
    monkeypatch.setattr("core.atr.daily_atr_pct", lambda s, **kw: 5.0)
    got = plan(100.0, "BUY", day_low=98.0, symbol="X")
    assert got["ok"] is True
    assert got["stop"] == pytest.approx(98.0), "a real level was overridden"


def test_all_three_stop_sites_read_one_definition():
    """core/engine.py sized the entry stop from the daily range on
    18 August, core/trailing_stop.py followed on the 19th, and this
    third site was missed for a day -- the site that decides whether a
    pick reaches his phone at all."""
    from core import atr
    assert hasattr(atr, "scaled_stop_pct")
    src = (ROOT / "core" / "position_plan.py").read_text(encoding="utf-8")
    assert "scaled_stop_pct" in src


def test_the_board_passes_the_symbol_at_both_call_sites():
    """Without it the plan cannot widen anything and silently returns
    to refusing -- which is how this bug would come back."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert src.count("symbol=row.get(\"symbol\")") >= 1
    assert src.count("symbol=mover.get(\"symbol\")") >= 1


# ---------------------------------------------------------------
# 2. THE SCORE REACHES THE PHONE
# ---------------------------------------------------------------

@pytest.fixture
def desk(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x:y")
    import core.telegram_desk as td
    sent = []
    monkeypatch.setattr(td, "_call",
                        lambda m, **kw: (sent.append(kw) or {"ok": True}))
    d = td.TelegramDesk()
    d.sent = sent
    return d


def _push(desk, symbol, score):
    desk.push({"symbol": symbol, "kind": "ranked-buy",
               "message": f"[score {score}] {symbol} BUY 10 @ 100 stop 97"})
    return desk.sent[-1]["text"]


def test_the_alert_carries_the_score_the_ranker_sorted_by(desk):
    assert "[score 30.7]" in _push(desk, "RAILTEL", 30.7)


def test_each_alert_says_where_it_stands(desk):
    """A live stream cannot be sorted -- the 11:00 pick does not exist
    when the 09:31 one is sent. Where it STANDS can be said, and that
    is the difference between a list and a queue."""
    assert "first pick" in _push(desk, "MGL", 25.6)
    assert "BEST of 2" in _push(desk, "RAILTEL", 30.7)
    assert "#3 of 3" in _push(desk, "KTKBANK", 5.5)


def test_the_best_so_far_is_marked_and_a_weak_one_is_not(desk):
    best = _push(desk, "RAILTEL", 30.7)
    weak = _push(desk, "KTKBANK", 5.5)
    assert best.split(chr(10))[0].startswith("***")
    assert not weak.split(chr(10))[0].startswith("***")


def test_an_alert_with_no_score_is_left_exactly_as_it_was(desk):
    """Structural breakouts are not ranked, so they carry no score and
    must not be given a fake standing among ones that are."""
    desk.push({"symbol": "GSFC", "kind": "alert-only-LONG",
               "message": "GSFC LONG would have been entered at 164.10"})
    text = desk.sent[-1]["text"]
    assert "of" not in text.split(chr(10))[1]
    assert "score" not in text.lower()


def test_the_standing_resets_with_the_day(desk):
    _push(desk, "A", 10.0)
    desk._score_day = "1999-01-01"
    assert "first pick" in _push(desk, "B", 1.0)


def test_it_reads_the_score_back_rather_than_recomputing_it():
    """The phone and the board must never disagree about which pick
    was stronger."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    body = src[src.find("def _rank_today"):src.find("def _card")]
    for banned in ("W_VOLUME", "score +=", "sector_lead"):
        assert banned not in body


# ---------------------------------------------------------------
# 3. WHY A PICK DID NOT ALERT IS KEPT
# ---------------------------------------------------------------

def test_main_keeps_what_take_decided():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in src.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "engine.routing_decisions = auto_entry.take(" in code, (
        "the record take() returns is being thrown away again")


def test_the_snapshot_publishes_it():
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert '"routing"' in src
    assert "_safe_routing" in src


def test_WHY_tells_him_a_board_pick_never_alerted():
    """It used to answer "it is on the board" -- true, and not the
    question he was asking."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    body = src[src.find("def _why("):src.find("def _opportunities")]
    assert "routing" in body
    assert "No alert sent" in body
