"""
==========================================================
Everything the bot knows about ONE stock
==========================================================

    "dashboard must contain all info from bot. recall the memory of
     any stock on demand"                -- operator, 29 July 2026

That sentence is a principle, not a feature: if the bot holds a fact
and acts on it, hiding that fact is a bug by definition. Four times in
one session the answer to his question was "the bot knows, the screen
doesn't" -- the results calendar, entry reasons, circuit bands, and
what a company actually does.

WHAT THIS IS
------------
One read that gathers, for a single symbol, every piece the bot already
has scattered across eight places:

    master_stocks.csv     what the business is, sector, exposures
    circuit_monitor       live price, prev close, day range, UC / LC
    orb_engine            today's opening range
    breakout_feed         did it break out, which attempt
    signal_journal        was it taken or refused, and why
    quarterly_results     last quarter, QoQ, YoY, grade
    announcement_watcher  filings today
    news_watcher          news today
    trade_memory          every trade the operator has ever made in it
    open_positions        what is held right now

NOTHING IS COMPUTED HERE that is not already computed elsewhere. This
is a gatherer, not a calculator -- a second implementation of any of
those numbers would eventually disagree with the first, and then the
dashboard would be confidently wrong in a new way.

EVERY SOURCE IS OPTIONAL. A missing feed produces a missing SECTION,
never a wrong number and never an exception. The card degrades to what
is actually known, which is the whole point of it.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import diagnostic


def _f(value):
    """A float, or None. Never raises, never guesses."""
    try:
        out = float(value)
        return out if out == out else None          # NaN guard
    except (TypeError, ValueError):
        return None


def _text(value):
    """A clean string, or None.

    An empty cell in master_stocks.csv comes back from pandas as the
    float NaN, and NaN IS TRUTHY -- so `row.get(...) or None` sails
    straight past it and hands NaN to the JSON encoder, which refuses
    it: "Out of range float values are not JSON compliant". That is a
    500 on /api/stock/<symbol> for EVERY symbol in the universe, and
    the stock search -- the whole point of the new dashboard -- came
    back blank for all 973 of them. One empty cell, every search.
    """
    if value is None:
        return None
    if isinstance(value, float) and value != value:        # NaN
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None


def _split(value):
    """The master file stores lists as 'A | B | C'."""
    value = _text(value)
    if not value:
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


class StockCard:
    """Gathers one symbol's whole picture. Read-only, fail-quiet."""

    def __init__(self, engine=None, market_data=None, master_loader=None,
                 quarterly_results=None, announcement_watcher=None,
                 news_watcher=None, trade_memory=None, signal_journal=None,
                 telegram=None, news_impact=None, stock_memory=None,
                 stock_events=None):
        self.engine = engine
        self.market_data = market_data
        self.master_loader = master_loader
        self.quarterly_results = quarterly_results
        self.announcement_watcher = announcement_watcher
        self.news_watcher = news_watcher
        self.trade_memory = trade_memory
        self.signal_journal = signal_journal
        self.telegram = telegram
        # core/stock_events.py -- what has HAPPENED to this stock, typed
        # and with the numbers pulled out. The raw messages are still
        # reachable through `telegram`; this is the curated view.
        self.stock_events = stock_events
        self.news_impact = news_impact
        # core/stock_memory.py -- dividends, splits, bonuses, demergers
        # with ex-dates. The bot VETOES on these; the card must show them.
        self.stock_memory = stock_memory

    # ------------------------------------------------------------

    def build(self, symbol):
        """The whole card. Always returns a dict; `found` says whether
        this symbol exists in the master at all."""
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return {"found": False, "symbol": "", "reason": "no symbol given"}

        card = {"symbol": symbol, "found": False}
        for section, builder in (
                ("business", self._business),
                ("price", self._price),
                ("today", self._today),
                ("results", self._results),
                ("news", self._news),
                ("history", self._history),
                ("position", self._position),
                ("memory", self._memory),
                ("events", self._events),
                # NOTE, 30 July 2026: telegram chatter and news->stock
                # impact are NOT separate sections. _news() below already
                # nests them under "telegram" and "impact", and adding
                # top-level copies created two sources for the same truth
                # -- which is the exact drift that produced every bug
                # found today. One shape, read correctly.
        ):
            try:
                card[section] = builder(symbol)
            except Exception as exc:                       # noqa: BLE001
                # A broken section must never cost the operator the
                # other six.
                diagnostic(f"[CARD] {symbol} {section}: {exc}")
                card[section] = None
        card["found"] = bool(card.get("business") or card.get("price"))
        return card

    # ------------------------------------------------------------

    def _business(self, symbol):
        """What the company actually does. Already in the master file
        for all 973 stocks and never once shown on screen."""
        if self.master_loader is None:
            return None
        row = self.master_loader.get_by_symbol(symbol)
        if not row:
            return None
        # Every field goes through _text(). Any empty cell in the
        # master is a NaN, and one NaN anywhere in this dict is a 500
        # for the whole card.
        return {
            "name": _text(row.get("COMPANY NAME")),
            "sector": _text(row.get("SECTOR")),
            "industry": _text(row.get("INDUSTRY")),
            "does": _text(row.get("CORE BUSINESS")),
            "type": _text(row.get("BUSINESS_TYPE")),
            "ownership": _text(row.get("OWNERSHIP")),
            "commodity_exposure": _split(row.get("COMMODITY_EXPOSURE")),
            "economic_sensitivity": _split(row.get("ECONOMIC_SENSITIVITY")),
            "themes": _split(row.get("THEMES")),
            "tradeable": (_text(row.get("SUBSCRIBE")) or "").upper() == "YES",
            "not_tradeable_because": _text(row.get("SUBSCRIBE_REASON")),
        }

    def _price(self, symbol):
        """Live price and the circuit bands -- polled all day by
        core/circuit_monitor.py and shown nowhere."""
        quote = {}
        if self.engine is not None:
            try:
                quote = (self.engine.get_circuit_snapshot() or {}).get(symbol) or {}
            except Exception:                              # noqa: BLE001
                quote = {}
        live = None
        if self.market_data is not None:
            live = _f(self.market_data.get_latest_price(symbol))

        last = live if live is not None else _f(quote.get("last_price"))
        prev = _f(quote.get("prev_close"))
        upper = _f(quote.get("upper_circuit_limit"))
        lower = _f(quote.get("lower_circuit_limit"))
        if last is None and prev is None:
            return None

        out = {
            "last": last, "prev_close": prev,
            "open": _f(quote.get("open")),
            "high": _f(quote.get("high")), "low": _f(quote.get("low")),
            "volume": quote.get("volume"),
            "upper_circuit": upper or None, "lower_circuit": lower or None,
        }
        if last is not None and prev:
            out["change_pct"] = round((last - prev) / prev * 100, 2)
        # How close to a circuit -- the number that decides whether the
        # bot may enter, and whether a long is at its best or its worst.
        if last is not None and upper and upper > 0:
            out["pct_to_upper"] = round((upper - last) / last * 100, 2)
        if last is not None and lower and lower > 0:
            out["pct_to_lower"] = round((last - lower) / last * 100, 2)
        return out

    def _today(self, symbol):
        """The opening range, the breakout, and what the bot did."""
        out = {}
        if self.engine is not None:
            try:
                orb = self.engine.orb_engine.get_range(symbol)
                if orb:
                    out["orb_high"] = _f(orb.get("high"))
                    out["orb_low"] = _f(orb.get("low"))
                    out["orb_complete"] = self.engine.orb_engine.is_complete(symbol)
            except Exception:                              # noqa: BLE001
                pass
            try:
                blocks = dict(self.engine.entry_blocked).get(symbol) or {}
                if blocks:
                    out["blocked"] = dict(blocks)
            except Exception:                              # noqa: BLE001
                pass
            try:
                feed = self.engine.breakout_feed
                if feed is not None:
                    out["attempt"] = feed.attempt_for(symbol, "LONG")
            except Exception:                              # noqa: BLE001
                pass
            try:
                out["volume_multiple"] = self.engine._volume_multiple(
                    symbol, self.engine.candle_engine.last_closed(symbol))
            except Exception:                              # noqa: BLE001
                pass
        return out or None

    def _results(self, symbol):
        """Last quarter with its grade. core/quarterly_results.py."""
        if self.quarterly_results is None:
            return None
        compared = self.quarterly_results.compare(symbol)
        if not compared:
            return None
        qoq = compared.get("qoq") or {}
        yoy = compared.get("yoy") or {}
        return {
            "period": compared.get("period"),
            "grade": compared.get("grade"),
            "summary": compared.get("summary"),
            "sales_qoq": qoq.get("sales"), "pat_qoq": qoq.get("pat"),
            "sales_yoy": yoy.get("sales"), "pat_yoy": yoy.get("pat"),
            "opm_bps_qoq": qoq.get("opm_bps"),
        }

    def _news(self, symbol):
        """Filings and news today, if any."""
        out = {}
        if self.announcement_watcher is not None:
            item = self.announcement_watcher.for_symbol(symbol)
            if item:
                out["filing"] = {"kind": item.get("kind"),
                                 "at": item.get("filed_at") or item.get("at"),
                                 "subject": item.get("subject")
                                 or item.get("headline")}
        if self.news_watcher is not None:
            item = self.news_watcher.for_symbol(symbol)
            if item:
                out["news"] = {"kind": item.get("kind"),
                               "at": item.get("at"),
                               "headline": item.get("headline")
                               or item.get("title")}
        # What the operator's Telegram channels have said about this
        # stock. Shown next to the filings and clearly labelled as
        # chat, because they are not the same kind of fact.
        if self.telegram is not None:
            said = self.telegram.for_symbol(symbol, limit=3)
            if said:
                out["telegram"] = said
        # Every story that touched this stock, whether or not the
        # company was named in it -- the ABS-regulation-to-Bosch link.
        if self.news_impact is not None:
            touched = self.news_impact.for_symbol(symbol, limit=5)
            if touched:
                out["impact"] = touched
        return out or None

    def _events(self, symbol):
        """Every recorded event for this stock, newest first.

            "we cannot throw away data just like that ... by completing
             these 3 items we will see the end to end on stock"

        RESULT with its grade, ORDER with its value and customer, NEWS
        with its headline -- the answer to "has anything happened to this
        company", without reading a single message.
        """
        if self.stock_events is None:
            return None
        try:
            rows = self.stock_events.for_symbol(symbol, limit=20) or []
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[CARD] {symbol} events: {exc}")
            return None
        if not rows:
            return None
        return {"rows": [{
            "at": r.get("at"), "kind": r.get("kind"),
            "grade": r.get("grade"), "value_cr": r.get("value_cr"),
            "counterparty": r.get("counterparty"),
            "headline": r.get("headline"), "source": r.get("source"),
            "url": r.get("url"),
            "from_image": bool(r.get("from_image")),
        } for r in rows], "count": len(rows)}

    def _memory(self, symbol):
        """Corporate actions the bot holds for this stock.

            "memory -- everything must be showed on demand"

        An ex-date inside a holding period is a VETO, and the bot applies
        it without asking. Showing it is the difference between "the bot
        refused this" and "the bot refused this BECAUSE the stock goes
        ex-dividend on the 13th".
        """
        if self.stock_memory is None:
            return None
        try:
            facts = self.stock_memory.history_for(symbol) or []
        except Exception:                                  # noqa: BLE001
            return None
        if not facts:
            return None
        def _date(v):
            # ex_date arrives as a datetime.date. The JSON encoder refuses
            # it, and one refusal is a 500 for the WHOLE card -- the same
            # way one NaN from the master file used to blank every search.
            return v.isoformat() if hasattr(v, "isoformat") else (
                str(v) if v else None)

        return {"actions": [{"action": f.get("action_type"),
                             "ex_date": _date(f.get("ex_date")),
                             "detail": f.get("detail"),
                             "source": f.get("source")} for f in facts[:10]],
                "count": len(facts)}

    def _history(self, symbol):
        """Every trade the operator has ever made in this stock.

        The question a card exists to answer: have I been here before,
        and how did it go. KAYNES on 29 July is the example -- bought
        3,338, trail-exited 3,398, then it ran to 3,685.
        """
        if self.trade_memory is None:
            return None
        # by_symbol() returns a LIST of {"key": SYMBOL, ...}, not a dict
        # keyed by symbol. Calling .get() on it raised, the try above
        # swallowed it, and every stock silently read "never traded" --
        # found by running the preview rather than by any test.
        rows = self.trade_memory.by_symbol(min_trades=1) or []
        for row in rows:
            if (row.get("key") or "").upper() == symbol:
                return {
                    "trades": row.get("trades"),
                    "wins": row.get("wins"),
                    "win_rate": row.get("win_rate"),
                    "pnl": row.get("total_pnl"),
                    "avg_pnl": row.get("avg_pnl"),
                }
        return None

    def _position(self, symbol):
        """What is held right now, if anything."""
        if self.engine is None:
            return None
        position = (self.engine.open_positions or {}).get(symbol)
        if not position:
            return None
        return {
            "qty": position.get("qty"),
            "entry_price": _f(position.get("entry_price")),
            "entry_time": str(position.get("entry_time") or ""),
            "entry_reason": position.get("entry_reason"),
            "stop": _f(position.get("atr_stop")
                       if position.get("atr_stop") is not None
                       else position.get("initial_stop")),
            "yours": position.get("entry_reason", "").startswith("MANUAL"),
        }
