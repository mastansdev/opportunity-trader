"""
==========================================================
Corporate Actions Fetcher -- fills the Stock Memory
==========================================================

Pulls forthcoming corporate actions from NSE and BSE (both libraries
already installed for the news engine) and writes them into
core/stock_memory.py, so the engine can ask "is anything special
happening with this stock today?" BEFORE it trades.

The exchanges publish these ahead of time -- splits, bonuses, dividends,
rights, demergers all have a known EX-DATE. There is no excuse for the
bot to be surprised by one, which is exactly what happened with JLHL's
2:10 split on 2026-07-24 (read as an -80% crash).

Failure posture, same as every other external feed in this project:
NEVER raise. A blocked IP, a changed response shape, or a dead endpoint
means the memory simply isn't updated -- the bot then behaves exactly as
it does today. A missing fact must never stop trading.

KNOWN RISK (carried over from news_bot/exchange_announcements.py): NSE
and BSE have been observed refusing connections from cloud/datacenter
IPs. The first real run's log is the verdict for your machine.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

from core.logger import decision, diagnostic, warn

# Exchange "purpose" text -> our normalized action type. Matched as a
# lowercase substring, longest/most specific first, because the raw
# strings are messy ("Bonus issue 1:1", "Interim Dividend - Rs 4/-",
# "Face Value Split From Rs.10/- To Rs.2/-").
_PURPOSE_MAP = [
    ("demerger", "DEMERGER"),
    ("split", "SPLIT"),
    ("sub-division", "SPLIT"),
    ("subdivision", "SPLIT"),
    ("face value", "SPLIT"),
    ("bonus", "BONUS"),
    ("rights", "RIGHTS"),
    ("buyback", "BUYBACK"),
    ("buy back", "BUYBACK"),
    ("dividend", "DIVIDEND"),
    ("amalgamation", "DEMERGER"),
    ("scheme of arrangement", "DEMERGER"),
]


def classify_purpose(text):
    """Map an exchange purpose string to our action type, or None if it
    isn't something that affects price."""
    if not text:
        return None
    low = str(text).lower()
    for needle, action in _PURPOSE_MAP:
        if needle in low:
            return action
    return None


def _parse_date(value):
    """Exchange date strings come in several shapes. Returns a date or
    None -- never raises, never guesses."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%d-%m-%Y",
                "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _first(row, *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def fetch_nse(memory, days_ahead=30, known_symbols=None):
    """Forthcoming NSE equity corporate actions -> memory.

    Returns (fetched, stored). BOTH numbers, because reporting only
    `stored` made the startup line ambiguous: 2026-07-27 08:30 stored 19
    new facts, and every restart after that printed "0 new from NSE, 0
    new from BSE" simply because the same rows were already held.
    MONDAY_CHECKLIST.md read that as "exchanges blocking" and the
    operator was told, wrongly, that the memory was dead. A real failure
    prints a [CORP_ACTIONS] warning and returns (0, 0); a healthy repeat
    run returns (150, 0). Those must not look identical."""
    stored = 0
    try:
        from nse import NSE
        with NSE(download_folder="data") as nse:
            rows = nse.actions(
                segment="equities",
                from_date=datetime.now() - timedelta(days=2),
                to_date=datetime.now() + timedelta(days=days_ahead),
            ) or []
    except Exception as exc:
        warn(f"[CORP_ACTIONS] NSE fetch failed (bot continues): {exc}")
        return (0, 0)

    for row in rows:
        try:
            symbol = _first(row, "symbol", "Symbol", "SYMBOL")
            purpose = _first(row, "subject", "purpose", "Purpose", "SUBJECT")
            ex = _parse_date(_first(row, "exDate", "ex_date", "EX-DATE", "exdate"))
            if not symbol or ex is None:
                continue
            symbol = str(symbol).strip().upper()
            if known_symbols is not None and symbol not in known_symbols:
                continue                    # not in our 750, ignore
            action = classify_purpose(purpose)
            if action is None:
                continue
            if memory.remember(symbol, action, ex, detail=str(purpose or ""),
                               source="NSE"):
                stored += 1
        except Exception:
            continue                        # one bad row never stops the rest
    return (len(rows), stored)


def fetch_bse(memory, days_ahead=30, known_symbols=None):
    """Same for BSE. Symbols are matched by the scrip's short name when
    available; rows we can't map to our universe are skipped."""
    stored = 0
    try:
        from bse import BSE
        with BSE(download_folder="data") as b:
            rows = b.actions(
                segment="equity",
                from_date=datetime.now() - timedelta(days=2),
                to_date=datetime.now() + timedelta(days=days_ahead),
            ) or []
    except Exception as exc:
        warn(f"[CORP_ACTIONS] BSE fetch failed (bot continues): {exc}")
        return (0, 0)

    for row in rows:
        try:
            symbol = _first(row, "short_name", "scrip_name", "ShortName",
                            "Scrip_Name", "symbol")
            purpose = _first(row, "Purpose", "purpose", "LongName")
            ex = _parse_date(_first(row, "Ex_date", "ex_date", "ExDate",
                                    "exdate"))
            if not symbol or ex is None:
                continue
            symbol = str(symbol).strip().upper()
            if known_symbols is not None and symbol not in known_symbols:
                continue
            action = classify_purpose(purpose)
            if action is None:
                continue
            if memory.remember(symbol, action, ex, detail=str(purpose or ""),
                               source="BSE"):
                stored += 1
        except Exception:
            continue
    return (len(rows), stored)


