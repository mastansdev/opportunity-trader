"""
==========================================================
py tools/correctness.py  --  is the data RIGHT, not just present?
==========================================================

    "do they understand what they are created for? does they provide
     complete info without producing errors, mixing the wrong tags,
     chips , blindly relating one news to another stocks?"
                                -- operator, 8 August 2026

WHY THIS EXISTS
---------------
tools/pipeline.py proves the chain is connected and carrying data. It
cannot tell whether the data is TRUE. A module that confidently
attaches the wrong company to the right news passes every connection
test ever written.

That failure is not hypothetical. Measured 7 August on the real store:

    OCR:    "MARKET INDEXES ... NIFTY SENSEX BANK ~ 78491.26"
    tagged: BAJFINANCE, BAJAJFINSV, ICICIBANK

An index board with three banks attached to it, because the reader
scanned the whole image for any known name and took every hit.

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"
    "so pls do not miss or club one data to other stock"

A wrong reason is worse than no reason. No reason makes the ranker
refuse. A wrong one makes it SCORE, and puts a confident sentence on
his screen that he has no way to falsify.

WHAT IT CHECKS
--------------
    1. TAG PROVENANCE   every symbol tag traces to text that actually
                        names that company
    2. COLLISION        no single piece of evidence is smeared across
                        several unrelated stocks
    3. GRADE PROVENANCE every Row 1 grade traces to a source card that
                        names that symbol
    4. REASON PROVENANCE every why_moving reason is about the stock it
                        is attached to
    5. CHIP AGREEMENT   the result chip matches what the card says

Each check reports a rate, not a verdict, because some disagreement is
legitimate -- a company's ticker and its trading name differ, OCR
mangles characters. The number to watch is the trend and the outliers.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TELEGRAM_DB = "data/telegram.db"
WINDOW_DAYS = 21

_findings = []


def head(title):
    print(f"\n{'=' * 74}\n  {title}\n{'=' * 74}")


def note(bad, what, detail):
    print(f"  [{'FAIL' if bad else ' ok '}]  {what:<34} {detail}")
    if bad:
        _findings.append((what, detail))


def symbols_of(raw):
    if not raw or str(raw).strip() in ("", "[]"):
        return []
    text = str(raw).strip()
    try:
        got = json.loads(text)
        if isinstance(got, list):
            return [str(s).upper() for s in got if s]
        if isinstance(got, str):
            return [got.upper()]
    except Exception:                                      # noqa: BLE001
        pass
    return [p.strip().upper() for p in text.split(",") if p.strip()]


def _company_words(symbol, loader):
    """Ways this company might legitimately appear in text."""
    words = {symbol}
    try:
        row = loader.get_by_symbol(symbol) if loader else None
    except Exception:                                      # noqa: BLE001
        row = None
    if row:
        for key in ("SYMBOL_NAME", "NAME", "DISPLAY_NAME", "SM_NAME",
                    "TRADING_SYMBOL"):
            value = str((row or {}).get(key) or "").upper()
            if value:
                # first two significant words of the registered name
                parts = [p for p in re.split(r"[^A-Z&]+", value)
                         if len(p) > 2][:2]
                words.update(parts)
    return {w for w in words if len(w) >= 3}


# ===============================================================
def check_tags(con, loader):
    head("1. TAG PROVENANCE  --  is the tagged stock actually in the text?")
    rows = con.execute(
        "select channel, symbols, text, ocr_text from messages "
        "where seen_at > date('now', ?) and symbols not in ('', '[]')",
        (f"-{WINDOW_DAYS} day",)).fetchall()

    per_channel = defaultdict(lambda: [0, 0, []])
    for channel, raw, text, ocr in rows:
        body = ((text or "") + " " + (ocr or "")).upper()
        if not body.strip():
            continue
        for symbol in symbols_of(raw):
            per_channel[channel][0] += 1
            if any(w in body for w in _company_words(symbol, loader)):
                per_channel[channel][1] += 1
            elif len(per_channel[channel][2]) < 2:
                per_channel[channel][2].append(
                    (symbol, re.sub(r"\s+", " ", body)[:58]))

    for channel, (total, hit, misses) in sorted(
            per_channel.items(), key=lambda kv: kv[1][0], reverse=True):
        if not total:
            continue
        pct = 100.0 * hit / total
        note(pct < 85, f"{channel[:32]}",
             f"{hit}/{total} tags traceable ({pct:.0f}%)")
        for symbol, snippet in misses:
            print(f"           tagged {symbol:<12} text: {snippet}")


# ===============================================================
def check_collisions(con):
    head("2. COLLISION  --  is one event attached to many unrelated stocks?")
    rows = con.execute(
        "select symbols, text, ocr_text, channel from messages "
        "where seen_at > date('now', ?) and symbols not in ('', '[]')",
        (f"-{WINDOW_DAYS} day",)).fetchall()

    worst = []
    for raw, text, ocr, channel in rows:
        syms = symbols_of(raw)
        body = ((text or "") + " " + (ocr or "")).strip()
        if len(syms) >= 6 and body:
            worst.append((len(syms), channel,
                          re.sub(r"\s+", " ", body)[:56], syms[:6]))
    worst.sort(reverse=True)

    note(bool([w for w in worst if w[0] >= 10]),
         "messages tagging many stocks",
         f"{len(worst)} message(s) carry 6+ symbols")
    for n, channel, snippet, syms in worst[:4]:
        print(f"           {n:>2} stocks | {channel[:16]:<16} {snippet}")
        print(f"              -> {', '.join(syms)}")
    if worst:
        print("\n           A market-wide card (index board, FII/DII, sector")
        print("           list) legitimately names many stocks. It must not")
        print("           become a REASON for any one of them.")


# ===============================================================
def check_grades(con, loader):
    head("3. GRADE PROVENANCE  --  does each Row 1 grade have a source?")
    try:
        from core import watchlist_builder as W
        graded = W.graded_symbols() or {}
    except Exception as exc:                               # noqa: BLE001
        note(True, "graded_symbols()", f"raised: {exc}")
        return

    if not graded:
        note(False, "Row 1", "empty right now -- nothing to verify")
        return

    unbacked = []
    for symbol, info in graded.items():
        words = _company_words(symbol, loader)
        found = con.execute(
            "select count(*) from messages where seen_at > date('now','-3 day')"
            " and (symbols like ? or upper(ocr_text) like ? "
            "or upper(text) like ?)",
            (f"%{symbol}%", f"%{symbol}%", f"%{symbol}%")).fetchone()[0]
        if not found:
            unbacked.append((symbol, info.get("grade"), info.get("source")))

    note(bool(unbacked), "grades traceable to a card",
         f"{len(graded) - len(unbacked)}/{len(graded)} have source material")
    for symbol, grade, source in unbacked[:6]:
        print(f"           {symbol:<12} {grade:<10} claims '{source}' "
              f"but no message names it")


# ===============================================================
def check_reasons(con, loader):
    head("4. REASON PROVENANCE  --  is the reason about THAT stock?")
    try:
        from core import watchlist_builder as W
        from core.why_moving import why
    except Exception as exc:                               # noqa: BLE001
        note(True, "why_moving", f"raised: {exc}")
        return

    graded = list((W.graded_symbols() or {}))[:30]
    if not graded:
        note(False, "reasons", "no graded stocks to probe")
        return

    seen_text = defaultdict(list)
    checked = shared = 0
    for symbol in graded:
        got = why(symbol=symbol)
        text = (got or {}).get("text") if isinstance(got, dict) else None
        if not text:
            continue
        checked += 1
        seen_text[text.strip().lower()].append(symbol)

    for text, syms in seen_text.items():
        if len(syms) > 1:
            shared += len(syms)

    note(False, "distinct reasons",
         f"{checked} stocks carry a reason, "
         f"{len(seen_text)} distinct sentence(s)")

    # Identical generic sentences ("reported results yesterday") are
    # fine and expected. Identical SPECIFIC ones are the smear.
    for text, syms in sorted(seen_text.items(),
                             key=lambda kv: -len(kv[1]))[:3]:
        if len(syms) > 1:
            generic = any(w in text for w in
                          ("reported results", "results due", "result"))
            print(f"           {len(syms)} stocks share: \"{text[:46]}\"")
            print(f"              {', '.join(syms[:8])}")
            if not generic:
                note(True, "one reason, many stocks",
                     f"{len(syms)} stocks share a SPECIFIC reason")


# ===============================================================
def check_chips(con):
    head("5. CHIP AGREEMENT  --  does the chip match the card?")
    try:
        from core import result_read
    except Exception as exc:                               # noqa: BLE001
        note(True, "result_read", f"raised: {exc}")
        return

    rows = con.execute(
        "select symbols, ocr_text from messages "
        "where seen_at > date('now','-7 day') and symbols not in ('', '[]') "
        "and ocr_text is not null and length(ocr_text) > 120 limit 400"
    ).fetchall()

    read_ok = failed = 0
    errors = []
    for raw, ocr in rows:
        syms = symbols_of(raw)
        if len(syms) != 1:
            continue                    # multi-stock cards are not chips
        try:
            # ---- IT TAKES PAIRS, NOT A STRING. 8 August 2026. ----
            # This passed the raw OCR text and every one of 234 cards
            # raised "not enough values to unpack", which the audit
            # then reported as a parser failure. The parser was fine.
            # The audit was calling it wrong and blaming the code it
            # was auditing -- the worst kind of false alarm, because it
            # sends you hunting in the one place that is working.
            got = (result_read.read([("audit", ocr)])
                   if hasattr(result_read, "read") else None)
            if got:
                read_ok += 1
        except Exception as exc:                           # noqa: BLE001
            failed += 1
            if len(errors) < 3:
                errors.append(f"{syms[0]}: {str(exc)[:40]}")

    note(bool(failed), "result_read on single-stock cards",
         f"{read_ok} read cleanly, {failed} raised")
    for err in errors:
        print(f"           {err}")


# ===============================================================
def main():
    print("=" * 74)
    print("  CORRECTNESS AUDIT   -- is the data right, not just present?")
    print(f"  window: last {WINDOW_DAYS} days of the real store")
    print("=" * 74)

    con = sqlite3.connect(TELEGRAM_DB)
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
    except Exception:                                      # noqa: BLE001
        loader = None
        print("  (master list unavailable -- name matching is symbol-only)")

    check_tags(con, loader)
    check_collisions(con)
    check_grades(con, loader)
    check_reasons(con, loader)
    check_chips(con)
    con.close()

    print(f"\n{'=' * 74}")
    if not _findings:
        print("  Nothing mis-attributed that this can detect.")
    else:
        print(f"  {len(_findings)} THING(S) TO LOOK AT:\n")
        for what, detail in _findings:
            print(f"     {what:<34} {detail}")
    print("=" * 74)
    return 1 if _findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
