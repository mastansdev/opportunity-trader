"""---- SETTINGS THAT LOOK LIVE AND ARE NOT. 31 August 2026. ----

    "still i suspect something under codes were there which is not
     working or opposite of what i want to do."

He was right, and it has a shape. Three faults found in one evening
were all the same one:

    LIVE_ALLOW_BOT_ENTRIES   described in three files, implemented in
                             none -- the only thing between the bot's
                             own signals and real money was a comment.
    ENABLE_FILING_PDF_READING = True, and ResultsIngestor is imported,
                             set to None, and never constructed.
    MAX_NOTIONAL_PER_TRADE_RS  a docstring promised it capped every
                             position; sizing moved to the MTF margin
                             on 29 July and nothing reads it.

A setting nobody reads costs the bot nothing at runtime. What it costs
is the reader: six flags in this file spell out what an AI is not
allowed to do -- AI_MAY_MOVE_STOPS, AI_MAY_SIZE_POSITIONS -- and no
line of code consults any of them. They read as safety and are
decoration.

So every setting is either read by the code or carries DECIDES NOTHING
on its own line, and this test holds the two in step: a setting that
goes dead must be marked, and a marked one that comes back to life must
lose the mark.
"""

import io
import pathlib
import re
import tokenize

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARK = "DECIDES NOTHING"


def _settings():
    """{name: (line_number, is_marked)} for every config setting."""
    out = {}
    text = (ROOT / "config.py").read_text(encoding="utf-8")
    for i, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^([A-Z][A-Z0-9_]{3,})\s*=", line)
        if m:
            out[m.group(1)] = (i, MARK in line)
    return out


def _read_by_the_code():
    """Every setting name that appears in real code -- not in a
    comment, not in a docstring. Comments were what fooled the first
    version of this sweep: I had written ABOUT FIXED_TARGET_RS in a
    comment that same evening, and it made a dead setting look alive."""
    names = set()
    for path in ROOT.rglob("*.py"):
        s = str(path).replace("\\", "/")
        if "/tests/" in s or "__pycache__" in s: continue
        # config.py IS scanned: several settings exist only to define
        # another (TOP_N_MOMENTUM_MODE = ATR_ENTRY_SIZING). Excluding it
        # reported ATR_ENTRY_SIZING as dead when its whole job is to
        # name the mode one line later.
        if path.name == "config.py":
            # Only the RIGHT-hand side of each assignment counts here.
            # A setting naming itself on the left is not a use, but
            # TOP_N_MOMENTUM_MODE = ATR_ENTRY_SIZING on the right is --
            # skipping config.py entirely reported ATR_ENTRY_SIZING as
            # dead when naming the mode is its whole job.
            rhs = []
            for line in path.read_text(encoding="utf-8",
                                       errors="ignore").split("\n"):
                if re.match(r"^[A-Z][A-Z0-9_]{3,}\s*=", line):
                    rhs.append(line.split("=", 1)[1])
            for chunk in rhs:
                for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", chunk):
                    names.add(word)
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type is tokenize.NAME:
                    names.add(tok.string)
        except Exception:                                  # noqa: BLE001
            continue
    return names


def test_every_dead_setting_is_marked():
    """A value that cannot change what the bot does must say so where
    it is defined -- not in a note further down, which is where
    LIVE_ALLOW_BOT_ENTRIES's own contradiction lived for weeks."""
    live = _read_by_the_code()
    missing = [n for n, (_, marked) in _settings().items()
               if n not in live and not marked]
    assert not missing, (
        "these settings are read by no line of code and do not say so:\n  "
        + "\n  ".join(sorted(missing))
        + "\n\nAdd '# DECIDES NOTHING -- <why>' on the definition line, "
          "or wire it up.")


def test_no_marked_setting_is_secretly_live():
    """The other direction, and the more dangerous one. A setting
    labelled inert that something starts reading would be a control
    changing the bot's behaviour while its own line says it cannot."""
    live = _read_by_the_code()
    lying = [n for n, (_, marked) in _settings().items()
             if marked and n in live]
    assert not lying, (
        "these are marked DECIDES NOTHING and something reads them:\n  "
        + "\n  ".join(sorted(lying))
        + "\n\nRemove the mark -- a live control must not describe "
          "itself as dead.")


def test_the_known_dead_ones_are_still_marked():
    """Named individually so that deleting the mark is a deliberate act
    rather than a side effect. Each of these was found by hand and each
    one had already misled somebody."""
    settings = _settings()
    for name in ("FIXED_STOP_LOSS_RS",        # looks like the risk number
                 "FIXED_TARGET_RS",           # looks like the profit target
                 "AI_MAY_MOVE_STOPS",         # looks like a safety gate
                 "AI_MAY_SIZE_POSITIONS",     # looks like a safety gate
                 "MIS_LEVERAGE_MULTIPLIER"):  # the bot is MTF, not MIS
        assert name in settings, f"{name} vanished from config"
        assert settings[name][1], f"{name} lost its DECIDES NOTHING mark"


def test_live_allow_bot_entries_still_says_it_is_inert():
    """The one that started all of this. It was documented in three
    files as the thing standing between the bot and real money, and no
    line of the order path ever read it."""
    # The DEFINITION line, not the first mention. The first mention is
    # a comment 700 lines earlier, which is exactly the problem: a note
    # somewhere else is not what a reader sees next to the value.
    settings = _settings()
    assert "LIVE_ALLOW_BOT_ENTRIES" in settings
    assert settings["LIVE_ALLOW_BOT_ENTRIES"][1], (
        "LIVE_ALLOW_BOT_ENTRIES no longer says it is inert ON ITS OWN "
        "LINE. It was documented in three files as the thing standing "
        "between the bot and real money, and no line of the order path "
        "ever read it.")
