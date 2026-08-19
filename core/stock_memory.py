"""
==========================================================
Stock Memory -- what the bot KNOWS about each of the 750
==========================================================

Operator's own proposal, 2026-07-25:

    "I proposed a memory bot for every 750 stocks... so that Brain Bot,
     before selecting any trade, will understand the stock situation and
     use the opportunity. ex - JLHL: stock split, but bot sees it as 80%
     down from last closed price. If memory bot is there and sends
     signals to Brain Bot for every special case -- stock split,
     dividend, and anything else which will affect the stock price --
     it will be seen BEFORE opening the trade itself."

That is exactly the missing layer. Everything else in this bot reasons
about PRICE. Nothing reasoned about WHY a price is what it is.

The concrete failure this fixes:

    JLHL, 2026-07-24: a 2:10 stock split. The exchange halved the
    reference price; our prev_close was the UNADJUSTED one. The bot
    therefore read a routine corporate action as an **-80% crash** --
    ranked it the day's biggest loser, and in the replay "shorted" it.
    Nothing was wrong with the market. The bot simply did not know.

    Same class: a stock going ex-dividend opens lower by the dividend
    amount. That is not weakness, and shorting it is a mistake.

So this module stores FACTS about a symbol -- corporate actions with
their effective dates -- and answers one question the engine asks before
every entry: **"is anything special going on with this stock today?"**

Design, deliberately mirroring news_bot/news_store.py (same reasoning:
survives restarts, shared across processes, dedupes on its own key):
  - SQLite locally, Postgres on Railway (DATABASE_URL), same code.
  - UNIQUE(symbol, action_type, ex_date) so re-polling can't duplicate.
  - Read path is cached in memory by the caller; the tick path never
    touches the database.
  - Fail-OPEN everywhere. An empty memory must never block trading --
    it just means the bot knows nothing special, which is today's
    behaviour anyway.

Sources: NSE (`nse.actions`) and BSE (`bse.actions`) forthcoming
corporate actions, both already installed for the news engine. Manual
entries are supported too, for anything the feeds miss.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, Date, DateTime, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, insert, select,
)
from sqlalchemy.exc import IntegrityError

from core.db import resolve_database_url

# Action types that MOVE THE PRICE MECHANICALLY -- the reference price
# changes, so a % move computed against yesterday's close is a lie.
# These are the ones that must block or adjust, not merely inform.
# 2026-07-26, OPERATOR CORRECTION: "when did i say to block trading for
# any dividend stocks? dividend is very minimal effect."
#
# Correct, and DIVIDEND was in this set on my initiative, never asked
# for. The measured effect on real names:
#
#     CRISIL      Rs 10.00 on Rs 4,347  = 0.23%
#     TATACAP     Rs  0.57 on Rs   342  = 0.17%
#     PERSISTENT  Rs 18.00 on Rs 5,200  = 0.35%
#     DLF         Rs  8.00 on Rs   645  = 1.24%
#
# Against a normal 2-3% daily range that is noise, and blocking a liquid
# large-cap over it costs a whole day's opportunity in that name. A
# SPLIT is a different animal entirely -- JLHL's 2:10 read as -80%.
#
# So dividends are INFORMATIONAL: remembered, shown, never a veto.
PRICE_ADJUSTING = {"SPLIT", "BONUS", "RIGHTS", "DEMERGER"}

# Everything else is context: it may explain volatility, but the price
# scale is unchanged (or changes so little it does not matter).
INFORMATIONAL = {"EARNINGS", "BOARD_MEETING", "AGM", "BUYBACK",
                 "DIVIDEND", "OTHER"}

# THE ONE EXCEPTION, and it is a real one. A SPECIAL dividend can be a
# large fraction of the share price -- companies have paid out 20%+ of
# their market cap in one go. That is a genuine rescaling, identical in
# effect to a split, and the "dividends are noise" reasoning above stops
# applying somewhere.
#
# This threshold is where. Anything below it never blocks, which covers
# every ordinary dividend you will ever see (the largest above is
# 1.24%). Set it to None to switch the safety net off entirely.
DIVIDEND_BLOCK_PCT = 5.0

# Actions whose materiality we can compute (needs the rupee amount and
# the price). Everything in PRICE_ADJUSTING blocks unconditionally.
_MEASURABLE = {"DIVIDEND"}

_AMOUNT_RE = re.compile(
    r"(?:rs|re|inr)\.?\s*([0-9]+(?:[0-9,]*)(?:\.[0-9]+)?)", re.IGNORECASE
)


def parse_amount(detail):
    """
    Pull the rupee figure out of an exchange detail string:

        "Dividend - Rs 5.20 Per Share"        -> 5.20
        "Interim Dividend - Rs 10  Per Share" -> 10.0
        "Dividend - Re 0.57 Per Share"        -> 0.57

    Returns None when there is no parseable amount -- and the caller
    then treats the action as material, because an unmeasurable
    distortion must never be assumed to be small.
    """
    match = _AMOUNT_RE.search(str(detail or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _utcnow():
    return datetime.now(timezone.utc)


class StockMemory:
    """Per-symbol facts. Construct once and share."""

    def __init__(self, url=None):
        self.url = resolve_database_url(url, default="sqlite:///data/stock_memory.db")
        connect_args = {}
        if self.url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)

        self.engine = create_engine(
            self.url, future=True, pool_pre_ping=True, connect_args=connect_args
        )
        self.metadata = MetaData()
        self.actions = Table(
            "stock_actions", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            # SPLIT / BONUS / DIVIDEND / RIGHTS / DEMERGER / EARNINGS / ...
            Column("action_type", String(32), nullable=False),
            # The date the price actually changes (ex-date). This is the
            # one that matters -- NOT the announcement date.
            Column("ex_date", Date, nullable=False, index=True),
            # Free text as the exchange gave it ("Rs 4 per share",
            # "2:10", "1:1"). Parsing every format is a losing game; the
            # bot only needs to KNOW, and a human can read the detail.
            Column("detail", Text),
            Column("source", String(32)),
            Column("created_at", DateTime(timezone=True), default=_utcnow),
            UniqueConstraint("symbol", "action_type", "ex_date",
                             name="uq_stock_action"),
        )
        self.metadata.create_all(self.engine)

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------

    def remember(self, symbol, action_type, ex_date, detail="", source="manual"):
        """Store one fact. Returns True if newly stored, False if the
        bot already knew. Never raises on a duplicate."""
        if not symbol or not action_type or ex_date is None:
            return False
        action_type = action_type.strip().upper()
        symbol = symbol.strip().upper()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.actions.c.id).where(
                    (self.actions.c.symbol == symbol)
                    & (self.actions.c.action_type == action_type)
                    & (self.actions.c.ex_date == ex_date)
                ).limit(1)
            ).first()
            if existing is not None:
                return False
            try:
                conn.execute(insert(self.actions).values(
                    symbol=symbol, action_type=action_type, ex_date=ex_date,
                    detail=(detail or "")[:500], source=source,
                    created_at=_utcnow(),
                ))
            except IntegrityError:
                return False
        return True

    # ----------------------------------------------------------
    # READ -- what the engine asks
    # ----------------------------------------------------------

    def facts_for(self, symbol, on_date=None, window_days=1):
        """Every known action for `symbol` whose ex-date falls within
        +/- window_days of `on_date` (default today). The window exists
        because the price distortion straddles the ex-date: the day
        before is when the old close becomes stale."""
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.symbol == symbol.strip().upper())
                    & (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                ).order_by(self.actions.c.ex_date)
            ).all()
        return [dict(r._mapping) for r in rows]

    def price_distorting_symbols(self, on_date=None, window_days=1,
                                 price_lookup=None,
                                 min_pct=DIVIDEND_BLOCK_PCT):
        """
        The set the engine actually needs: every symbol whose PRICE SCALE
        is being changed MATERIALLY around `on_date`. A %-move computed
        for one of these against an unadjusted previous close is
        meaningless -- this is the JLHL case, and the direct answer to
        "know before trading".

        price_lookup: optional callable symbol -> last close. When given,
        a DIVIDEND is only counted if it is at least `min_pct` of the
        share price (see DIVIDEND_BLOCK_PCT for why, with real
        numbers). Splits, bonuses, rights and demergers always count.

        WITHOUT a price_lookup the behaviour is unchanged -- every
        price-adjusting action blocks. That keeps every existing caller
        and test working, and means the conservative path is the default.

        FAIL-CLOSED, unlike most of this codebase: if the amount cannot
        be parsed or the price is unknown, the action IS counted. An
        unmeasurable distortion must never be assumed to be a small one.

        Returned as {symbol: [reasons]} so the log can say WHY.
        """
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                    & (self.actions.c.action_type.in_(
                        tuple(PRICE_ADJUSTING) + tuple(_MEASURABLE)))
                )
            ).all()
        out = {}
        for r in rows:
            d = dict(r._mapping)
            reason = (f"{d['action_type']}"
                      + (f" ({d['detail']})" if d.get("detail") else ""))

            if d["action_type"] in _MEASURABLE:
                # Dividends are informational (see PRICE_ADJUSTING's
                # note). The ONLY one that still blocks is a special
                # dividend large enough to rescale the price like a
                # split -- DIVIDEND_BLOCK_PCT. Set that to None and no
                # dividend ever blocks.
                if min_pct is None or price_lookup is None:
                    continue
                pct = self._distortion_pct(d, price_lookup)
                if pct is None or pct < min_pct:
                    # Unmeasurable is treated as SMALL here, the opposite
                    # of the old rule -- because "dividend" now means
                    # "almost certainly noise", so the burden of proof is
                    # on blocking, not on trading.
                    continue
                reason += f" -- {pct:.2f}% of price, a special dividend"

            out.setdefault(d["symbol"], []).append(reason)
        return out

    @staticmethod
    def _distortion_pct(action, price_lookup):
        """How much of the share price this action removes, as a
        percentage. None when it cannot be determined -- the caller then
        treats it as material."""
        amount = parse_amount(action.get("detail"))
        if amount is None or amount <= 0:
            return None
        try:
            price = price_lookup(action["symbol"])
        except Exception:
            return None
        if not price or price <= 0:
            return None
        return amount / price * 100.0

    def immaterial_symbols(self, on_date=None, window_days=1,
                           price_lookup=None,
                           min_pct=DIVIDEND_BLOCK_PCT):
        """
        The mirror of the above: actions we are DELIBERATELY ignoring
        because they are too small to matter. Exists so the decision is
        visible in the log rather than silent -- a stock quietly not
        being blocked is exactly the kind of thing that should be
        auditable.
        """
        if price_lookup is None:
            return {}
        blocked = self.price_distorting_symbols(
            on_date, window_days, price_lookup=price_lookup, min_pct=min_pct)
        everything = self.price_distorting_symbols(on_date, window_days)
        out = {}
        for symbol, reasons in everything.items():
            if symbol not in blocked:
                out[symbol] = reasons
        return out

    def all_symbols_with_facts(self, on_date=None, window_days=1):
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                ).order_by(self.actions.c.symbol)
            ).all()
        out = {}
        for r in rows:
            d = dict(r._mapping)
            out.setdefault(d["symbol"], []).append(d)
        return out

    def count(self):
        from sqlalchemy import func
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.actions)
            ).scalar_one()

    # ----------------------------------------------------------
    # HISTORY -- "how many times has this stock done X?"
    # ----------------------------------------------------------
    # Operator, 2026-07-26: "how many times stocks are releasing their
    # results & dividend/buyback/splits announcing, or any other
    # announcements in memory". The memory was only ever queried for
    # TODAY; everything it had already stored about the past was
    # invisible. These are read-only views over the same table -- no new
    # data, no new fetching, just the ability to look backwards.

    def history_for(self, symbol):
        """Every fact ever stored for one symbol, oldest ex-date first."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    self.actions.c.symbol == str(symbol).strip().upper()
                ).order_by(self.actions.c.ex_date)
            ).all()
        return [dict(r._mapping) for r in rows]

    def counts_for(self, symbol):
        """{action_type: n} for one symbol."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.action_type, func.count())
                .where(self.actions.c.symbol == str(symbol).strip().upper())
                .group_by(self.actions.c.action_type)
            ).all()
        return {r[0]: r[1] for r in rows}

    def event_counts(self):
        """{action_type: n} across the whole universe."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.action_type, func.count())
                .group_by(self.actions.c.action_type)
                .order_by(func.count().desc())
            ).all()
        return {r[0]: r[1] for r in rows}

    def busiest_symbols(self, limit=20):
        """[(symbol, n)] -- who has the most corporate activity on
        record. Useful mostly as a data-quality check: a name with far
        more entries than its peers usually means a duplicate feed, not
        an unusually busy company."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.symbol, func.count())
                .group_by(self.actions.c.symbol)
                .order_by(func.count().desc())
                .limit(limit)
            ).all()
        return [(r[0], r[1]) for r in rows]

    def date_range(self):
        """(earliest ex-date, latest ex-date) or (None, None)."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            row = conn.execute(select(
                func.min(self.actions.c.ex_date),
                func.max(self.actions.c.ex_date))).first()
        return (row[0], row[1]) if row else (None, None)


