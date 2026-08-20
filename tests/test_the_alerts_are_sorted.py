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


def _push(desk, symbol, score=None):
    """A message shaped the way core/auto_entry.take() now builds one.

    The first version of this helper injected "[score 30.7]" itself,
    which take() had stopped doing -- so the test failed on a string
    the fixture had put there. A double that drifts from the thing it
    doubles tests nothing.
    """
    desk.push({"symbol": symbol, "kind": "ranked-buy", "at": "11:01:02",
               "message": (f"{symbol} BUY -- up 4% on 6x volume"
                           f"{chr(10)}qty 10{chr(10)}entry 100"
                           f"{chr(10)}target 110{chr(10)}exit 97")})
    return desk.sent[-1]["text"]


def test_the_card_shows_no_score_and_no_ranking(desk):
    """---- THESE ASSERTIONS WERE INVERTED. 19 August 2026. ----

    Earlier the same day the score went ON the card so he could tell a
    strong pick from a weak one. He asked what use it was to a trader:

        "i don't want to see ranking by bot"
        "whats the use for trader on seeing the score ?"

    None, yet -- it is an internal number on no scale, and nothing has
    shown a higher one leads to a better outcome. The 8 August replay
    pointed the other way. It rides on the routing record now, where
    that question can be asked, and off the thing he reads at speed.
    """
    text = _push(desk, "RAILTEL", 30.7)
    assert "score" not in text.lower()
    assert "BEST of" not in text
    assert "#1 of" not in text


def test_the_time_leads_the_card(desk):
    """The first field he named. A card with no time cannot be told
    from a repeat."""
    desk.push({"symbol": "MGL", "kind": "ranked-buy", "at": "11:01:02",
               "message": "MGL BUY -- a reason"})
    assert desk.sent[-1]["text"].startswith("*11:01  MGL")


