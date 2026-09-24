from __future__ import annotations

from fastapi import HTTPException

from app.api import frontend_routes
from app.models.schemas import ModeEnum, StockDirectoryItem


def test_generate_stock_ai_summary_maps_short_to_candlestick(monkeypatch):
    captured: dict[str, str] = {}

    def fake_generate(symbol: str, category: str) -> str:
        captured["symbol"] = symbol
        captured["category"] = category
        return "AI summary text"

    monkeypatch.setattr(frontend_routes, "generate_stock_pattern_summary", fake_generate)

    response = frontend_routes.generate_stock_ai_summary(
        ticker=" aapl ",
        category="short",
        current_user={"sub": "test-user"},
    )

    assert response.ticker == "AAPL"
    assert response.category == ModeEnum.CANDLESTICK
    assert response.summary == "AI summary text"
    assert captured == {"symbol": "AAPL", "category": "candlestick"}


def test_generate_stock_ai_summary_accepts_canonical_category(monkeypatch):
    captured: dict[str, str] = {}

    def fake_generate(symbol: str, category: str) -> str:
        captured["symbol"] = symbol
        captured["category"] = category
        return "Harmonic summary"

    monkeypatch.setattr(frontend_routes, "generate_stock_pattern_summary", fake_generate)

    response = frontend_routes.generate_stock_ai_summary(
        ticker="AAPL",
        category="harmonic",
        current_user={"sub": "test-user"},
    )

    assert response.category == ModeEnum.HARMONIC
    assert response.summary == "Harmonic summary"
    assert captured == {"symbol": "AAPL", "category": "harmonic"}


def test_generate_stock_ai_summary_rejects_invalid_category():
    try:
        frontend_routes.generate_stock_ai_summary(
            ticker="AAPL",
            category="invalid",
            current_user={"sub": "test-user"},
        )
    except HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == "category must be one of: short, medium, long, candlestick, chart, harmonic"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected HTTPException for invalid category")


def test_generate_stock_ai_summary_returns_404_for_missing_patterns(monkeypatch):
    def fake_generate(symbol: str, category: str) -> str:
        raise LookupError("No detected patterns found for AAPL (harmonic)")

    monkeypatch.setattr(frontend_routes, "generate_stock_pattern_summary", fake_generate)

    try:
        frontend_routes.generate_stock_ai_summary(
            ticker="AAPL",
            category="long",
            current_user={"sub": "test-user"},
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "No detected patterns found for AAPL (harmonic)"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected HTTPException 404 for missing patterns")


def test_generate_stock_ai_summary_returns_503_for_llm_runtime_error(monkeypatch):
    def fake_generate(symbol: str, category: str) -> str:
        raise RuntimeError("Failed to generate an LLM response")

    monkeypatch.setattr(frontend_routes, "generate_stock_pattern_summary", fake_generate)

    try:
        frontend_routes.generate_stock_ai_summary(
            ticker="AAPL",
            category="long",
            current_user={"sub": "test-user"},
        )
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail == "Failed to generate an LLM response"
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected HTTPException 503 for LLM failures")


def test_stock_directory_returns_ticker_and_stock_name(monkeypatch):
    expected = [
        StockDirectoryItem(ticker="AAPL", stockName="Apple Inc."),
        StockDirectoryItem(ticker="MSFT", stockName="Microsoft Corporation"),
    ]

    monkeypatch.setattr(frontend_routes, "get_stock_directory", lambda: expected)

    response = frontend_routes.stock_directory(current_user={"sub": "test-user"})

    assert response == expected


