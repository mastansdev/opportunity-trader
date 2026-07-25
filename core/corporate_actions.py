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
    """Forthcoming NSE equity corporate actions -> memory. Returns how
    many NEW facts were stored."""
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
        return 0

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
    return stored


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
        return 0

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
    return stored


def refresh(memory=None, known_symbols=None, days_ahead=30):
    """
    One full refresh of the stock memory. Call at startup and, ideally,
    once a day. Never raises.
    """
    if memory is None:
        from core.stock_memory import default_memory
        memory = default_memory()

    n_nse = fetch_nse(memory, days_ahead, known_symbols)
    n_bse = fetch_bse(memory, days_ahead, known_symbols)

    today = datetime.now().date()
    distorting = memory.price_distorting_symbols(today)
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

    decision(
        f"[MEMORY] Stock memory refreshed: {n_nse} new from NSE, "
        f"{n_bse} new from BSE, {memory.count()} facts known in total."
    )
    return n_nse + n_bse
