"""
==========================================================
BUY SBIN ran bare -- no target, no trail.
==========================================================

    "telegram command center must do work if i command
     BUY SBIN = then bot must buy SBIN MTF with assigned rules
     (capital, target, stoploss, trailling)"
                                -- operator, 23 August 2026

Three of the four already worked:

    MTF      the desk refuses a non-MTF stock BEFORE quoting -- his
             rule of 18 August, "if it is not MTF, it is not bought"
    capital  risk-sized from RISK_PER_TRADE_RS against the stop
    stop     volatility-scaled, floored at HARD_STOP_FROM_ENTRY_PCT

TARGET and TRAILING did not exist on ANY entry. Engine._enter() has
accepted `target` and `stop_mode` since it was written; the manual
call passed neither, so every dashboard and Telegram buy ran bare.

AND THEY WERE MUTUALLY EXCLUSIVE

_check_trailing_stop() routed a position with fixed_target to
_check_fixed_bracket() and RETURNED, so the ratchet never ran. A
position can now carry both: it trails until the target is reached,
then books.

ONLY HIS ENTRIES

The bot's own keep holding to the close. Seven target widths were
measured on 22-23 August and every one underperformed holding, so
applying this everywhere would have made the bot worse. He was asked
and chose the split, and it also keeps a paper session a clean read of
the bot's own behaviour.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import config

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# THE SETTINGS EXIST AND SAY WHAT THEY MEAN
# ---------------------------------------------------------------

def test_the_target_is_his_number():
    assert config.MANUAL_BUY_TARGET_RS == 2000.0


def test_trailing_is_on_for_his_buys():
    assert config.MANUAL_BUY_TRAILS is True


def test_the_bot_now_gets_the_same_rules_his_manual_buys_do():
    """The split closed, 29 August 2026.

    His buys got a target and a trail on 23 August; the bot's own
    entries got neither, because seven target widths measured on
    22-23 August underperformed holding.

    Both are on for the bot now, for a reason that is his and not a
    backtest:

        "incase if bot carry towards close some stocks may lock at
         upper circuits ... some may fade out & become no profit /
         loss . to fix this i need one simple solution"

    A stop that only moves up handles both: the circuit-locker keeps
    making highs so it never fires, the fader gives back and is
    booked. TRADING_MODE is PAPER, so this is measured forward.
    """
    assert config.ENABLE_BOT_TRAILING_STOP is True
    assert config.MANUAL_BUY_TRAILS is True, (
        "his own buys must not have lost theirs")
    # The bot's exit IS the trail. A hard target came on and off the
    # same day: at Rs 2,500 it capped a Rs 10,800 runner, and below it
    # the trail was booking anyway. TARGET_REWARD_BY_REGIME is the one
    # dial, read by the engine AND the alert card.
    assert config.TARGET_REWARD_BY_REGIME == {}


# ---------------------------------------------------------------
# THE MANUAL PATH PASSES THEM
# ---------------------------------------------------------------

def test_the_manual_buy_passes_a_target_and_a_trail():
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    i = src.find("ENTRY_REASON_MANUAL_DASHBOARD, LONG, qty=qty")
    assert i > 0, "the manual buy call moved"
    call = src[i - 700:i + 300]
    assert "target=target" in call, "the manual buy still has no target"
    assert "STOP_MODE_ATR_TRAILING" in call, "it still does not trail"


def test_the_target_is_rupees_not_percent():
    """Rs 2,000 on 100 shares is a Rs 20 move; on 500 shares it is
    Rs 4. The target must be derived from the QUANTITY, or a big
    position books far too early."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    i = src.find("MANUAL_BUY_TARGET_RS / abs(int(qty))")
    assert i > 0, "the target is not being divided by the quantity"


def test_a_bot_entry_still_gets_no_target():
    """_enter defaults target to None, so anything that does not ask
    for one keeps holding to the close."""
    import inspect

    from core.engine import Engine
    sig = inspect.signature(Engine._enter)
    assert sig.parameters["target"].default is None
    assert sig.parameters["stop_mode"].default != "ATR_TRAILING"


# ---------------------------------------------------------------
# TARGET AND TRAIL NO LONGER EXCLUDE EACH OTHER
# ---------------------------------------------------------------

def test_a_position_can_carry_both():
    """It used to route to the fixed bracket and RETURN, so a position
    with a target never trailed."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _check_trailing_stop"):
               src.find("def _check_atr_trailing")]
    assert "STOP_MODE_ATR_TRAILING" in body
    assert "_check_atr_trailing(symbol, position, price, tick_time)" in body
    assert "EXIT_REASON_FIXED_TARGET" in body


def test_it_reuses_the_existing_exit_reason():
    """There was already an EXIT_REASON_FIXED_TARGET. A second name for
    the same thing is how this codebase ends up with two of
    everything."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert "EXIT_REASON_TARGET =" not in src
    assert 'EXIT_REASON_FIXED_TARGET = "FIXED_TARGET"' in src


def test_the_mtf_rule_still_guards_the_command():
    """His 18 August rule. A cash-only stock must never get as far as
    a YES to type against."""
    src = (ROOT / "core" / "telegram_desk.py").read_text(encoding="utf-8")
    assert "_mtf_check" in src and "NO BUY" in src


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert "BUY SBIN" in src