def _daily_close_lookup():
    """symbol -> last stored daily close, or None if the daily store is
    unavailable. Built once per refresh and cached in a dict, so the
    materiality check does not hit SQLite once per action."""
    try:
        from core.daily_store import DailyStore
        store = DailyStore()
        cache = {}

        def lookup(symbol):
            if symbol not in cache:
                bars = store.history(symbol, days=1)
                cache[symbol] = bars[-1]["close"] if bars else None
            return cache[symbol]

        return lookup
    except Exception:
        return None


def refresh(memory=None, known_symbols=None, days_ahead=30):
    """
    One full refresh of the stock memory. Call at startup and, ideally,
    once a day. Never raises.
    """
    if memory is None:
        from core.stock_memory import default_memory
        memory = default_memory()

    got_nse, n_nse = fetch_nse(memory, days_ahead, known_symbols)
    got_bse, n_bse = fetch_bse(memory, days_ahead, known_symbols)

    today = datetime.now().date()

    # Materiality (2026-07-26). A dividend shifts the reference price by
    # the rupee amount, which is usually a fraction of a percent -- on
    # 2026-07-26 this rule was blocking CRISIL for 0.23% and TATACAP for
    # 0.17%, both well inside a normal day's range. Last close comes from
    # the daily-candle store; if it is unavailable, price_lookup stays
    # None and EVERY price-adjusting action blocks, exactly as before.
    price_lookup = _daily_close_lookup()

    distorting = memory.price_distorting_symbols(today,
                                                 price_lookup=price_lookup)
    if distorting:
        decision(
            "[MEMORY] Price-distorting corporate actions in effect around "
            "today -- these will NOT be traded: "
            + ", ".join(f"{s} ({'; '.join(r)})" for s, r in
                        sorted(distorting.items())[:12])
            + ("..." if len(distorting) > 12 else "")
        )
    else:
        diagnostic("[MEMORY] No price-distorting corporate actions today.")

    # Say out loud what we chose to IGNORE. A stock quietly not being
    # blocked is exactly the kind of decision that should be auditable.
    ignored = memory.immaterial_symbols(today, price_lookup=price_lookup)
    if ignored:
        decision(
            "[MEMORY] Too small to matter, still tradeable: "
            + ", ".join(f"{s} ({'; '.join(r)})" for s, r in
                        sorted(ignored.items())[:12])
            + ("..." if len(ignored) > 12 else "")
        )

    # FETCHED and NEW are both printed. "0 new" on its own is ambiguous
    # -- it is the normal answer on any restart after the first, and it
    # is also what a dead feed looks like. "150 fetched, 0 new" is
    # healthy; "0 fetched, 0 new" is the one to worry about, and it is
    # always accompanied by a [CORP_ACTIONS] warning above.
    healthy = "" if (got_nse or got_bse) else "  <-- NOTHING FETCHED, see warnings above"
    decision(
        f"[MEMORY] Stock memory refreshed: NSE {got_nse} fetched / "
        f"{n_nse} new, BSE {got_bse} fetched / {n_bse} new. "
        f"{memory.count()} facts known in total.{healthy}"
    )
    return n_nse + n_bse
