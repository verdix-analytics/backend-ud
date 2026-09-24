from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import (
    FundamentalsResponse,
    CalendarEventsResponse,
    NewsResponse,
    SocialSentimentResponse,
    SocialSentimentDetailsResponse,
    StockTwitsResponse,
)
from app.services.fundamentals_service import get_fundamentals
from app.services.calendar_events_service import get_calendar_events
from app.services.news_service import get_news
from app.services.social_sentiment_service import get_social_platform_top, get_social_platform_ticker
from app.services.stocktwits_service import get_stocktwits_messages

router = APIRouter()


@router.get("/fundamentals/{symbol}", response_model=FundamentalsResponse)
def get_fundamentals_endpoint(symbol: str) -> FundamentalsResponse:
    """
    Get company fundamentals from Yahoo Finance.

    Path parameters:
    - symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
    - FundamentalsResponse with comprehensive financial data including:
      * Key statistics (market cap, P/E ratio, etc.)
      * Financial statements (income, balance sheet, cash flow)
      * Analyst recommendations and price targets
      * Earnings history and estimates

    Example: GET /api/fundamentals/AAPL
    """
    try:
        return get_fundamentals(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch fundamentals: {str(exc)}") from exc


@router.get("/calendar/{symbol}", response_model=CalendarEventsResponse)
def get_calendar_endpoint(symbol: str) -> CalendarEventsResponse:
    """
    Get calendar events and corporate actions from Yahoo Finance.

    Path parameters:
    - symbol: Stock ticker symbol (e.g., "AAPL")

    Returns:
    - CalendarEventsResponse with comprehensive calendar data including:
      * Upcoming earnings dates and calls
      * Dividend history and upcoming ex-dividend dates
      * Stock splits and capital gains
      * All corporate actions (dividends, splits combined)
      * Dividend yield and payout ratios
      * Earnings date history (past + upcoming)

    Example: GET /api/calendar/AAPL
    """
    try:
        return get_calendar_events(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch calendar events: {str(exc)}") from exc


@router.get("/news/{symbol}", response_model=NewsResponse)
def get_news_endpoint(symbol: str, limit: int = Query(None, ge=1, le=100)) -> NewsResponse:
    """
    Get news articles for a given stock ticker.

    Path parameters:
    - symbol: Stock ticker symbol (e.g., "AAPL")

    Query parameters:
    - limit: Maximum number of articles to return (1-100, optional)

    Returns:
    - NewsResponse with comprehensive news data including:
      * Article title, summary, and full description
      * Publication date and display time
      * Content type (story, video, etc.)
      * Provider information and source
      * Thumbnail images with multiple resolutions
      * Canonical and click-through URLs
      * Metadata (editors pick status)
      * Finance-specific data (premium status)

    Example: GET /api/news/AAPL?limit=10
    """
    try:
        return get_news(symbol, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch news: {str(exc)}") from exc


@router.get("/social-platform-sentiment", response_model=SocialSentimentResponse)
def get_social_platform_sentiment_endpoint(
    filter_type: str = Query(
        "wallstreetbets",
        description="Filter by platform: all-stocks, all-crypto, wallstreetbets, stocks, options, stockmarket, robinhoodpennystocks, pennystocks, shortsqueeze, cryptocurrency"
    ),
    page: int = Query(1, ge=1, description="Page number for pagination (1-based)")
) -> SocialSentimentResponse:
    """
    Get top tickers from social platforms (ApeWisdom API).

    Updated hourly from multiple subreddits including r/wallstreetbets, r/stocks, r/options, etc.

    Query parameters:
    - filter_type: Platform/subreddit filter (defaults to wallstreetbets)
      Available: all-stocks, all-crypto, wallstreetbets, stocks, options,
                 stockmarket, robinhoodpennystocks, pennystocks, shortsqueeze, cryptocurrency
    - page: Page number for pagination (defaults to 1)

    Returns:
    - SocialSentimentResponse with:
      * Tickers being discussed on social platforms
      * Mention counts (current and 24h ago)
      * Upvote scores and ranking information
      * Sentiment analysis and sentiment scores
      * Summary statistics (trending, gainers, most mentioned)

    Example: GET /api/social-platform-sentiment?filter_type=wallstreetbets
    Example: GET /api/social-platform-sentiment?filter_type=all-stocks&page=2
    Example: GET /api/social-platform-sentiment?filter_type=options
    """
    try:
        return get_social_platform_top(filter_type, page)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch social platform sentiment: {str(exc)}") from exc


@router.get("/social-platform-sentiment/{symbol}", response_model=SocialSentimentDetailsResponse)
def get_social_platform_sentiment_ticker_endpoint(symbol: str) -> SocialSentimentDetailsResponse:
    """
    Get detailed sentiment data for a specific ticker from social platforms (ApeWisdom API).

    Path parameters:
    - symbol: Stock ticker symbol (e.g., "AAPL", "NVDA")

    Returns:
    - SocialSentimentDetailsResponse with:
      * Current mention count and 24h comparison
      * Upvote score and ranking information
      * Sentiment analysis and sentiment score
      * List of subreddits discussing this ticker
      * Last updated timestamp

    Example: GET /api/social-platform-sentiment/AAPL
    Example: GET /api/social-platform-sentiment/NVDA
    Example: GET /api/social-platform-sentiment/TSLA
    """
    try:
        return get_social_platform_ticker(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch social platform sentiment for ticker: {str(exc)}") from exc


@router.get("/social/{symbol}", response_model=StockTwitsResponse)
def get_stocktwits_endpoint(
    symbol: str,
    limit: int = Query(15, ge=1, le=30, description="Number of messages to return (1-30)")
) -> StockTwitsResponse:
    """
    Get recent StockTwits messages for a given ticker.

    Path parameters:
    - symbol: Stock ticker symbol (e.g., "AAPL")

    Query parameters:
    - limit: Number of messages to return (1-30, defaults to 15)

    Returns:
    - StockTwitsResponse with:
      * username of the poster
      * created_at timestamp
      * sentiment (Bullish / Bearish / null)
      * likes count
      * body (message text)

    Example: GET /api/social/AAPL
    Example: GET /api/social/TSLA?limit=20
    """
    try:
        return get_stocktwits_messages(symbol, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch StockTwits messages: {str(exc)}") from exc

