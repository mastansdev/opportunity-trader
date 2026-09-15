"""
==========================================================
Price action at the moment of buying
==========================================================

---- WHAT THE CANDLES SAY, NOT A PERCENT. 15 September 2026. ----

    "check the previous formed candles & volume, price action formed.
     if bot takes right stock at right time then this price dip concept
     won't come at all. like i asked whenever seat is free, instead of
     racing to fill that seat, bot needs to check complete
     sortlisted/ranked stocks about their rank price & current trading
     price & price action formed by that stock"      -- the operator

What it replaces: "price fell 0.0% since it was ranked" refused FSL on
15 Sep for a one-tick dip. One tick against the ranked price is not
price action. The candles are.

Read off the bot's own 1-minute candles (core/candle_engine, in memory,
fed by every tick -- no database, no network, nothing added to the tick
path). Direction only; the one count here is how many candles make a
picture:

    LOOK_BACK  the last 5 closed 1-minute candles
    AT_LEAST   3 of them before anything is judged -- until then the
               stock's price action has not formed and it waits

Four questions, each a plain yes or no:

    1. NEW LOW      is the last candle breaking below the lows of the
                    candles before it? A stock making lower lows is
                    falling, whatever its rank.
    2. RANK PRICE   is it below the price it was ranked at AND did the
                    last candle close down? Below the rank with a green
                    candle and no new low is a pullback that held --
                    that passes. Below the rank and still falling does
                    not.
    3. VOLUME       over those candles, did more shares trade on the
                    falling candles than on the rising ones? Then
                    sellers are doing the work.
    4. VWAP         is the price under today's volume-weighted average?
                    The average buyer today is losing money.

A question that cannot be read (no volume in quote-less ticks, no VWAP
yet, no ranked price) is skipped, never counted as a failure -- the rule
auto_entry keeps for the tick and the flow. Not enough candles is
different: it is the answer "not formed yet", and that one waits.

Author : H&M Opportunity Trader
==========================================================
"""

LOOK_BACK = 5
AT_LEAST = 3


def _f(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def read(candles, ltp, ranked_price=None, vwap=None,
         look_back=LOOK_BACK, at_least=AT_LEAST):
    """{"ok": bool, "why": sentence, "facts": {...}}.

    `candles` oldest first, as CandleEngine.last_n_closed returns them.
    Never raises.
    """
    try:
        bars = [c for c in (candles or [])[-look_back:]
                if _f(c.get("open")) is not None and _f(c.get("close")) is not None
                and _f(c.get("low")) is not None and _f(c.get("high")) is not None]
        ltp = _f(ltp)
        facts = {"candles": len(bars)}
        if len(bars) < at_least:
            return {"ok": False, "facts": facts,
                    "why": (f"price action not formed yet -- {len(bars)} of "
                            f"{at_least} one-minute candles closed")}

        last, before = bars[-1], bars[:-1]
        green = _f(last["close"]) >= _f(last["open"])
        prior_low = min(_f(c["low"]) for c in before)
        facts.update({"last_candle": "up" if green else "down",
                      "last_low": _f(last["low"]), "prior_low": prior_low})

        # 1. New low.
        if _f(last["low"]) < prior_low:
            return {"ok": False, "facts": facts,
                    "why": (f"making a new low -- last candle low "
                            f"{_f(last['low']):g} broke {prior_low:g} of the "
                            f"{len(before)} candles before it")}

        # 2. Rank price vs now.
        ranked = _f(ranked_price)
        price = ltp if ltp is not None else _f(last["close"])
        if ranked and price is not None:
            facts.update({"ranked_at": ranked, "now": price})
            if price < ranked and not green:
                return {"ok": False, "facts": facts,
                        "why": (f"below its ranked price ({price:g} vs "
                                f"{ranked:g}) and the last candle closed "
                                f"down -- still falling")}

        # 3. Volume on rising vs falling candles.
        up_vol = down_vol = 0.0
        known = False
        for c in bars:
            v = _f(c.get("volume"))
            if v is None or v <= 0:
                continue
            known = True
            if _f(c["close"]) >= _f(c["open"]):
                up_vol += v
            else:
                down_vol += v
        if known:
            facts.update({"up_volume": up_vol, "down_volume": down_vol})
            if down_vol > up_vol:
                return {"ok": False, "facts": facts,
                        "why": (f"more volume on falling candles than rising "
                                f"ones in the last {len(bars)} minutes "
                                f"({down_vol:,.0f} vs {up_vol:,.0f})")}

        # 4. VWAP.
        vw = _f(vwap)
        if vw and price is not None:
            facts["vwap"] = round(vw, 2)
            if price < vw:
                return {"ok": False, "facts": facts,
                        "why": (f"below today's VWAP ({price:g} vs {vw:.2f}) "
                                f"-- the average buyer today is losing")}

        bits = [f"{len(bars)} candles, no new low",
                f"last candle {'up' if green else 'down'}"]
        if ranked and price is not None:
            bits.append(f"{price:g} vs ranked {ranked:g}")
        if known:
            bits.append(f"up-volume {up_vol:,.0f} vs down {down_vol:,.0f}")
        if vw:
            bits.append("above VWAP")
        return {"ok": True, "facts": facts, "why": "; ".join(bits)}
    except Exception as exc:                               # noqa: BLE001
        # A broken check refuses the trade (tests/
        # test_a_broken_check_refuses_the_trade.py) -- a crash here is
        # not the same as a stock with no volume reading.
        return {"ok": False, "facts": {},
                "why": f"price action check failed ({exc})"}


def for_symbol(engine, symbol, ltp, ranked_price=None, now=None):
    """read() off the engine's own candles. None when the engine has no
    candle store (a test double) -- no reading, not a refusal."""
    store = getattr(engine, "candle_engine", None)
    if store is None:
        return None
    try:
        candles = list(store.last_n_closed(symbol, LOOK_BACK))
        vwap = store.vwap(symbol)
        everything = store.last_n_closed(symbol, 10 ** 6) or []
    except Exception:                                      # noqa: BLE001
        return None
    # Only today's session candles. The engine builds candles from every
    # tick, including the 09:00-09:08 pre-open, and a tick can carry a
    # stale last-trade time from the day before (15 Sep: 15:59:50) --
    # neither is price action formed in the market.
    if now is None:
        from datetime import datetime
        now = datetime.now()
    opened = now.replace(hour=9, minute=15, second=0, microsecond=0)
    # VWAP is the whole session's average. After a mid-day restart the
    # store holds only the candles since the restart, and a "VWAP" of the
    # last hour is not today's average buyer -- the same restart fault
    # that shrank the day's range (dashboard.state._day_range). So VWAP is
    # asked only when this process's candles for the stock reach back to
    # the opening minutes; otherwise that one question is skipped.
    # A stale last-trade time from yesterday can sit at the front of the
    # list, so the first candle stamped TODAY is the one that counts.
    started_late = True
    for c in everything:
        t0 = c.get("time")
        try:
            if t0 is not None and t0.date() == now.date():
                started_late = t0 > opened.replace(minute=20)
                break
        except (AttributeError, TypeError):
            continue
    if started_late:
        vwap = None
    session = []
    for c in candles:
        t = c.get("time")
        try:
            if t is not None and t.date() == now.date() and t >= opened:
                session.append(c)
        except (AttributeError, TypeError):
            continue
    return read(session, ltp, ranked_price=ranked_price, vwap=vwap)
