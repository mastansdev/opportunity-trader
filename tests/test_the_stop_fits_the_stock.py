"""
==========================================================
One stop width for 1,312 different stocks
==========================================================

    "do not fix the 2.5% for every stock. as u suggested
     volatility-scaled stop may be best suited option & depending on
     other factors the entry can be triggered as early as 09:15 ...
     incase we wait for 09:30 orb confirmation the most of the run
     would have missed or in some great events on the stock will not
     give the opportunity to enter at all as stocks lock at circuits"
                                -- operator, 18 August 2026

TWO CHANGES, ONE CAUSE. Both came out of core/signal_journal.py
scoring 12,036 recorded signals against the candles that followed
them -- the first time anything in this repo had read that journal
back.

1. THE STOP WAS THE SAME WIDTH FOR EVERY STOCK
   At a flat 2.5% the stop was hit BEFORE the move on 46.3% of
   signals carrying evidence and 27.8% of those carrying none.
   Evidence-backed names move further both ways (best +1.73% against
   +1.25%, worst -3.01% against -2.20%), so one number that is merely
   tight on a quiet stock is a guaranteed exit on a live one.

   The ATR machinery already existed and read ONE-MINUTE candles:

       symbol       1-min ATR   x0.8 stop     daily ATR
       NAVINFLUOR      0.34%       0.27%         3.46%
       POLYCAB         0.23%       0.18%         1.79%
       ICIL            0.23%       0.19%         4.99%

   Arming it as it stood would have set quarter-percent stops -- ten
   times TIGHTER than the number it was meant to improve on. Right
   machinery, wrong clock, and nothing in the code said which clock
   it assumed.

   Measured on identical signals before it was armed:

       flat 2.5% (old)     evidence stopped 46.3%   result -1.07%
       daily ATR x1.0      evidence stopped 27.8%   result -0.74%
       daily ATR x1.2      evidence stopped 18.5%   result -0.36%

2. THE 09:15 LANE ONLY OPENED FOR RESULTS
   auto_entry.early_rows() exists so a stock with a known reason does
   not have to wait for the 09:30 range. Its admission test was
   _is_pre_graded() -- overnight RESULTS GRADES and nothing else. An
   order win or a business update filed at 20:00 was not a grade, so
   it waited. The journal's best-performing refusal bucket of all was
   "filed today, numbers not read yet": n=91, +0.25% at the close and
   +3.53% at its best, against +1.22% for stocks with no event.

HONEST LIMITS, stated here so they are not lost: n=54 evidence
signals at minute resolution over two sessions, because
tools/collector.py stopped filling data/history_candles.db on
31 July. And every stop variant is still NEGATIVE on average -- a
wider stop cuts the loss, it does not manufacture a profit.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import datetime

import pytest

from core import atr, auto_entry
from core.engine import Engine

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    atr.reset_daily_cache()
    yield
    atr.reset_daily_cache()


# ---- FIXED_STOP_PCT IS OFF AGAIN. 29 August 2026. ----
#
# It was set to 2.0 that morning and reverted the same day: chosen and
# measured on one eight-session window, and worse than this rule on
# eleven sessions it had never seen. VOLATILITY_SCALED_STOP is live
# and this file is what proves it.
#
# Pinned to None here anyway, because the dial is one line from being
# set again and these tests must keep proving the rule underneath it.
@pytest.fixture(autouse=True)
def _scaled_stop(monkeypatch):
    from core import engine as engine_module
    monkeypatch.setattr(engine_module, "FIXED_STOP_PCT", None)


def _engine():
    """An Engine shell -- _hard_stop_pct touches no other state."""
    return Engine.__new__(Engine)


# ---------------------------------------------------------------
# THE WIDTH FITS THE STOCK
# ---------------------------------------------------------------

def test_a_calm_stock_and_a_wild_one_do_not_get_the_same_stop(
        monkeypatch):
    reading = {"CALMCO": 1.5, "WILDCO": 4.5}
    monkeypatch.setattr(atr, "daily_atr_pct",
                        lambda s, **kw: reading.get(s))
    monkeypatch.setattr("core.engine.daily_atr_pct",
                        lambda s, **kw: reading.get(s))
    engine = _engine()
    calm = engine._hard_stop_pct("CALMCO")
    wild = engine._hard_stop_pct("WILDCO")
    assert wild > calm, "the whole point of the change"

    # ---- DERIVED, NOT HARDCODED. 22 August 2026 ----
    # These read 0.018 and 0.054 -- 1.2 x the two ATRs. The multiple
    # moved to 2.0 on a measurement over 16,186 signals (x1.2 lost
    # 0.414% and stopped out 15.1%; x2.0 lost 0.256% and stopped out
    # 8.0%, flattening there), and this failed for describing the old
    # constant rather than the rule.
    #
    # What the test is FOR is that a wild stock gets a wider stop than
    # a calm one, in proportion to its own range. Pinning the arithmetic
    # to the config keeps that true at any multiple, so a future
    # measurement does not have to edit a test to land.
    from config import DAILY_ATR_STOP_MULT
    from core.rules import MAX_STOP_DISTANCE_PCT

    def want(atr_pct):
        return min(DAILY_ATR_STOP_MULT * atr_pct,
                   MAX_STOP_DISTANCE_PCT) / 100

    assert calm == pytest.approx(want(1.5), abs=1e-6)
    assert wild == pytest.approx(want(4.5), abs=1e-6)

    # ---- THE CEILING BINDS AT x2.0, AND THAT IS INTENDED ----
    # A 4.5% ATR stock asks for 9% at the new multiple and is held to
    # MAX_STOP_DISTANCE_PCT (6%). The 16,186-signal measurement that
    # chose 2.0 was run WITH this ceiling in place, so the improvement
    # it found is the improvement this code delivers -- the cap is not
    # a surprise the number did not account for.
    assert wild == pytest.approx(MAX_STOP_DISTANCE_PCT / 100, abs=1e-6)


def test_an_unmeasurable_stock_falls_back_to_the_flat_number():
    """A stop derived from a volatility nobody measured is worse than
    an honestly flat one."""
    from config import HARD_STOP_FROM_ENTRY_PCT
    engine = _engine()
    assert engine._hard_stop_pct("NEVERLISTEDCO") == pytest.approx(
        HARD_STOP_FROM_ENTRY_PCT)


def test_a_silly_reading_is_clamped_at_both_ends(monkeypatch):
    """A stock whose range reads 0.2% must not get a 0.24% stop, and
    one reading 9% must not get a 10.8% one."""
    from core.rules import MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT
    engine = _engine()

    monkeypatch.setattr("core.engine.daily_atr_pct", lambda s, **kw: 0.2)
    assert engine._hard_stop_pct("X") == pytest.approx(
        MIN_STOP_DISTANCE_PCT / 100.0)

    monkeypatch.setattr("core.engine.daily_atr_pct", lambda s, **kw: 9.0)
    assert engine._hard_stop_pct("X") == pytest.approx(
        MAX_STOP_DISTANCE_PCT / 100.0)


def test_the_two_constants_that_share_a_name_are_not_confused():
    """config.MIN_STOP_DISTANCE_PCT is 0.01, a FRACTION.
    core/rules.MIN_STOP_DISTANCE_PCT is 0.75, a PERCENT.
    Reading rules' value as a fraction puts the floor at 75% of price,
    which is not a stop."""
    import config
    from core import rules
    assert config.MIN_STOP_DISTANCE_PCT < 1
    assert rules.MIN_STOP_DISTANCE_PCT > 1 - 0.5
    engine = _engine()
    assert engine._hard_stop_pct("NEVERLISTEDCO") < 0.10, (
        "the stop is more than a tenth of the price -- units are crossed")


def test_it_reads_real_stocks_off_the_daily_store():
    """Against the actual bhavcopy store, not a stub. If daily bars
    stop arriving this fails rather than quietly flattening every
    stop back to 2.5%."""
    calm = atr.daily_atr_pct("POLYCAB")
    wild = atr.daily_atr_pct("ICIL")
    assert calm and wild, "the daily store answered nothing"
    assert wild > calm


def test_a_thin_history_is_refused_rather_than_averaged():
    """A two-bar 'ATR' on a fresh listing is a number, not a
    measurement."""
    assert atr._atr_pct_from([(10.0, 9.0, 9.5)] * 3) is None
    assert atr._atr_pct_from([]) is None
    assert atr._atr_pct_from(None) is None


def test_the_reading_never_raises_on_a_broken_store():
    assert atr.daily_atr_pct("X", db_path="no-such-file.db") is None
    assert atr.daily_atr_pct(None) is None
    assert atr.daily_atr_pct("") is None


def test_a_replay_cannot_read_tomorrows_volatility():
    """as_of bounds the query. Without it, replaying a past morning
    would size its stops on volatility that had not happened yet."""
    src = (ROOT / "core" / "atr.py").read_text(encoding="utf-8")
    body = src[src.find("def daily_atr_pct"):src.find("def _atr_pct_from")]
    assert "date <= ?" in body


# ---------------------------------------------------------------
# THE STOP IS STILL HARD. ONLY ITS WIDTH MOVED.
# ---------------------------------------------------------------

def test_the_two_questions_stay_separate():
    """THE LINE THAT MUST NOT MOVE, restated 29 August 2026.

    Whether the stop TRAILS and how WIDE it starts are two questions,
    and one flag was answering both. That was the whole point of this
    test -- and asserting ENABLE_BOT_TRAILING_STOP is False was the
    wrong way to protect it, because it made the two INSEPARABLE in
    the opposite direction: the trail could never be reconsidered
    without this failing.

    On 29 August the trail went back on, to be measured forward in
    paper against stocks fading into the close. The coupling then
    showed itself immediately: turning it on took the entry width
    onto a one-minute ATR under a 1% floor, collapsing every stop to
    1.00% on names whose daily range is near 3.9%, and tripling every
    position. _atr_entry_sizing now decides the width FIRST.

    So this asserts the independence rather than either value. Flip
    the trail and the width must not move.
    """
    import config
    import core.engine as engine_module
    from core.engine import Engine, LONG

    assert config.VOLATILITY_SCALED_STOP is True

    widths = {}
    for trail in (False, True):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", trail)
            mp.setattr(engine_module, "compute_atr",
                       lambda candles, period: 0.5)
            mp.setattr(engine_module, "daily_atr_pct", lambda s, **kw: 3.9)
            mp.setattr(Engine, "_risk_sized_qty", lambda self, *a, **k: 75)
            engine = Engine()
            engine.candle_engine.last_n_closed = lambda symbol, n: [
                {"high": 661.0, "low": 659.0, "close": 660.0}] * n
            stop, _t, _q = engine._atr_entry_sizing("X", LONG, 660.0)
            widths[trail] = round(660.0 - stop, 6)
    assert widths[True] == widths[False], (
        f"the trail flag moved the entry width again: {widths}")

    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _atr_entry_sizing"):]
    body = body[:body.find("return stop_price")]
    assert body.find("if VOLATILITY_SCALED_STOP:") <         body.find("elif ENABLE_BOT_TRAILING_STOP:"), (
        "the width must be decided before the trail flag is consulted")


def test_turning_the_switch_off_restores_the_flat_number(monkeypatch):
    from config import HARD_STOP_FROM_ENTRY_PCT
    monkeypatch.setattr("core.engine.VOLATILITY_SCALED_STOP", False)
    monkeypatch.setattr("core.engine.daily_atr_pct", lambda s, **kw: 4.0)
    assert _engine()._hard_stop_pct("X") == pytest.approx(
        HARD_STOP_FROM_ENTRY_PCT)


# ---------------------------------------------------------------
# THE 09:15 LANE NOW OPENS FOR EVIDENCE, NOT ONLY FOR GRADES
# ---------------------------------------------------------------

def _mover(symbol="NEWSCO", **kw):
    """A mover the real gates can actually judge.

    `volume` and `ltp` are what core/ranker.volume_ratio() reads, and
    _liquid below supplies the ADV it is divided by. Feeding the gate
    a field it does not read would make every test below pass for the
    wrong reason -- the first version of this file did exactly that
    and three tests failed closed on a missing ADV.
    """
    row = {"symbol": symbol, "ltp": 100.0, "change_pct": 2.0,
           "day_high": 100.0, "day_low": 97.0, "open": 98.0,
           "volume": 300_000}                     # 3 cr traded
    row.update(kw)
    return row


@pytest.fixture
def _liquid(monkeypatch):
    """Every test symbol has a 1-crore normal day, so a 3-crore
    session reads as 3.0x and clears MIN_VOLUME_RATIO."""
    monkeypatch.setattr("core.liquidity.adv", lambda s: 1.0)
    return True


def _early(movers, evidence_of=None, monkeypatch=None):
    return auto_entry.early_rows(
        movers, now=datetime(2026, 8, 18, 9, 20),
        plan_of=lambda m: {"ok": True, "qty": 10, "stop": 97.0,
                           "target": 106.0},
        evidence_of=evidence_of)


def test_a_stock_with_news_and_no_results_grade_gets_in(monkeypatch,
                                                        _liquid):
    """THE GAP HE DESCRIBED. An order win filed at 20:00 is not a
    results grade, so this lane could not see it and the stock waited
    for the 09:30 range -- which on a stock that opens and locks is
    not a delay, it is the whole trade."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded", lambda s: False)
    rows = _early([_mover()], evidence_of=lambda s: "order_win")
    assert rows, "a stock with a published reason still had to wait"
    assert rows[0]["symbol"] == "NEWSCO"
    assert "order_win" in rows[0]["why"]
    assert rows[0]["early_source"] == "evidence"


