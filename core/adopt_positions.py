"""
==========================================================
Every position gets a stop -- including the ones he opened
==========================================================

    "my goal is to stop manual trading & let the bot trade . do not
     ask me how ? thats your job"
    "everything i need control over the bot. it must follow me ."
                                -- operator, 5 August 2026

WHAT WAS WRONG
--------------
On the evening of 5 August the bot's own log said this, three times:

    [BOOK] BERGEPAINT: 100 at Dhan, opened outside the bot.
           Shown on the panel; the bot will not stop or exit it.
    [BOOK] DEEPAKNTR: 100 ...
    [BOOK] MOREPENLAB: 2000 ...

About Rs 2 lakh on MTF, carried overnight, with no stop, no trail and
nothing watching it. DEEPAKNTR had fallen 6% that day and made its
high in the first sixty seconds.

That behaviour came from a rule he set on 3 August --

    "why bot is concerned on user trading - thats his choice"

-- and it was right THEN, when the complaint was the bot nagging him
every sixty seconds for using the Dhan app. It is wrong NOW, because
what he wants has changed:

    "my goal is to stop manual trading & let the bot trade"

"Do not nag me about my trades" and "do not protect my trades" are
different instructions. The bot has been obeying the first by doing
the second.

WHAT THIS DOES
--------------
A position that appears at the broker and is not in the bot's book is
ADOPTED: recorded as a real position, with a stop seeded from the same
hard floor the bot uses for its own entries, so the trailing stop, the
target, the circuit guard and MOVE_DIED all start working on it.

WHAT IT WILL NOT DO
-------------------
It never invents an entry price. Dhan sends the average cost on every
holding; without one there is nothing to measure a stop against and
the position is left alone and SAID SO, loudly, rather than protected
with a guessed number.

It never adopts silently. Every adoption prints what stop was placed
and why, because the first he hears of it must not be a sell order.

It adopts only what the BROKER confirms. The direction of travel is
always Dhan -> bot, never bot -> Dhan, so a bug here can add a stop to
something he owns. It cannot invent a position he does not.

Author : H&M Opportunity Trader
==========================================================
"""

LONG = "LONG"
SHORT = "SHORT"

# The same floor the Engine seeds its own manual buys with. Kept as an
# argument rather than imported so the caller passes the one live
# config value and this file has no opinion of its own.
DEFAULT_STOP_PCT = 0.025


def stop_for(entry_price, direction, stop_pct=DEFAULT_STOP_PCT,
             last_price=None):
    """The hard stop for an adopted position, or None.

    ---- A STOP MEASURED FROM ENTRY CAN ALREADY BE BREACHED ----
         5 August 2026.

        "if yes morning all will exit as all are under the prices u
         mentioned. which i don't want ."

    The first version of this measured 2.5% below what he PAID. For a
    position already underwater that stop sits ABOVE the current
    price, and the very first tick of the next session sells it.

    His three real holdings, checked against the 5 August closes:

        BERGEPAINT   paid  546.26  stop  532.60  closed  540.65   ok
        MOREPENLAB   paid   77.77  stop   75.82  closed   76.77   ok
        DEEPAKNTR    paid 1799.94  stop 1754.94  closed 1723.50   <-- BELOW

    DEEPAKNTR would have been market-sold at the open for about
    Rs 7,644, not because he chose to cut it and not because anything
    moved, but because the bot adopted it with a stop it had already
    passed. Protection that liquidates on contact is not protection.

    So the stop is measured from WHERE IT IS as well as what he paid,
    and the wider of the two wins -- for a long, whichever is LOWER.
    An underwater position gets room to work; it never gets sold for
    being underwater at the moment it was adopted.

    No entry price means no stop. A guessed one would be a sell order
    at a number nobody chose.
    """
    try:
        entry = float(entry_price)
    except (TypeError, ValueError):
        return None
    if entry <= 0:
        return None
    pct = abs(float(stop_pct or DEFAULT_STOP_PCT))

    try:
        last = float(last_price) if last_price is not None else None
    except (TypeError, ValueError):
        last = None
    if last is not None and last <= 0:
        last = None

    if str(direction or LONG).upper() == SHORT:
        stop = entry * (1.0 + pct)
        if last is not None:
            stop = max(stop, last * (1.0 + pct))
        return round(stop, 2)

    stop = entry * (1.0 - pct)
    if last is not None:
        stop = min(stop, last * (1.0 - pct))
    return round(stop, 2)


