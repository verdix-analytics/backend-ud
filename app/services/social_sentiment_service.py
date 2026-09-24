import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

import requests
import pandas as pd
import numpy as np

from app.models.schemas import (
    SocialSentimentResponse,
    SocialSentimentDetailsResponse,
    SocialSentimentTicker,
)

logger = logging.getLogger(__name__)

# ApeWisdom API base URL
APEWISDOM_API_BASE = "https://apewisdom.io/api/v1.0"

# Available filter types from ApeWisdom
VALID_FILTERS = {
    "all-stocks",
    "all-crypto",
    "wallstreetbets",
    "stocks",
    "options",
    "stockmarket",
    "robinhoodpennystocks",
    "pennystocks",
    "shortsqueeze",
    "cryptocurrency",
}


def _fetch_apewisdom_top(filter_type: str = "wallstreetbets", page: int = 1) -> pd.DataFrame:
    """Fetch top tickers from ApeWisdom API."""
    try:
        url = f"{APEWISDOM_API_BASE}/filter/{filter_type}/page/{page}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            logger.warning(f"ApeWisdom API status code: {response.status_code}")
            return pd.DataFrame()

        data = response.json()
        df = pd.DataFrame(data.get("results", []))

        # Sort by mentions (most discussed first)
        if not df.empty and "mentions" in df.columns:
            df = df.sort_values("mentions", ascending=False)

        return df
    except Exception as exc:
        logger.error(f"Error fetching ApeWisdom data: {exc}")
        return pd.DataFrame()


def _fetch_apewisdom_ticker(ticker: str) -> Dict[str, Any]:
    """Fetch details for a specific ticker from ApeWisdom."""
    try:
        url = f"{APEWISDOM_API_BASE}/filter/all-stocks/ticker/{ticker.upper()}"
        response = requests.get(url, timeout=10)

        if response.status_code != 200:
            logger.warning(f"ApeWisdom ticker API status code: {response.status_code}")
            return {}

        return response.json()
    except Exception as exc:
        logger.error(f"Error fetching ticker details from ApeWisdom: {exc}")
        return {}


def _analyze_sentiment_summary(tickers: List[SocialSentimentTicker]) -> Dict[str, Any]:
    """Analyze sentiment data and provide summary statistics."""
    if not tickers:
        return {}

    summary = {
        "total_tickers": len(tickers),
        "average_mentions": 0,
        "average_upvotes": 0,
        "average_sentiment_score": 0,
        "sentiment_distribution": {},
        "top_gainers": [],
        "most_mentioned": [],
    }

    if tickers:
        total_mentions = sum(t.mentions or 0 for t in tickers)
        total_upvotes = sum(t.upvotes or 0 for t in tickers)
        total_sentiment_score = sum(t.sentiment_score or 0 for t in tickers)

        summary["average_mentions"] = total_mentions / len(tickers) if len(tickers) > 0 else 0
        summary["average_upvotes"] = total_upvotes / len(tickers) if len(tickers) > 0 else 0
        summary["average_sentiment_score"] = total_sentiment_score / len(tickers) if len(tickers) > 0 else 0

        # Get sentiment distribution
        sentiments = [t.sentiment for t in tickers if t.sentiment]
        if sentiments:
            from collections import Counter
            sentiment_counts = Counter(sentiments)
            summary["sentiment_distribution"] = dict(sentiment_counts.most_common())

        # Top gainers (rank improvement)
        gainers = []
        for t in tickers:
            if t.rank and t.rank_24h_ago and t.rank_24h_ago > t.rank:
                gainers.append({
                    "ticker": t.ticker,
                    "rank": t.rank,
                    "rank_24h_ago": t.rank_24h_ago,
                    "improvement": t.rank_24h_ago - t.rank
                })
        summary["top_gainers"] = sorted(gainers, key=lambda x: x["improvement"], reverse=True)[:5]

        # Most mentioned
        most_mentioned = sorted(tickers, key=lambda x: x.mentions or 0, reverse=True)[:5]
        summary["most_mentioned"] = [
            {"ticker": t.ticker, "mentions": t.mentions}
            for t in most_mentioned
        ]

    return summary