def test_a_stock_with_neither_is_still_refused(monkeypatch, _liquid):
    """Widening the door is not removing it."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded", lambda s: False)
    assert _early([_mover()], evidence_of=lambda s: None) == []
    assert _early([_mover()], evidence_of=None) == []


def test_a_parsed_grade_still_outranks_raw_evidence(monkeypatch,
                                                    _liquid):
    """An overnight grade has been READ. A filing at 09:16 has only
    been NOTICED. Both get in; the parsed one sorts first."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded",
                        lambda s: s == "GRADEDCO")
    monkeypatch.setattr(auto_entry, "_graded_cache",
                        {"map": {"GRADEDCO": {"grade": "EXCELLENT"}},
                         "at": 0.0})
    rows = _early([_mover("NEWSCO"), _mover("GRADEDCO")],
                  evidence_of=lambda s: "filing")
    assert [r["symbol"] for r in rows] == ["GRADEDCO", "NEWSCO"]


def test_every_other_early_gate_still_applies_to_it(monkeypatch,
                                                    _liquid):
    """Widening the door does not widen the room. Volume, making
    highs and up-on-the-day are unchanged and apply to both kinds."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded", lambda s: False)
    evidence = lambda s: "order_win"                      # noqa: E731

    falling = _mover(change_pct=-1.0)
    assert _early([falling], evidence_of=evidence) == [], "bought a faller"

    faded = _mover(day_high=110.0, day_low=99.0, ltp=100.0)
    assert _early([faded], evidence_of=evidence) == [], (
        "bought one that had already run and come back")

    quiet = _mover(volume=5_000)          # 0.05 cr against a 1 cr day
    assert _early([quiet], evidence_of=evidence) == [], (
        "bought a reason nobody was trading")


def test_the_window_is_unchanged(monkeypatch, _liquid):
    """09:15 to 09:30. This lane exists to beat the range, not to
    replace every entry of the day."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded", lambda s: False)
    got = auto_entry.early_rows(
        [_mover()], now=datetime(2026, 8, 18, 11, 0),
        plan_of=lambda m: {"ok": True, "qty": 10, "stop": 97.0},
        evidence_of=lambda s: "order_win")
    assert got == []


