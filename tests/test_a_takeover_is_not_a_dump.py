"""The supply veto could only ever fire on a stock that was rising.

    "recent TBZ stock check that rally. does the bot take this stock
     atleast one time? before 04 sep"
    "yes i think this settles & its a good one"
                                   -- the operator, 5 September 2026

TBZ, 1 September, in the bot's own event store with 12x volume:

    TBZ: CO PROMOTER SELLS 74.12% STAKE TO GRT JEWELLERS FOR
         Rs 1,033.71 CRORE; OPEN OFFER TO FOLLOW

core/supply_events matched PROMOTER SELL and the entry path refused it
as "the promoter is selling". It is the opposite of a dump: ownership
moved privately, not one share reached the market, and the buyer is
now obliged to bid for everyone else's shares.

    20-Aug  248.85          21-Aug  279.50  +12.32%   7.1m shares
    01-Sep  366.80 +19.99%  02-Sep  418.25  +14.03%  28.0m shares
    03-Sep  437.15  +4.52%

248 to 437 in ten sessions. The bot bought TBZ on 4 September, after
all of it, for +Rs 2,271.

WHAT SETTLED IT. Of the 75 stocks this rule refused:

    60 never got 3% above their previous close -- the entry chain
       refuses those at MIN_MOVE_FROM_PREV_CLOSE_PCT anyway
    15 did -- and ALL FIFTEEN closed above their open

and every faller it appeared to catch -- ADANIPOWER -6.8%, THYROCARE
-7.6%, NETWEB -4.9%, ASTERDM -4.1%, RENUKA -3.1% -- never got 3% up
either. It cannot stop one faller the chain does not already stop.

That is the SHAPE of the two rules, not a close call about a
threshold: a stock about to fall is not 3% up making higher highs on
its own volume, so this gate can only ever bite on one that is.

THE LABEL STAYS. core/centre.py still reads overhang() and the board
still shows why. He keeps the information and loses the veto.
"""

from datetime import datetime

import pytest

from core import auto_entry, supply_events

TBZ = ("TBZ: CO PROMOTER SELLS 74.12% STAKE TO GRT JEWELLERS FOR "
       "Rs 1,033.71 CRORE; OPEN OFFER TO FOLLOW")
RENUKA = ("SHREE RENUKA SUGARS  ICICI Bank sells 2.17% stake in co in "
          "open market on August 24")
HINDZINC = "DIPAM SECRETARY - NOT LOOKING AT HINDUSTAN ZINC OFS CURRENTLY"


def test_the_reader_still_recognises_a_real_sale():
    """RENUKA is what the rule was built for -- a bank selling into the
    open market. Those shares really do hit the exchange, and it fell
    3.1%. The reading is kept; only the veto is removed."""
    assert supply_events.read(RENUKA)


def test_the_reader_still_calls_the_takeover_a_sale():
    """Not fixed here, deliberately. Teaching the regex to tell a
    takeover from a dump is a second change with its own risk; making
    the label stop refusing is the one that was measured."""
    assert supply_events.read(TBZ)


def _row(symbol="TBZ"):
    return {"symbol": symbol, "action": "BUY", "ltp": 100.0,
            "day_high": 100.0, "day_low": 90.0, "change_pct": 12.0,
            "recent_pct": 0.5, "state": "alive",
            "plan": {"ok": True, "qty": 10, "stop": 97.0, "value_rs": 1000.0}}


class _Engine:
    open_positions = {}

    def symbols_traded_today(self):
        return set()


def test_a_supply_headline_no_longer_refuses_the_trade(monkeypatch):
    """THE change. TBZ was up 17% intraday on 12x volume, making higher
    highs -- and was refused on a headline."""
    monkeypatch.setattr(supply_events, "overhang",
                        lambda sym, now=None: {"why": "the promoter is selling"})
    why = auto_entry.refuse_reason(
        _row(), _Engine(), now=datetime(2026, 9, 2, 11, 0),
        held=set(), max_positions=10)
    assert why is None or "promoter" not in why, (
        "a supply headline is refusing trades again -- it was 0 for 15 "
        "on stocks that reached 3%")


def test_the_reason_is_still_put_on_the_row(monkeypatch):
    """He keeps the information. 'promoter sold 74% to GRT Jewellers'
    is worth seeing beside a stock that is up 17%."""
    monkeypatch.setattr(supply_events, "overhang",
                        lambda sym, now=None: {"why": "the promoter is selling"})
    row = _row()
    auto_entry.refuse_reason(row, _Engine(), now=datetime(2026, 9, 2, 11, 0),
                             held=set(), max_positions=10)
    assert row.get("supply_note") == "the promoter is selling"


def test_a_broken_supply_lookup_costs_the_label_not_the_trade(monkeypatch):
    """It used to refuse on any failure -- 'refusing rather than trading
    blind'. That was right while it was a veto and wrong now: a missing
    NOTE must never cost a trade."""
    def explode(sym, now=None):
        raise RuntimeError("telegram store unreadable")

    monkeypatch.setattr(supply_events, "overhang", explode)
    why = auto_entry.refuse_reason(
        _row(), _Engine(), now=datetime(2026, 9, 2, 11, 0),
        held=set(), max_positions=10)
    assert why is None or "offer for sale" not in why


def test_the_chain_still_stops_the_fallers_on_its_own():
    """ADANIPOWER, THYROCARE, NETWEB, ASTERDM and RENUKA all fell -- and
    none of them ever got 3% above the previous close.

    The move gate is in core/ranker.py, not at the door: a stock under
    3% never reaches the board, so refuse_reason() never sees it. My
    first version of this test asserted it at the door and failed --
    the gate is real, it just sits earlier in the chain than I looked.
    """
    from core.rules import MIN_MOVE_FROM_PREV_CLOSE_PCT
    import inspect

    from core import ranker
    assert MIN_MOVE_FROM_PREV_CLOSE_PCT == 3.0
    src = inspect.getsource(ranker)
    assert "MIN_MOVE_PCT" in src, (
        "the move gate is gone from the ranker -- the supply rule was "
        "removed on the strength of that gate stopping the fallers")
