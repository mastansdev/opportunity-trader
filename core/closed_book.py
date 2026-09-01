"""
==========================================================
The closed book -- every trade, whoever placed it
==========================================================

    "post tab will be my closing positions . and pnl"
    "yes book needs to carry both right?"
                                    -- operator, 4 August 2026

WHY THIS EXISTS
---------------
On 4 August he made about Rs 10,000 trading entirely from the Dhan
platform. The bot placed zero orders. The POST tab said:

    no closed trades today

It was reading engine.closed_positions -- a list the engine appends to
when IT exits a position IT opened. Honest, and about the wrong thing.
He wanted the ACCOUNT's day; it reported the BOT's day.

That also broke his own standing rule. Open positions already show
regardless of origin, because they come from Dhan. Closed ones did not,
because nothing read Dhan's closed rows.

WHY POSITIONS AND NOT THE TRADE BOOK
------------------------------------
The obvious source is GET /trades, and it is the wrong one. It returns
that DAY's fills only. A position opened yesterday and closed today
arrives as a lone SELL with no buy to pair against -- and on MTF, with
overnight holds, that is most of his trades. Pairing fills would have
meant inventing the entry price.

GET /positions carries positionType CLOSED, with buyAvg, sellAvg and
realizedProfit already computed by the broker across whatever days the
position was open. Confirmed against DhanHQ v2 docs, not assumed:

    positionType     LONG | SHORT | CLOSED
    buyAvg/sellAvg   average in and out
    buyQty/sellQty   totals, netQty = buyQty - sellQty
    realizedProfit   booked P&L -- the broker's own number
    productType      CNC | INTRADAY | MARGIN | MTF | CO | BO

realizedProfit is the broker's arithmetic on the broker's fills. This
module does not recompute it and does not "correct" it. Where the two
disagree, Dhan is right and we are wrong -- it is his money and their
contract note.

WHAT IT DOES NOT DO
-------------------
It does not net a symbol he traded twice into one line, and it does not
subtract charges. Dhan's realizedProfit is gross of brokerage; the
charges column stays the engine's own estimate, clearly separate, so
the two are never silently mixed.

Author : H&M Opportunity Trader
==========================================================
"""

BOT = "BOT"
DHAN = "DHAN"

# A row Dhan considers finished. netQty 0 is the arithmetic definition;
# positionType CLOSED is Dhan saying so itself. Either is enough --
# requiring both would drop a row the moment one of them is missing,
# and a missing closed trade is exactly the failure being fixed.
_CLOSED = "CLOSED"


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def is_closed(row):
    """Has this position been squared off?"""
    if not isinstance(row, dict):
        return False
    if str(row.get("positionType") or "").upper() == _CLOSED:
        return True
    net = row.get("netQty")
    if net is None:
        return False
    # netQty 0 with nothing ever traded is not a closed trade, it is an
    # empty row. Those turn up and must not be counted as flat trades.
    # bool(), not the raw `and` result. This returned a quantity -- an
    # int -- which is truthy and works everywhere except a test that
    # asks `is True`. A predicate that answers 10 is a predicate nobody
    # can assert on cleanly.
    return bool(_i(net) == 0
                and (_i(row.get("buyQty")) or _i(row.get("sellQty"))))


