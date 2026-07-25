"""
Decision-correctness tests for News Bot Stage 3 (AI
classification). No real network/API calls -- a fake client
matching the real Anthropic SDK response shape
(response.content[0].text) is injected every time.
"""

import pytest

from news_bot import classification
from news_bot.models import NewsItem

_COMPANY = {
    "SYMBOL": "TCS",
    "COMPANY NAME": "Tata Consultancy Services",
    "SECTOR": "IT",
    "INDUSTRY": "Software",
    "OWNERSHIP": "PRIVATE",
    "COMMODITY_EXPOSURE": "NONE",
    "ECONOMIC_SENSITIVITY": "LOW",
}


def _item(title="Some headline"):
    return NewsItem(
        source="TEST",
        title=title,
        summary="",
        link="https://example.com/x",
        published_raw="",
        guid="g1",
    )


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeClient:
    def __init__(self, response_text=None, raise_exc=None):
        self._response_text = response_text
        self._raise_exc = raise_exc
        self.messages = self
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return _FakeResponse(self._response_text)


_GOOD_JSON = (
    '{"direction": "bullish", "confidence": 85, '
    '"materiality": "material", "reason": "Large new export order."}'
)


def test_valid_response_is_parsed_correctly():
    client = _FakeClient(response_text=_GOOD_JSON)

    result = classification.classify(_item(), _COMPANY, client=client)

    assert result == {
        "direction": "bullish",
        "confidence": 85,
        "materiality": "material",
        "reason": "Large new export order.",
    }


def test_prompt_includes_company_facts_not_just_headline():
    client = _FakeClient(response_text=_GOOD_JSON)

    classification.classify(_item("Some headline"), _COMPANY, client=client)

    prompt = client.last_kwargs["messages"][0]["content"]
    assert "Tata Consultancy Services" in prompt
    assert "IT" in prompt
    assert "Some headline" in prompt


def test_api_failure_raises_classification_error():
    client = _FakeClient(raise_exc=ConnectionError("down"))

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=client)


def test_unparseable_json_raises_classification_error():
    client = _FakeClient(response_text="not json at all")

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=client)


def test_invalid_direction_is_rejected_not_guessed():
    bad = _GOOD_JSON.replace('"bullish"', '"very bullish"')
    client = _FakeClient(response_text=bad)

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=client)


def test_confidence_out_of_range_is_rejected():
    bad = _GOOD_JSON.replace('"confidence": 85', '"confidence": 150')
    client = _FakeClient(response_text=bad)

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=client)


def test_missing_reason_is_rejected():
    bad = _GOOD_JSON.replace(
        '"reason": "Large new export order."', '"reason": ""'
    )
    client = _FakeClient(response_text=bad)

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=client)


def test_missing_package_raises_classification_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module named anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=None)


def test_missing_api_key_raises_classification_error(monkeypatch):
    import config

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")

    with pytest.raises(classification.ClassificationError):
        classification.classify(_item(), _COMPANY, client=None)


def test_is_configured_false_when_key_missing(monkeypatch):
    import config

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    assert classification.is_configured() is False


def test_is_configured_true_when_package_and_key_present(monkeypatch):
    import sys
    import types

    import config

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-fake-key")
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    assert classification.is_configured() is True