def get_social_platform_top(
    filter_type: str = "wallstreetbets",
    page: int = 1
) -> SocialSentimentResponse:
    """
    Get top tickers from social platforms (ApeWisdom).

    Args:
        filter_type: One of: all-stocks, all-crypto, wallstreetbets, stocks,
                     options, stockmarket, robinhoodpennystocks, pennystocks,
                     shortsqueeze, cryptocurrency (defaults to wallstreetbets)
        page: Page number for pagination (defaults to 1)
    """
    if filter_type not in VALID_FILTERS:
        raise ValueError(
            f"Invalid filter_type '{filter_type}'. Must be one of: {', '.join(sorted(VALID_FILTERS))}"
        )

    if page < 1:
        raise ValueError("Page must be >= 1")

    try:
        df = _fetch_apewisdom_top(filter_type, page)

        tickers: List[SocialSentimentTicker] = []

        if not df.empty:
            for _, row in df.iterrows():
                # Handle NaN values
                mentions = row.get("mentions")
                mentions = int(mentions) if pd.notna(mentions) and mentions is not None else None

                mentions_24h = row.get("mentions_24h_ago")
                mentions_24h = int(mentions_24h) if pd.notna(mentions_24h) and mentions_24h is not None else None

                upvotes = row.get("upvotes")
                upvotes = int(upvotes) if pd.notna(upvotes) and upvotes is not None else None

                rank = row.get("rank")
                rank = int(rank) if pd.notna(rank) and rank is not None else None

                rank_24h = row.get("rank_24h_ago")
                rank_24h = int(rank_24h) if pd.notna(rank_24h) and rank_24h is not None else None

                sentiment_score = row.get("sentiment_score")
                sentiment_score = float(sentiment_score) if pd.notna(sentiment_score) and sentiment_score is not None else None

                ticker = SocialSentimentTicker(
                    ticker=row.get("ticker"),
                    name=row.get("name"),
                    mentions=mentions,
                    mentions_24h_ago=mentions_24h,
                    upvotes=upvotes,
                    rank=rank,
                    rank_24h_ago=rank_24h,
                    sentiment=row.get("sentiment"),
                    sentiment_score=sentiment_score,
                )
                tickers.append(ticker)

        # Generate summary
        summary = _analyze_sentiment_summary(tickers)

        response = SocialSentimentResponse(
            filter_type=filter_type,
            page=page,
            data=tickers,
            total_count=len(tickers),
            summary=summary,
        )

        return response

    except Exception as exc:
        logger.error(f"Failed to fetch social platform data for filter '{filter_type}': {exc}")
        raise ValueError(f"Unable to fetch social platform data for filter '{filter_type}': {str(exc)}")


def get_social_platform_ticker(ticker: str) -> SocialSentimentDetailsResponse:
    """
    Get detailed sentiment data for a specific ticker from ApeWisdom.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL", "NVDA")
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("Ticker must be a non-empty string")

    ticker_upper = ticker.strip().upper()
    if not ticker_upper:
        raise ValueError("Ticker cannot be empty after trimming")

    try:
        data = _fetch_apewisdom_ticker(ticker_upper)

        if not data:
            logger.warning(f"No data found for ticker {ticker_upper}")
            return SocialSentimentDetailsResponse(ticker=ticker_upper)

        response = SocialSentimentDetailsResponse(
            ticker=data.get("ticker") or ticker_upper,
            name=data.get("name"),
            mentions=data.get("mentions"),
            mentions_24h_ago=data.get("mentions_24h_ago"),
            upvotes=data.get("upvotes"),
            rank=data.get("rank"),
            rank_24h_ago=data.get("rank_24h_ago"),
            sentiment=data.get("sentiment"),
            sentiment_score=data.get("sentiment_score"),
            subreddits=data.get("subreddits", []),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        return response

    except Exception as exc:
        logger.error(f"Failed to fetch social platform details for {ticker_upper}: {exc}")
        raise ValueError(f"Unable to fetch social platform data for ticker '{ticker_upper}': {str(exc)}")