def from_dhan(rows):
    """Dhan's own closed rows, in the shape the dashboard already draws.

    Returns [] for None so "could not ask" and "nothing closed" do not
    become the same thing further up.
    """
    out = []
    for row in (rows or []):
        if not is_closed(row):
            continue
        symbol = str(row.get("tradingSymbol") or "").upper().strip()
        if not symbol:
            continue

        buy_qty, sell_qty = _i(row.get("buyQty")), _i(row.get("sellQty"))
        entry, exit_price = _f(row.get("buyAvg")), _f(row.get("sellAvg"))

        # SHORT first, then bought back: the sell is the entry. Dhan
        # reports the same four fields either way, so direction has to
        # come from which side happened first, and the only signal in
        # the payload is positionType on the way in. A row already
        # CLOSED has lost that -- so infer it from carry-forward and
        # day quantities, and where it is genuinely ambiguous, say LONG
        # rather than guess, because realizedProfit is signed correctly
        # by Dhan regardless and nothing downstream re-derives it.
        shorted = (_i(row.get("carryForwardSellQty")) > _i(row.get("carryForwardBuyQty")))
        direction = "SHORT" if shorted else "LONG"
        if direction == "SHORT":
            entry, exit_price = exit_price, entry

        out.append({
            "symbol": symbol,
            "qty": min(buy_qty, sell_qty) or buy_qty or sell_qty,
            "entry_price": entry,
            "exit_price": exit_price,
            "direction": direction,
            # THE BROKER'S OWN NUMBER. Not recomputed here.
            "pnl": _f(row.get("realizedProfit")),
            "product": str(row.get("productType") or "").upper(),
            "origin": DHAN,
            "exit_reason": "closed on the Dhan platform",
        })
    return out


def merge(bot_rows, dhan_rows, mode=None):
    """The bot's book and the account's book, as one list.

    Where both describe the same symbol, DHAN WINS -- it is the
    settled record, and the engine's copy can drift after a restart or
    a fill it never saw. The bot's own reason is kept, because "why it
    closed" is the one thing Dhan cannot tell him.
    """
    merged = []
    by_symbol = {}
    for row in (bot_rows or []):
        row = dict(row)
        row.setdefault("origin", BOT)
        by_symbol[str(row.get("symbol") or "").upper()] = row
        merged.append(row)

    # ---- IN PAPER THEY ARE NEVER THE SAME TRADE. 1 Sept 2026. ----
    #
    #     "each mode has two tables thats settles & doesn't interfere"
    #
    # On 1 September the bot bought MARINE on paper -- 109 @ 430.16,
    # out at 431.78 for +Rs 177 -- while he separately bought MARINE
    # himself on Dhan, 100 @ 415, out at 429.91.
    #
    # Two trades, two different sums of money, one symbol. This merged
    # them into ONE row carrying HIS prices and the BOT'S label, so his
    # trade appeared in the bot's table showing +Rs 1,491 against a
    # trade that actually made Rs 177. He spotted it; every store
    # disagreed with the screen.
    #
    # The merge is right when the bot is LIVE: then the bot's order and
    # Dhan's record ARE one trade, and Dhan is the settled truth.
    #
    # In PAPER the bot's orders never reach Dhan, so a Dhan row for the
    # same symbol is always a SEPARATE, real trade of his. Merging them
    # is not reconciliation, it is two people's money in one row.
    paper = str(mode or "").upper() == "PAPER"
    for row in (dhan_rows or []):
        mine = by_symbol.get(row["symbol"])
        if mine is None or paper:
            # Paper: his row stands on its own, marked as his, even when
            # the bot happened to trade the same stock.
            merged.append(row)
            continue
        # LIVE, same symbol: one trade, two records. Take Dhan's prices
        # and P&L, keep the bot's explanation -- "why it closed" is the
        # one thing Dhan cannot tell him.
        reason = mine.get("exit_reason") or mine.get("reason")
        mine.update({k: v for k, v in row.items()
                     if k not in ("exit_reason", "origin") and v is not None})
        mine["origin"] = BOT
        if reason:
            mine["exit_reason"] = reason
    return merged


def totals(rows):
    """What the header line needs, computed once, in one place."""
    rows = [r for r in (rows or []) if r.get("pnl") is not None]
    wins = [r for r in rows if r["pnl"] > 0]
    losses = [r for r in rows if r["pnl"] < 0]
    return {
        "trades": len(rows),
        "won": len(wins),
        "lost": len(losses),
        "gross_pnl": round(sum(r["pnl"] for r in rows), 2),
        "best": round(max((r["pnl"] for r in wins), default=0.0), 2),
        "worst": round(min((r["pnl"] for r in losses), default=0.0), 2),
        "bot_trades": len([r for r in rows if r.get("origin") == BOT]),
        "dhan_trades": len([r for r in rows if r.get("origin") == DHAN]),
    }
