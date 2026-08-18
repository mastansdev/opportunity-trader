"""
==========================================================
Every signal the bot saw -- including the ones it refused
==========================================================

    "real movers are ignored by bot. as first see = buy & 10 slots
     filled."                            -- operator, 29 July 2026

He was almost certainly right. It could not be checked, because the
evidence did not exist: core/breakout_feed.py holds every signal in
memory and the process exits at 15:30. Every breakout the bot saw and
refused was deleted daily, all six months.

So the most important entry question in the project --

    did the setups we REFUSED do better than the ones we TOOK?

-- has never had an answer, and could not get one.

WHAT THIS DOES
--------------
Writes one row per structural signal to data/signal_journal.db:

    when, symbol, direction, break price, the range it broke,
    whether it was TAKEN or REFUSED, and if refused, WHY.

One row per symbol+direction+day. A breakout that keeps re-firing on
every candle is one event, not forty -- the row is updated, and the
final outcome is what gets stored.

WHY A DATABASE AND NOT A LOG LINE
---------------------------------
Because it has to be joined against the price data afterwards. The
whole point is to ask "what did this stock do in the two hours after
we said no", and grep cannot answer that. tools/refused_review.py
does the join.

IT DECIDES NOTHING. Writing a row cannot block, allow, size or exit
anything. It is a notebook, and it fails silently by design -- a
journal that could break the tick loop would be worse than no journal.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import threading
from datetime import datetime

from core.logger import decision, diagnostic

DB_PATH = os.path.join("data", "signal_journal.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    trade_date   TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    direction    TEXT NOT NULL,
    first_seen   TEXT,
    last_seen    TEXT,
    break_price  REAL,
    orb_high     REAL,
    orb_low      REAL,
    taken        INTEGER DEFAULT 0,
    refused_why  TEXT,
    fired_count  INTEGER DEFAULT 1,
    open_positions_at_signal INTEGER,
    -- The three confirmations the operator asked for, 29 July 2026:
    --   "1) Results (good) + 2) Volume + 3) News"
    -- Recorded on EVERY signal, gating on none of them except volume.
    -- Two data points cannot decide a rule; thirty can. In two weeks
    -- tools/refused_review.py answers whether news-backed breakouts
    -- actually outperform, and only then does anything become a gate.
    volume_mult   REAL,
    news_kind     TEXT,
    filing_kind   TEXT,
    results_grade TEXT,
    attempt       INTEGER,
    sector        TEXT,
    confirmations INTEGER,
    PRIMARY KEY (trade_date, symbol, direction)
);
"""


