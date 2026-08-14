"""
==========================================================
Reading a finished session back off the disk
==========================================================

    "todays all data gone?"
    "if possible show me all available data including news, events,
     trades and all we did today in this new dashboard"
                                    -- operator, 29 July 2026, night

WHY THIS EXISTS
---------------
No. Almost nothing was lost -- but almost nothing was VISIBLE either,
and to the operator those are the same thing.

The dashboard reads the live Engine's own memory: open_positions,
closed_positions, entry_blocked, the breakout feed, the news and
announcement watchers. Every one of those is in RAM and only in RAM.
main.py exits at 15:30, the process dies, and the screen that showed
a whole trading day goes blank -- while the day itself is still
sitting on disk in five different stores that nothing reads back:

    data/trade_memory.db      every closed trade, with its reason
    data/backtest_candles.db  every minute of every symbol
    data/premarket.json       the overnight world
    logs/trade_log.csv        every order actually sent
    logs/diagnostics_*.log    news, filings, refusals, breakouts

This module reads those five and hands back the same shapes the live
Engine would have held, so the dashboard can render a finished day
exactly as it rendered the live one.

WHAT IT IS NOT
--------------
It does not simulate, re-decide, or re-price anything. It reports
what was recorded. If the bot did not write it down, this module
does not invent it -- a replayed panel is either the truth or it is
visibly empty, never a plausible guess.

TWO THINGS GENUINELY DO NOT SURVIVE, and the dashboard says so
rather than showing a confident blank:

    pre-open book   NSE only publishes it 09:00-09:12 and nothing
                    stored it today -- gone until tomorrow 09:12.
    circuit bands   polled live from Dhan, never persisted. The
                    replay leaves them None, so "how close to the
                    upper circuit" reads as unknown, not as zero.

Read-only. Opens every store read-only, writes nothing, and every
single source is independently optional -- a missing log costs you
that one panel and nothing else.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os
import re
import sqlite3
from datetime import datetime
from urllib.parse import quote

from core.logger import diagnostic

CANDLES_DB = os.path.join("data", "backtest_candles.db")
TRADE_MEMORY_DB = os.path.join("data", "trade_memory.db")
TRADE_LOG_CSV = os.path.join("logs", "trade_log.csv")
LOG_GLOB = os.path.join("logs", "diagnostics*.log*")

# Symbols that only ever existed inside a pytest run. They reached the
# live diagnostics log all through 27-28 July and would otherwise fill
# the replayed panels with fiction.
FIXTURES = {"X", "AAA", "BBB", "NEW", "OLD", "WEAK", "STRONG", "HOLD",
            "TESTCO", "UP_CO", "DOWN_CO", "PENNY", "WAKEFIT", "SYM"}

_TS = "%Y-%m-%d %H:%M:%S"


def _dt(value):
    """A datetime, or None. dashboard/state.py calls .strftime() on
    entry_time / exit_time, so a string here would crash the panel."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", _TS, "%Y-%m-%d %H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _sqlite_uri(path):
    """A read-only SQLite URI that works on Windows as well as Linux.

    sqlite3.connect(..., uri=True) parses the string as a URI, and a
    URI path is NOT a Windows path:

        file:data\\trade_memory.db?mode=ro   -> unable to open
        file:D:\\Opportunity Trader\\...     -> unable to open

    os.path.join hands back backslashes on Windows and this project
    lives at "D:\\Opportunity Trader" -- a path with a space in it,
    which also has to be percent-escaped. The first version of this
    module opened every store this way, so on Windows the replay read
    NOTHING while it read everything on a POSIX box. A "works on my
    machine" bug in the most literal sense.

    Correct form, both platforms:

        file:///D:/Opportunity%20Trader/data/trade_memory.db?mode=ro
        file:///home/user/bot/data/trade_memory.db?mode=ro
    """
    absolute = os.path.abspath(path).replace(os.sep, "/").replace("\\", "/")
    safe = quote(absolute, safe="/:")
    if not safe.startswith("/"):
        safe = "/" + safe                 # Windows "D:/..." -> "/D:/..."
    return f"file://{safe}?mode=ro"


def _ro(path):
    """Open a database strictly read-only.

    The live bot may be running. A replay that could write to the
    trade record would be a far worse bug than a blank panel.
    """
    return sqlite3.connect(_sqlite_uri(path), uri=True)


