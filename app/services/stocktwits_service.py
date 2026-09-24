import logging
from typing import List

from curl_cffi import requests

from app.models.schemas import StockTwitsMessage, StockTwitsResponse

logger = logging.getLogger(__name__)

STOCKTWITS_API_BASE = "https://api.stocktwits.com/api/2/streams/symbol"


def get_stocktwits_messages(symbol: str, limit: int = 15) -> StockTwitsResponse:
    """
    Fetch recent messages for a ticker from StockTwits.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        limit: Maximum number of messages to return (1-30)
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string")

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise ValueError("Symbol cannot be empty after trimming")

    limit = max(1, min(limit, 30))

    try:
        url = f"{STOCKTWITS_API_BASE}/{symbol_upper}.json"
        response = requests.get(url, impersonate="chrome124", timeout=30)

        if response.status_code == 404:
            logger.warning(f"StockTwits: symbol not found: {symbol_upper}")
            return StockTwitsResponse(symbol=symbol_upper)

        if response.status_code != 200:
            logger.warning(f"StockTwits API returned {response.status_code} for {symbol_upper}")
            raise ValueError(f"StockTwits API error {response.status_code} for symbol '{symbol_upper}'")

        data = response.json()
        raw_messages = data.get("messages", [])

        messages: List[StockTwitsMessage] = []
        for msg in raw_messages[:limit]:
            sentiment = (
                msg.get("entities", {}).get("sentiment") or {}
            ).get("basic")

            messages.append(
                StockTwitsMessage(
                    username=msg.get("user", {}).get("username"),
                    created_at=msg.get("created_at"),
                    sentiment=sentiment,
                    likes=msg.get("likes", {}).get("total", 0),
                    body=msg.get("body"),
                )
            )

        return StockTwitsResponse(
            symbol=symbol_upper,
            total_count=len(messages),
            messages=messages,
        )

    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"Failed to fetch StockTwits messages for {symbol_upper}: {exc}")
        raise ValueError(f"Unable to fetch StockTwits data for symbol '{symbol_upper}': {str(exc)}")
