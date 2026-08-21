"""
==========================================================
One stray underscore and the alert never arrives.
==========================================================

    "why i didn't get any alerts to buy stocks in telegram ?"
                                -- operator, 19 August 2026

Found 20 August, sending him a plain test message from his own bot:

    HTTP 400 :: Bad Request: can't parse entities: Can't find end
    of the entity starting at byte offset 12

The text was "test @HMalgo_Bot ping". The underscore in his bot's own
name opened a Markdown italic that never closed, so Telegram REFUSED
THE WHOLE MESSAGE. Not the formatting -- the message.

send() passed parse_mode="Markdown" unconditionally, and _call turns a
refusal into one diagnostic line and returns None. Nothing raises,
nothing retries, and the desk looks asleep.

WHY THIS WAS ALWAYS GOING TO FIRE

The alert card quotes the PRO channel message VERBATIM, and those are
arbitrary text written by strangers -- "Q1_FY27", a bare underscore in
a filing title, a "*BREAKOUT*" missing its second star. Every one of
those is an alert he never sees, on exactly the days something is
happening.

THE TRADE THIS MAKES

Bold is worth nothing. The message is worth everything. Markdown is
attempted first and, if Telegram will not parse it, the SAME text goes
out plain. He would rather read an ugly alert than miss a good one.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core import telegram_desk as td

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Telegram:
    """Records every sendMessage. `strict` refuses Markdown the way the
    real API does -- 400, which _call reports as None."""

    def __init__(self, strict=False):
        self.calls = []
        self.strict = strict

    def __call__(self, method, **params):
        self.calls.append(params)
        if method != "sendMessage":
            return None
        if self.strict and params.get("parse_mode") == "Markdown":
            return None
        return {"message_id": len(self.calls)}


def _patch(monkeypatch, api):
    monkeypatch.setattr(td, "_call", api)
    monkeypatch.setattr(td, "_chat_id", lambda: "787902453")


# ---------------------------------------------------------------
# THE MESSAGE GETS THROUGH
# ---------------------------------------------------------------

def test_unparseable_markdown_still_reaches_him(monkeypatch):
    """THE CASE THAT WAS FOUND. One underscore, and before this fix
    nothing arrived at all."""
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    assert td.send("test @HMalgo_Bot ping") is True
    assert len(api.calls) == 2, "it gave up after Telegram refused"
    assert "parse_mode" not in api.calls[1], "the retry was not plain"


def test_the_retry_carries_the_same_words(monkeypatch):
    """A fallback that truncated or mangled the alert would be its own
    bug -- he acts on the numbers in it."""
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    text = "09:41 IREDA BUY  ORDER_WIN Q1_FY27  qty 30  1520 - 1580 - 1495"
    td.send(text)
    assert api.calls[0]["text"] == text
    assert api.calls[1]["text"] == text


def test_good_markdown_is_sent_once_and_stays_formatted(monkeypatch):
    """The control. If the fallback fired every time, the whole desk
    would silently lose its formatting and nothing above would notice.
    """
    api = _Telegram(strict=False)
    _patch(monkeypatch, api)
    assert td.send("*IREDA* is up") is True
    assert len(api.calls) == 1, "a working Markdown send was retried"
    assert api.calls[0]["parse_mode"] == "Markdown"


def test_markdown_is_still_tried_first(monkeypatch):
    """Plain-first would be simpler and would throw away the bold
    header on every alert he reads on a phone."""
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    td.send("x_y")
    assert api.calls[0].get("parse_mode") == "Markdown"


# ---------------------------------------------------------------
# AND IT STILL FAILS HONESTLY
# ---------------------------------------------------------------

def test_a_dead_network_reports_failure_not_success(monkeypatch):
    """When BOTH attempts fail there is no message, and send() must say
    so -- callers count on the return value to decide whether an alert
    was delivered."""
    _patch(monkeypatch, lambda method, **p: None)
    assert td.send("anything") is False


def test_it_does_not_retry_when_there_is_nothing_to_send(monkeypatch):
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    assert td.send("") is False
    assert td.send(None) is False
    assert api.calls == []


def test_it_never_raises_on_junk(monkeypatch):
    """A desk that throws takes the tick loop down with it."""
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    for text in (0, 3.5, ["a"], {"b": 1}, object()):
        assert td.send(text) in (True, False)


def test_the_long_message_cap_survives_the_fallback(monkeypatch):
    """4000 chars is Telegram's limit. The retry must clip too, or the
    fallback trades a parse error for a length error."""
    api = _Telegram(strict=True)
    _patch(monkeypatch, api)
    td.send("_" * 9000)
    assert len(api.calls[1]["text"]) <= 4000


def test_the_reason_is_written_down_where_it_broke():
    """This cost a day of "the alerts are not arriving". The next
    person to see parse_mode should find out why it is guarded."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    body = src[src.find("def send("):src.find("class TelegramDesk")]
    assert "can't parse entities" in body
