"""---- HIS BOOK IS NOT THE BOT'S BOOK. 1 September 2026. ----

    "bot doesnot confuse with my trades incase i trade in vtl , bot can
     also trade if all rules satisfies"
                                                -- the operator

For a few hours on 1 September the bot refused any stock he held at
Dhan. That came from his earlier message the same day --

    "another thing dhan & bot is not inline. i had caplinpoint stock
     but bot does'nt know that still"

-- which I read as "do not buy on top of me". He meant the opposite of
a trading rule: the two books must not be CONFUSED with each other.
That is a REPORTING problem and it is answered where reporting lives --
two separate tables on the Trade tab, and the three buckets in
core/broker_sync.py that feed them.

WHAT THAT SHORT-LIVED RULE WOULD HAVE COST. On the live snapshot at the
time, CAPLIPOINT and SSWL were both his positions AND live candidates;
SSWL was running at 51.8x its normal volume. Refusing them would have
taken two of the day's strongest names off the board for a reason that
has nothing to do with whether they were good trades.

WHAT STILL BLOCKS THE BOT, and why it is different:

    already holding it -- no pyramiding      the BOT'S own open position
    already traded today                     the BOT'S own closed trade

Both are the bot's own book. Neither is his.
"""

import inspect
from pathlib import Path

from core import auto_entry


ROW = {"symbol": "VTL", "action": "BUY", "state": "ok",
       "plan": {"ok": True, "qty": 159, "stop": 587.58, "entry": 603.60},
       "score": 52.15}


class _Engine:
    def __init__(self):
        self.open_positions = {}
        self.closed_positions = []
        self.alert_only = False


# ------------------------------------------- his positions block nothing

def test_a_stock_he_holds_is_still_tradeable_by_the_bot():
    """The whole point. He holds VTL; the bot may still buy VTL."""
    got = auto_entry.refuse_reason(ROW, _Engine(), held=set(),
                                   max_positions=3)
    assert got is None, f"his own holding is still refusing the bot: {got}"


def test_nothing_on_the_entry_path_reads_his_broker_book():
    """The rule was removed, not merely bypassed. If a reader comes
    back it will refuse his stocks again the first morning he holds one
    the bot wants."""
    src = inspect.getsource(auto_entry)
    assert "owned_elsewhere" not in src, (
        "the entry path is consulting his Dhan holdings again")
    assert "already hold it at Dhan" not in src

    for path in ("main.py", "core/engine.py", "dashboard/state.py"):
        text = Path(path).read_text(encoding="utf-8")
        assert "symbols_at_broker" not in text, (
            f"{path} still reads his broker book into a decision")


# ------------------------------------------ but the bot's own book does

def test_the_bots_own_open_position_still_blocks_it():
    """Pyramiding into itself is a different thing entirely."""
    got = auto_entry.refuse_reason(ROW, _Engine(), held={"VTL"},
                                   max_positions=3)
    assert got and "no pyramiding" in got, got


def test_the_bots_own_closed_trade_still_blocks_it():
    """One stock, one trade a day -- his rule, and it is about the
    bot's trades, not his."""
    got = auto_entry.refuse_reason(ROW, _Engine(), held=set(),
                                   max_positions=3, traded_today={"VTL"})
    assert got and "one trade a day" in got, got


# ------------------------------------ and the two books stay apart on screen

