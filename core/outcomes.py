"""
==========================================================
What happened AFTER each chip
==========================================================

    "the bot is good at showing you evidence and has never been
     measured at predicting anything"
                    -- the honest audit, 1 August 2026

Every layer built to this point describes the PAST. quarterly_results
reads what was reported, Earnings Pulse grades it, the tally counts
which metrics cleared the bar, the AI explains one story. Not one of
them has ever been checked against what the stock then DID.

The one measurement that exists -- core/reaction.py -- covers results
grades only, and its answer is uncomfortable. On 665 graded results:

    CONFIRMS      35.5%    grade and move agreed
    NO REACTION   42.9%    the move was inside the noise
    PRICED IN     14.0%    good result, stock fell
    LESS BAD       7.7%    weak result, stock rose

A grade points the wrong way 21.7% of the time. This module asks the
same question of EVERY chip, so that "which of these is worth reading"
stops being a matter of opinion.

WHAT IT MEASURES
----------------
For each event that produced a chip: the move on the session AFTER
it, against yesterday's close. Same rule as core/reaction.py -- news
filed after 15:30 is answered by the NEXT session, because reading the
same day's move would credit the news with a move that finished before
the news existed.

THE BASELINE IS NOT OPTIONAL
----------------------------
"Stocks with an ORDER WIN chip averaged +0.8%" says nothing on a day
the whole market rose 0.8%. Every number here is reported against the
MEDIAN move of every stock that traded that session, so what comes out
is an EDGE and not a market direction.

The median, not the mean: one stock at +19% on a listing day drags a
mean and tells you nothing about the middle.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not change a single score, and nothing in the trading path
imports it. Re-weighting the panel on four days of data would be
exactly the mistake tools/refused_review.py already warns about:

    "Do not change a rule on one day of this. Most buckets need a
     fortnight before they mean anything."

It reports N beside every number for the same reason. A chip seen
eleven times has no lesson in it yet, and the honest thing is to say
so rather than round it into a recommendation.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from core.logger import diagnostic
from core.reaction import Reaction

EVENTS_DB = os.path.join("data", "stock_events.db")
DAILY_DB = os.path.join("data", "daily_candles.db")
MINUTE_DB = os.path.join("data", "history_candles.db")

# The stored event stamp is UTC. The market runs on IST.
IST_OFFSET = timedelta(hours=5, minutes=30)

# Below this a bucket is a coincidence, not a finding. Reported, but
# never described as a result.
MIN_SAMPLE = 20


# ---------------------------------------------------------------
# WHICH CHIP DID THIS EVENT PRODUCE?
# ---------------------------------------------------------------
# Read off the STORED event rather than by re-running the panel, on
# purpose: the panel's output depends on price, volume and the other
# events beside it, and mixing those in would measure the whole row
# instead of the one chip being asked about.
_CHIP_RULES = (
    ("ONE-OFF", re.compile(r"^ONE-?OFF\b", re.I)),
    ("NOT CLEAN", re.compile(r"^NOT\s+CLEAN\b", re.I)),
    ("WATCH gauge", re.compile(r"^WATCH\b", re.I)),
    ("CLEAN brief", re.compile(r"^CLEAN\s*\|", re.I)),
    ("BEAT/MISS tally", re.compile(r"^(BEAT|MISS|MET)\b", re.I)),
    ("vs estimate", re.compile(r"\bvs\s+est\b", re.I)),
)

_EXPECTED = re.compile(r"^EXPECTED\s+(BULLISH|BEARISH|NEUTRAL)\b", re.I)


def chips_for(event):
    """Every chip label this one event is responsible for.

    A card can earn more than one -- a brief carrying both a grade and
    a flagged one-off is two separate claims about the same quarter,
    and they are measured separately.
    """
    out = []
    head = str(event.get("headline") or "")
    kind = str(event.get("kind") or "").upper()
    grade = str(event.get("grade") or "").upper()

    if kind == "RESULT" and grade:
        out.append(f"PULSE {grade}")
    if kind == "ORDER":
        out.append("ORDER WIN")

    hit = _EXPECTED.match(head)
    if hit:
        out.append(f"EXPECTED {hit.group(1).upper()}")

    for label, pattern in _CHIP_RULES:
        if pattern.search(head):
            out.append(label)

    direction = str(event.get("ai_direction") or "").strip().upper()
    if direction in ("POSITIVE", "NEGATIVE"):
        out.append(f"AI {direction}")
    return out


# ---------------------------------------------------------------
# THE BASELINE
# ---------------------------------------------------------------
class Baseline:
    """The median move of everything that traded, per session.

    Without it a chip that "averages +0.8%" cannot be told apart from
    a market that rose 0.8%.
    """

    def __init__(self, db_path=DAILY_DB):
        self.db_path = db_path
        self._cache = {}

    def median_move(self, on_date):
        if on_date in self._cache:
            return self._cache[on_date]
        value = None
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT close, prev_close FROM daily_bars "
                "WHERE date = ? AND prev_close > 0 AND close > 0",
                (on_date,)).fetchall()
            conn.close()
            moves = [(c / p - 1.0) * 100.0 for c, p in rows]
            if len(moves) >= 100:
                value = round(statistics.median(moves), 3)
        except sqlite3.Error as exc:
            diagnostic(f"[OUTCOMES] baseline {on_date}: {exc}")
        self._cache[on_date] = value
        return value


# ---------------------------------------------------------------
# THE MEASUREMENT
# ---------------------------------------------------------------
def measure(events_db=EVENTS_DB, daily_db=DAILY_DB, hours=None):
    """{chip: {n, edge_median, edge_mean, up_pct, sample}} .

    `edge` is the stock's move MINUS the market's median that session.
    """
    reaction = Reaction(db_path=daily_db)
    baseline = Baseline(db_path=daily_db)

    try:
        conn = sqlite3.connect(events_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, at, kind, grade, headline, ai_direction "
            "FROM events WHERE symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] could not read events: {exc}")
        return {}

    buckets = defaultdict(list)
    unanswered = 0
    for raw in rows:
        # dict, not sqlite3.Row -- chips_for() takes a mapping so the
        # same function works on a replayed event and on a test case.
        row = dict(raw)
        labels = chips_for(row)
        if not labels:
            continue
        move, on_date = reaction.move_after(row["symbol"], row["at"])
        if move is None:
            # The normal case for anything filed in the last session.
            # It must never be counted as a zero.
            unanswered += 1
            continue
        market = baseline.median_move(on_date)
        if market is None:
            continue
        edge = round(move - market, 3)
        for label in labels:
            buckets[label].append((row["symbol"], on_date, move, edge))

    out = {}
    for label, hits in buckets.items():
        edges = [h[3] for h in hits]
        out[label] = {
            "n": len(edges),
            "edge_median": round(statistics.median(edges), 2),
            "edge_mean": round(statistics.fmean(edges), 2),
            "up_pct": round(100.0 * sum(1 for e in edges if e > 0)
                            / len(edges), 1),
            "enough": len(edges) >= MIN_SAMPLE,
            "sample": sorted(hits, key=lambda h: -abs(h[3]))[:3],
        }
    out["_unanswered"] = unanswered
    return out



# ---------------------------------------------------------------
# THE SAME QUESTION, ASKED PER KIND OF BUSINESS
# ---------------------------------------------------------------
#     "the grader has no concept of provisions or asset quality --
#      which for a lender IS the result"
#                       -- claimed in the audit, 1 August 2026
#
# That claim came from ONE case. APTUS was graded STRONG on +19% YoY
# profit and fell 5.77% because provisions had doubled, and it was
# treated ever after as proof that lenders need their own grader.
#
# Measured the moment the machinery existed to measure it:
#
#     A GOOD-or-better grade      N     EDGE     UP%
#     lenders (broad, 120 names)  50   +0.60    74.0
#     everything else            394   +0.79    62.9
#
# Lenders did FINE -- a better hit rate than everything else. Narrowed
# to banks only the edge turns negative, but on EIGHT samples, which
# is an anecdote wearing a decimal point.
#
# So no lender-specific grader was built. There is no measured problem
# to fix, and building one on n=8 is how a bot acquires a rule nobody
# can ever justify removing. This function exists so the question
# answers itself in a fortnight instead.
_SECTOR_RULES = (
    ("BANK", re.compile(r"\bbank\b", re.I)),
    ("NBFC / HFC", re.compile(r"nbfc|housing finance|microfinanc|"
                              r"non.?banking financ", re.I)),
    ("BROKER / AMC", re.compile(r"asset management|broking|brokerage|"
                                r"capital market|wealth", re.I)),
)


def sector_of(record):
    """Which measurement group a master-file record belongs to."""
    if not record:
        return "everything else"
    blob = " ".join(str(record.get(k) or "") for k in
                    ("SECTOR", "INDUSTRY", "COMPANY NAME", "CORE BUSINESS"))
    for label, pattern in _SECTOR_RULES:
        if pattern.search(blob):
            return label
    return "everything else"


def by_sector(master_loader, chip_prefix="PULSE ",
              events_db=EVENTS_DB, daily_db=DAILY_DB):
    """{sector: {n, edge_median, up_pct, enough}} for one family of chips.

    Returns {} without a master loader -- the sector has to come from
    somewhere, and guessing it from the ticker would be worse than not
    answering.
    """
    if master_loader is None:
        return {}
    reaction = Reaction(db_path=daily_db)
    baseline = Baseline(db_path=daily_db)
    try:
        conn = sqlite3.connect(events_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, at, kind, grade, headline, ai_direction "
            "FROM events WHERE symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] by_sector: {exc}")
        return {}

    groups, cache = defaultdict(list), {}
    for raw in rows:
        row = dict(raw)
        if not any(c.startswith(chip_prefix) for c in chips_for(row)):
            continue
        move, on_date = reaction.move_after(row["symbol"], row["at"])
        if move is None:
            continue
        market = baseline.median_move(on_date)
        if market is None:
            continue
        symbol = row["symbol"]
        if symbol not in cache:
            try:
                cache[symbol] = sector_of(master_loader.get_by_symbol(symbol))
            except Exception:                              # noqa: BLE001
                cache[symbol] = "everything else"
        groups[cache[symbol]].append(move - market)

    return {label: {
        "n": len(edges),
        "edge_median": round(statistics.median(edges), 2),
        "up_pct": round(100.0 * sum(1 for e in edges if e > 0)
                        / len(edges), 1),
        "enough": len(edges) >= MIN_SAMPLE,
    } for label, edges in groups.items()}



# ---------------------------------------------------------------
# WHAT WAS LEFT WHEN THE CHIP ACTUALLY REACHED HIM
# ---------------------------------------------------------------
#     "before the movement i need to trust as early bird not in a over
#      crowded place after rally done then i will become volume to
#      early entries right? in simple if i bought even a good stock at
#      near Upper Circuit whats the use?"
#                                    -- operator, 1 August 2026
#
# He is right, and measure() above answers the wrong question for him.
# It reads the whole session's move, which credits a chip with a rally
# that finished before he could click.
#
# This reads the MINUTE bar at the moment the chip landed and measures
# only what came after. Measured the first time it ran:
#
#     CHIP               open->close     chip->close
#     PULSE EXCELLENT      +1.32%          +0.66%
#     CLEAN brief          +1.02%          +0.52%
#     vs estimate          +0.69%          -0.09%
#     PULSE GOOD           +0.23%          +0.02%
#
# Half the edge, and on two of them all of it. That is the honest
# number, and it is the one to watch from now on.
#
# WHEN HE GETS IN, BY THE RULE THE MARKET IMPOSES
#   before the session   -> the answering session's OPEN. He had all
#                           night; this is the only entry with a whole
#                           day in front of it.
#   during the session   -> the close of the minute the chip landed in.
#   after the close      -> the NEXT session's open, which is what
#                           Reaction.move_after() already decides.
def _ist(at):
    try:
        return datetime.fromisoformat(
            str(at).replace("Z", "").split("+")[0]) + IST_OFFSET
    except Exception:                                      # noqa: BLE001
        return None


def from_chip_time(events_db=EVENTS_DB, daily_db=DAILY_DB,
                   minute_db=MINUTE_DB):
    """{chip: {n, to_close, best, worst, win_pct}} priced at chip time.

    Returns {} when there are no minute bars to price against, which
    is the honest answer rather than falling back to the session open
    and calling it the same thing.
    """
    if not os.path.exists(minute_db):
        return {}
    reaction = Reaction(db_path=daily_db)

    try:
        conn = sqlite3.connect(events_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, at, kind, grade, headline, ai_direction "
            "FROM events WHERE symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] from_chip_time: {exc}")
        return {}

    # Grouped by the session that answers, so the 3 GB minute store is
    # read one date at a time instead of once per event.
    work = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        labels = chips_for(row)
        if not labels:
            continue
        when = _ist(row["at"])
        if when is None:
            continue
        _move, answered_on = reaction.move_after(row["symbol"], row["at"])
        if answered_on:
            work[answered_on].append((row["symbol"], when, labels))
    if not work:
        return {}

    buckets, unpriced = defaultdict(list), 0
    try:
        conn = sqlite3.connect(minute_db)
        for day in sorted(work):
            wanted = {s for s, _w, _l in work[day]}
            series = defaultdict(list)
            for symbol, minute, high, low, close in conn.execute(
                    "SELECT symbol, minute, h, l, c FROM candles "
                    "WHERE date = ?", (day,)):
                if symbol in wanted:
                    series[symbol].append((minute, high, low, close))
            for symbol in series:
                series[symbol].sort()

            for symbol, when, labels in work[day]:
                bars = series.get(symbol)
                if not bars:
                    unpriced += 1
                    continue
                same_session = when.strftime("%Y-%m-%d") == day
                start = 0
                if same_session:
                    stamp = when.strftime("%Y-%m-%dT%H:%M:00")
                    start = next((i for i, b in enumerate(bars)
                                  if b[0] >= stamp), None)
                    if start is None:
                        # Landed after the last bar of its own session.
                        unpriced += 1
                        continue
                after = bars[start:]
                entry = after[0][3]
                if not entry or not after:
                    unpriced += 1
                    continue
                to_close = (after[-1][3] / entry - 1.0) * 100.0
                best = (max(b[1] for b in after) / entry - 1.0) * 100.0
                worst = (min(b[2] for b in after) / entry - 1.0) * 100.0
                for label in labels:
                    buckets[label].append((to_close, best, worst))
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] minute bars: {exc}")
        return {}

    out = {}
    for label, hits in buckets.items():
        closes = [h[0] for h in hits]
        out[label] = {
            "n": len(hits),
            "to_close": round(statistics.median(closes), 2),
            "best": round(statistics.median(h[1] for h in hits), 2),
            "worst": round(statistics.median(h[2] for h in hits), 2),
            "win_pct": round(100.0 * sum(1 for c in closes if c > 0)
                             / len(closes), 1),
            "enough": len(hits) >= MIN_SAMPLE,
        }
    out["_unpriced"] = unpriced
    return out


def contrast(events_db=EVENTS_DB, daily_db=DAILY_DB):
    """Stocks that had ANY chip, against stocks that had none.

    ---- WHY THIS NUMBER HAS TO BE ON THE PAGE ----

    Every edge in measure() is computed against the median move of
    EVERY stock that traded. That is the wrong comparison and it
    flatters the whole table: a stock the channels wrote about is not
    the same animal as one nobody mentioned. It is bigger, more
    liquid, and it is in the news precisely because something moved.

    So this reports the honest version. Same sessions, two groups:

        stocks carrying at least one chip that day
        stocks in the same universe carrying none

    If the second number is close to the first, the chips are
    describing "a stock that had news" rather than anything the panel
    added, and every row in measure() should be read that way.
    """
    try:
        conn = sqlite3.connect(events_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, at, kind, grade, headline, ai_direction "
            "FROM events WHERE symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] contrast: {exc}")
        return None

    reaction = Reaction(db_path=daily_db)
    chipped = defaultdict(set)          # date -> symbols with a chip
    for raw in rows:
        row = dict(raw)
        if not chips_for(row):
            continue
        _move, on_date = reaction.move_after(row["symbol"], row["at"])
        if on_date:
            chipped[on_date].add(row["symbol"])
    if not chipped:
        return None

    with_chip, without = [], []
    try:
        conn = sqlite3.connect(daily_db)
        for on_date, symbols in chipped.items():
            bars = conn.execute(
                "SELECT symbol, close, prev_close FROM daily_bars "
                "WHERE date = ? AND prev_close > 0 AND close > 0",
                (on_date,)).fetchall()
            for symbol, close, prev in bars:
                move = (close / prev - 1.0) * 100.0
                (with_chip if symbol in symbols else without).append(move)
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] contrast bars: {exc}")
        return None

    if len(with_chip) < MIN_SAMPLE or len(without) < MIN_SAMPLE:
        return None
    return {
        "with_chip_n": len(with_chip),
        "with_chip_median": round(statistics.median(with_chip), 2),
        "no_chip_n": len(without),
        "no_chip_median": round(statistics.median(without), 2),
        "gap": round(statistics.median(with_chip)
                     - statistics.median(without), 2),
        "sessions": sorted(chipped),
    }


# ---------------------------------------------------------------
# THE SAME CHIPS, SCORED THE WAY THE BOOK ACTUALLY PAYS
# ---------------------------------------------------------------
#     "pls build me a bot which works"      -- operator, 12 Aug 2026
#
# Everything above reports MEDIAN edge. That was the right statistic
# for asking "does this chip point the right way", and it is the wrong
# one for asking "does this chip make money here", because this book is
# not symmetric:
#
#     HARD_STOP_FROM_ENTRY_PCT = 0.025   losses truncated at -2.5%
#     nothing caps the upside            winners run to the close
#
#     "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING STOCKS"
#                                    -- core/result_read.py
#
# A median deliberately throws away the tail. The tail is the entire
# business model. Measured on the 13 rows that SKIP-sources-disagree
# vetoed, the two statistics disagree about the SIGN:
#
#     median edge                 -0.03%     "the veto works"
#     mean with the stop applied  +1.87%     "the veto cost money"
#     OMNI alone       +19.77%  vs  all six losers stopped  -11.12%
#
# One name paid for every loser in the bucket twice over. Any grader
# that reports only the median will keep recommending the veto.
#
# The stop is applied to the RAW move, because that is what triggers
# it, and the market's median is subtracted afterwards -- doing it the
# other way stops on a number no broker can see.
STOP_PCT = 2.5
_STOCK_VALUE_RS = 120_000.0        # MTF_MARGIN_PER_POSITION_RS x MTF_LEVERAGE


def expectancy(events_db=EVENTS_DB, daily_db=DAILY_DB,
               stop_pct=STOP_PCT, stock_value=_STOCK_VALUE_RS):
    """{chip: {n, median_edge, mean_stopped, rupees, tail_share, enough}}.

    `mean_stopped`  the average edge once every loss is truncated at
                    the hard stop -- the number this book earns.
    `tail_share`    how much of all the gain came from the best tenth
                    of trades. High means the chip lives or dies on
                    outliers and a median will lie about it.
    """
    reaction = Reaction(db_path=daily_db)
    baseline = Baseline(db_path=daily_db)

    try:
        conn = sqlite3.connect(events_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, at, kind, grade, headline, ai_direction "
            "FROM events WHERE symbol IS NOT NULL").fetchall()
        conn.close()
    except sqlite3.Error as exc:
        diagnostic(f"[OUTCOMES] expectancy: {exc}")
        return {}

    buckets = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        labels = chips_for(row)
        if not labels:
            continue
        move, on_date = reaction.move_after(row["symbol"], row["at"])
        if move is None:
            continue
        market = baseline.median_move(on_date)
        if market is None:
            continue
        raw_edge = move - market
        stopped_edge = max(move, -abs(stop_pct)) - market
        for label in labels:
            buckets[label].append((raw_edge, stopped_edge))

    out = {}
    for label, hits in buckets.items():
        raws = [h[0] for h in hits]
        stops = [h[1] for h in hits]
        gains = sorted((s for s in stops if s > 0), reverse=True)
        top = gains[:max(1, len(stops) // 10)]
        out[label] = {
            "n": len(hits),
            "median_edge": round(statistics.median(raws), 2),
            "mean_stopped": round(statistics.fmean(stops), 2),
            "rupees": round(statistics.fmean(stops) / 100.0 * stock_value),
            "tail_share": (round(100.0 * sum(top) / sum(gains), 1)
                           if gains else 0.0),
            "enough": len(hits) >= MIN_SAMPLE,
        }
    return out


def ranked(events_db=EVENTS_DB, daily_db=DAILY_DB):
    """The chips, best first, by what they actually pay -- printable."""
    got = expectancy(events_db, daily_db)
    rows = sorted(((k, v) for k, v in got.items() if v["enough"]),
                  key=lambda kv: -kv[1]["mean_stopped"])
    lines = ["=" * 76,
             " CHIPS RANKED BY WHAT THEY PAY (stop applied, n>=%d)" % MIN_SAMPLE,
             "=" * 76,
             f" {'chip':<26}{'n':>5}{'median':>9}{'w/stop':>9}"
             f"{'Rs/trade':>10}{'tail%':>8}",
             " " + "-" * 74]
    for label, v in rows:
        lines.append(f" {label:<26}{v['n']:>5}{v['median_edge']:>+9.2f}"
                     f"{v['mean_stopped']:>+9.2f}{v['rupees']:>+10,}"
                     f"{v['tail_share']:>8.0f}")
    lines.append("=" * 76)
    lines.append(" median vs w/stop disagreeing on SIGN means the chip lives")
    lines.append(" on its tail -- size it for the tail, not the median.")
    lines.append("=" * 76)
    return "\n".join(lines)
