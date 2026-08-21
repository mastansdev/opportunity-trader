"""
==========================================================
"12_5cr" reached his phone as "125cr".
==========================================================

He pasted his own phone back at me on 21 August. I had sent:

    INBOUND + FORMATTING TEST from @HMalgo_Bot -- Q1_FY27

He received:

    INBOUND + FORMATTING TEST from @HMalgoBot -- Q1FY27

Two underscores made a balanced pair, Telegram parsed them as italics,
and DELETED THEM FROM THE TEXT.

WHY THIS IS WORSE THAN THE CRASH FIXED THE SAME MORNING

A single stray underscore returns HTTP 400 and the alert never
arrives -- bad, but LOUD, and the operator notices silence. A matched
pair arrives looking perfectly fine and says something other than what
was written. Nothing anywhere reports a problem.

The card quotes the PRO channel message VERBATIM -- text written by
strangers, thick with underscores and stars:

    "Q1_FY27 order_win 12_5cr"   ->   "Q1FY27 orderwin 125cr"

12_5cr becoming 125cr is a NUMBER CHANGING on an alert he trades on.

WHAT IS ESCAPED AND WHAT IS NOT

Only the body -- the part we did not write. The bold header and the
`BUY SYM` block are ours, they are deliberate, and he triages on them.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import telegram_desk as td

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _card(message, symbol="IREDA", kind="alert-only-LONG"):
    desk = td.TelegramDesk.__new__(td.TelegramDesk)
    return td.TelegramDesk._card(desk, symbol, kind, message, note_at="09:41")


# ---------------------------------------------------------------
# THE TEXT SURVIVES
# ---------------------------------------------------------------

def test_the_underscores_are_not_eaten():
    """THE CASE HE PASTED BACK."""
    assert r"Q1\_FY27" in _card("Q1_FY27")


def test_a_number_cannot_be_rewritten():
    """The one that would actually cost him money."""
    card = _card("order won 12_5cr today")
    assert r"12\_5cr" in card
    assert "125cr" not in card


def test_stars_survive_too():
    """Channel cards arrive wrapped in stars for emphasis."""
    assert r"\*BREAKOUT\*" in _card("*BREAKOUT*")


def test_a_lone_underscore_no_longer_kills_the_message():
    """The HTTP 400 case, now neutralised BEFORE it is sent rather
    than retried after."""
    assert r"12\_5" in _card("up 12_5 percent")


def test_backticks_in_channel_text_cannot_open_a_code_block():
    assert r"\`" in _card("see `this`")


def test_a_backslash_is_escaped_before_anything_else():
    r"""Escaping _ first and the backslash second would double-escape.
    Order matters and this pins it."""
    got = _card(r"a\_b")
    assert r"a\\\_b" in got


# ---------------------------------------------------------------
# OUR OWN FORMATTING IS UNTOUCHED
# ---------------------------------------------------------------

def test_the_header_is_still_bold():
    """He triages on the header. Escaping it would print literal
    asterisks on every alert."""
    card = _card("plain text")
    assert card.startswith("*09:41  IREDA  ")
    assert card.splitlines()[0].endswith("*")


def test_the_buy_command_block_still_formats():
    card = _card("plain text")
    assert "`BUY IREDA`" in card
    assert "_(then_" in card


def test_the_evidence_header_still_switches():
    """The stamp is read BEFORE the body is escaped -- escaping first
    would hide '[EVIDENCE:' from the check and every alert would say
    BREAKOUT."""
    assert "EVIDENCE" in _card("moved on [EVIDENCE: order win]")
    assert "no evidence" in _card("moved [PRICE ONLY -- no reason found]")


# ---------------------------------------------------------------
# IT NEVER RAISES
# ---------------------------------------------------------------

def test_it_survives_junk():
    for bad in (None, "", 0, 3.5, ["a"], {"b": 1}):
        assert isinstance(td._escape_md(bad), str)


def test_an_empty_body_still_produces_a_card():
    assert "IREDA" in _card("")


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    body = src[src.find("def _escape_md"):src.find("def send(")]
    assert "12_5cr" in body and "125cr" in body
