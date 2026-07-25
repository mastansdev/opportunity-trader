"""
Decision-correctness tests for the dashboard operator token:
stable across repeated calls (same as a restart), never empty,
never guessable-short.
"""

import os

from dashboard.access_token import get_or_create_token


def test_creates_a_token_when_none_exists(tmp_path):
    path = os.path.join(str(tmp_path), "token.txt")
    token = get_or_create_token(path=path)

    assert token
    assert len(token) >= 20  # not a trivially guessable short value
    assert os.path.exists(path)


def test_returns_the_same_token_on_a_second_call_not_a_new_one(tmp_path):
    """Stability across restarts -- an operator control link that
    changes every run isn't a link worth bookmarking."""
    path = os.path.join(str(tmp_path), "token.txt")
    first = get_or_create_token(path=path)
    second = get_or_create_token(path=path)

    assert first == second


def test_two_different_paths_get_two_different_tokens(tmp_path):
    path_a = os.path.join(str(tmp_path), "a.txt")
    path_b = os.path.join(str(tmp_path), "b.txt")

    token_a = get_or_create_token(path=path_a)
    token_b = get_or_create_token(path=path_b)

    assert token_a != token_b


def test_recovers_if_the_file_exists_but_is_empty(tmp_path):
    path = os.path.join(str(tmp_path), "token.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("")

    token = get_or_create_token(path=path)
    assert token  # regenerates rather than handing back an empty secret
