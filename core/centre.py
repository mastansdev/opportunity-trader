"""
==========================================================
THE CENTRE -- one refined record per stock
==========================================================

    "we will keep the brain bot/trading bot/news bot like one owner for
     one & interconnected everything to center where everything is
     refined - stored - displayed on dashboard. now the dashboard is
     still showing the mess which i don't want to see at all as it
     brings more confusion than clarity"
                                -- operator, 8 August 2026

    "trading bot shouldn't be concerned about the subscription /
     eligibility / any other parameters"

WHY THIS EXISTS
---------------
He asked for this more than once and I did the opposite. On 8 August
alone I added a run-up chip and a delivery chip to a row that already
carried the result tag, FADING and CIRCUIT. Six things shouting at him
on one line, each true, none of them an answer.

The cause is not the chips. dashboard/state.py builds the watchlist,
reads the results cards, computes the run-up, computes delivery, ranks
the movers, sizes the position AND renders it. Four owners in one
file. A screen assembled by four owners looks like four owners.

WHAT THIS IS
------------
The place they meet. Every source stays where it is and keeps its own
job; the centre asks each one about a stock and resolves the answers
into ONE record:

    verdict     the single thing to do, in one word
    line        one sentence he can read in two seconds
    evidence    everything underneath it, for when he wants it
    blocking    why NOT, when the answer is no

    UNIVERSE  ->  is it even tradeable      (mcap, price, liquidity)
    INTEL     ->  what is known about it    (grade, reason, run-up,
                                             delivery, catalyst)
    TAPE      ->  what it is doing now      (move, volume, circuit)
                          |
                          v
                    ONE RECORD  ->  dashboard, brain, trader

STAGE 1 IS DELIBERATELY ADDITIVE
--------------------------------
Nothing is moved and nothing is deleted. The centre READS the existing
modules; the live path is untouched. He trades on Monday and a
half-migrated codebase on a Monday morning is a real risk that buys
him nothing.

Once the dashboard reads the centre instead of assembling chips
itself, the old assembly code in state.py becomes dead and can be
removed with the screen already proven against the new source.

THE ONE RULE
------------
The centre RESOLVES. It never shows two things that mean the same
thing, and it never shows a chip that says nothing. "NORMAL delivery"
and "FLAT run-up" are absences, not findings, and they do not reach
his screen.

Author : H&M Opportunity Trader
==========================================================
"""

# ---- VERDICTS ----
# One word each, ordered worst to best. A stock has exactly one.
BLOCKED = "BLOCKED"      # cannot be traded at all -- universe says no
WATCH = "WATCH"          # tradeable, nothing to act on
READY = "READY"          # a reason and the tape agree; the brain may rank it
AVOID = "AVOID"          # tradeable, but the evidence says do not

VERDICTS = (BLOCKED, AVOID, WATCH, READY)


def _safe(fn, *args, **kwargs):
    """Every source is optional. One broken input must never blank the
    whole record -- that is how a screen becomes untrustworthy."""
    try:
        return fn(*args, **kwargs)
    except Exception:                                      # noqa: BLE001
        return None


# ---------------------------------------------------------------
# UNIVERSE -- may we trade it at all
# ---------------------------------------------------------------
def _supply_of(symbol, on_date=None):
    """Is this stock under an OFS / QIP / block deal right now?"""
    from datetime import datetime
    from core import supply_events
    now = on_date
    if now is None:
        now = datetime.now()
    elif not isinstance(now, datetime):
        now = datetime.combine(now, datetime.min.time().replace(hour=9,
                                                                minute=30))
    return supply_events.overhang(symbol, now=now)


_MCAP = {}


def _mcap_from_master(symbol, path="data/master_stocks.csv"):
    """MCAP_CR straight out of the master. Loaded once."""
    if not _MCAP:
        import csv
        try:
            with open(path, newline="", encoding="utf-8",
                      errors="ignore") as handle:
                for row in csv.DictReader(handle):
                    try:
                        _MCAP[str(row["SYMBOL"]).strip().upper()] = float(
                            row.get("MCAP_CR") or 0) or None
                    except (KeyError, TypeError, ValueError):
                        continue
        except Exception:                                      # noqa: BLE001
            _MCAP["__broken__"] = None
    return _MCAP.get(str(symbol or "").upper())