def plan_adoptions(only_at_broker, already_held=None,
                   stop_pct=DEFAULT_STOP_PCT, price_of=None,
                   prev_close_of=None, skip_symbols=None):
    """What to adopt, and what cannot be adopted and why.

    `only_at_broker` is core/broker_sync.compare()'s list -- the rows
    Dhan has that the bot does not.

    Returns (adopt, skip):
        adopt  [{"symbol", "qty", "direction", "entry_price", "stop"}]
        skip   [{"symbol", "why"}]           -- every one is printed
    """
    held = {str(s).upper() for s in (already_held or [])}
    # His own positions from before this session. Never adopted --
    # "i told you too not track my old positions."
    held |= {str(s).upper() for s in (skip_symbols or [])}
    adopt, skip = [], []

    for row in (only_at_broker or []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in held:
            continue

        qty = row.get("broker_qty")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            qty = 0.0
        if not qty:
            continue

        direction = SHORT if qty < 0 else LONG
        entry = row.get("avg_price")
        # WHERE IT IS, not only what he paid. See stop_for(): a stop
        # measured from entry alone is already breached on anything
        # underwater, and adoption becomes liquidation.
        last = row.get("cmp")
        if last is None and price_of is not None:
            try:
                last = price_of(symbol)
            except Exception:                              # noqa: BLE001
                last = None
        # ---- BEFORE 09:15 THERE IS NO LIVE PRICE. 6 August 2026. ----
        #
        # Adoption runs at 08:00, when the feed has not spoken. last
        # came back None, stop_for() fell back to his COST, and three
        # positions were armed with stops ABOVE the market:
        #
        #     CORONA      stop 2209.59   last close 2097.00
        #     DEEPAKFERT  stop 1633.12   last close 1590.30
        #     DEEPAKNTR   stop 1754.94   last close 1723.50
        #
        # All three would have been market-sold on the first tick of
        # the session. That is the SAME defect he caught last night --
        # I fixed it for the case where a price exists and left the
        # pre-open path measuring from cost.
        #
        # Yesterday's close is the last price the market actually
        # traded at. It is the right reference until the feed opens.
        if last is None and prev_close_of is not None:
            try:
                last = prev_close_of(symbol)
            except Exception:                              # noqa: BLE001
                last = None
        stop = stop_for(entry, direction, stop_pct, last_price=last)
        if stop is None:
            # LOUD, not silent. An unprotected position he does not
            # know about is worse than one he does.
            skip.append({
                "symbol": symbol,
                "why": ("Dhan sent no average cost, so there is no price "
                        "to set a stop against. It is NOT protected -- "
                        "set one in the Dhan app."),
            })
            continue

        underwater = (last is not None
                      and ((direction == LONG and float(last) < float(entry))
                           or (direction == SHORT
                               and float(last) > float(entry))))
        adopt.append({"symbol": symbol, "qty": abs(qty),
                      "direction": direction,
                      "entry_price": float(entry), "stop": stop,
                      "last_price": last, "underwater": underwater})
    return adopt, skip


def adopt(only_at_broker, engine, security_id_of=None,
          stop_pct=DEFAULT_STOP_PCT, register=None, say=None,
          warn_about=None, price_of=None, prev_close_of=None,
          skip_symbols=None):
    """Put the broker's positions into the bot's book, each with a stop.

    `register(symbol, qty, direction, entry_price, stop, security_id)`
    is injected so this is testable without an Engine and so nothing
    here reimplements what the Engine already does.

    Never raises -- it runs on the trading loop.
    """
    held = set(getattr(engine, "open_positions", {}) or {})
    adoptions, skipped = plan_adoptions(only_at_broker, held, stop_pct,
                                        price_of=price_of,
                                        prev_close_of=prev_close_of,
                                        skip_symbols=skip_symbols)

    for row in skipped:
        if warn_about is not None:
            warn_about(f"[ADOPT] {row['symbol']}: {row['why']}")

    done = []
    for row in adoptions:
        security_id = None
        if security_id_of is not None:
            try:
                security_id = security_id_of(row["symbol"])
            except Exception:                              # noqa: BLE001
                security_id = None
        if not security_id:
            if warn_about is not None:
                warn_about(f"[ADOPT] {row['symbol']}: no security id, so "
                           f"the bot cannot place an exit for it. NOT "
                           f"protected.")
            continue
        try:
            register(row["symbol"], row["qty"], row["direction"],
                     row["entry_price"], row["stop"], security_id)
        except Exception as exc:                           # noqa: BLE001
            if warn_about is not None:
                warn_about(f"[ADOPT] {row['symbol']}: could not be "
                           f"adopted ({exc}). NOT protected.")
            continue
        if say is not None:
            note = ""
            if row.get("underwater") and row.get("last_price"):
                note = (f" It is already under water at "
                        f"{float(row['last_price']):.2f}, so the stop is "
                        f"set below THAT, not below your cost -- it will "
                        f"not be sold just for being down.")
            say(f"[ADOPT] {row['symbol']} {row['direction']} "
                f"{row['qty']:.0f} @ {row['entry_price']:.2f} is now in "
                f"the bot's book with a stop at {row['stop']:.2f}. You "
                f"opened it; the bot will protect it and can exit it."
                + note)
        done.append(row)
    return done, skipped
