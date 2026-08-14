"""
==========================================================
Every fill: what we wanted, what we got
==========================================================

    "another thing while buying & selling slippages too cost us.
     need to place as limit orders (need to discuss)"
                                    -- operator, 29 July 2026

THE POINT
---------
trading/slippage.py estimates the gap between the price the bot
decides on and the price it gets. Its own docstring is honest about
what those numbers are:

    "These numbers are ESTIMATES, not measurements. Nobody here has
     placed a real order yet. 0.05% on a liquid name and 0.20% on a
     thin one at the open are conventional retail figures, not this
     bot's own data."

    "From 30 July the operator places real orders. Every real fill
     should be compared against the price the bot wanted, and THAT
     difference should replace these constants."

This is the store that makes the second paragraph possible.

Both executors already compute the miss on every single fill --
trading/paper_execution.py and trading/live_execution.py return
slippage_rs -- and nothing has ever kept it. On 29 July that meant
84 fills produced a slippage figure that existed only in a terminal.
The FIRST REAL ORDERS are placed on 30 July, and losing those would
mean deciding the limit-order question on estimates for another month.

WHAT IT IS FOR
--------------
Two questions, in order:

  1. What does immediacy actually cost us? Measured, per symbol, per
     side, per hour -- not assumed.
  2. Only then: are limit orders worth the risk of not filling at all?

That second question is the operator's, and it needs his own numbers
under it. A missed entry costs the whole move; a market order costs a
few basis points. Which is worse is an empirical question and this is
how it gets answered.

MODE IS RECORDED ON EVERY ROW, and paper and live are never mixed in
a single figure. A modelled cost and a real one are different kinds of
number, and the one rule this project has never bent is that those two
do not share a column.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import threading
from datetime import datetime

from core.logger import diagnostic, warn

DB_PATH = os.path.join("data", "fills.db")


class FillLog:
    """Every fill, paper and live, with what it was meant to be.

    Write-once, read-later. Never raises: a bookkeeping failure must
    not be able to break an order.
    """

    def __init__(self, db_path=None):
        # Read the module global at CALL time, not at def time. A
        # default argument is bound once when the function is defined,
        # so `db_path=DB_PATH` would capture the production path at
        # import and tests/conftest.py's redirect would silently do
        # nothing -- every pytest run would then write fixture fills
        # into the real store, which is precisely the bug that put
        # test trades in logs/trade_log.csv.
        self.db_path = db_path or DB_PATH
        self._lock = threading.Lock()
        self._ready = False
        self._ensure()

    def _ensure(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fills ("
                " id INTEGER PRIMARY KEY,"
                " at TEXT, trade_date TEXT, mode TEXT, side TEXT,"
                " symbol TEXT, security_id TEXT, qty INTEGER,"
                " intent_price REAL, fill_price REAL,"
                " slip_rs REAL, slip_pct REAL,"
                " reason TEXT, order_id TEXT, turnover_cr REAL)")
            conn.execute("CREATE INDEX IF NOT EXISTS fills_date "
                         "ON fills (trade_date)")
            conn.commit()
            conn.close()
            self._ready = True
        except (sqlite3.Error, OSError) as exc:
            # LOUD, not quiet. Everywhere else in this project a
            # failed store costs one panel. Here it costs the first
            # real fills this bot will ever place, which happen once
            # and cannot be recreated -- and the failure mode is a
            # store that silently accepts nothing while every order
            # still succeeds.
            warn(f"[FILLS] CANNOT WRITE {self.db_path} ({exc}) -- real "
                 f"fill prices will NOT be recorded. The slippage "
                 f"constants stay guesses until this is fixed.")

    # ------------------------------------------------------------

    def record(self, mode, side, symbol, security_id, qty, intent_price,
               fill_price, reason="", order_id=None, turnover_cr=None,
               at=None):
        """One fill. Returns True if it was stored.

        `mode` is "PAPER" or "LIVE" and is never optional -- a real
        fill and a modelled one must always be separable.
        """
        if not self._ready:
            # Say it once per LIVE fill. A paper fill going unrecorded
            # is a shame; a real one is data that cannot be recreated.
            if str(mode).upper() == "LIVE":
                warn(f"[FILLS] {symbol} LIVE fill NOT recorded -- "
                     f"{self.db_path} is not writable.")
            return False
        try:
            intent = float(intent_price)
            filled = float(fill_price)
            qty = int(qty)
        except (TypeError, ValueError):
            return False
        if intent <= 0 or filled <= 0 or qty <= 0:
            return False

        # Signed the way it costs money: a BUY filling HIGH is a loss,
        # a SELL filling LOW is a loss. A negative number here means
        # the fill came back BETTER than asked, which does happen and
        # must not be hidden -- averaging only the bad ones would
        # overstate the true cost of trading.
        miss = (filled - intent) if str(side).upper() == "BUY" \
            else (intent - filled)
        when = at or datetime.now()
        try:
            with self._lock:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    "INSERT INTO fills (at, trade_date, mode, side, symbol,"
                    " security_id, qty, intent_price, fill_price, slip_rs,"
                    " slip_pct, reason, order_id, turnover_cr)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (when.strftime("%Y-%m-%d %H:%M:%S"),
                     when.strftime("%Y-%m-%d"), str(mode).upper(),
                     str(side).upper(), symbol, str(security_id or ""), qty,
                     round(intent, 4), round(filled, 4),
                     round(miss * qty, 2), round(miss / intent * 100, 4),
                     reason or "", order_id, turnover_cr))
                conn.commit()
                conn.close()
            return True
        except sqlite3.Error as exc:
            # WARN, not diagnostic. A fill is a TRADE RECORD: it is the
            # evidence of what was actually bought or sold, at what price,
            # and it is the input to every P&L and slippage figure
            # afterwards. Losing one at DEBUG level means the numbers
            # quietly stop adding up and nothing points at why -- the same
            # failure mode as the Telegram store, where 80 messages a poll
            # went missing behind a warning that blamed the wrong thing.
            warn(f"[FILLS] COULD NOT RECORD the fill for {symbol}: {exc}. "
                 f"This fill is NOT stored, so P&L, charges and slippage "
                 f"will be short by one trade and the trade log and fills "
                 f"store will disagree.")
            return False

    # ------------------------------------------------------------

    def rows(self, mode=None, date=None, limit=2000):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            sql, params = "SELECT * FROM fills", []
            where = []
            if mode:
                where.append("mode = ?")
                params.append(str(mode).upper())
            if date:
                where.append("trade_date = ?")
                params.append(date)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY at DESC LIMIT ?"
            params.append(limit)
            out = [dict(r) for r in conn.execute(sql, params)]
            conn.close()
            return out
        except sqlite3.Error:
            return []

    def stats(self, mode="LIVE", date=None):
        """What immediacy actually costs, from real fills only.

        Defaults to LIVE because that is the whole reason this store
        exists. Ask for PAPER explicitly if you want the model's own
        output -- and never put the two in one table.
        """
        rows = self.rows(mode=mode, date=date)
        if not rows:
            return {"mode": str(mode).upper(), "fills": 0,
                    "note": "no fills recorded yet"}
        pcts = sorted(r["slip_pct"] for r in rows)
        by_side = {}
        for row in rows:
            by_side.setdefault(row["side"], []).append(row["slip_pct"])
        return {
            "mode": str(mode).upper(),
            "fills": len(rows),
            "total_rs": round(sum(r["slip_rs"] for r in rows), 2),
            "median_pct": pcts[len(pcts) // 2],
            "worst_pct": pcts[-1],
            "better_than_asked": sum(1 for p in pcts if p < 0),
            "by_side": {side: round(sum(v) / len(v), 4)
                        for side, v in by_side.items()},
            # This is the number that should replace
            # config.SLIPPAGE_BASE_PCT once there are enough real fills
            # to trust it.
            "suggested_pct": round(sum(pcts) / len(pcts) / 100, 5),
        }
