"""
==========================================================
One word per stock: EXCELLENT, GOOD or AVOID
==========================================================

    "keep simple only excellent , good , avoid thats it"
    "i only trade in long positions"
    "pls make the background work i need to see the stock result
     only with tags/chips next to stock name"
                                    -- operator, 5 August 2026

WHAT THIS IS
------------
The PRO channels send nine different ratings across four channels for
a single company. He does not want to read nine ratings. He wants one
word beside the stock name and nothing else.

Everything happens here so nothing happens on his screen.

LONG ONLY
---------
He does not short. So a bad result is not a SELL signal in this
module -- it is simply not a setup, and it says AVOID. There is no
fourth value and there never will be.

WHAT DECIDES THE WORD
---------------------
Only what the channels actually publish, read off real messages:

    Earnings Pulse    "Excellent / Great / Good / OK / Weak Results"
    Earnings 360      a green, amber or red dot on the summary
    Earnings Pulse    "- Beat" / "- Miss"          (verdict)
    Earnings Pro      "- Beat" / "- Strong Miss"   (vs estimates)

    EXCELLENT   the strongest reading available AND nothing
                contradicting it
    GOOD        clearly positive, or positive with one source silent
    AVOID       anything weak, anything red, anything missed, and
                anything where two sources DISAGREE

WHY DISAGREEMENT IS AVOID AND NOT A MIDDLE GRADE
------------------------------------------------
He is long only and takes one or two positions. A name where Pulse
says GOOD and Earnings 360 says RED is not a small negative -- it is
an unresolved question, and there is no reason to spend a slot on an
unresolved question when a clean one exists. Three words means the
ambiguous ones have to fall somewhere, and for a long-only book they
fall out.

WHAT DELIBERATELY DOES *NOT* CHANGE THE WORD
--------------------------------------------
FORENSIC QUALITY -- "one-off", "exceptional item", "tax credit".

On 5 August I marked SHILPAMED as SKIP on exactly that flag. It closed
+11.96%. The EarningsPulse guides are written for INVESTORS asking
whether earnings are repeatable next quarter. He holds ONE TO THREE
DAYS. A one-off tax credit does not stop a stock running 12% today.

So it is carried as a NOTE on the row -- useful for deciding whether
to hold it overnight -- and it does not touch the tag. It only becomes
a rule if it earns one against real outcomes.

Author : H&M Opportunity Trader
==========================================================
"""

import re

EXCELLENT = "EXCELLENT"
GOOD = "GOOD"
AVOID = "AVOID"

# ---- what the channels actually write, read off real messages ----
_PULSE = re.compile(
    r"\b(Excellent|Great|Good|OK|Weak)\s+Results\b", re.I)
# "#SYMBOL - Beat", "— Strong Miss". The dash form is what both
# Earnings Pulse and Earnings Pro use for the verdict line.
_VERDICT = re.compile(
    r"[-–—]\s*(Strong Beat|Strong Miss|Beat|Miss|Inline|Met|Mixed)\b", re.I)
_ONE_OFF = re.compile(
    r"one[- ]?off|exceptional item|tax credit|deferred tax", re.I)

_STRONG = {"EXCELLENT", "GREAT"}
_POSITIVE = {"GOOD"}
_NEGATIVE = {"WEAK"}
_NEUTRAL = {"OK"}

_BEAT = {"STRONG BEAT", "BEAT"}
_MISS = {"STRONG MISS", "MISS"}
_FLAT = {"INLINE", "MET", "MIXED"}


def read(messages):
    """Everything the channels said about ONE stock, as plain fields.

    `messages` is [(channel, text), ...] for a single symbol.
    Returns {"pulse", "dot", "verdict", "one_off"} -- any of which may
    be None, because a silent source is not a negative one.
    """
    out = {"pulse": None, "dot": None, "verdict": None, "one_off": False}
    for _channel, text in (messages or []):
        text = str(text or "")

        found = _PULSE.search(text)
        if found:
            out["pulse"] = found.group(1).upper()

        found = _VERDICT.search(text)
        if found and out["verdict"] is None:
            out["verdict"] = found.group(1).upper()

        # Earnings 360's traffic light.
        if "\U0001F7E2" in text:            # green circle
            out["dot"] = "GREEN"
        elif "\U0001F7E1" in text:          # yellow circle
            out["dot"] = "AMBER"
        elif "\U0001F534" in text:          # red circle
            out["dot"] = "RED"

        if _ONE_OFF.search(text):
            out["one_off"] = True
    return out


def tag(read_fields):
    """EXCELLENT, GOOD or AVOID. Never anything else.

    Nothing here looks at price. This is the RESULT's quality only --
    core/ranker.py decides separately whether the stock is actually
    moving and whether he can trade it.
    """
    fields = read_fields or {}
    pulse = (fields.get("pulse") or "").upper() or None
    dot = (fields.get("dot") or "").upper() or None
    verdict = (fields.get("verdict") or "").upper() or None

    # ---- anything openly negative ends it ----
    if pulse in _NEGATIVE or dot == "RED" or verdict in _MISS:
        return AVOID

    # ---- two sources pointing opposite ways ----
    # Not a middle grade. He is long only with one or two slots; an
    # unresolved question is not worth a slot when a clean name exists.
    positive = {p for p in (
        pulse in (_STRONG | _POSITIVE) and "pulse" or None,
        dot == "GREEN" and "dot" or None,
        verdict in _BEAT and "verdict" or None) if p}
    negative = {n for n in (
        pulse in _NEGATIVE and "pulse" or None,
        dot in ("RED", "AMBER") and "dot" or None,
        verdict in _MISS and "verdict" or None) if n}
    if positive and negative:
        return AVOID

    # ---- nothing positive said at all ----
    if not positive:
        return AVOID

    # ---- the top grade needs the strongest reading, uncontradicted ----
    if pulse in _STRONG and dot != "AMBER" and verdict not in _MISS:
        return EXCELLENT
    # A clear beat with a green light is the other way to earn it.
    if verdict in _BEAT and dot == "GREEN" and pulse not in _NEUTRAL:
        return EXCELLENT

    return GOOD


def note(read_fields):
    """The one line worth carrying beside the tag, or "".

    Only the overnight caution. It does NOT change the tag -- see the
    module docstring and SHILPAMED, 5 August.
    """
    if (read_fields or {}).get("one_off"):
        return "profit flattered by a one-off -- fine to trade, "\
               "think twice about holding it overnight"
    return ""
