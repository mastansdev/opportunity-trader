"""
==========================================================
Trade Memory -- the learning loop (OBSERVATION ONLY)
==========================================================

From the operator's architecture deck (HM_ORB_AI_Final_Architecture):

    Position lifecycle:  ENTRY -> MONITOR -> NEWS -> RECALCULATE ->
                         TRAIL -> EXIT -> **LEARN -> MEMORY**

    Core ideology:  "Every completed trade becomes new memory,
                     improving future decisions."

Until now the bot forgot everything at 15:15. It could not tell you that
its breakouts in METALS had failed nine times this month, or that its
10:00 entries lose while its 11:00 entries win. Every session started
blind. This module is the missing half.

**IT DOES NOT VOTE.** Deliberate, operator-approved (2026-07-25):
observation first. It records what happened and reports what it sees;
nothing in the engine reads it to block or size a trade. The reason is
the same discipline that has caught three false conclusions already --
a handful of samples looks like a pattern long before it is one. Let it
learn in public for a few weeks; give it a vote only once its numbers
are backed by enough sessions to mean something.

What makes this useful is not the P&L (that's in trade_log.csv already)
but the CONTEXT captured at entry: the sector, the relative strength,
the hour, the market regime. Those are the conditions we can later ask
questions about.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, func, insert, select,
)
from sqlalchemy.exc import IntegrityError

from core.db import resolve_database_url
from core.logger import warn, diagnostic, decision


def _utcnow():
    return datetime.now(timezone.utc)


def _size_of(symbol):
    """{"band", "cap_cr", "rank"} for this company, or {}.

    Never raises and never guesses. A company that is not on NSE's
    list -- 235 of the 1,976 followed, mostly listed after the filing
    period -- records no band at all, which is a different thing from
    recording SMALL.
    """
    try:
        from core import company_size
        return company_size.of(symbol) or {}
    except Exception:                                      # noqa: BLE001
        return {}

def _as_datetime(value):
    """A datetime, whatever shape it arrived in.

    The engine hands real datetimes. data/session_state.json hands ISO
    strings back for anything carried across a restart -- and on MTF
    the bot carries positions overnight by design, so this is the
    normal case, not the edge one.
    """
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None



class TradeMemory:

    def __init__(self, url=None):
        self.url = resolve_database_url(url, default="sqlite:///data/trade_memory.db")
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
        self.trades = Table(
            "trade_memory", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            Column("direction", String(8), nullable=False),
            Column("trade_date", String(10), nullable=False, index=True),
            Column("entry_time", DateTime),
            Column("exit_time", DateTime),
            Column("entry_price", Float),
            Column("exit_price", Float),
            Column("qty", Integer),
            Column("pnl", Float),
            Column("exit_reason", String(32), index=True),
            Column("entry_reason", String(48)),
            Column("holding_minutes", Float),
            # ---- CONTEXT AT ENTRY: the part worth learning from ----
            Column("sector", String(64), index=True),
            Column("entry_hour", String(5), index=True),      # "09:34" -> "09"
            Column("rel_strength", Float),                     # vs market
            Column("regime", String(12)),
            # ---- THE REASON, added 2026-07-28 ----
            # The four columns above are all PRICE context: sector,
            # hour, relative strength, regime. With only those, the
            # memory can answer "do metals breakouts at 10am work" --
            # the price-and-volume question the operator has already
            # said is not enough -- and can NEVER answer the one he
            # cares about:
            #
            #     "no info why gaining = no entry at all"
            #
            # Do ORDER_WIN entries beat BROKER upgrades? Does a STRONG
            # results grade beat a MIXED one? Are entries WITH a reason
            # better than entries without? None of that was being
            # recorded, so six months of trades could not answer it.
            #
            # Stamped at ENTRY, not at exit -- what was known when the
            # decision was made, never what turned out to be true.
            Column("news_kind", String(24), index=True),   # ORDER_WIN, BROKER...
            Column("filing_kind", String(24)),             # RESULTS, PAYOUT...
            Column("results_grade", String(12), index=True),  # STRONG/GOOD/...
            Column("days_since_results", Integer),
            Column("had_reason", Integer, index=True),     # 1/0, the headline
            Column("reason_summary", String(160)),         # human-readable
            # The fingerprint of the entry -- see LATE_COLUMNS.
            Column("door", String(16), index=True),
            Column("volume_x", Float),
            Column("jump_x", Float),
            Column("liveness", String(12)),
            Column("off_high_pct", Float),
            # How big the company is -- see LATE_COLUMNS.
            Column("mcap_band", String(8), index=True),
            Column("mcap_cr", Float),
            # Right stock at right time, both readings -- see
            # LATE_COLUMNS. Recorded, never consulted.
            Column("run_up_pct", Float),
            Column("move_age_min", Float),
            Column("reason_kind", String(24), index=True),
            Column("reason_pct_of_company", Float),
            # How much of the move it actually kept -- see LATE_COLUMNS.
            Column("peak_price", Float),
            Column("peak_mtm", Float),
            Column("recorded_at", DateTime(timezone=True), default=_utcnow),
            # ---- ONE ROW PER STOCK PER DAY LOST HALF A SESSION ----
            #      1 September 2026.
            #
            # This said "matches the engine's own one-attempt-per-day
            # rule". The engine has no such rule: on 1 September it
            # bought MARINE at 11:08, sold it at 11:29 and bought it
            # again at 11:30. Two trades, and the database refused the
            # second -- not the code guard, THIS, at the storage layer,
            # raising IntegrityError into an `except: return False`.
            # The report card showed 2 trades out of 4 and said nothing.
            #
            # ENTRY TIME is what separates them. Two round trips have
            # different ones; the same trade re-recorded after a
            # restart has the same one, so the double-count this was
            # written to prevent is still prevented. An adopted broker
            # position has no entry time at all and is still guarded by
            # the price check in record().
            UniqueConstraint("symbol", "direction", "trade_date",
                             "entry_time", name="uq_trade_memory"),
        )
        self.metadata.create_all(self.engine)
        self._add_missing_columns()
        self._widen_the_unique_constraint()

    # ----------------------------------------------------------

    #: Columns added after the table already existed in the wild.
    #: create_all() creates MISSING TABLES -- it does not alter an
    #: existing one, so a live trade_memory.db keeps its old shape and
    #: every insert of a new field fails silently (record() swallows
    #: exceptions by design, so nothing would ever be recorded again
    #: and nobody would notice).
    LATE_COLUMNS = {
        "news_kind": "TEXT",
        "filing_kind": "TEXT",
        "results_grade": "TEXT",
        "days_since_results": "INTEGER",
        "had_reason": "INTEGER",
        "reason_summary": "TEXT",
        # ---- THE FINGERPRINT. 4 September 2026. ----
        #
        #     "i want to make sure that which combination of rules set
        #      were yielding results = profits"        -- the operator
        #
        # reason_summary says WHAT was known about the stock -- news,
        # results, a filing. It does not say which RULE admitted it to
        # the pool, nor what the numbers were when the bot decided.
        # Without those, a rule change can be argued about but never
        # scored: after a week he cannot say whether news plus a volume
        # jump beats news alone.
        #
        # These record the FACTS at the moment of entry and group
        # nothing. Deciding the buckets now would throw away every
        # question neither of us has thought of yet.
        #
        #   door        which rule opened the pool to it -- news,
        #               filing, results, reporting, surge, opening
        #   volume_x    the day-total ratio, the old surge measure
        #   jump_x      this minute against its own recent minutes
        #   liveness    alive / fading, as the gate read it
        #   off_high    how far below its own day high it was bought
        "door": "TEXT",
        "volume_x": "REAL",
        "jump_x": "REAL",
        "liveness": "TEXT",
        "off_high_pct": "REAL",
        # ---- HOW BIG THE COMPANY IS. 6 September 2026. ----
        #
        #     "does that brings any change in trading & overall
        #      outcome?"                             -- the operator
        #
        # Not by itself, and that is the point of putting it HERE
        # rather than in a gate. Asked on 6 September whether size
        # predicts anything, this book could not answer:
        #
        #     from 29 August, under the rules running now
        #       LARGE    2 trades    2 up    0 down
        #       MID      3 trades    3 up    0 down
        #       SMALL   56 trades   25 up   31 down
        #
        # Five non-small trades. The 139 trades before 29 August ran a
        # different stop, target and sizing, and his rule is that a new
        # rule is never tuned on trades from the old one. So the
        # question is not unanswered because it is hard -- it is
        # unanswered because nothing wrote the size down.
        #
        # NOT the free-float figure core/cause_effect.py's gate reads.
        # That one is deliberately different; see core/company_size.py
        # for why the two are separate modules.
        "mcap_band": "TEXT",
        "mcap_cr": "REAL",
        # ---- HIS ANSWER AND MINE, SIDE BY SIDE. 6 Sep 2026. ----
        #
        #     "no rupee will go into trade unless there is potential to
        #      move"                              -- the operator
        #
        # He says volume settles it and the REASON behind the volume --
        # news, an event, or pure price action. I found Friday's seven
        # late entries lost every one. He settled it: "yes both will
        # settle the answer i guess". So both are written down and
        # neither decides anything.
        #
        #   run_up_pct              how far it had already run when
        #                           bought, from yesterday's close
        #   move_age_min            how long ago the move began, by the
        #                           bot's own definition of moving
        #   reason_kind             ORDER_WIN, GUIDANCE, BUSINESS_UPDATE
        #   reason_pct_of_company   the reason's size against the
        #                           company. Rs 15,840 cr against a
        #                           Rs 33,636 cr company is 47% and is
        #                           potential; the same order against
        #                           L&T is 3% and is not.
        "run_up_pct": "REAL",
        "move_age_min": "REAL",
        "reason_kind": "TEXT",
        "reason_pct_of_company": "REAL",
        #
        # ---- HOW MUCH OF IT DID WE KEEP. 14 September 2026. ----
        #
        #     "after gaining around 8k bot booked profit of 700 rs
        #      change by giving back almost all the mtm profits"
        #                                       -- the operator
        #
        #   peak_price   the highest the trail ever saw this position
        #   peak_mtm     (peak - entry) * qty, the most it was ever
        #                worth, in rupees
        #
        # He is right that it happens; what could not be answered was
        # how OFTEN, and whether protecting it pays. Three protection
        # rules were simulated against the candles on 14 September --
        # a breakeven ratchet, a proportional give-back, and one that
        # only guards large gains -- and ALL THREE lost money, because
        # every trail tight enough to stop a round-trip also clips the
        # BUYING_DRIED_UP winners that earn +68,770. Keeping about 45%
        # of the peak looks like the price of letting winners run.
        #
        # "Looks like" is the problem. That whole answer comes from
        # replaying minute candles over four sessions, because the book
        # itself never recorded the peak. These two columns mean the
        # question can be asked of the bot's own trades, per exit rule,
        # on sessions nobody has tuned anything on.
        #
        # Recorded, never consulted -- like every other column here.
        "peak_price": "REAL",
        "peak_mtm": "REAL",
    }

    def _widen_the_unique_constraint(self):
        """Rebuild a table still carrying the old one-row-per-day rule.

        ---- IT DROPPED HALF A SESSION. 1 September 2026. ----

        UNIQUE(symbol, direction, trade_date) refused the second trade
        in a stock on the same day. The bot did exactly that twice on
        1 September (MARINE and VTL), so the report card showed two
        trades out of four and logged nothing, because record() catches
        IntegrityError and returns False.

        SQLite cannot ALTER a constraint, so the table is rebuilt. It
        is COPIED, never dropped-and-recreated: a bookkeeping change
        must not be able to lose 143 real trades. A .backup file is
        written first, and if anything fails the original is left
        exactly as it was.

        Idempotent and silent once done -- it looks at the constraint,
        not at a version number.
        """
        import shutil
        from datetime import datetime as _dt

        if not self.url.startswith("sqlite"):
            return
        path = self.url.replace("sqlite:///", "", 1)
        if not path or path == ":memory:" or not os.path.exists(path):
            return
        try:
            with self.engine.begin() as conn:
                sql = conn.exec_driver_sql(
                    "select sql from sqlite_master where type='table' "
                    "and name='trade_memory'").scalar()
            # Match the CONSTRAINT text itself. An earlier version of
            # this check looked for "entry_time" near the constraint and
            # found the COLUMN of that name instead, so it decided the
            # table was already migrated and returned -- silently, which
            # is the same failure shape as the bug it is fixing.
            if not sql:
                return
            if "UNIQUE (symbol, direction, trade_date, entry_time)" in sql:
                return                      # already wide
            if "UNIQUE (symbol, direction, trade_date)" not in sql:
                return                      # some other shape; leave it

            stamp = _dt.now().strftime("%Y%m%d-%H%M%S")
            backup = f"{path}.backup-{stamp}"
            shutil.copy2(path, backup)

            # ---- THE RENAME BRINGS THE INDEXES WITH IT. ----
            #
            # SQLite moves a table's indexes when the table is renamed
            # and KEEPS THEIR NAMES, so create_all() then fails on
            # "index ix_trade_memory_entry_hour already exists" -- after
            # the rename, with the real table already out of the way.
            # The first version of this migration hit exactly that and
            # left trade_memory empty while reporting "the database is
            # untouched". Drop them first, and put the table back if
            # anything goes wrong.
            with self.engine.begin() as conn:
                before = conn.exec_driver_sql(
                    "select count(*) from trade_memory").scalar()
                cols = [r[1] for r in conn.exec_driver_sql(
                    "pragma table_info(trade_memory)")]
                idx = [r[0] for r in conn.exec_driver_sql(
                    "select name from sqlite_master where type='index' "
                    "and tbl_name='trade_memory' and name not like "
                    "'sqlite_autoindex%'")]
                for name in idx:
                    conn.exec_driver_sql(f'drop index if exists "{name}"')
                conn.exec_driver_sql(
                    "alter table trade_memory rename to trade_memory_old")

            try:
                self.metadata.create_all(self.engine)
                names = ", ".join(f'"{c}"' for c in cols)
                with self.engine.begin() as conn:
                    conn.exec_driver_sql(
                        f"insert into trade_memory ({names}) "
                        f"select {names} from trade_memory_old")
                    after = conn.exec_driver_sql(
                        "select count(*) from trade_memory").scalar()
                    if after != before:
                        raise RuntimeError(
                            f"copied {after} of {before} trades")
                    conn.exec_driver_sql("drop table trade_memory_old")
            except Exception:
                # PUT IT BACK. Losing the trade history to a bookkeeping
                # change is far worse than keeping the old constraint.
                with self.engine.begin() as conn:
                    conn.exec_driver_sql("drop table if exists trade_memory")
                    conn.exec_driver_sql(
                        "alter table trade_memory_old rename to trade_memory")
                raise

            decision(f"[LEARN] Trade memory rebuilt: a stock can be traded "
                     f"more than once a day now and every trade is kept. "
                     f"{before} past trades carried over, backup at "
                     f"{os.path.basename(backup)}.")
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LEARN] Could not widen the trade-memory constraint "
                 f"({exc}). Re-entries into the same stock will still be "
                 f"dropped from the report. The trades are intact -- the "
                 f"table was put back and a backup was written first.")

    def _add_missing_columns(self):
        """Idempotent, runs at every startup, never raises.

        Added 2026-07-28 with the reason columns. The 28 trades already
        stored keep their rows -- they simply have NULL in the new
        fields, which is honest: nobody recorded a reason for them.
        """
        try:
            from sqlalchemy import text
            with self.engine.begin() as conn:
                existing = {
                    row[1] for row in conn.execute(
                        text("PRAGMA table_info(trade_memory)")).fetchall()
                } if self.url.startswith("sqlite") else set()
                if not existing:
                    return
                for column, sql_type in self.LATE_COLUMNS.items():
                    if column in existing:
                        continue
                    conn.execute(text(
                        f"ALTER TABLE trade_memory ADD COLUMN {column} {sql_type}"))
                    diagnostic(f"[LEARN] trade_memory: added column {column}.")
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[LEARN] Could not migrate trade_memory ({exc}). "
                       f"Reason columns may not record.")

    # ----------------------------------------------------------

    def record(self, closed_position):
        """Store one completed trade. Takes the engine's own
        closed_positions record (plus the entry-context fields the
        engine stamps onto it). Returns True if newly stored. Never
        raises -- a bookkeeping failure must not affect trading."""
        try:
            symbol = closed_position.get("symbol")
            direction = closed_position.get("direction")
            # ---- A CARRIED TRADE CAME BACK AS TEXT. 1 Sept 2026. ----
            #
            # data/session_state.json is JSON, so a position that
            # survives a restart returns its times as ISO STRINGS. Every
            # isinstance(..., datetime) test below then failed and the
            # trade was filed with entry_time None -- which is the
            # signature this file uses to mean "adopted, the bot never
            # saw the fill". A trade the bot opened itself and carried
            # is not that, and must not be treated as that.
            entry_time = _as_datetime(closed_position.get("entry_time"))
            exit_time = _as_datetime(closed_position.get("exit_time"))
            if not symbol or not direction:
                return False
            trade_date = (entry_time.date().isoformat()
                          if isinstance(entry_time, datetime)
                          else datetime.now().date().isoformat())
            hour = (entry_time.strftime("%H")
                    if isinstance(entry_time, datetime) else None)
            holding = closed_position.get("holding_seconds")
            values = dict(
                symbol=symbol,
                direction=direction,
                trade_date=trade_date,
                entry_time=entry_time if isinstance(entry_time, datetime) else None,
                exit_time=exit_time,
                entry_price=closed_position.get("entry_price"),
                exit_price=closed_position.get("exit_price"),
                qty=closed_position.get("qty"),
                pnl=closed_position.get("pnl"),
                exit_reason=closed_position.get("exit_reason"),
                entry_reason=closed_position.get("entry_reason"),
                holding_minutes=(holding / 60.0) if holding else None,
                sector=closed_position.get("sector"),
                entry_hour=hour,
                rel_strength=closed_position.get("rel_strength"),
                regime=closed_position.get("regime"),
                # The reason, as it was known AT ENTRY (2026-07-28).
                news_kind=closed_position.get("news_kind"),
                filing_kind=closed_position.get("filing_kind"),
                results_grade=closed_position.get("results_grade"),
                days_since_results=closed_position.get("days_since_results"),
                had_reason=1 if closed_position.get("had_reason") else 0,
                reason_summary=closed_position.get("reason_summary"),
                # The fingerprint -- see LATE_COLUMNS. Facts, not
                # groupings. None wherever the bot could not say.
                door=closed_position.get("door"),
                volume_x=closed_position.get("volume_x"),
                jump_x=closed_position.get("jump_x"),
                liveness=closed_position.get("liveness"),
                off_high_pct=closed_position.get("off_high_pct"),
                run_up_pct=closed_position.get("run_up_pct"),
                move_age_min=closed_position.get("move_age_min"),
                reason_kind=(closed_position.get("reason_kind")
                             or closed_position.get("news_kind")),
                reason_pct_of_company=closed_position.get(
                    "reason_pct_of_company"),
                # A company's size class does not move during a
                # session, so unlike door and liveness this can be
                # read here rather than stamped at entry -- and it is
                # taken from the position first, so an engine that
                # starts stamping it later wins without a change here.
                mcap_band=(closed_position.get("mcap_band")
                           or _size_of(symbol).get("band")),
                mcap_cr=(closed_position.get("mcap_cr")
                         or _size_of(symbol).get("cap_cr")),
                # What it was worth at its best, so the capture ratio
                # is a fact about this trade and not a candle replay.
                peak_price=closed_position.get("peak_price"),
                peak_mtm=closed_position.get("peak_mtm"),
                recorded_at=_utcnow(),
            )
            with self.engine.begin() as conn:
                # ---- IT KEPT ONE TRADE PER STOCK PER DAY. 1 Sep ----
                #
                #     "for today no issue but from tomorrow it must
                #      report"                      -- the operator
                #
                # This guard exists so a restart cannot double-count a
                # trade, and it did that job. It also threw away every
                # RE-ENTRY. On 1 September the bot traded MARINE twice
                # and VTL twice; the report card showed two trades out
                # of four, silently, with no error logged:
                #
                #   MARINE  11:08 -> 11:29  +177   stored
                #   MARINE  11:30 -> 14:58   +98   DROPPED as a duplicate
                #   VTL     14:38 -> 15:02   -32   stored
                #   VTL     15:02 -> 15:17   +24   DROPPED as a duplicate
                #
                # Re-entering the same name the same day is ordinary --
                # it happened twice in one session -- so the day is not
                # a fine enough key. The ENTRY TIME is: two round trips
                # have different ones, and the same trade re-recorded
                # after a restart has the same one. Where there is no
                # entry time (an adopted broker position) the old
                # day-level guard still applies, which is the case it
                # was written for.
                where = ((self.trades.c.symbol == symbol)
                         & (self.trades.c.direction == direction)
                         & (self.trades.c.trade_date == trade_date))
                if entry_time is not None:
                    where = where & (self.trades.c.entry_time == entry_time)
                existing = conn.execute(
                    select(self.trades.c.id).where(where).limit(1)
                ).first()
                if existing is not None:
                    return False

                # ---- THE SAME FILL, FILED UNDER A SECOND DATE ----
                #
                # 16 August 2026. The check above is (symbol, direction,
                # trade_date) and its comment is honest about what that
                # buys: "a re-run or a restart can't double-count a
                # trade". It cannot see a restart on the NEXT day.
                #
                # An adopted broker position is re-adopted once per
                # process start. Start again tomorrow and the same
                # holding is adopted, closed and recorded a second time
                # under a new trade_date, which satisfies the constraint
                # perfectly:
                #
                #   CORONA     2026-08-05  2266.24 -> 2096.70  -16,954
                #   CORONA     2026-08-06  2266.24 -> 2096.70  -16,954
                #   DEEPAKNTR  x2   -6,324      DEEPAKFERT x2  -4,030
                #
                # Rs 27,309 of loss counted twice, out of a book of
                # Rs 69,766 -- so the adopted trades read 64% worse than
                # they were, and every conclusion drawn from the total
                # was drawn from a number that was wrong.
                #
                # tools/dry_run_live_path.py's junction 15 was built for
                # exactly this ("DEEPAKNTR appeared twice ... adopted
                # once per process start") and watches session_state
                # .json, which is cleared between sessions. The
                # duplicates land HERE, and here had no guard.
                #
                # ---- ONLY FOR A POSITION WITH NO FILL TIME. ----
                #
                # The first version of this guard checked every trade
                # and broke test_same_symbol_on_a_different_day_is_a_
                # new_trade, which is RIGHT: the same stock bought at
                # the same price on two different days is two trades,
                # and refusing the second would hide live business.
                #
                # The bug is specific to ADOPTED positions, and they
                # have a signature -- entry_time is None, because the
                # bot never saw the fill. A trade it opened itself
                # always carries one. So the guard applies only where
                # the fault lives.
                if values.get("entry_time") is not None:
                    try:
                        conn.execute(insert(self.trades).values(**values))
                    except IntegrityError:
                        return False
                    return True

                same_fill = conn.execute(
                    select(self.trades.c.id).where(
                        (self.trades.c.symbol == symbol)
                        & (self.trades.c.direction == direction)
                        & (self.trades.c.entry_price == values["entry_price"])
                        & (self.trades.c.exit_price == values["exit_price"])
                        & (self.trades.c.qty == values["qty"])
                    ).limit(1)
                ).first()
                if same_fill is not None:
                    return False
                try:
                    conn.execute(insert(self.trades).values(**values))
                except IntegrityError:
                    return False
            return True
        except Exception as exc:                           # noqa: BLE001
            # ---- A LOST TRADE IS A LOST P&L. 31 August 2026. ----
            #
            # This returned False and said nothing. His entire record of
            # what the bot did comes out of this store -- day_report,
            # the scorecard, every "how much did it make" answer -- so a
            # write that fails here is a trade that happened and cannot
            # be seen. The books would simply be short by one, with
            # nothing anywhere to say which one.
            warn(f"[TRADE MEMORY] Could not record a completed trade "
                 f"({exc}). The trade HAPPENED; it is missing from "
                 f"data/trade_memory.db and from every report built on "
                 f"it.")
            return False

    # ----------------------------------------------------------
    # WHAT IT HAS LEARNED  (reporting only -- nothing reads this to
    # make a trading decision)
    # ----------------------------------------------------------

    def _bucket(self, column, min_trades=1):
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    column,
                    func.count().label("n"),
                    func.sum(self.trades.c.pnl).label("total"),
                    func.avg(self.trades.c.pnl).label("avg"),
                ).group_by(column).order_by(func.count().desc())
            ).all()
        out = []
        for r in rows:
            key, n, total, avg = r[0], r[1], r[2] or 0.0, r[3] or 0.0
            if n < min_trades or key is None:
                continue
            wins = self._wins_for(column, key)
            out.append(dict(key=key, trades=n, wins=wins,
                            win_rate=100.0 * wins / n,
                            total_pnl=total, avg_pnl=avg))
        return out

    def _wins_for(self, column, key):
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.trades).where(
                    (column == key) & (self.trades.c.pnl > 0)
                )
            ).scalar_one()

    def by_sector(self, min_trades=1):
        return self._bucket(self.trades.c.sector, min_trades)

    def by_hour(self, min_trades=1):
        return sorted(self._bucket(self.trades.c.entry_hour, min_trades),
                      key=lambda d: d["key"])

    def by_direction(self, min_trades=1):
        return self._bucket(self.trades.c.direction, min_trades)

    def by_exit_reason(self, min_trades=1):
        return self._bucket(self.trades.c.exit_reason, min_trades)

    def by_symbol(self, min_trades=1):
        return self._bucket(self.trades.c.symbol, min_trades)

    def overall(self):
        with self.engine.begin() as conn:
            n = conn.execute(
                select(func.count()).select_from(self.trades)
            ).scalar_one()
            if not n:
                return dict(trades=0, sessions=0, wins=0, win_rate=0.0,
                            total_pnl=0.0, avg_win=0.0, avg_loss=0.0)
            total = conn.execute(
                select(func.sum(self.trades.c.pnl))
            ).scalar_one() or 0.0
            wins = conn.execute(
                select(func.count()).select_from(self.trades)
                .where(self.trades.c.pnl > 0)
            ).scalar_one()
            avg_win = conn.execute(
                select(func.avg(self.trades.c.pnl))
                .where(self.trades.c.pnl > 0)
            ).scalar_one() or 0.0
            avg_loss = conn.execute(
                select(func.avg(self.trades.c.pnl))
                .where(self.trades.c.pnl < 0)
            ).scalar_one() or 0.0
            sessions = conn.execute(
                select(func.count(func.distinct(self.trades.c.trade_date)))
            ).scalar_one()
        return dict(trades=n, sessions=sessions, wins=wins,
                    win_rate=100.0 * wins / n, total_pnl=total,
                    avg_win=avg_win, avg_loss=avg_loss)

    def count(self):
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.trades)
            ).scalar_one()


_default = None


def default_trade_memory():
    global _default
    if _default is None:
        _default = TradeMemory()
    return _default