class SessionReplay:
    """One finished trading day, read back off the disk."""

    @staticmethod
    def latest_date(candles_db=CANDLES_DB):
        """The most recent date that actually HAS a session.

        NOT today. Today at 01:00 is a date with no candles, no trades
        and no log -- and defaulting to it made the whole preview look
        like it had been wiped:

            "i closed & re run as day changed everything reset"

        Nothing had reset. It was reading an empty date. A replay of
        "the last session" is what is wanted every single time; asking
        for a specific day is the exception, so the default now means
        the last day with data in it.
        """
        try:
            conn = _ro(candles_db)
            row = conn.execute("SELECT MAX(date) FROM candles").fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
        except (sqlite3.Error, OSError):
            pass
        return datetime.now().strftime("%Y-%m-%d")

    def __init__(self, date=None, candles_db=CANDLES_DB,
                 trade_memory_db=TRADE_MEMORY_DB,
                 trade_log=TRADE_LOG_CSV, log_glob=LOG_GLOB):
        self.date = date or self.latest_date(candles_db)
        self.candles_db = candles_db
        self.trade_memory_db = trade_memory_db
        self.trade_log = trade_log
        self.log_glob = log_glob
        self._lines = None
        self._notes = []
        self._prev_close_source = None

    # ------------------------------------------------------------
    # what could not be recovered -- shown on screen, never hidden
    # ------------------------------------------------------------

    def notes(self):
        return list(self._notes)

    def _missing(self, what, why):
        self._notes.append({"what": what, "why": why})
        diagnostic(f"[REPLAY] {what}: {why}")

    # ------------------------------------------------------------
    # trades -- data/trade_memory.db
    # ------------------------------------------------------------

    def closed_positions(self):
        """Every trade closed on this date, in the exact shape
        engine.closed_positions holds -- so dashboard/state.py's
        _build_closed_positions() needs no special case at all.

        P&L is read, never recomputed. The bot's own recorded figure
        is the one that must appear; a second calculation here would
        eventually disagree with the first and there would be no way
        to tell which screen was lying.
        """
        if not os.path.exists(self.trade_memory_db):
            self._missing("closed trades", "data/trade_memory.db not found")
            return []
        try:
            conn = _ro(self.trade_memory_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trade_memory WHERE trade_date = ? "
                "ORDER BY exit_time", (self.date,)).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            self._missing("closed trades", f"{exc}")
            return []

        out = []
        for row in rows:
            entry_time = _dt(row["entry_time"])
            exit_time = _dt(row["exit_time"])
            holding = row["holding_minutes"]
            out.append({
                "symbol": row["symbol"],
                "direction": row["direction"] or "LONG",
                "qty": row["qty"],
                "entry_price": row["entry_price"],
                "exit_price": row["exit_price"],
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_reason": row["entry_reason"],
                "exit_reason": row["exit_reason"],
                "pnl": row["pnl"],
                "holding_seconds": (holding * 60) if holding else None,
                # Never persisted per trade. None reads as "unknown"
                # on the dashboard; 0 would read as a stop at zero.
                "initial_stop": None,
                "fixed_target": None,
                "sector": row["sector"],
                "news_kind": row["news_kind"],
                "filing_kind": row["filing_kind"],
                "results_grade": row["results_grade"],
            })
        return out

    # ------------------------------------------------------------
    # prices -- data/backtest_candles.db
    # ------------------------------------------------------------

    def _prev_session(self):
        """The trading day before this one, as the candle store itself
        saw it -- not date minus one, which lands on a Sunday every
        weekend and on every exchange holiday."""
        try:
            conn = _ro(self.candles_db)
            row = conn.execute(
                "SELECT MAX(date) FROM candles WHERE date < ?",
                (self.date,)).fetchone()
            conn.close()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def _official_closes(self, date):
        """NSE's published close for a date, from data/daily_candles.db
        (loaded from the exchange's own bhavcopy). {} if that day was
        never downloaded -- `py tools/preflight.py` fills the gaps."""
        path = os.path.join("data", "daily_candles.db")
        if not os.path.exists(path):
            return {}
        try:
            conn = _ro(path)
            rows = conn.execute(
                "SELECT symbol, close FROM daily_bars "
                "WHERE date = ? AND series = 'EQ'", (date,)).fetchall()
            conn.close()
            return {s: c for s, c in rows if c}
        except sqlite3.Error:
            return {}

    def day_quotes(self):
        """Per symbol: the day's real open / high / low / close /
        volume, and the previous session's close.

        This is what makes the whole LIVE tab work after hours --
        breadth, top gainers and losers, sector strength and the
        movers table all read engine.get_circuit_snapshot(), and
        this returns exactly that shape from the minute candles the
        bot recorded itself.

        The % change is left to the dashboard, which computes it the
        one way the operator insists on -- against the previous
        close, NSE's own convention. Nothing is computed twice here.
        """
        if not os.path.exists(self.candles_db):
            self._missing("prices", "data/backtest_candles.db not found")
            return {}
        try:
            conn = _ro(self.candles_db)
            rows = conn.execute(
                "SELECT symbol, MIN(minute), MAX(minute), MAX(h), MIN(l), "
                "       SUM(v), COUNT(*) "
                "FROM candles WHERE date = ? GROUP BY symbol", (self.date,)
            ).fetchall()
            if not rows:
                conn.close()
                self._missing("prices", f"no candles stored for {self.date}")
                return {}

            # open = first minute's open, close = last minute's close.
            firsts = dict(conn.execute(
                "SELECT symbol, o FROM candles c WHERE date = ? AND minute = "
                "(SELECT MIN(minute) FROM candles WHERE date = c.date "
                " AND symbol = c.symbol)", (self.date,)).fetchall())
            lasts = dict(conn.execute(
                "SELECT symbol, c FROM candles c WHERE date = ? AND minute = "
                "(SELECT MAX(minute) FROM candles WHERE date = c.date "
                " AND symbol = c.symbol)", (self.date,)).fetchall())

            prev_date = self._prev_session()
            prevs = {}
            if prev_date:
                prevs = dict(conn.execute(
                    "SELECT symbol, c FROM candles c WHERE date = ? AND minute = "
                    "(SELECT MAX(minute) FROM candles WHERE date = c.date "
                    " AND symbol = c.symbol)", (prev_date,)).fetchall())
            else:
                self._missing("previous close",
                              "no earlier session in the candle store")
            conn.close()

            # NSE'S OWN NUMBER WINS. Our last minute candle is NOT the
            # official close -- measured against the 27 July bhavcopy
            # it is 0.15% out at the median and more than 1% out on
            # nine symbols, because the snapshot feed never sees the
            # closing auction. The operator's standing rule decides
            # this: "change in % of stock raising / falling must
            # follow with NSE -- do not invent on our own formulas."
            # So the bhavcopy figure is used wherever one exists and
            # the candle close only fills the gaps.
            self._prev_close_source = "our own snapshot feed"
            if prev_date:
                official = self._official_closes(prev_date)
                if official:
                    # Only symbols we actually track. Merging the whole
                    # bhavcopy would add 2,400 symbols we never trade
                    # and make the coverage count meaningless.
                    covered = 0
                    for symbol in list(prevs):
                        if symbol in official:
                            prevs[symbol] = official[symbol]
                            covered += 1
                    self._prev_close_source = (
                        f"NSE bhavcopy for {prev_date} on {covered} of "
                        f"{len(prevs)} symbols; the rest from our own "
                        f"last candle")
        except sqlite3.Error as exc:
            self._missing("prices", f"{exc}")
            return {}

        quotes = {}
        for symbol, _first_min, _last_min, high, low, volume, count in rows:
            if symbol in FIXTURES:
                continue
            quotes[symbol] = {
                "last_price": lasts.get(symbol),
                "prev_close": prevs.get(symbol),
                "open": firsts.get(symbol),
                "high": high, "low": low, "volume": volume,
                # Never persisted. None means unknown, and the card
                # says "unknown" rather than drawing a band at zero.
                "upper_circuit_limit": None,
                "lower_circuit_limit": None,
                "minutes": count,
                "replayed": True,
            }
        if prev_date:
            missing = sum(1 for q in quotes.values() if not q["prev_close"])
            if missing:
                self._missing(
                    "previous close",
                    f"{missing} of {len(quotes)} symbols had no candle on "
                    f"{prev_date} -- those show no % change")
        return quotes

    def post_exit(self, trades=None):
        """For every trade closed that day, where the stock went after.

        Live, engine._watch_after_exit() follows each symbol tick by
        tick. A finished day has no ticks -- but it has every minute
        candle, so the same answer is one query away:

            KAYNES exited 10:14 at 3,398 -> high of 3,684.70 by 14:22

        Same shape the engine holds, so dashboard/state.py cannot tell
        the two apart and needs no replay-specific branch.
        """
        trades = self.closed_positions() if trades is None else trades
        if not trades or not os.path.exists(self.candles_db):
            return {}
        out = {}
        try:
            conn = _ro(self.candles_db)
            for trade in trades:
                exit_time = trade.get("exit_time")
                exit_price = trade.get("exit_price")
                if not exit_time or not exit_price:
                    continue
                after = exit_time.strftime("%Y-%m-%dT%H:%M")
                row = conn.execute(
                    "SELECT MAX(h), MIN(l) FROM candles WHERE date = ? "
                    "AND symbol = ? AND minute > ?",
                    (self.date, trade["symbol"], after)).fetchone()
                last = conn.execute(
                    "SELECT c FROM candles WHERE date = ? AND symbol = ? "
                    "ORDER BY minute DESC LIMIT 1",
                    (self.date, trade["symbol"])).fetchone()
                if not row or row[0] is None:
                    continue
                peak_at = conn.execute(
                    "SELECT minute FROM candles WHERE date = ? AND symbol = ? "
                    "AND minute > ? AND h = ? LIMIT 1",
                    (self.date, trade["symbol"], after, row[0])).fetchone()
                out[trade["symbol"]] = {
                    "exit_price": exit_price, "exit_time": exit_time,
                    "last": last[0] if last else row[0],
                    "peak": row[0], "trough": row[1],
                    "peak_at": _dt((peak_at[0] or "").replace("T", " "))
                    if peak_at else None,
                }
            conn.close()
        except sqlite3.Error as exc:
            self._missing("move after exit", f"{exc}")
            return {}
        return out

    def last_prices(self):
        """{symbol: closing price} -- fed into MarketData so open
        positions and the stock card show a price rather than a dash."""
        return {s: q["last_price"] for s, q in self.day_quotes().items()
                if q.get("last_price")}

    # ------------------------------------------------------------
    # the session log -- news, filings, refusals, breakouts
    # ------------------------------------------------------------

    def _log_lines(self):
        """Every line this date wrote, across every log file.

        main.py logs to logs/diagnostics_<pid>.log and rotates to
        .log.1, so one session is spread over several files and the
        plain diagnostics.log may be days stale. Files not touched
        since the date are skipped without being opened -- otherwise
        this reads a hundred megabytes to find one day.
        """
        if self._lines is not None:
            return self._lines
        cutoff = _dt(self.date + " 00:00:00")
        seen, lines = set(), []
        for path in glob.glob(self.log_glob):
            try:
                if cutoff and datetime.fromtimestamp(
                        os.path.getmtime(path)) < cutoff:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        if not line.startswith(self.date):
                            continue
                        line = line.rstrip("\n")
                        # The same session is written twice whenever a
                        # log rotates mid-run.
                        if line in seen:
                            continue
                        seen.add(line)
                        lines.append(line)
            except OSError:
                continue
        lines.sort(key=lambda ln: ln[:19])
        self._lines = lines
        if not lines:
            self._missing("session log",
                          f"no log file holds any line from {self.date}")
        return lines

    def _stamped_lines(self):
        """Every line in this date's files, INCLUDING the ones that
        carry no timestamp of their own.

        The ORB breakout banner prints as a block:

            ORB BREAKOUT   : JYOTHYLAB
            Breakout Close : 208.17

        Neither line starts with a date, so _log_lines() drops both
        and the breakouts panel silently reads zero -- which is
        exactly what it did on the first run of this module. Here the
        last real timestamp seen is carried forward, so a banner line
        inherits the time of the log entry it belongs to.
        """
        cutoff = _dt(self.date + " 00:00:00")
        out = []
        for path in sorted(glob.glob(self.log_glob)):
            try:
                if cutoff and datetime.fromtimestamp(
                        os.path.getmtime(path)) < cutoff:
                    continue
                stamp = None
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.rstrip("\n")
                        if line[:10] == self.date:
                            stamp = line[11:19]
                        elif line[:4].isdigit():
                            stamp = None        # a different day's block
                        if stamp:
                            out.append((stamp, line))
            except OSError:
                continue
        return out

    @staticmethod
    def _at(line):
        return line[11:19]

    def _tagged(self, tag):
        needle = f"[{tag}]"
        return [ln for ln in self._log_lines() if needle in ln]

    _NEWS = re.compile(
        r"\[NEWS\] ([A-Z0-9&_-]+) -- (\w+) filed (\d\d:\d\d:\d\d)"
        r"[^:]*: (.+)$")

    def news_rows(self):
        """Every filing the announcement watcher actually saw today.

        Neither watcher persists anything, so this is the only record
        that survives the process -- and the operator's complaint was
        precisely that he could not see them:

            "both me & bot didn't know whats going in the market,
             which stock is getting results?"
        """
        rows = []
        for line in self._tagged("NEWS"):
            match = self._NEWS.search(line)
            if not match:
                continue
            symbol, kind, filed_at, subject = match.groups()
            if symbol in FIXTURES:
                continue
            rows.append({"symbol": symbol, "kind": kind,
                         "filed_at": filed_at, "at": filed_at,
                         "subject": subject.strip(),
                         "headline": subject.strip(),
                         "seen_at": self._at(line)})
        return rows

    _FILING = re.compile(r"\[FILING\] ([A-Z0-9&_-]+): read (\d+) quarters"
                         r"[^-]*-- (.+)$")

    def result_rows(self):
        """Results PDFs read and graded during the session."""
        rows = []
        for line in self._tagged("FILING"):
            match = self._FILING.search(line)
            if not match:
                continue
            symbol, quarters, verdict = match.groups()
            if symbol in FIXTURES:
                continue
            grade = verdict.split(":")[0].strip()
            rows.append({"symbol": symbol, "quarters": int(quarters),
                         "grade": grade, "summary": verdict.strip(),
                         # `kind` is not decoration. dashboard/state.py's
                         # shortlist reads row["kind"] directly, and a
                         # row without it took the WHOLE shortlist panel
                         # down with a KeyError -- caught by running the
                         # replay, not by any test.
                         "kind": "RESULTS",
                         "headline": f"{grade}: {verdict.strip()}",
                         "at": self._at(line)})
        return rows

    _REFUSED = re.compile(r"\[NO_TRADE\] ([A-Z0-9&_-]+) (LONG|SHORT) "
                          r"skipped -- (.+?)(?: No \w+ trade for .*)?$")
    _GATED = re.compile(r"\[RESULTS_GATE\] ([A-Z0-9&_-]+) blocked -- (.+)$")

    def refusals(self):
        """Every stock the bot looked at and would not buy, and why.

        The single most useful record of a session in which the bot
        took 29 trades out of a 666-symbol universe -- and until
        tonight it existed only as scrolling text in a terminal.
        """
        rows, seen = [], set()
        for line in self._tagged("NO_TRADE"):
            match = self._REFUSED.search(line)
            if not match:
                continue
            symbol, direction, why = match.groups()
            if symbol in FIXTURES or (symbol, why) in seen:
                continue
            seen.add((symbol, why))
            rows.append({"symbol": symbol, "direction": direction,
                         "reason": why.strip(), "at": self._at(line),
                         "source": "entry rule"})
        for line in self._tagged("RESULTS_GATE"):
            match = self._GATED.search(line)
            if not match:
                continue
            symbol, why = match.groups()
            if symbol in FIXTURES or (symbol, why) in seen:
                continue
            seen.add((symbol, why))
            rows.append({"symbol": symbol, "direction": "LONG",
                         "reason": why.strip(), "at": self._at(line),
                         "source": "results gate"})
        rows.sort(key=lambda r: r["at"])
        return rows

    _BREAKOUT = re.compile(r"ORB (BREAKOUT|BREAKDOWN)\s*: ([A-Z0-9&_-]+)")

    def breakouts(self):
        """Every opening-range break the bot saw, taken or not."""
        rows, seen = [], set()
        for stamp, line in self._stamped_lines():
            match = self._BREAKOUT.search(line)
            if not match:
                continue
            kind, symbol = match.groups()
            if symbol in FIXTURES:
                continue
            key = (symbol, kind)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"symbol": symbol,
                         "direction": "LONG" if kind == "BREAKOUT" else "SHORT",
                         "at": stamp})
        rows.sort(key=lambda r: r["at"])
        return rows

    _FILL = re.compile(
        r"(PAPER|LIVE) (BUY|SELL)\s+([A-Z0-9&_-]+)\s+qty=(\d+) @ ([\d.]+) "
        r"\(([A-Z_]+)\)(?:\s+\[wanted ([\d.]+), slipped ([\d.]+) = Rs (\d+)\])?")

    def fills(self):
        """Every fill, with what it was meant to be and what it cost.

            "while buying & selling slippages too cost us"
                                        -- operator, 29 July 2026

        The bot has printed the slipped rupees on every single fill
        all along. Nothing has ever added them up.
        """
        rows = []
        for stamp, line in self._stamped_lines():
            match = self._FILL.search(line)
            if not match:
                continue
            mode, side, symbol, qty, price, reason, wanted, slip, cost = \
                match.groups()
            if symbol in FIXTURES:
                continue
            rows.append({
                "at": stamp, "mode": mode, "side": side, "symbol": symbol,
                "qty": int(qty), "price": float(price), "reason": reason,
                "wanted": float(wanted) if wanted else None,
                "slipped": float(slip) if slip else None,
                "slippage_rs": float(cost) if cost else 0.0,
            })
        rows.sort(key=lambda r: r["at"])
        return rows

    def slippage_total(self):
        """What the gap between intended and actual price cost today."""
        rows = self.fills()
        return {
            "fills": len(rows),
            "total_rs": round(sum(r["slippage_rs"] for r in rows), 2),
            "worst": max(rows, key=lambda r: r["slippage_rs"], default=None),
        }

    _MISSED = re.compile(r"\[MISSED_STOP\] ([A-Z0-9&_-]+) (LONG|SHORT) traded "
                         r"to ([\d.]+), through a stop of ([\d.]+)")

    def missed_stops(self):
        """Stops the snapshot feed never showed us a tick for. These
        are the real cost of a 4.6-second snapshot cadence and belong
        on screen, not buried in a warning."""
        rows = []
        for line in self._tagged("MISSED_STOP"):
            match = self._MISSED.search(line)
            if not match:
                continue
            symbol, direction, traded, stop = match.groups()
            if symbol in FIXTURES:
                continue
            rows.append({"symbol": symbol, "direction": direction,
                         "traded_to": float(traded), "stop": float(stop),
                         "at": self._at(line)})
        return rows

    def warnings(self):
        """The session's own warnings, deduplicated by message.

        The [MTF] leverage failure appeared twelve times today and
        the operator saw it only because he happened to be reading
        the terminal.
        """
        counts, first = {}, {}
        for line in self._log_lines():
            if "[WARNING]" not in line:
                continue
            text = line.split("WARNING: ", 1)[-1].strip()
            # Collapse per-symbol repeats into one row with a count.
            key = re.sub(r"\b[A-Z0-9&_-]{3,}\b(?=:)", "<symbol>", text)
            counts[key] = counts.get(key, 0) + 1
            first.setdefault(key, self._at(line))
        rows = [{"message": k, "count": v, "first_at": first[k]}
                for k, v in counts.items()]
        rows.sort(key=lambda r: -r["count"])
        return rows

    # ------------------------------------------------------------
    # orders -- logs/trade_log.csv
    # ------------------------------------------------------------

    def actions(self):
        """Every order actually sent today, from the order log."""
        if not os.path.exists(self.trade_log):
            self._missing("orders", "logs/trade_log.csv not found")
            return []
        rows = []
        try:
            with open(self.trade_log, encoding="utf-8", errors="ignore") as fh:
                for row in csv.DictReader(fh):
                    when = (row.get("time") or "")
                    if not when.startswith(self.date):
                        continue
                    if (row.get("symbol") or "") in FIXTURES:
                        continue
                    rows.append({
                        "at": when[11:19],
                        "action": (row.get("side") or "").upper(),
                        "symbol": row.get("symbol"),
                        "qty": row.get("qty"),
                        "price": row.get("price"),
                        "detail": row.get("reason"),
                        "ok": True,
                    })
        except OSError as exc:
            self._missing("orders", f"{exc}")
            return []
        rows.sort(key=lambda r: r["at"], reverse=True)
        return rows

    # ------------------------------------------------------------

    def summary(self):
        """One line per source: what was recovered, what was not."""
        trades = self.closed_positions()
        quotes = self.day_quotes()
        return {
            "date": self.date,
            "trades": len(trades),
            "pnl": round(sum(t["pnl"] or 0 for t in trades), 2),
            "symbols_priced": len(quotes),
            "prev_close_source": self._prev_close_source,
            "filings": len(self.news_rows()),
            "results_read": len(self.result_rows()),
            "refusals": len(self.refusals()),
            "breakouts": len(self.breakouts()),
            "orders": len(self.actions()),
            "missed_stops": len(self.missed_stops()),
            "warnings": len(self.warnings()),
            "fills": self.slippage_total()["fills"],
            "slippage_rs": self.slippage_total()["total_rs"],
            "not_recovered": self.notes(),
        }
