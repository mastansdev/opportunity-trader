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
import statistics
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Date, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, insert, select, update,
)

from core.db import resolve_database_url
from core.logger import warn

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

    # How far a quarter's sales may sit from the company's own median
    # before it is treated as a misread rather than a business event.
    #
    # Twenty is deliberately loose. A genuine doubling, a merger, even
    # a fourfold jump on a new plant all pass. What it catches is the
    # decimal-place and wrong-column class of error, which is never
    # subtle: the real cases were 100x to 2,600x out.
    SALES_SANITY_RATIO = 20.0

    # Below this a company has no history to judge a new quarter
    # against, and refusing on two data points would block every
    # newly-covered stock.
    SALES_SANITY_MIN_HISTORY = 3

    def _implausible(self, symbol, sales):
        """Why this sales figure cannot be believed, or None.

        Compares the company against ITSELF. There is no absolute
        rupee threshold that is right for both Reliance and a
        small-cap, and inventing one would refuse real quarters.
        """
        if sales is None:
            return None
        try:
            sales = float(sales)
        except (TypeError, ValueError):
            return "sales is not a number"
        if sales < 0:
            return f"sales is negative ({sales})"
        if sales == 0:
            return None                 # genuinely possible, and rare
        try:
            with self.engine.begin() as conn:
                rows = conn.execute(
                    select(self.results.c.sales).where(
                        (self.results.c.symbol == symbol)
                        & (self.results.c.sales.isnot(None)))
                ).fetchall()
        except Exception:                                  # noqa: BLE001
            return None                 # never block a write on a read
        history = [float(r[0]) for r in rows if r[0] and float(r[0]) > 0]
        if len(history) < self.SALES_SANITY_MIN_HISTORY:
            return None
        median = statistics.median(history)
        if median <= 0:
            return None
        ratio = max(sales / median, median / sales)
        if ratio >= self.SALES_SANITY_RATIO:
            return (f"sales {sales:,.2f} is {ratio:,.0f}x from this "
                    f"company's own median of {median:,.2f} -- almost "
                    f"certainly a misread column, not a quarter")
        return None

    def remember(self, symbol, period_end, sales=None, other_income=None,
                 operating_profit=None, opm_pct=None, pat=None, eps=None,
                 period_label=None, source="bse", trusted=False):
        """Store or update one quarter. Returns "new", "updated" or
        "unchanged" so a fetcher can report honestly -- "0 new" is
        ambiguous between "nothing arrived" and "nothing was different",
        and this project has already been bitten by that once (see
        core/corporate_actions.py's fetched/stored split)."""
        if not symbol or period_end is None:
            return "unchanged"
        symbol = str(symbol).strip().upper()

        # ---- A COMPANY'S SALES DO NOT MOVE BY A FACTOR OF TWENTY ----
        # 1 August 2026, found by auditing the store after 200 filings
        # were fetched and parsed:
        #
        #     BAJFINANCE  Jun-26  sales     12.00   own median  8,308.97
        #     REDINGTON   Jun-26  sales     19.59   own median  6,400.64
        #     TORNTPHARM  Mar-26  sales      1.00   own median  2,599.00
        #     VEDL        Jun-25  sales     24.61   own median 15,754.00
        #
        # 21 rows of 1,685, nineteen of them from the PDF parser
        # reading the wrong column of a results table. Bajaj Finance
        # did not do twelve crore of sales.
        #
        # A wrong number is worse than a missing one. A missing quarter
        # leaves the panel labelled with the older quarter's name,
        # which is visible; a wrong one produces a confident grade off
        # arithmetic that is nonsense.
        #
        # The test is the company against ITSELF, never a threshold in
        # rupees -- there is no absolute figure that is right for both
        # Reliance and a small-cap.
        # ---- `trusted` EXISTS BECAUSE THE GUARD BLOCKS THE CURE ----
        #
        # WESTLIFE's stored history is 1.0 and 1.0, both misread from a
        # filing PDF. Earnings Pulse's own card says 736. Compared
        # against that history the CORRECT figure is a 736x outlier and
        # the guard refuses it -- the corrupt data defending itself.
        #
        # So a reading that came from the channel's published grid
        # skips the self-comparison. It is not a weaker check; it is a
        # better SOURCE. The channel prints the figure the company
        # reported, minutes after it reports, and it does not have to
        # find a table inside a fourteen-megabyte PDF to do it.
        refused = None if trusted else self._implausible(symbol, sales)
        if refused:
            warn(f"[RESULTS] {symbol} {period_label or period_end}: "
                 f"REFUSED -- {refused}. The older quarter is kept.")
            return "unchanged"

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

        # ---- LIKE WITH LIKE. 30 August 2026. ----
        #
        #     "never pool all stocks , never average the stocks data"
        #                                     -- the operator
        #
        # This took rows[0] and rows[1] whatever they were. The store
        # holds the same company from three sources that do not report
        # on the same basis:
        #
        #     NAZARA   Jun-26  428.77   filing_pdf   (consolidated)
        #              Mar-26   18.44   bse          (standalone)
        #
        # +2,225% QoQ, arithmetic done perfectly on two numbers that
        # were never comparable, and the stock went ungraded for it.
        #
        # So the previous quarter is taken from the SAME SOURCE where
        # one exists. Falling back to the next row otherwise keeps the
        # old behaviour for the single-source case, which is most of
        # them -- and _implausible_change() still guards what is left.
        prev = next((r for r in rows[1:]
                     if r.get("source") and r.get("source") == latest.get("source")),
                    rows[1])

        # Same quarter a year ago: the row closest to 365 days back,
        # matched by date rather than by counting four rows back -- a
        # missing quarter would silently make "YoY" mean five quarters.
        year_ago = None
        target = latest["period_end"].toordinal() - 365
        # Same source first, for the same reason as prev above: AVL
        # read +1,454% YoY off a filing_pdf quarter against a
        # pulse_grid one.
        for same_source in (True, False):
            for r in rows[1:]:
                if r is prev:
                    continue
                if same_source and r.get("source") != latest.get("source"):
                    continue
                if abs(r["period_end"].toordinal() - target) <= 45:
                    year_ago = r
                    break
            if year_ago is not None:
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

        # ---- +1839% IS NOT A QUARTER. 1 August 2026. ----
        #
        # The store held these, and the panel was showing them:
        #
        #     RAINBOW    GOOD    sales +1839% QoQ
        #     NAZARA     STRONG  PAT +750% QoQ
        #     CHOICEIN   STRONG  PAT +428% QoQ
        #
        # RAINBOW's two figures were 0.33 and 6.40. Both wrong, both
        # from the PDF parser, and a self-comparison cannot see it
        # because NEITHER of them is the outlier -- the whole history
        # is wrong together.
        #
        # remember()'s sanity check compares a company against its own
        # median and so is blind to exactly this: it also needs three
        # stored quarters, and 618 of 748 companies have fewer.
        #
        # This catches the SYMPTOM instead, which needs no history at
        # all. Measured across 916 consecutive quarters in the store:
        #
        #     50th percentile of |sales QoQ|      12.0%
        #     90th                                55.9%
        #     95th                                91.6%
        #     above 400%                     12 pairs, 1.3%
        #
        # and every one of those twelve is visibly a misread --
        # JINDWORLD 0.02 -> 539.90, COROMANDEL 56.61 -> 7,743.55.
        #
        # The comparison is still RETURNED so the operator can look at
        # it. Only the grade and the summary are withheld, because
        # those are what the panel turns into a chip, and a chip that
        # says STRONG on a data error is the failure this whole file
        # was written to avoid.
        unbelievable = _implausible_change(qoq, yoy)
        if unbelievable:
            warn(f"[RESULTS] {symbol}: no grade -- {unbelievable}")

        return {
            "symbol": str(symbol).strip().upper(),
            "period": latest.get("period_label") or str(latest["period_end"]),
            "latest": latest,
            "qoq": qoq,
            "yoy": yoy,
            "grade": None if unbelievable else grade(qoq, yoy),
            "summary": (f"figures not believable ({unbelievable})"
                        if unbelievable else summarise(qoq, yoy)),
            "unreliable": unbelievable,
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

# A quarter-on-quarter sales change beyond this is a data error, not a
# business event. Measured across 916 consecutive quarters held on
# 1 August 2026: the 95th percentile is 91.6%, and only 12 pairs (1.3%)
# exceed 400% -- every one of them a visible misread.
#
# Sales only. PAT can legitimately swing enormously on a small base,
# and _pct() already refuses a negative base, so a loss-to-profit swing
# never produces a number here at all.
MAX_BELIEVABLE_SALES_CHANGE_PCT = 400.0

# A quarter bigger than this multiple of the full-year column beside
# it is not the same company on the same basis. Loose on purpose: the
# newest quarter belongs to the NEXT financial year, so exceeding the
# previous year's total is growth, not a fault. COROMANDEL's was 25x.
QUARTER_OVER_YEAR = 1.5


def _implausible_change(qoq, yoy):
    """Why this comparison cannot be believed, or None."""
    for label, block in (("QoQ", qoq), ("YoY", yoy)):
        if not block:
            continue
        change = block.get("sales")
        if change is None:
            continue
        if abs(change) > MAX_BELIEVABLE_SALES_CHANGE_PCT:
            return (f"sales {change:+,.0f}% {label} -- beyond anything a "
                    f"real quarter does, so one of the two figures is "
                    f"misread")
    return None


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


# --------------------------------------------------------------
# BSE resultsSnapshot -- the real payload shape
# --------------------------------------------------------------
# Confirmed live 2026-07-27, bse.BSE().resultsSnapshot('543596') for TMB:
#
#   {"currency_unit": "in Cr.",
#    "periods": ["Mar-26", "Dec-25", "FY25-26"],
#    "results_in_crores": {
#       "fields": ["title", "Mar-26", "Dec-25", "FY25-26"],
#       "data": [["Revenue",    "1,550.38", "1,469.41", "5,819.42"],
#                ["Net Profit",   "373.65",   "341.50", "1,337.55"],
#                ["EPS",           "23.60",    "21.57",    "84.47"],
#                ["NPM %",         "24.10",    "23.24",    "22.98"],
#                ["CAR %",            "--",       "--",       "--"]]},
#    "period_links": [{"FY": "FY25-26", "LQ": "Jun-26", "SQ": "Mar-26", ...}]}
#
# THREE THINGS THAT MATTER, ALL LEARNED FROM THAT ONE RESPONSE:
#
# 1. IT LAGS. TMB reported on 2026-07-27 and this still showed Mar-26 as
#    its latest quarter, while period_links.LQ already said "Jun-26".
#    Same as CANBK, still Mar-26 ninety-eight minutes after its numbers
#    were public. So this is a HISTORY source. Same-day numbers have to
#    come from the filing itself, never from here.
#
# 2. ONLY TWO QUARTERS COME BACK, plus a full year. That is enough for
#    QoQ and never enough for YoY on its own -- YoY only appears once the
#    store has accumulated four quarters of its own.
#
# 3. THE LINE ITEMS DEPEND ON THE INDUSTRY. TMB is a bank, so it reports
#    Revenue / Net Profit / EPS / NPM % / CAR %. A manufacturer reports
#    Sales and OPM. So titles are matched permissively and anything
#    unrecognised is skipped rather than guessed at.

_TITLE_MAP = {
    "revenue": "sales", "sales": "sales", "net sales": "sales",
    "total income": "sales", "revenue from operations": "sales",
    "net profit": "pat", "pat": "pat", "profit after tax": "pat",
    "profit for the period": "pat", "net profit/loss": "pat",
    "eps": "eps", "basic eps": "eps", "earnings per share": "eps",
    "operating profit": "operating_profit", "pbidt": "operating_profit",
    "ebitda": "operating_profit",
    "opm %": "opm_pct", "opm": "opm_pct", "operating margin": "opm_pct",
    "other income": "other_income",
}


def _num(value):
    """'1,550.38' -> 1550.38. '--' and '' -> None, never 0.0 -- a missing
    figure and a zero figure are different facts."""
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text or text in ("--", "-", "NA", "N.A."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_results_snapshot(payload):
    """BSE's resultsSnapshot dict -> [{period_label, sales, pat, ...}].

    Full-year columns are dropped: "FY25-26" is not a quarter, and
    storing one as though it were would silently corrupt every QoQ
    comparison afterwards.
    """
    if not isinstance(payload, dict):
        return []
    block = payload.get("results_in_crores") or payload.get("results_in_millions")
    if not isinstance(block, dict):
        return []
    fields = block.get("fields") or []
    rows = block.get("data") or []
    if len(fields) < 2 or not rows:
        return []

    scale = 0.1 if payload.get("results_in_crores") is None else 1.0

    # ==========================================================
    # THREE COLUMNS, NOT ONE SERIES.  30 August 2026.
    # ==========================================================
    #
    #     "fix those 8 stocks parsed sales figures"
    #                                     -- the operator
    #
    # COROMANDEL, fetched live from BSE on 30 August:
    #
    #     Revenue      Jun-26 7,743.55   Mar-26 56.61   FY25-26 305.31
    #     Net Profit          376.96             1.54            20.09
    #     NPM %                  4.87             2.73             6.58
    #
    # Every column is internally consistent -- 376.96/7743.55 = 4.87%
    # and 1.54/56.61 = 2.72%, both matching the NPM row BSE printed
    # beside them. So no single column is corrupt.
    #
    # But ONE QUARTER IS TWENTY-FIVE TIMES THE WHOLE FINANCIAL YEAR
    # next to it. Those three columns cannot be the same company on
    # the same basis; BSE is serving standalone and consolidated in
    # adjacent columns, and this parser stored them as one series. The
    # +13,579% QoQ that left COROMANDEL ungraded was arithmetic done
    # correctly on two figures that were never comparable.
    #
    # THE FULL-YEAR COLUMN IS THE CHECK, and it costs nothing: it is
    # already in the payload and was being dropped. A quarter may
    # exceed the PREVIOUS year's total -- it belongs to the next one
    # and companies grow -- so the test is deliberately loose. Half as
    # much again is growth; twenty-five times is a different entity.
    #
    # Nothing is kept from a payload that fails. Storing the columns
    # that happen to agree would leave the store holding a mixture and
    # no way to tell afterwards which basis each row came from.
    year_sales = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        if _TITLE_MAP.get(str(row[0]).strip().lower()) != "sales":
            continue
        for col, label in enumerate(fields[1:], start=1):
            if str(label).strip().upper().startswith("FY") and len(row) > col:
                year_sales = _num(row[col])
        break
    if year_sales and year_sales > 0:
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            if _TITLE_MAP.get(str(row[0]).strip().lower()) != "sales":
                continue
            for col, label in enumerate(fields[1:], start=1):
                if str(label).strip().upper().startswith("FY"):
                    continue
                got = _num(row[col]) if len(row) > col else None
                if got is not None and got > year_sales * QUARTER_OVER_YEAR:
                    from core.logger import warn
                    warn(f"[RESULTS] Dropping a snapshot whose own columns "
                         f"disagree: {label} sales {got:,.2f} against a full "
                         f"year of {year_sales:,.2f}. BSE is serving more "
                         f"than one reporting basis; none of it is stored.")
                    return []
            break

    out = []
    for col, label in enumerate(fields[1:], start=1):
        label = str(label).strip()
        if not label or label.upper().startswith("FY"):
            continue
        record = {"period_label": label}
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) <= col:
                continue
            key = _TITLE_MAP.get(str(row[0]).strip().lower())
            if key is None:
                continue
            value = _num(row[col])
            if value is None:
                continue
            # EPS and any % are per-share or ratios -- never rescaled.
            if scale != 1.0 and key in ("sales", "pat", "operating_profit",
                                        "other_income"):
                value *= scale
            record[key] = value
        if len(record) > 1:
            out.append(record)
    return out


_default = None


def default_results():
    global _default
    if _default is None:
        _default = QuarterlyResults()
    return _default
