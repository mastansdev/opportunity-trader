"""---- WHICH COMBINATION MADE THE MONEY. 4 September 2026. ----

    "today rules as set -1 & now proposed rules to set-1 becomes set-2
     so that we can track which set gives us more adapted to markets &
     make money more."
    "i want to make sure that which combination of rules set were
     yielding results = profits"                     -- the operator

Every trade already recorded WHAT was known about the stock --
news:ORDER, results:STRONG. Nothing recorded which RULE admitted it to
the candidate pool, nor what the numbers were at the instant of the
decision. Without those a rule change can be argued about but never
scored: after a week he could not say whether news plus a volume jump
beats news alone.

A DOOR IS NOT A REASON. RESPONIND on 4 September had reason_summary
None and came in purely on volume. AFFLE had filed:CONCALL *and* a
volume jump, and only one of those actually opened the door.

FACTS, NOT GROUPINGS. door, volume_x, jump_x, liveness, off_high_pct
are recorded raw. Deciding the buckets tonight would throw away every
question neither of us has thought of yet -- "do entries before 10:30
beat entries after 13:00" is answerable from this and was not on
anyone's list when it was built.

IT WILL NOT ANSWER ANYTHING TOMORROW. At ~25 trades a day a specific
combination may have two examples in a week. The reason to build it now
is that data not recorded is gone: every session without it is a
session that cannot be learned from.
"""

import io
import sqlite3


def test_the_trade_record_can_hold_a_fingerprint():
    """The columns exist and migrate onto an existing database."""
    from core.trade_memory import TradeMemory
    TradeMemory()
    cols = {r[1] for r in sqlite3.connect("data/trade_memory.db")
            .execute("PRAGMA table_info(trade_memory)")}
    for c in ("door", "volume_x", "jump_x", "liveness", "off_high_pct"):
        assert c in cols, "trade_memory cannot record %s" % c


def test_the_pool_records_which_source_admitted_each_stock():
    """Asserted on the source: the tag is written where the decision is
    made, and nowhere else knows it."""
    src = io.open("dashboard/state.py", encoding="utf-8").read()
    fn = src[src.index("def _symbols_with_news_today"):]
    fn = fn[:fn.index("\n    def ", 10)]
    assert "self._door" in fn
    for door in ('"news"', '"filing"', '"results"', '"surge"'):
        assert door in fn, "no stock can ever be tagged %s" % door


def test_the_first_source_to_bring_it_in_owns_it():
    """A stock with news AND a surge came in through whichever spoke
    first. Overwriting would credit the wrong rule."""
    src = io.open("dashboard/state.py", encoding="utf-8").read()
    fn = src[src.index("def _symbols_with_news_today"):]
    assert "if key and key not in self._door" in fn


def test_a_row_the_pool_never_tagged_is_opening_not_blank():
    """It reached the board as a mover, not by a rule. That is itself
    a door and must be named, or those trades vanish from the split."""
    src = io.open("dashboard/state.py", encoding="utf-8").read()
    assert 'row["door"] = (getattr(self, "_door", None) or {}).get(' in src
    assert '"opening")' in src


def _fingerprint_block(src):
    """The whole entry_facts block, however long it grows.

    ---- IT WAS A CHARACTER COUNT. 6 September 2026. ----

    This sliced a fixed 1400 characters from the marker. Four fields
    were added to the fingerprint that day -- run_up_pct,
    move_age_min, reason_kind, reason_pct_of_company -- and the
    `except Exception` that is the whole point of the test fell 233
    characters outside the window. The code was correct and the test
    failed, which is the wrong way round.

    So it reads to the END of the block instead: the enter() call that
    follows it. The guard is unchanged -- the try/except must still be
    there, and it must still say it never blocks a trade.
    """
    start = src.index("THE FINGERPRINT OF THIS ENTRY")
    tail = src[start:]
    end = tail.index("enter(symbol")
    return tail[:end]


def test_the_facts_are_stamped_at_the_moment_of_the_decision():
    """Not rebuilt later from the board -- by then the numbers have
    moved, which is the whole fault this session has been chasing."""
    src = io.open("core/auto_entry.py", encoding="utf-8").read()
    block = _fingerprint_block(src)
    for k in ('"door"', '"volume_x"', '"jump_x"', '"liveness"', '"off_high_pct"'):
        assert k in block
    assert "engine.entry_facts" in block


def test_bookkeeping_never_blocks_a_trade():
    """The oldest rule in this file. A fingerprint that cannot be built
    must cost a field, never an order."""
    src = io.open("core/auto_entry.py", encoding="utf-8").read()
    block = _fingerprint_block(src)
    assert "except Exception" in block
    assert "never block a trade" in block


def test_a_fingerprint_from_another_stock_is_not_used():
    """Left-over facts would file one stock's numbers against another's
    trade -- worse than recording nothing."""
    src = io.open("core/engine.py", encoding="utf-8").read()
    block = src[src.index("THE FINGERPRINT. 4 September 2026"):][:900]
    assert '.get("symbol") == symbol' in block