_default = None


def default_memory():
    global _default
    if _default is None:
        _default = StockMemory()
    return _default


# ==========================================================
#  THE EVENT LEDGER -- WHAT HAPPENED FROM THE UPDATE TO THE
#  NEXT RESULT
# ==========================================================
#
#     "bot needs to know day to day updates & memory must be updated -
#      tracked whether stock performed from the update to next result.
#      still user doing manual updates/data maintainance which is not
#      ideal to do so bot must maintain the complete record from event
#      date, price on that date to movement on the event date to next
#      result date + guidance from the company."
#                                 -- operator, 19 August 2026
#
# WHY NOTHING ALREADY DID THIS
# ----------------------------
# All three inputs were already on disk and no line of code joined
# them:
#
#     data/stock_events.db      15,130 events, 1,727 symbols
#     data/results_calendar.db   7,086 results dates
#     data/daily_candles.db      1.1M daily bars, back to 2016
#
# core/outcomes.py measures the session AFTER an event. core/
# opportunity.py measures a family's average next-session move. Both
# answer "did the market react", and neither answers his question,
# which is about a HOLDING PERIOD: an order win in May is a claim
# about a quarter, and the quarter ends when the company next
# reports. Judging it on the following morning's candle grades the
# claim before the evidence exists.
#
# So this walks event -> next results date, which is the window the
# company itself is judged over.
#
# WHAT IT DELIBERATELY DOES NOT DO
# --------------------------------
# It does not rank, gate, or feed the entry path. It is a RECORD -- he
# asked to stop maintaining one by hand, not for another opinion. The
# day a number here earns a trading rule, that rule gets written and
# argued on its own, the same way core/opportunity.py's payoff tilt
# was on 19 August.
#
# AN OPEN WINDOW IS NOT A ZERO. An event whose next results date has
# not arrived is reported as still_open with the move so far, never
# folded into a completed average. Half the value of this ledger is
# knowing which claims are still unsettled.

