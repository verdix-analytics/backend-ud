from __future__ import annotations

from app.models.schemas import StockDirectoryItem
from app.services import stock_service


def test_get_stock_directory_returns_cached_rows_without_db(monkeypatch):
    cached = [{"ticker": "AAPL", "stockName": "Apple Inc."}]

    monkeypatch.setattr(stock_service, "get_stock_directory_from_cache", lambda: cached)
    monkeypatch.setattr(
        stock_service,
        "get_stock_directory_rows",
        lambda: (_ for _ in ()).throw(AssertionError("DB should not be queried on cache hit")),
    )

    result = stock_service.get_stock_directory()

    assert result == [StockDirectoryItem(ticker="AAPL", stockName="Apple Inc.")]


def test_get_stock_directory_caches_database_rows_on_miss(monkeypatch):
    rows = [
        {"ticker": "AAPL", "stockName": "Apple Inc."},
        {"ticker": "MSFT", "stockName": "Microsoft Corporation"},
    ]
    captured: dict[str, object] = {}

    monkeypatch.setattr(stock_service, "get_stock_directory_from_cache", lambda: None)
    monkeypatch.setattr(stock_service, "get_stock_directory_rows", lambda: rows)

    def fake_cache(items, ttl_seconds=0):
        captured["items"] = items
        captured["ttl_seconds"] = ttl_seconds

    monkeypatch.setattr(stock_service, "cache_stock_directory", fake_cache)

    result = stock_service.get_stock_directory()

    assert result == [
        StockDirectoryItem(ticker="AAPL", stockName="Apple Inc."),
        StockDirectoryItem(ticker="MSFT", stockName="Microsoft Corporation"),
    ]
    assert captured == {
        "items": rows,
        "ttl_seconds": 300,
    }

