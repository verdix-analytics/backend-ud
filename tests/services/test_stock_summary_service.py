from __future__ import annotations

from types import SimpleNamespace

from app.services import stock_summary_service


def _pattern(pattern: str, category: str, confidence: float, direction: str):
    return SimpleNamespace(
        pattern=pattern,
        category=category,
        confidence=confidence,
        signal={"direction": direction},
    )


def test_build_stock_pattern_summary_context_builds_prompt_inputs(monkeypatch):
    patterns = [
        _pattern("Bat Harmonic", "harmonic", 91.2, "bullish"),
        _pattern("Cypher Harmonic", "harmonic", 84.7, "neutral"),
    ]

    monkeypatch.setattr(stock_summary_service, "get_detected_patterns", lambda category, symbol, days_lookback=None: patterns)
    monkeypatch.setattr(
        stock_summary_service,
        "search_stock",
        lambda symbol: {"companyName": "Apple Inc.", "exchange": "NASDAQ"},
    )

    context = stock_summary_service.build_stock_pattern_summary_context("aapl", "harmonic")
    prompt = stock_summary_service.build_stock_pattern_summary_prompt(context)

    assert context.symbol == "AAPL"
    assert context.stock_name == "Apple Inc."
    assert context.exchange == "NASDAQ"
    assert context.pattern_name == "Bat Harmonic"
    assert context.pattern_category == "harmonic"
    assert context.trend == "bullish"
    assert "Stock name: Apple Inc." in prompt
    assert "Stock symbol: AAPL" in prompt
    assert "Stock exchange name: NASDAQ" in prompt
    assert "Confidence score: 91.20" in prompt
    assert "Context score:" in prompt
    assert "Pattern name: Bat Harmonic" in prompt
    assert "Pattern category name: harmonic" in prompt
    assert "Trend: bullish" in prompt
    assert "pattern_name=Bat Harmonic; pattern_category=harmonic; confidence_score=91.20; trend=bullish" in prompt


def test_generate_stock_pattern_summary_calls_llm(monkeypatch):
    patterns = [_pattern("Bat Harmonic", "harmonic", 91.2, "bullish")]

    monkeypatch.setattr(stock_summary_service, "get_detected_patterns", lambda category, symbol, days_lookback=None: patterns)
    monkeypatch.setattr(
        stock_summary_service,
        "search_stock",
        lambda symbol: {"companyName": "Apple Inc.", "exchange": "NASDAQ"},
    )

    captured = {}

    def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "AI summary"

    monkeypatch.setattr(stock_summary_service, "generate_llm_response", fake_llm)

    result = stock_summary_service.generate_stock_pattern_summary("AAPL", "harmonic")

    assert result == "AI summary"
    assert "Apple Inc." in captured["prompt"]
    assert "Bat Harmonic" in captured["prompt"]


def test_build_stock_pattern_summary_context_rejects_unknown_category():
    try:
        stock_summary_service.build_stock_pattern_summary_context("AAPL", "invalid")
    except ValueError as exc:
        assert str(exc) == "category must be one of: candlestick, chart, harmonic"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected ValueError for invalid category")


def test_trend_from_pattern_uses_db_value_or_neutral_fallback():
    bullish = _pattern("Bat Harmonic", "harmonic", 91.2, "bullish")
    bearish = _pattern("Bat Harmonic", "harmonic", 91.2, "bearish")
    neutral = _pattern("Bat Harmonic", "harmonic", 91.2, "neutral")
    unknown = _pattern("Bat Harmonic", "harmonic", 91.2, "uptrend")

    assert stock_summary_service._trend_from_pattern(bullish) == "bullish"
    assert stock_summary_service._trend_from_pattern(bearish) == "bearish"
    assert stock_summary_service._trend_from_pattern(neutral) == "neutral"
    assert stock_summary_service._trend_from_pattern(unknown) == "neutral"


