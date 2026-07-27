"""
==========================================================
Quarterly Results -- did the numbers actually get BETTER?
==========================================================

Operator, 2026-07-25, proposing this:

    "I proposed a memory bot for every 750 stocks... so that Brain Bot,
     before selecting any trade, will understand the stock situation and
     use the opportunity."

and 2026-07-27, on what makes a trade worth taking:

    "results genuinely better than the previous quarter, with better
     management guidance"

THE HOLE THIS FILLS
-------------------
core/results_calendar.py knows WHO reports and WHEN.
core/announcement_watcher.py knows a filing just LANDED.
Neither knows whether the numbers were any good.

On 2026-07-27 that distinction was the entire day:

    KFINTECH    filed, revenue +30% YoY, profit beat    +9.2%
    TMB         update, total advances +27% YoY        +12.1%
    SENCO       update, revenue +60% YoY                +7.4%
    ACUTAAS     filed the same week                    -Rs 1,593 for us
    CREDITACC   filed the same week                    -Rs   241 for us

Six of the nine stocks the bot bought that day had a results event in
the calendar. So did seven of the day's fourteen biggest winners. The
calendar cannot separate them. Only the numbers can.

WHAT IS STORED
--------------
One row per symbol per quarter, matching the shape of the earnings-pulse
cards the operator already reads:

    sales, other income, operating profit, OPM %, PAT, EPS

with the period end date, so QoQ (vs last quarter) and YoY (vs the same
quarter last year) both fall out of ordinary SQL rather than needing the
feed to hand them over.

THE GRADE, AND WHAT IT IS NOT
-----------------------------
grade() is arithmetic on those numbers and nothing else -- it is
reproducible, and every input is printed alongside it so the operator can
disagree with it in one glance.

It is NOT validated against what the price then did. Nobody has yet
measured whether "STRONG" quarters outperform, because that needs several
years of stored results matched to daily bars, and this store starts
empty today. Until that test exists, treat the grade as a fast way to
read the numbers, not as a reason to buy. The project has been burned
before by a plausible-sounding rule nobody had measured.

AND THE FIRST THREE REAL CASES ALREADY DISAGREE WITH IT
-------------------------------------------------------
Loading the actual reported figures for 2026-07-27:

    ACUTAAS     WEAK    sales -19% QoQ, PAT -37% QoQ        fell    correct
    KFINTECH    MIXED   PAT -7% QoQ, sales +30% YoY         +9.2%   WRONG
    MOLDTKPAC   STRONG  sales +26% QoQ, PAT +24% QoQ        -6.5%   WRONG

One out of three.

KFINTECH is the instructive one. Its profit genuinely FELL 7% QoQ, and
the stock rose 9.2% anyway -- because the number beat what analysts had
forecast. The market prices SURPRISE, not growth, and this module cannot
see surprise: it has the reported figures and no estimate to compare
them against.

So the grade answers "did the business grow" -- a real and useful
question, and the one the operator asked for. It does not answer "will
this go up", and nothing here should be read as though it does.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Date, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, insert, select, update,
)

from core.db import resolve_database_url

# Growth at or above this counts as genuinely better, not noise. Indian
# quarterly numbers swing on seasonality and one-offs; a 2% "rise" in
# sales is not a signal. Deliberately a named constant so it can be
# tested and argued with rather than buried in a comparison.
MATERIAL_GROWTH_PCT = 5.0
# PAT growth at or above this is what the operator called "genuinely
# better". KFINTECH's beat, TMB's +27% advances and SENCO's +60% revenue
# were all far above it.
STRONG_GROWTH_PCT = 15.0


def _utcnow():
    return datetime.now(timezone.utc)


def _pct(now, before):
    """Percentage change, or None when it cannot honestly be computed.

    Returns None if the base is zero OR NEGATIVE. A company swinging from
    a loss to a profit produces a mathematically valid but meaningless
    percentage (-100 to +50 is not "150% growth"), and printing one would
    be worse than printing nothing.
    """
    if now is None or before is None or before <= 0:
        return None
    return (now - before) / before * 100.0


class QuarterlyResults:
    """Per-symbol quarterly financials. Construct once and share."""

    def __init__(self, url=None):
        self.url = resolve_database_url(
            url, default="sqlite:///data/quarterly_results.db")
        connect_args = {}
        if self.url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)

        self.engine = create_engine(
            self.url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self.metadata = MetaData()
        self.results = Table(
            "quarterly_results", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            # The quarter's END date -- the sortable key. A label like
            # "Jun-26" is for humans and sorts alphabetically, which puts
            # Dec before Jun. Ordering on a real date avoids a whole
            # family of quiet bugs.
            Column("period_end", Date, nullable=False, index=True),
            Column("period_label", String(16)),
            Column("sales", Float),
            Column("other_income", Float),
            Column("operating_profit", Float),
            Column("opm_pct", Float),
            Column("pat", Float),
            Column("eps", Float),
            Column("source", String(32)),
            # WHEN WE READ IT, not when the company filed it. On
            # 2026-07-27 BSE's own resultsSnapshot was still showing
            # Mar-26 for CANBK 98 minutes after the numbers were public.
            # Without this column, "the bot knew" and "the bot could have
            # known" are indistinguishable after the fact.
            Column("read_at", DateTime(timezone=True), default=_utcnow),
            UniqueConstraint("symbol", "period_end", name="uq_quarter"),
        )
        self.metadata.create_all(self.engine)

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------

    def remember(self, symbol, period_end, sales=None, other_income=None,
                 operating_profit=None, opm_pct=None, pat=None, eps=None,
                 period_label=None, source="bse"):
        """Store or update one quarter. Returns "new", "updated" or
        "unchanged" so a fetcher can report honestly -- "0 new" is
        ambiguous between "nothing arrived" and "nothing was different",
        and this project has already been bitten by that once (see
        core/corporate_actions.py's fetched/stored split)."""
        if not symbol or period_end is None:
            return "unchanged"
        symbol = str(symbol).strip().upper()
        values = dict(
            sales=sales, other_income=other_income,
            operating_profit=operating_profit, opm_pct=opm_pct,
            pat=pat, eps=eps, period_label=period_label, source=source,
        )
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.results).where(
                    (self.results.c.symbol == symbol)
                    & (self.results.c.period_end == period_end))
            ).first()
            if row is None:
                conn.execute(insert(self.results).values(
                    symbol=symbol, period_end=period_end,
                    read_at=_utcnow(), **values))
                return "new"
            existing = dict(row._mapping)
            changed = {k: v for k, v in values.items()
                       if v is not None and existing.get(k) != v}
            if not changed:
                return "unchanged"
            conn.execute(update(self.results).where(
                self.results.c.id == existing["id"]
            ).values(read_at=_utcnow(), **changed))
            return "updated"

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------

    def history(self, symbol, limit=8):
        """Newest quarter first."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.results)
                .where(self.results.c.symbol == str(symbol).strip().upper())
                .order_by(self.results.c.period_end.desc())
                .limit(limit)
            ).all()
        return [dict(r._mapping) for r in rows]

    def latest(self, symbol):
        rows = self.history(symbol, limit=1)
        return rows[0] if rows else None

    def compare(self, symbol):
        """The whole point of this module: is the latest quarter better
        than the one before, and better than the same quarter last year?

        Returns None when there is nothing to compare -- one stored
        quarter is a fact, not a trend, and inventing a comparison from
        it would be exactly the kind of confident-and-wrong output this
        project has already paid for.
        """
        rows = self.history(symbol, limit=8)
        if len(rows) < 2:
            return None
        latest = rows[0]
        prev = rows[1]

        # Same quarter a year ago: the row closest to 365 days back,
        # matched by date rather than by counting four rows back -- a
        # missing quarter would silently make "YoY" mean five quarters.
        year_ago = None
        target = latest["period_end"].toordinal() - 365
        for r in rows[2:]:
            if abs(r["period_end"].toordinal() - target) <= 45:
                year_ago = r
                break

        def block(base):
            if base is None:
                return None
            return {
                "sales": _pct(latest["sales"], base["sales"]),
                "pat": _pct(latest["pat"], base["pat"]),
                "eps": _pct(latest["eps"], base["eps"]),
                "opm_bps": (round((latest["opm_pct"] - base["opm_pct"]) * 100)
                            if latest.get("opm_pct") is not None
                            and base.get("opm_pct") is not None else None),
                "period": base.get("period_label") or str(base["period_end"]),
            }

        qoq = block(prev)
        yoy = block(year_ago)
        return {
            "symbol": str(symbol).strip().upper(),
            "period": latest.get("period_label") or str(latest["period_end"]),
            "latest": latest,
            "qoq": qoq,
            "yoy": yoy,
            "grade": grade(qoq, yoy),
            "summary": summarise(qoq, yoy),
        }

    def count(self):
        from sqlalchemy import func
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.results)).scalar_one()

    def symbols(self):
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.results.c.symbol).distinct()).all()
        return {r[0] for r in rows}


# --------------------------------------------------------------
# GRADING -- arithmetic, printed alongside its own inputs
# --------------------------------------------------------------

def grade(qoq, yoy):
    """STRONG / GOOD / MIXED / WEAK, or None when unknown.

    Sales and PAT only. OPM and EPS are shown to the operator but do not
    grade: OPM moves on one-off costs and EPS moves on share count, and
    neither is the question "did the business sell more and earn more".

    NOT VALIDATED AGAINST PRICE. See the module docstring. This is a fast
    way to read the numbers, not evidence that they predict anything.
    """
    if not qoq:
        return None
    parts = [b for b in (qoq, yoy) if b]
    sales = [b["sales"] for b in parts if b.get("sales") is not None]
    pat = [b["pat"] for b in parts if b.get("pat") is not None]
    if not sales and not pat:
        return None

    up = [v for v in sales + pat if v >= MATERIAL_GROWTH_PCT]
    down = [v for v in sales + pat if v <= -MATERIAL_GROWTH_PCT]
    strong_pat = [v for v in pat if v >= STRONG_GROWTH_PCT]

    if down and not up:
        return "WEAK"
    if up and not down:
        return "STRONG" if strong_pat and len(up) >= 2 else "GOOD"
    if up and down:
        return "MIXED"
    return "MIXED"


def summarise(qoq, yoy):
    """One line a human can read at a glance, e.g.
    "sales +26% QoQ, PAT +24% QoQ, sales +25% YoY"."""
    bits = []
    for block, tag in ((qoq, "QoQ"), (yoy, "YoY")):
        if not block:
            continue
        for key, label in (("sales", "sales"), ("pat", "PAT")):
            v = block.get(key)
            if v is not None and abs(v) >= MATERIAL_GROWTH_PCT:
                bits.append(f"{label} {v:+.0f}% {tag}")
    return ", ".join(bits)


_default = None


def default_results():
    global _default
    if _default is None:
        _default = QuarterlyResults()
    return _default