def test_the_score_still_rides_on_the_routing_record():
    """Off the card is not out of the system -- otherwise the question
    "does a higher score pay" could never be answered."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    assert src.count('"score": _num(row.get("score"))') >= 3, (
        "a routing row is not carrying the score it was sorted by")


# ---------------------------------------------------------------
# THE CARD USES WHAT THE BOARD ALREADY KNOWS
# ---------------------------------------------------------------
#
#     "why you are not using complete resources & expecting spoon
#      feeding by me ?"           -- operator, 19 August 2026
#
# core/ranker.py puts about twenty-five computed facts on every row.
# The alert carried the reason, a quantity and two prices.
# core/tick_ohlc.pressure() -- the order book -- had been read by
# NOTHING since it was written on 17 August.

def _rich_row():
    return {
        "symbol": "BLACKBUCK", "ltp": 626.35, "score": 32.0,
        "why": "up 6.4%, while Logistics is up 0.2%, 7.0x volume",
        "moving": "7.0x volume, holding 82% of its range, up 5.3%",
        "delivery": {"reading": "ACCUMULATION", "pct": 44.2, "avg": 42.2},
        "pressure": {"buy": 120847.0, "sell": 130109.0, "ratio": 0.929,
                     "above_atp": True},
        "headroom_pct": 12.8, "at_circuit": False,
        "mtf_leverage": 2.9, "adv_cr": 10.4,
    }


def test_the_card_carries_delivery_pressure_room_and_movement():
    from core.auto_entry import _alert_lines
    got = " | ".join(_alert_lines(_rich_row(), {"qty": 136}))
    assert "delivery 44.2%" in got and "ACCUMULATION" in got
    assert "book" in got
    assert "82% of its range" in got
    assert "12.8% to the circuit" in got
    assert "MTF 2.9x" in got
    assert "10.4cr" in got


def test_a_reading_AGAINST_the_trade_is_printed_just_as_loudly():
    """An alert that only lists reasons to buy is an advertisement.
    BLACKBUCK's book had more sellers than buyers and the card says
    so, in capitals."""
    from core.auto_entry import _alert_lines
    got = " | ".join(_alert_lines(_rich_row(), {"qty": 1}))
    assert "SELLERS" in got


def test_below_the_average_price_is_said_out_loud():
    from core.auto_entry import _alert_lines
    row = _rich_row()
    row["pressure"] = {"ratio": 2.0, "above_atp": False}
    got = " | ".join(_alert_lines(row, {"qty": 1}))
    assert "BELOW" in got


def test_a_stock_at_its_circuit_is_called_a_queue_not_a_trade():
    from core.auto_entry import _alert_lines
    row = _rich_row()
    row["at_circuit"] = True
    got = " | ".join(_alert_lines(row, {"qty": 1}))
    assert "queue" in got


def test_a_missing_fact_is_omitted_not_filled_with_a_zero():
    """A dash on a card reads as a measurement. Silence does not."""
    from core.auto_entry import _alert_lines
    got = _alert_lines({"symbol": "X"}, {"qty": 1})
    assert got == []


def test_it_never_raises_on_a_malformed_row():
    from core.auto_entry import _alert_lines
    for row in ({"delivery": "not-a-dict"}, {"pressure": []},
                {"pressure": {"ratio": 0}}, {"headroom_pct": "x"},
                {"mtf_leverage": None}):
        assert isinstance(_alert_lines(row, {}), list)


def test_nothing_on_the_card_is_recomputed():
    """Every number is lifted off the row the ranker built, so the
    card and the board cannot disagree."""
    src = (ROOT / "core" / "auto_entry.py").read_text(encoding="utf-8")
    body = src[src.find("def _alert_lines"):src.find("def refuse_reason")]
    for banned in ("adv(", "volume_ratio(", "daily_atr_pct(", "score +="):
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

# ---------------------------------------------------------------
# WHO DECIDES HOW MANY OPPORTUNITIES A DAY HAS
# ---------------------------------------------------------------
#
#     "why only 25 ? who decideds the markets"
#     "increase top=6 so i don't miss ranker approved setups"
#                                 -- operator, 20 August 2026
#
# Both numbers were mine. On 20 August the alert cap withheld NINE of
# 34 qualified alerts, and on the 19th the list cap discarded NINE of
# 15 ranker-approved setups before the next filter even saw them.
#
# They are regression brakes now, sitting far above any honest day,
# and the gates upstream decide what he sees.

def test_the_alert_ceiling_is_a_brake_not_a_view_on_the_market():
    from core.telegram_desk import PUSH_MAX_PER_DAY
    assert PUSH_MAX_PER_DAY >= 100, (
        "the ceiling is back down where it withholds real setups")


def test_the_ranked_list_is_bigger_than_a_busy_day_survives():
    """15 survived every gate on 19 August. The list may not be the
    thing that decides what he sees."""
    from core.ranker import RANKED_LIST_SIZE
    assert RANKED_LIST_SIZE >= 20
    import inspect
    from core import ranker
    assert inspect.signature(ranker.rank).parameters["top"].default ==         RANKED_LIST_SIZE


def test_both_are_still_bounded():
    """A brake with no limit is not a brake. A runaway upstream must
    not be able to ring his phone three hundred times or hand the
    board a thousand rows."""
    from core.ranker import RANKED_LIST_SIZE
    from core.telegram_desk import PUSH_MAX_PER_DAY
    assert PUSH_MAX_PER_DAY <= 500
    assert RANKED_LIST_SIZE <= 100


def test_the_plain_breakout_lane_cannot_spend_the_whole_budget(desk):
    """20 August, by lane: 24 plain breakouts against 9 ranked picks,
    sharing one first-come-first-served budget. A quiet-but-good
    morning must not be crowded out by a busy-but-thin one."""
    from core.telegram_desk import PUSH_MAX_UNRANKED_PER_DAY

    for i in range(PUSH_MAX_UNRANKED_PER_DAY + 10):
        desk.push({"symbol": f"BRK{i}", "kind": "alert-only-LONG",
                   "message": f"BRK{i} LONG -- STRUCTURAL_LONG_BREAKOUT"})
    spent = len(desk.sent)

    desk.push({"symbol": "RAILTEL", "kind": "ranked-buy",
               "at": "11:00:00",
               "message": "RAILTEL BUY -- order win, 29x volume"})
    assert len(desk.sent) > spent, (
        "a ranked pick was blocked by the plain-breakout lane's noise")


def test_the_lane_budget_announces_itself_once(desk):
    from core.telegram_desk import PUSH_MAX_UNRANKED_PER_DAY

    for i in range(PUSH_MAX_UNRANKED_PER_DAY + 5):
        desk.push({"symbol": f"B{i}", "kind": "alert-only-LONG",
                   "message": f"B{i} LONG -- breakout"})
    said = [m for m in desk.sent if "lane" in m["text"]
            or "breakouts today" in m["text"]]
    assert len(said) == 1, "the lane budget went quiet, or nagged"


def test_a_ranked_pick_is_never_counted_against_the_lane_budget(desk):
    from core.telegram_desk import PUSH_MAX_UNRANKED_PER_DAY

    for i in range(PUSH_MAX_UNRANKED_PER_DAY + 20):
        desk.push({"symbol": f"R{i}", "kind": "ranked-buy",
                   "at": "11:00:00",
                   "message": f"R{i} BUY -- a real reason"})
    assert len(desk.sent) >= PUSH_MAX_UNRANKED_PER_DAY + 20, (
        "ranked picks are being charged to the unranked lane")
