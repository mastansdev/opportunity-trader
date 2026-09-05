"""
==========================================================
A large order is still a reason a fortnight later
==========================================================

    "why WELCORP is showing Still refused? its a clear winner with
     +3 % right"                -- the operator, 5 September 2026

He was right, and my first measurement was wrong in a way worth
writing down: I banded these orders by RUPEES, found nothing, and
recommended display-only -- after he had already told me rupees is the
wrong yardstick. Re-asked with HIS measure, every stock-day a standing
order would have admitted:

    share of co.   stock-days   moved 3%+ with 2x volume   ran 3% from open
    0-5%                  241                          7             7 of 7
    5-10%                 123                          2             1 of 2
    10-20%                 74                          3             3 of 3
    20-100%               117                         15           15 of 15

Nine DISTINCT days in the top band -- WELCORP on 24 and 27 August and
1 and 3 September, AFCONS, TEJASNET, RAILTEL, INOXWIND twice -- and
every one reached +3% from the open. A day in that band is about four
times more likely to qualify than one in the bottom band.

THE CASE ITSELF. On 3 September WELCORP opened 2,554.7 and closed
2,641.6: up 3.4%, high +4.7%, on 1.7x volume. From the order day it was
+31.7% in ten sessions. The board refused it all three days for
"nothing published, volume 4.1" while a Rs 15,840 crore order worth 47%
of the company sat in this bot's own store.

WHAT THIS CHANGES, AND WHAT IT DOES NOT

  It lets a large standing order count as a PUBLISHED REASON past the
  24-hour staleness window. That is all. The stock still has to be up
  3%, still has to carry the volume, still has to be alive, and still
  has to win one of ten seats. His own read: "here our rule saves us
  without taking all entries too."

  STALE_REASON_HOURS is still 24 and every path in why() above this one
  is untouched. It is asked ONLY when nothing fresher answered, so a
  stock with real news today is never handed an old order instead.

  The bar is the SHARE OF THE COMPANY, not the rupees. A rupee bar
  would admit L&T's Rs 15,000 cr order -- 3% of L&T -- while refusing
  RailTel's Rs 630 cr, which is 27% of RailTel. That is the exact
  mistake this replaces.

  A stock whose size is unknown gets nothing. 500 sizes are on file for
  1,976 symbols, and letting the unmeasured ones in on a rupee bar
  would bring the fault back through the side door.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import tempfile
from datetime import date

import pytest

from core import cause_effect as ce
from core import market_cap


@pytest.fixture()
def caps(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "market_cap.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"at": "2026-09-05T22:00:00",
                   "caps": {"WELCORP": 33636.0,     # 15,840 -> 47%
                            "RAILTEL": 2370.0,      #    630 -> 27%
                            "LT": 528000.0,         # 15,000 ->  3%
                            "NUVAMA": 14099.0}},    # 15,840 -> 112%
                  fh)
    monkeypatch.setattr(market_cap, "STORE", path)
    return path


def _events(rows):
    path = os.path.join(tempfile.mkdtemp(), "stock_events.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, symbol TEXT,"
                 " at TEXT, kind TEXT, value_cr REAL, headline TEXT)")
    for sym, at, kind, val, head in rows:
        conn.execute("INSERT INTO events (symbol, at, kind, value_cr,"
                     " headline) VALUES (?,?,?,?,?)",
                     (sym, at, kind, val, head))
    conn.commit()
    conn.close()
    return path


ON = date(2026, 9, 5)
WELSPUN = ("WELCORP", "2026-08-21T03:23", "ORDER", 15840.0,
           "WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER IN "
           "COMPANY HISTORY VALUED AT APPROX USD 1.8 BILLION FOR "
           "SUPPLY OF PIPES")
LARSEN = ("LT", "2026-08-21T03:23", "ORDER", 15000.0,
          "LT: CO WINS ULTRA-MEGA OFFSHORE ORDER WORTH 15,000 CRORE")
RAIL = ("RAILTEL", "2026-08-21T03:23", "ORDER", 630.0,
        "RAILTEL: CO SECURES 630 CRORE ORDER FROM THE RAILWAYS")
NUVAMA = ("NUVAMA", "2026-08-21T07:05", "ORDER", 15840.0,
          "NUVAMA: CO SECURES ORDER WORTH 15,840 CRORE")


# ------------------------------------------------------------------
# it opens for the case he raised
# ------------------------------------------------------------------

def test_welspuns_order_is_still_a_reason(caps):
    got = ce.standing_reason("WELCORP", on=ON, events_db=_events([WELSPUN]))
    assert got is not None
    assert got["source"] == "standing order"
    assert got["pct_of_company"] == 47.1
    assert "47% of the company" in got["text"]


def test_a_small_share_is_not_a_reason(caps):
    """L&T's Rs 15,000 cr is 3% of L&T. On a rupee bar it would be one
    of the biggest orders on the board."""
    assert ce.standing_reason("LT", on=ON,
                              events_db=_events([LARSEN])) is None


def test_a_small_order_to_a_small_company_IS_a_reason(caps):
    """RailTel's Rs 630 cr is a quarter of RailTel. On a rupee bar it
    would be invisible. This is the whole point of the measure."""
    got = ce.standing_reason("RAILTEL", on=ON, events_db=_events([RAIL]))
    assert got is not None
    assert got["pct_of_company"] == 26.6


def test_an_order_bigger_than_the_company_opens_nothing(caps):
    """NUVAMA reads 112%. That row is an acquisition approach filed as
    an order, and a bad row must never open a door."""
    assert ce.standing_reason("NUVAMA", on=ON,
                              events_db=_events([NUVAMA])) is None


def test_an_unknown_company_size_opens_nothing(caps):
    """500 sizes for 1,976 symbols. Admitting the unmeasured ones on a
    rupee bar would bring the fault back through the side door."""
    other = ("SOMECO", "2026-08-21T03:23", "ORDER", 9000.0,
             "SOMECO: CO SECURES 9,000 CRORE ORDER")
    assert ce.standing_reason("SOMECO", on=ON,
                              events_db=_events([other])) is None


def test_it_closes_once_the_order_is_old(caps):
    """Two trading weeks. The Welspun order was ten sessions old while
    it was still running."""
    late = date(2026, 10, 15)
    assert ce.standing_reason("WELCORP", on=late,
                              events_db=_events([WELSPUN])) is None


# ------------------------------------------------------------------
# and it reaches the ranker's own question
# ------------------------------------------------------------------

def test_why_returns_it_when_nothing_fresher_answers(caps, monkeypatch):
    from core import why_moving
    monkeypatch.setattr(why_moving, "_why_before_payoff",
                        lambda **kw: None)
    monkeypatch.setattr(
        ce, "standing_reason",
        lambda symbol, on=None, events_db=None: (
            {"text": "Rs 15,840 cr order = 47% of the company, "
                     "10 sessions ago",
             "weight": 0.45, "direction": "POSITIVE",
             "source": "standing order", "pct_of_company": 47.1,
             "sessions_ago": 10} if symbol == "WELCORP" else None))
    got = why_moving.why(symbol="WELCORP", on_date="2026-09-05")
    assert isinstance(got, dict)
    assert got["source"] == "standing order"


def test_a_fresh_reason_always_wins(caps, monkeypatch):
    """A stock with real news today must never be handed an old order
    instead. This is asked ONLY when nothing fresher answered."""
    from core import why_moving
    fresh = {"text": "results filed, STRONG", "weight": 0.9,
             "direction": "POSITIVE", "source": "PRO channel verdict"}
    monkeypatch.setattr(why_moving, "_why_before_payoff",
                        lambda **kw: dict(fresh))
    asked = []
    monkeypatch.setattr(ce, "standing_reason",
                        lambda *a, **k: asked.append(1))
    got = why_moving.why(symbol="WELCORP", on_date="2026-09-05")
    assert got["source"] == "PRO channel verdict"
    assert not asked, "the memory was consulted despite a fresh reason"


def test_a_standing_order_ranks_below_fresh_news(caps):
    """It is a cause still standing, not news that broke this morning."""
    got = ce.standing_reason("WELCORP", on=ON, events_db=_events([WELSPUN]))
    assert got["weight"] < 0.8


# ------------------------------------------------------------------
# what must not have moved
# ------------------------------------------------------------------

def test_the_stale_window_is_unchanged():
    """Every path above this one in why() is untouched. Only the case
    where NOTHING answered is new."""
    from core.why_moving import STALE_REASON_HOURS
    assert STALE_REASON_HOURS == 24.0


def test_the_gate_asks_the_memory_only_as_a_last_resort():
    import io
    src = io.open("core/why_moving.py", encoding="utf-8").read()
    block = src[src.index("def why(events=None"):]
    block = block[:block.index("if not isinstance(got, dict):\n        return got")]
    assert "if not isinstance(got, dict) and symbol:" in block, \
        "the memory must be asked only when nothing fresher answered"


def test_nothing_but_why_moving_reads_the_gate():
    """One door, one key. If this is ever widened it should be a
    deliberate act."""
    import io
    for path in ("core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "standing_reason" not in src, \
            f"{path} reads the standing-order gate directly"