def test_a_broken_evidence_lookup_never_kills_the_lane(monkeypatch,
                                                       _liquid):
    """An early lane that throws is an early lane that silently
    becomes the old one."""
    monkeypatch.setattr(auto_entry, "_is_pre_graded",
                        lambda s: s == "GRADEDCO")
    monkeypatch.setattr(auto_entry, "_graded_cache",
                        {"map": {"GRADEDCO": {"grade": "GREAT"}},
                         "at": 0.0})

    def _explode(symbol):
        raise RuntimeError("news store is locked")

    rows = _early([_mover("GRADEDCO")], evidence_of=_explode)
    assert [r["symbol"] for r in rows] == ["GRADEDCO"]


def test_the_board_hands_the_lane_the_engines_own_answer():
    """One place knows what is behind a stock this morning --
    _capture_reason(). A second opinion would drift from it."""
    src = (ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert "evidence_of=self._evidence_for" in src
    body = src[src.find("def _evidence_for"):src.find("def _mtf_for")]
    assert "_capture_reason" in body
    assert "had_reason" in body


def test_auto_entry_still_holds_no_engine_reference():
    """early_rows() is HANDED evidence_of, mtf_of, plan_of and adv_of.
    A function on the entry path that reaches into the Engine itself
    is one two people have to keep in step.

    ---- SLICE THE FUNCTION, NOT THE NEIGHBOURHOOD. 19 Aug 2026 ----
    This read from "def early_rows" to whatever def it happened to
    know came next, and two helpers were later added in between -- one
    of them handed the engine deliberately, to write the journal. The
    invariant was never "this word may not appear nearby".
    """
    import inspect

    from core import auto_entry

    code = chr(10).join(
        ln for ln in inspect.getsource(auto_entry.early_rows).splitlines()
        if not ln.lstrip().startswith("#"))
    assert "_capture_reason" not in code
    assert "evidence_of" in code