EVENTS_DB = os.path.join("data", "stock_events.db")
RESULTS_DB = os.path.join("data", "results_calendar.db")
DAILY_DB = os.path.join("data", "daily_candles.db")

#: Event kinds that belong to a COMPANY and can be judged against its
#: next print. MACRO, MARKET_ANSWER and AI_VERDICT are commentary or
#: market-wide and are not this stock's claim to answer for.
COMPANY_KINDS = ("ORDER", "RESULT", "REPORTED", "CONCALL", "NEWS",
                 "EXPECTATION")

#: Kinds that carry what management SAID rather than what it did --
#: his "+ guidance from the company".
GUIDANCE_KINDS = ("CONCALL", "EXPECTATION")


def _read_only(path):
    try:
        if not os.path.exists(path):
            return None
        return sqlite3.connect("file:" + path + "?mode=ro", uri=True)
    except Exception:                                       # noqa: BLE001
        return None


def _day(value):
    """The DATE part of whatever the store happened to write.

    stock_events.db writes ISO timestamps with a zone
    ("2026-08-19T02:57:47+00:00"); results_calendar.db writes plain
    dates. Both are sliced to ten characters rather than parsed,
    because a parse that raises on one row would drop a symbol's whole
    history for a formatting reason.
    """
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _closes_for(conn, symbol, since=None):
    """[(date, close, prev_close)] oldest first, or []."""
    if conn is None:
        return []
    sql = ("SELECT date, close, prev_close FROM daily_bars "
           "WHERE symbol = ?")
    params = [str(symbol or "").upper()]
    if since:
        sql += " AND date >= ?"
        params.append(str(since))
    sql += " ORDER BY date"
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:                                       # noqa: BLE001
        return []


