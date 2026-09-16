"""
==========================================================
How much of his own cash goes into one position
==========================================================

---- ONE NUMBER, AND HE SETS IT. 16 September 2026. ----

    "reduce per position to 25000 so i get 3 seats on my current capital
     & why do not u gave option to select capital allocation on
     dashboard."                                    -- the operator

He was right to ask. The figure lived in TWO constants that had to
agree and were edited by hand in a source file:

    config.MTF_MARGIN_PER_POSITION_RS   how many shares one order buys
    core.capital.OWN_CASH_PER_POSITION_RS   how many seats the cash allows

One fact, one place. This module is that place. The dashboard writes it
(POST /api/per_position/{rupees}), every sizing path reads it, and it
survives a restart because it is stored in data/position_size.json.

WHAT IT DECIDES, with his Rs 75,463 at Dhan on 16 Sep:

    Rs 50,000 per position  ->  1 seat
    Rs 25,000 per position  ->  3 seats
    Rs 15,000 per position  ->  5 seats

Smaller seats mean more positions of a smaller size -- the same money,
spread wider. It does NOT change the stop, the exit rules or the daily
loss cap.

THE BOUNDS ARE A GUARD, NOT A RULE. Below Rs 5,000 an order is smaller
than one share of many stocks; above Rs 2,00,000 a single seat would
take more than his whole account. A typed mistake must not size a real
order.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import threading

from core.logger import decision, warn

PATH = os.path.join("data", "position_size.json")

MIN_RS = 5_000.0
MAX_RS = 200_000.0

_lock = threading.Lock()
_cache = {"value": None, "mtime": None}


def _default():
    try:
        from config import MTF_MARGIN_PER_POSITION_RS
        return float(MTF_MARGIN_PER_POSITION_RS)
    except Exception:                                      # noqa: BLE001
        return 50_000.0


def per_position_rs(default=None):
    """His own cash per position, in rupees. Never raises.

    Re-read when the file changes, so a change made on the dashboard
    reaches the running bot without a restart.

    `default` is what the caller would have used before this module
    existed -- its own config constant. It is used only when he has set
    nothing, which keeps every old caller (and every test that patches
    that constant) behaving exactly as it did.
    """
    fallback = _default() if default is None else float(default)
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return fallback
    with _lock:
        if _cache["mtime"] == mtime and _cache["value"] is not None:
            return _cache["value"]
    try:
        with open(PATH, encoding="utf-8") as handle:
            value = float((json.load(handle) or {}).get("per_position_rs"))
    except Exception as exc:                               # noqa: BLE001
        warn(f"[SIZE] Could not read {PATH} ({exc}) -- using "
             f"Rs {fallback:,.0f} per position.")
        return fallback
    if not (MIN_RS <= value <= MAX_RS):
        warn(f"[SIZE] Rs {value:,.0f} per position is outside "
             f"Rs {MIN_RS:,.0f}-{MAX_RS:,.0f} -- using Rs {fallback:,.0f}.")
        return fallback
    with _lock:
        _cache["value"], _cache["mtime"] = value, mtime
    return value


def set_per_position_rs(value, who="dashboard"):
    """Store a new size. Returns (ok, message) -- the message is shown
    to him, so a refusal says what was wrong with the number."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False, f"{value!r} is not a number of rupees"
    if value != value or not (MIN_RS <= value <= MAX_RS):
        return False, (f"Rs {value:,.0f} is outside the allowed range "
                       f"Rs {MIN_RS:,.0f} to Rs {MAX_RS:,.0f}")
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"per_position_rs": value, "set_by": who}, handle)
        os.replace(tmp, PATH)
    except OSError as exc:
        return False, f"could not save it ({exc})"
    with _lock:
        _cache["value"], _cache["mtime"] = None, None
    decision(f"[SIZE] Own cash per position is now Rs {value:,.0f} "
             f"(set from the {who}). New entries are sized on it; open "
             f"positions are untouched.")
    return True, f"Rs {value:,.0f} per position"


def seats_for(capital_rs):
    """How many positions `capital_rs` buys at the current size. For the
    screen -- core/capital.slots() remains the decision."""
    try:
        return int(float(capital_rs) // per_position_rs())
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