def universe_of(symbol, loader=None, mcap_of=None, price=None,
                min_price=50.0, min_mcap_cr=2000.0):
    """{"tradeable", "why"} -- the gate, and the sentence for it.

    Small companies are NOT permanently excluded. The operator's rule,
    8 August:

        "2000 CRORE CAN BE SOFTENED ONLY IF STOCK MOVING WITH HIGHER
         VOLUMES THAN ITS AVERAGE & THE REAL BACK SUPPORT TO THE STOCK"

    So this returns `soften_ok` when the only failure is size -- the
    caller may still admit it if the tape and the intel both agree.
    """
    symbol = str(symbol or "").upper()
    if not symbol:
        return {"tradeable": False, "why": "no symbol", "soften_ok": False}

    if loader is not None:
        blocked = _safe(loader.blocked_symbols) or {}
        if symbol in blocked:
            return {"tradeable": False, "soften_ok": False,
                    "why": str(blocked[symbol])}

    if price is not None and price < min_price:
        return {"tradeable": False, "soften_ok": False,
                "why": f"Rs {price:,.0f} is below the Rs {min_price:,.0f} "
                       f"floor"}

    mcap = None
    if mcap_of is not None:
        mcap = _safe(mcap_of, symbol)
    if mcap is None:
        # ---- THE MASTER ALREADY KNOWS. 8 August 2026. ----
        # Every caller had to supply mcap_of, and none did, so this
        # gate silently never fired and every record came back with
        # mcap_cr = None. data/master_stocks.csv now carries MCAP_CR
        # for 95% of the watch list, from NSE's own SEBI-LODR filing.
        # A gate nobody can feed is a gate that does not exist.
        mcap = _safe(_mcap_from_master, symbol)
    if mcap is not None and mcap < min_mcap_cr:
        return {"tradeable": False, "soften_ok": True, "mcap_cr": mcap,
                "why": f"Rs {mcap:,.0f} Cr is under the "
                       f"Rs {min_mcap_cr:,.0f} Cr floor -- needs unusual "
                       f"volume AND a real reason to qualify"}

    return {"tradeable": True, "soften_ok": False, "mcap_cr": mcap,
            "why": "tradeable"}


# ---------------------------------------------------------------
# INTEL -- what is known about it
# ---------------------------------------------------------------
def intel_of(symbol, on_date=None):
    """Everything the news side knows, gathered but not yet judged."""
    out = {}

    grade = None
    try:
        from core import watchlist_builder
        graded = watchlist_builder.graded_symbols(now=on_date) or {}
        entry = graded.get(str(symbol or "").upper()) or {}
        grade = entry.get("grade")
    except Exception:                                      # noqa: BLE001
        pass
    out["grade"] = grade

    try:
        from core.why_moving import why
        reason = why(symbol=symbol, on_date=on_date)
    except Exception:                                      # noqa: BLE001
        reason = None
    out["reason"] = reason if isinstance(reason, dict) else None

    try:
        from core import runup
        out["runup"] = runup.reading(symbol, on_date=on_date)
    except Exception:                                      # noqa: BLE001
        out["runup"] = None

    try:
        from core import delivery
        out["delivery"] = delivery.reading(symbol, on_date=on_date)
    except Exception:                                      # noqa: BLE001
        out["delivery"] = None

    return out


# ---------------------------------------------------------------
# THE RESOLUTION -- the whole point of the file
# ---------------------------------------------------------------
# Absences. A screen that prints these is printing "nothing happened"
# in a box, which is how six chips became noise.
_SILENT = {"NORMAL", "FLAT", None, ""}

TOP_GRADES = ("EXCELLENT", "GREAT", "GOOD")