def _close_on_or_after(closes, when):
    """The first session on or after `when`. A filing on a Saturday is
    answered by Monday, not discarded."""
    for row in closes:
        if str(row[0]) >= str(when):
            return row
    return None


def _pct(now, then):
    try:
        now, then = float(now), float(then)
    except (TypeError, ValueError):
        return None
    if then <= 0:
        return None
    return round((now - then) / then * 100.0, 2)


def event_record(symbol, since=None, limit=None):
    """Every company event for this stock, with what the price did.

    Returns [] rather than raising, always. One row per event:

        at                  the day it landed
        kind, headline      what it was
        price_on_event      that session's close
        move_on_event_pct   that session's own move
        next_results_date   the first results date AFTER it
        move_to_results_pct event close -> results close
        still_open          True when that print has not happened yet
        move_since_pct      event close -> latest close, always filled
        guidance            what management said, if anything was filed

    `still_open` rows carry move_since_pct and no move_to_results_pct.
    An unfinished window is not a zero and must never average as one.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return []

    events_conn = _read_only(EVENTS_DB)
    results_conn = _read_only(RESULTS_DB)
    daily_conn = _read_only(DAILY_DB)
    try:
        if events_conn is None:
            return []

        placeholders = ",".join("?" * len(COMPANY_KINDS))
        sql = (f"SELECT at, kind, grade, value_cr, headline, detail "
               f"FROM events WHERE symbol = ? "
               f"AND kind IN ({placeholders})")
        params = [symbol, *COMPANY_KINDS]
        if since:
            sql += " AND at >= ?"
            params.append(str(since))
        sql += " ORDER BY at"
        try:
            rows = events_conn.execute(sql, params).fetchall()
        except Exception:                                   # noqa: BLE001
            return []
        if not rows:
            return []

        results_dates = []
        if results_conn is not None:
            try:
                results_dates = [_day(r[0]) for r in results_conn.execute(
                    "SELECT results_date FROM results_events "
                    "WHERE symbol = ? ORDER BY results_date",
                    (symbol,)).fetchall()]
            except Exception:                               # noqa: BLE001
                results_dates = []

        closes = _closes_for(daily_conn, symbol)
        latest = closes[-1] if closes else None

        out = []
        for at, kind, grade, value_cr, headline, detail in rows:
            day = _day(at)
            if not day:
                continue
            bar = _close_on_or_after(closes, day)
            price = None if bar is None else bar[1]

            record = {
                "symbol": symbol,
                "at": day,
                "kind": kind,
                "grade": grade,
                "value_cr": value_cr,
                "headline": (str(headline or "").strip() or None),
                "price_on_event": price,
                "move_on_event_pct": (None if bar is None
                                      else _pct(bar[1], bar[2])),
                "guidance": ((str(detail or "").strip() or None)
                             if kind in GUIDANCE_KINDS else None),
                "next_results_date": None,
                "price_at_next_results": None,
                "move_to_results_pct": None,
                "sessions_to_results": None,
                "still_open": True,
                "move_since_pct": None,
            }

            if price is not None and latest is not None:
                record["move_since_pct"] = _pct(latest[1], price)

            nxt = next((d for d in results_dates if d > day), None)
            if nxt:
                after = _close_on_or_after(closes, nxt)
                if after is not None and price is not None:
                    record.update({
                        "next_results_date": nxt,
                        "price_at_next_results": after[1],
                        "move_to_results_pct": _pct(after[1], price),
                        "sessions_to_results": sum(
                            1 for c in closes
                            if day < str(c[0]) <= str(after[0])),
                        "still_open": False,
                    })
                else:
                    # The date is known and the bar is not -- the print
                    # is scheduled but has not traded yet.
                    record["next_results_date"] = nxt

            out.append(record)

        out.sort(key=lambda r: r["at"], reverse=True)
        return out[:limit] if limit else out
    finally:
        for conn in (events_conn, results_conn, daily_conn):
            if conn is not None:
                try:
                    conn.close()
                except Exception:                           # noqa: BLE001
                    pass


def track_record(symbol, since=None):
    """Did this company's updates actually lead anywhere?

    The summary his manual sheet was for. SETTLED windows only -- an
    event still waiting on its next print is counted and reported
    separately, never averaged in.
    """
    rows = event_record(symbol, since=since)
    settled = [r for r in rows if not r["still_open"]
               and r["move_to_results_pct"] is not None]
    open_rows = [r for r in rows if r["still_open"]]
    delivered = [r for r in settled if r["move_to_results_pct"] > 0]

    by_kind = {}
    for row in settled:
        by_kind.setdefault(row["kind"], []).append(
            row["move_to_results_pct"])

    return {
        "symbol": str(symbol or "").upper(),
        "events": len(rows),
        "settled": len(settled),
        "still_open": len(open_rows),
        "delivered": len(delivered),
        "delivered_pct": (round(len(delivered) * 100.0 / len(settled), 1)
                          if settled else None),
        "avg_move_to_results_pct": (
            round(sum(r["move_to_results_pct"] for r in settled)
                  / len(settled), 2) if settled else None),
        "by_kind": {k: {"n": len(v), "avg_pct": round(sum(v) / len(v), 2)}
                    for k, v in sorted(by_kind.items())},
        "latest": rows[0] if rows else None,
    }