class SignalJournal:
    """One row per structural signal per day. Never raises."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ready = False
        self._pending = {}

    # ------------------------------------------------------------

    def _connect(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        if not self._ready:
            conn.executescript(SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    # ------------------------------------------------------------

    def record(self, symbol, direction, break_price=None, orb_high=None,
               orb_low=None, taken=False, refused_why=None,
               open_positions=None, when=None, volume_mult=None,
               news_kind=None, filing_kind=None, results_grade=None,
               attempt=None, sector=None):
        """Buffer one signal. Flushed by flush(), not written per tick.

        Buffered deliberately: this is called from the tick path, and
        a SQLite write per signal per candle would put disk I/O in
        front of price processing. The buffer is a plain dict keyed by
        symbol+direction, so a signal that re-fires all afternoon costs
        one dict update, not forty inserts.
        """
        try:
            when = when or datetime.now()
            date = when.strftime("%Y-%m-%d")
            key = (date, symbol, direction)
            with self._lock:
                row = self._pending.get(key)
                if row is None:
                    row = {
                        "trade_date": date,
                        "symbol": symbol,
                        "direction": direction,
                        "first_seen": when.strftime("%Y-%m-%d %H:%M:%S"),
                        "break_price": break_price,
                        "orb_high": orb_high,
                        "orb_low": orb_low,
                        "taken": 0,
                        "refused_why": None,
                        "fired_count": 0,
                        "open_positions_at_signal": open_positions,
                        "volume_mult": None, "news_kind": None,
                        "filing_kind": None, "results_grade": None,
                        "attempt": None, "sector": None,
                        "confirmations": 0,
                    }
                    self._pending[key] = row
                row["last_seen"] = when.strftime("%Y-%m-%d %H:%M:%S")
                row["fired_count"] += 1

                # Confirmations are filled in as they become known --
                # a later call carrying news must not blank the volume
                # reading an earlier one recorded.
                # NOT named `key` -- that is the buffer key three lines
                # above, and shadowing it here would be a live grenade
                # for whoever edits this next.
                for field, value in (("volume_mult", volume_mult),
                                     ("news_kind", news_kind),
                                     ("filing_kind", filing_kind),
                                     ("results_grade", results_grade),
                                     ("attempt", attempt),
                                     ("sector", sector)):
                    if value is not None:
                        row[field] = value
                row["confirmations"] = sum([
                    1 if (row["volume_mult"] or 0) >= 1.5 else 0,
                    1 if row["news_kind"] or row["filing_kind"] else 0,
                    1 if (row["results_grade"] or "") in ("STRONG", "GOOD") else 0,
                ])
                if taken:
                    # Taken wins permanently. A signal that fired,
                    # was refused, then fired again and got in, is a
                    # TAKEN signal -- otherwise a later refusal would
                    # overwrite the truth.
                    row["taken"] = 1
                    row["refused_why"] = None
                elif refused_why and not row["taken"]:
                    row["refused_why"] = refused_why
        except Exception:                                  # noqa: BLE001
            pass

    # ------------------------------------------------------------

    def flush(self):
        """Write the buffer. Safe to call as often as you like."""
        try:
            with self._lock:
                rows = list(self._pending.values())
            if not rows:
                return 0
            conn = self._connect()
            conn.executemany(
                "INSERT INTO signals (trade_date, symbol, direction, "
                "first_seen, last_seen, break_price, orb_high, orb_low, "
                "taken, refused_why, fired_count, open_positions_at_signal, "
                "volume_mult, news_kind, filing_kind, results_grade, "
                "attempt, sector, confirmations) "
                "VALUES (:trade_date, :symbol, :direction, :first_seen, "
                ":last_seen, :break_price, :orb_high, :orb_low, :taken, "
                ":refused_why, :fired_count, :open_positions_at_signal, "
                ":volume_mult, :news_kind, :filing_kind, :results_grade, "
                ":attempt, :sector, :confirmations) "
                "ON CONFLICT(trade_date, symbol, direction) DO UPDATE SET "
                "last_seen=excluded.last_seen, taken=excluded.taken, "
                "refused_why=excluded.refused_why, "
                "fired_count=excluded.fired_count, "
                "volume_mult=excluded.volume_mult, "
                "news_kind=excluded.news_kind, "
                "filing_kind=excluded.filing_kind, "
                "results_grade=excluded.results_grade, "
                "attempt=excluded.attempt, sector=excluded.sector, "
                "confirmations=excluded.confirmations",
                rows)
            conn.commit()
            conn.close()
            return len(rows)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[JOURNAL] Could not write ({exc}).")
            return 0

    # ------------------------------------------------------------

    def close(self):
        written = self.flush()
        if written:
            decision(f"[JOURNAL] {written} signal(s) recorded today -- "
                     f"taken and refused both. tools/refused_review.py "
                     f"reads them back against what the stocks did.")
        return written

    def counts(self):
        """(taken, refused) buffered so far -- for the dashboard."""
        with self._lock:
            rows = list(self._pending.values())
        taken = sum(1 for r in rows if r["taken"])
        return taken, len(rows) - taken

    def today(self):
        """Every signal recorded today, taken AND refused, newest first.

        WHY THIS EXISTS -- the dashboard only ever received counts(), so
        the operator could see "6 taken / 3 refused" and never learn WHICH
        three or WHY. The reasons are the whole point:

            "we will get mostly idea where we are doing wrong & what
             needs to be corrected"          -- operator, 30 July 2026

        `refused_why` answers it directly, and `open_positions_at_signal`
        is the evidence for the first-come-first-served question -- a
        breakout refused with 10 positions already open was refused by
        the clock, not by a judgement about the stock.

        Reads the buffer AND the table, because a signal recorded minutes
        ago may not have been flushed yet and "not flushed" must not look
        like "did not happen".
        """
        import datetime
        today = datetime.date.today().isoformat()
        with self._lock:
            rows = [dict(r) for r in self._pending.values()]
        seen = {(r.get("symbol"), r.get("direction")) for r in rows}
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    "SELECT * FROM signals WHERE trade_date = ?", (today,)):
                row = dict(r)
                if (row.get("symbol"), row.get("direction")) not in seen:
                    rows.append(row)
        except sqlite3.Error as exc:
            diagnostic(f"[JOURNAL] today() read failed: {exc}")
        rows.sort(key=lambda r: str(r.get("first_seen") or ""), reverse=True)
        return rows


# ==========================================================
#  WHAT HAPPENED AFTER THE SIGNAL
# ==========================================================
#
#     "13,128 signals with taken and refused_why and no outcome
#      column. The bot has never scored what happened next to the
#      ones it refused."
#                        -- the gap, put to him on 18 August 2026
#
#     "do it - build the signal outcome scoring"      -- his answer
#
# WHY THIS AND NOT MORE GATES
# ---------------------------
# Every rule added to this bot so far has been reasoning: a fresh
# breakout should be at the day's high, evidence should beat no
# evidence, a full book should not silence an alert. Each is arguable
# and none has ever been checked. The journal has recorded the raw
# material for that check since 29 July and nothing has ever read it
# back.
#
# 13,333 signals. 51 taken. So the journal is almost entirely a record
# of what the bot REFUSED -- the one population no P&L statement can
# ever show him, and the only way to tell a gate that saves money from
# a gate that merely says no.
#
# TWO RESOLUTIONS, AND THE DIFFERENCE IS NOT COSMETIC
# ---------------------------------------------------
#     minute   data/history_candles.db, 19.1M rows
#              Walks the candles AFTER the signal in order, so it can
#              say whether the stop was hit BEFORE the high -- the one
#              thing that decides whether a trade made money.
#
#     daily    data/daily_candles.db
#              Day high, low and close against the break price. It
#              CANNOT say which came first. A signal showing a +4%
#              high and a -3% low may have been a winner or a
#              stop-out, and this resolution cannot tell them apart.
#              Reported, labelled, and never averaged into the minute
#              answers.
#
# The minute store stops at 2026-07-31 while signals run to today, so
# 1,411 of 13,333 can be scored properly and 12,037 only at daily
# resolution. That gap is itself a finding: tools/collector.py stopped
# filling the store the bot needs in order to learn anything.
#
# NO RULE IS CHANGED BY THIS CODE. It measures. Whether a number here
# ever becomes a gate is a separate decision made in daylight -- the
# same rule every other measurement in this repo follows.

CANDLES_DB = os.path.join("data", "history_candles.db")
DAILY_DB = os.path.join("data", "daily_candles.db")

#: The stop a structural entry actually carries, so "would it have
#: worked" is asked with the bot's own risk rather than a kind one.
SCORE_STOP_PCT = 2.5

#: A move worth calling a win, in the same terms.
SCORE_TARGET_PCT = 5.0


def _ro(path):
    """Read-only connection, or None.

    A scorer must not be able to write to a store the live bot reads.
    """
    try:
        if not os.path.exists(path):
            return None
        return sqlite3.connect("file:" + path + "?mode=ro", uri=True)
    except Exception:                                       # noqa: BLE001
        return None


def _pct(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if b <= 0:
        return None
    return (a - b) / b * 100.0


def _round(value, places=2):
    return None if value is None else round(value, places)


def _signed(value, direction):
    """A SHORT that falls 3% has made +3%.

    One sign convention for the whole file: positive is money for
    whichever side was signalled.
    """
    if value is None:
        return None
    return value if str(direction).upper() == "LONG" else -value


def _minute_walk(candles, entry, direction, stop_pct, target_pct):
    """Walk the candles in order, and answer what daily bars cannot.

    A stop is only a stop if it is hit FIRST. Reading a day's high and
    low without their order is exactly how a stopped-out trade gets
    counted as a +4% winner.
    """
    long_side = str(direction).upper() == "LONG"
    best = worst = None
    hit = None
    for row in candles:
        try:
            high, low = float(row[2]), float(row[3])
        except (TypeError, ValueError, IndexError):
            continue
        up, down = _pct(high, entry), _pct(low, entry)
        if up is None or down is None:
            continue
        favour, against = (up, down) if long_side else (-down, -up)
        best = favour if best is None else max(best, favour)
        worst = against if worst is None else min(worst, against)
        if hit is None:
            # WITHIN one candle the order is unknowable, so a candle
            # spanning both counts as the STOP. Assuming the good half
            # came first is precisely how a backtest flatters itself.
            if against <= -stop_pct:
                hit = "stop"
            elif favour >= target_pct:
                hit = "target"
    return best, worst, hit


def score_row(row, minutes=None, daily=None,
              stop_pct=SCORE_STOP_PCT, target_pct=SCORE_TARGET_PCT):
    """One signal, scored. None when it cannot be scored at all.

    `minutes` is that symbol's candles AFTER the signal, in order,
    each (minute, o, h, l, c). `daily` is (high, low, close) for the
    day. Both are handed in rather than fetched, so this is testable
    without a 3 GB store behind it.
    """
    try:
        entry = float(row.get("break_price") or 0)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    direction = str(row.get("direction") or "LONG").upper()

    out = {"trade_date": row.get("trade_date"),
           "symbol": row.get("symbol"),
           "direction": direction,
           "entry": entry,
           "taken": bool(row.get("taken")),
           "refused_why": row.get("refused_why"),
           "volume_mult": row.get("volume_mult"),
           "sector": row.get("sector"),
           "had_evidence": bool(row.get("news_kind")
                                or row.get("filing_kind")
                                or row.get("results_grade"))}

    if minutes:
        best, worst, hit = _minute_walk(minutes, entry, direction,
                                        stop_pct, target_pct)
        close_pct = _signed(_pct(minutes[-1][4], entry), direction)
        out.update({"resolution": "minute",
                    "mfe_pct": _round(best),
                    "mae_pct": _round(worst),
                    "hit_first": hit,
                    "close_pct": _round(close_pct)})
        # THE ONE NUMBER THAT IS AN ANSWER: the bot's own trade, run.
        # Stopped first is the stop. Target first is the target.
        # Neither is the close, which is what a carried position gets.
        if hit == "stop":
            out["result_pct"] = -stop_pct
        elif hit == "target":
            out["result_pct"] = target_pct
        else:
            out["result_pct"] = out["close_pct"]
        return out

    if daily:
        high, low, close = daily
        up, down = _pct(high, entry), _pct(low, entry)
        long_side = direction == "LONG"
        out.update({"resolution": "daily",
                    "mfe_pct": _round(up if long_side else
                                      (None if down is None else -down)),
                    "mae_pct": _round(down if long_side else
                                      (None if up is None else -up)),
                    "hit_first": None,
                    "close_pct": _round(_signed(_pct(close, entry),
                                                direction)),
                    "result_pct": None})
        return out
    return None


def _rows_for(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as exc:                                # noqa: BLE001
        diagnostic("[SCORE] query failed: "
                   + type(exc).__name__ + ": " + str(exc))
        return []


def score(db_path=DB_PATH, candles_db=CANDLES_DB, daily_db=DAILY_DB,
          limit=None, stop_pct=SCORE_STOP_PCT,
          target_pct=SCORE_TARGET_PCT):
    """Score every signal that can be scored. A list of dicts.

    Reads by DATE, not by signal: one query per session rather than
    13,333 of them against a nineteen-million-row table.
    """
    journal = _ro(db_path)
    if journal is None:
        return []
    journal.row_factory = sqlite3.Row
    signals = [dict(r) for r in _rows_for(
        journal, "SELECT * FROM signals ORDER BY trade_date, symbol")]
    journal.close()
    if limit:
        signals = signals[:limit]
    if not signals:
        return []

    by_date = {}
    for row in signals:
        by_date.setdefault(str(row.get("trade_date") or ""), []).append(row)

    minute_conn, daily_conn = _ro(candles_db), _ro(daily_db)
    scored = []
    for date, rows in sorted(by_date.items()):
        wanted = set(str(r.get("symbol") or "").upper() for r in rows)

        minutes = {}
        if minute_conn is not None:
            for got in _rows_for(
                    minute_conn,
                    "SELECT symbol, minute, o, h, l, c FROM candles "
                    "WHERE date = ? ORDER BY symbol, minute", (date,)):
                sym = str(got[0]).upper()
                if sym in wanted:
                    minutes.setdefault(sym, []).append(got[1:])

        daily = {}
        if daily_conn is not None:
            for got in _rows_for(
                    daily_conn,
                    "SELECT symbol, high, low, close FROM daily_bars "
                    "WHERE date = ?", (date,)):
                sym = str(got[0]).upper()
                if sym in wanted:
                    daily[sym] = (got[1], got[2], got[3])

        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            after = None
            seen = str(row.get("first_seen") or "")
            if sym in minutes and seen:
                # STRICTLY AFTER the signal. Including the signal's own
                # candle would score the bot on a move it had already
                # seen when it decided, which is not a prediction.
                after = [c for c in minutes[sym] if str(c[0]) > seen]
            got = score_row(row, minutes=after, daily=daily.get(sym),
                            stop_pct=stop_pct, target_pct=target_pct)
            if got is not None:
                scored.append(got)

    for conn in (minute_conn, daily_conn):
        if conn is not None:
            conn.close()
    return scored


def _mean(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def _summary(rows):
    minute = [r for r in rows if r.get("resolution") == "minute"]
    stopped = [r for r in minute if r.get("hit_first") == "stop"]
    target = [r for r in minute if r.get("hit_first") == "target"]
    closes = [r for r in rows if r.get("close_pct") is not None]
    return {
        "n": len(rows),
        "n_minute": len(minute),
        "avg_mfe_pct": _mean([r.get("mfe_pct") for r in rows]),
        "avg_mae_pct": _mean([r.get("mae_pct") for r in rows]),
        "avg_close_pct": _mean([r.get("close_pct") for r in rows]),
        "avg_result_pct": _mean([r.get("result_pct") for r in minute]),
        "stopped_first_pct": (round(len(stopped) * 100.0 / len(minute), 1)
                              if minute else None),
        "target_first_pct": (round(len(target) * 100.0 / len(minute), 1)
                             if minute else None),
        "up_at_close_pct": (
            round(sum(1 for r in closes if r["close_pct"] > 0)
                  * 100.0 / len(closes), 1) if closes else None),
    }


def report(scored=None, min_cases=20, **kwargs):
    """The questions the journal was always able to answer.

    Nothing here is a rule, and nothing becomes one by being printed.
    It is a measurement, and it is allowed to report that a gate this
    bot already trusts is not sorting anything.
    """
    rows = scored if scored is not None else score(**kwargs)
    if not rows:
        return {"available": False,
                "why": "no signal could be scored -- check that "
                       "data/history_candles.db and "
                       "data/daily_candles.db cover the journal's dates"}

    groups = {}
    for row in rows:
        groups.setdefault(str(row.get("refused_why") or "TAKEN")[:70],
                          []).append(row)
    by_reason = {why: _summary(group) for why, group in groups.items()
                 if len(group) >= min_cases}   # a bucket of 3 is not a finding

    return {
        "available": True,
        "overall": _summary(rows),
        "resolutions": {
            "minute": sum(1 for r in rows if r["resolution"] == "minute"),
            "daily": sum(1 for r in rows if r["resolution"] == "daily")},
        # HIS OWN HYPOTHESIS, MEASURED. 18 August 2026:
        #   "stocks raising with underlying evidence must have added
        #    advantage rather than normal breakout stocks"
        # That is a claim about outcomes, so it can be checked, and
        # this is the number that checks it.
        "evidence": {
            "with": _summary([r for r in rows if r["had_evidence"]]),
            "without": _summary([r for r in rows if not r["had_evidence"]])},
        "taken": {
            "taken": _summary([r for r in rows if r["taken"]]),
            "refused": _summary([r for r in rows if not r["taken"]])},
        "by_refusal": dict(sorted(
            by_reason.items(),
            key=lambda kv: -(kv[1]["avg_close_pct"]
                             if kv[1]["avg_close_pct"] is not None
                             else -99))),
    }
