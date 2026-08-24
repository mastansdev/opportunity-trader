"""A refusal must say what actually stopped the trade.

    "already holding 3 of 3 and not decisively better than the weakest"

RATNAMANI, 24 August 14:16:28. It was up 5.70% against a weakest
holder at -1.60% -- a 7.3-point gap over a 2.0-point bar. Decisively
better by any reading. Rotation refused on its FIRST line:

    if getattr(self, "alert_only", True):
        return False

The bot was not trading. The message blamed the stock. Reading it you
would conclude the bot had judged the day's best stock inferior to a
position sitting at -1.6%.

That trade's target hit: Rs +2,999 on qty 11.
"""

from datetime import datetime

import pytest

from core import auto_entry

NOW = datetime(2026, 8, 24, 14, 16, 28)
HELD = {"JBMA", "NCC", "CDSL"}

ROW = {"symbol": "RATNAMANI", "action": "BUY", "score": 45.99,
       "price": 2489.5, "ltp": 2489.5, "volume_x": 5.6, "change_pct": 5.7,
       "mtf": True, "security_id": "1", "sector": "METALS & MINING",
       "reason": "Bagging/Receiving of orders/contracts",
       "mechanism": "NSE filing",
       "plan": {"ok": True, "qty": 11, "stop": 2353.2,
                "target": 2762.1, "value": 27384.5}}


class _Engine:
    open_positions = {"JBMA": {}, "NCC": {}, "CDSL": {}}

    def __init__(self, alert_only=True):
        self.alert_only = alert_only

    def __getattr__(self, name):
        return lambda *a, **k: None


def _why(alert_only):
    return auto_entry.refuse_reason(ROW, _Engine(alert_only), now=NOW,
                                    held=HELD, max_positions=3)


def test_a_disarmed_bot_says_so():
    why = _why(alert_only=True)
    assert "not trading" in why, why
    assert "not decisively better" not in why, (
        "this blames the stock for the bot being switched off")


def test_it_still_names_the_full_book():
    # The seat count is real information and must survive.
    assert "3 of 3" in _why(alert_only=True)


def test_rotation_switched_off_is_named_separately(monkeypatch):
    monkeypatch.setattr(auto_entry, "ENABLE_SLOT_ROTATION", False)
    why = _why(alert_only=False)
    assert "rotation is OFF" in why, why


def test_the_strength_claim_is_only_made_when_it_was_tested(monkeypatch):
    """"not decisively better" may only appear when rotation ran."""
    monkeypatch.setattr(auto_entry, "ENABLE_SLOT_ROTATION", True)
    why = _why(alert_only=False)
    assert "not decisively better" in why


def test_an_empty_book_takes_it():
    assert auto_entry.refuse_reason(ROW, _Engine(False), now=NOW,
                                    held=set(), max_positions=3) is None