def record(symbol, tape=None, on_date=None, loader=None, mcap_of=None,
           min_price=50.0, min_mcap_cr=2000.0, volume_ratio=None):
    """ONE record for one stock.

    `tape` is {"ltp", "change_pct", "volume", "day_high", "day_low"} --
    whatever the live feed has right now, or None outside a session.

    Returns {"symbol", "verdict", "line", "evidence", "blocking",
             "grade", "mcap_cr"}.
    """
    symbol = str(symbol or "").upper()
    tape = tape or {}
    ltp = tape.get("ltp")

    gate = universe_of(symbol, loader=loader, mcap_of=mcap_of, price=ltp,
                       min_price=min_price, min_mcap_cr=min_mcap_cr)
    intel = intel_of(symbol, on_date=on_date)

    grade = (intel.get("grade") or "").upper() or None
    reason = intel.get("reason") or {}
    reason_text = reason.get("text") if isinstance(reason, dict) else None
    runup = intel.get("runup") or {}
    deliv = intel.get("delivery") or {}

    evidence, blocking = [], []

    # ---- SUPPLY IS NOT DEMAND. 8 August 2026. ----
    #
    #     "lic is hitting with more volumes due to some ofs news"
    #
    # core/supply_events.py was written on 8 August, tested, and
    # imported by nothing. LICI was picked on four of five replayed
    # days -- 165x its own first-minute volume, the largest flow on the
    # board -- and lost every time, while the OFS notice sat in
    # data/telegram.db from 3 August.
    #
    # An OFS, QIP or block deal produces exactly the signature the
    # volume filter hunts, and the price goes DOWN, because the whole
    # event is somebody selling. He is long only. So this is not a
    # weaker buy; it is not a buy.
    sold = _safe(_supply_of, symbol, on_date)
    if sold:
        blocking.append(sold["why"])

    # ---- the gate ----
    if not gate.get("tradeable"):
        if not gate.get("soften_ok"):
            return {"symbol": symbol, "verdict": BLOCKED,
                    "line": gate["why"], "evidence": [], "grade": grade,
                    "mcap_cr": gate.get("mcap_cr"),
                    "blocking": [gate["why"]]}
        # Small, but the operator's softening rule may still admit it.
        moving = (volume_ratio or 0) >= 2.0
        backed = bool(reason_text)
        if not (moving and backed):
            missing = []
            if not moving:
                missing.append("volume is not unusual")
            if not backed:
                missing.append("no reason behind the move")
            return {"symbol": symbol, "verdict": BLOCKED,
                    "line": gate["why"], "evidence": [], "grade": grade,
                    "mcap_cr": gate.get("mcap_cr"),
                    "blocking": missing}
        evidence.append(f"small cap admitted -- {volume_ratio:.1f}x volume "
                        f"with a reason behind it")

    # ---- what is known ----
    if grade:
        evidence.append(f"{grade} result")
    if reason_text:
        evidence.append(reason_text)
    if (runup.get("reading") or None) not in _SILENT:
        evidence.append(runup.get("text"))
        if runup.get("reading") == "SPENT":
            blocking.append("the move into the result is already spent")
    if (deliv.get("reading") or None) not in _SILENT:
        evidence.append(deliv.get("text"))
        if deliv.get("reading") == "DISTRIBUTION":
            blocking.append("delivery says stock is being distributed")
    if volume_ratio:
        evidence.append(f"{volume_ratio:.1f}x its normal volume")

    # ---- the single verdict ----
    if blocking:
        verdict = AVOID
    elif grade in TOP_GRADES and reason_text:
        verdict = READY
    elif grade in TOP_GRADES or reason_text:
        verdict = WATCH
    else:
        verdict = WATCH

    return {"symbol": symbol, "verdict": verdict,
            "line": _line(symbol, verdict, grade, reason_text, evidence,
                          blocking),
            "evidence": [e for e in evidence if e],
            "blocking": blocking, "grade": grade,
            "mcap_cr": gate.get("mcap_cr")}


def _line(symbol, verdict, grade, reason_text, evidence, blocking):
    """The one sentence. Two seconds to read, or it has failed."""
    if verdict == BLOCKED:
        return blocking[0] if blocking else "not tradeable"
    if verdict == AVOID:
        return blocking[0]
    if grade and reason_text:
        return f"{grade} result -- {reason_text}"
    if grade:
        return f"{grade} result"
    if reason_text:
        return reason_text
    return evidence[0] if evidence else "nothing known"


def records(symbols, tape_of=None, **kwargs):
    """The centre, for a list. {symbol: record}."""
    out = {}
    for symbol in (symbols or []):
        tape = _safe(tape_of, symbol) if tape_of else None
        out[str(symbol).upper()] = record(symbol, tape=tape, **kwargs)
    return out
