"""---- 77% OF THE LOG WAS REPEATS. 1 September 2026. ----

    "why main.py needs to print every thing ? is it mandatory"

Measured on his own log that morning, eight minutes before the open,
with no trading happening at all:

    6,167 lines
    77% of them repeats

    913x  [FLOWS] fii_cr differs between the two sources
    912x  [RANK] 262 stock(s) added by reason
    457x  [GL] No live prices -- showing the 2026-08-31 close
    456x  [RANK] refused: no event x169, not moving enough x73
    456x  [RULES] 1 pick(s) removed
    288x  [BRAIN] 8 candidate(s) -> would back [...]

Not one of those is a decision, a trade, or a fault. They are the
refresh loop -- which runs once a SECOND -- narrating a state that has
not changed. "No live prices" before 09:15 is true and unchanging for
ninety minutes.

WHY IT IS NOT MERELY UNTIDY. The log rotates at 25 MB and pre-flight
reported the largest already at 20 MB. At that rate the one line that
matters -- an order refused, the feed dropping, BUYING DRIED UP -- is
buried in five thousand identical ones. He would never find it.

NOT A RATE LIMIT AND NOT "SAY ONCE". Both of those hide a change, which
is the only thing worth printing. "refused: no event x169" must speak
again when 169 becomes 170.
"""

import pytest

from core.logger import when_it_changes, forget_what_was_said


@pytest.fixture(autouse=True)
def clean():
    forget_what_was_said()
    yield
    forget_what_was_said()


def _spy():
    said = []
    return said, said.append


def test_an_unchanging_line_is_said_once():
    """457 identical lines becomes 1."""
    said, spy = _spy()
    for _ in range(500):
        when_it_changes("gl", "[GL] No live prices -- 2647 symbols", how=spy)
    assert said == ["[GL] No live prices -- 2647 symbols"]


def test_a_change_is_always_said():
    """The whole point, and what separates this from a rate limit or a
    say-once. 169 becoming 170 is the only interesting event in that
    line, and both of those would swallow it."""
    said, spy = _spy()
    for n in (169, 169, 169, 170, 170, 171):
        when_it_changes("rank", f"refused: no event x{n}", how=spy)
    assert said == ["refused: no event x169",
                    "refused: no event x170",
                    "refused: no event x171"]


def test_it_speaks_again_when_a_value_returns():
    """169 -> 170 -> 169 is three events, not two. A stock count that
    goes back to what it was has still moved twice."""
    said, spy = _spy()
    for n in (169, 170, 169):
        when_it_changes("rank", f"x{n}", how=spy)
    assert said == ["x169", "x170", "x169"]


def test_keys_do_not_interfere():
    """Two panels reporting different things must not silence each
    other."""
    said, spy = _spy()
    when_it_changes("a", "same text", how=spy)
    when_it_changes("b", "same text", how=spy)
    assert len(said) == 2


def test_it_reports_whether_it_spoke():
    """So a caller can do more than log -- count it, or escalate."""
    assert when_it_changes("k", "one", how=lambda m: None) is True
    assert when_it_changes("k", "one", how=lambda m: None) is False
    assert when_it_changes("k", "two", how=lambda m: None) is True


def test_the_default_is_the_quiet_channel():
    """A caller has to opt in to anything louder than diagnostic. A
    helper that defaulted to warn() would turn tidying into noise of a
    worse kind."""
    import inspect

    src = inspect.getsource(when_it_changes)
    assert "how or diagnostic" in src


# ------------------------------------------- the five it was built for

def test_the_five_loudest_lines_all_use_it():
    """Named individually. If one is reverted to a bare diagnostic()
    the log goes back to thousands of identical lines and nothing
    fails, which is how it got there in the first place."""
    from pathlib import Path

    checks = [
        ("dashboard/state.py", "gl-no-live-prices"),
        ("dashboard/state.py", "rules-dropped"),
        ("dashboard/state.py", "rank-added-by-reason"),
        ("core/ranker.py", "rank-refused"),
        ("main.py", "brain-candidates"),
    ]
    for path, key in checks:
        src = Path(path).read_text(encoding="utf-8")
        assert f'"{key}"' in src, f"{path} no longer uses when_it_changes({key})"


def test_the_brain_line_stays_on_the_loud_channel():
    """It is a decision -- which stocks the bot would back. Quietening
    it to a diagnostic would hide it from the console entirely, which
    is a different bug from the one being fixed."""
    from pathlib import Path

    src = Path("main.py").read_text(encoding="utf-8")
    block = src[src.find("brain-candidates"):][:400]
    assert "how=decision" in block
