from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import requests as http_requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.models.schemas import (
    Candle,
    ModeEnum,
    PatternSummaryItem,
    PopularStockItem,
    SearchResultResponse,
    StockAnalysisResponse,
    StockDirectoryItem,
    StockSummaryResponse,
    TechnicalContextScoreResponse,
)
from app.services.csv_export_service import build_pattern_signals_csv
from app.services.cache_service import cache_candles, get_candles_from_cache, get_stock_summary_from_cache
from app.services.database_service import get_candles_from_db
from app.services.asset_service import get_popular_stocks, get_stock_analysis, get_stock_directory, search_stocks, get_technical_context_score, increment_search_count
from app.services.stock_summary_service import generate_stock_pattern_summaries
from app.services.external_stock_analysis_service import external_stock_analysis_service
from app.services.translation_service import translate_stock_analysis_response, translate_text
from app.services.user_profile_service import (
    get_profile_info,
    set_subscription,
    check_and_deduct_credit,
    CREDIT_COST_ANALYSIS,
    CREDIT_COST_SUMMARY,
)
from app.services.auth_service import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

# Maps the frontend tab identifiers (short/medium/long) to pattern categories
_MODE_PARAM_MAP: dict[str, ModeEnum] = {
    "short": ModeEnum.CANDLESTICK,
    "medium": ModeEnum.CHART,
    "long": ModeEnum.HARMONIC,
    # also accept canonical names directly
    "candlestick": ModeEnum.CANDLESTICK,
    "chart": ModeEnum.CHART,
    "harmonic": ModeEnum.HARMONIC,
}

# Maps frontend timeframe aliases to storage/database timeframes.
_TIMEFRAME_PARAM_MAP: dict[str, str] = {
    "short": "1m",
    "medium": "1h",
    "long": "1y",
}

_TIMEFRAME_LIMIT_MAP: dict[str, int] = {
    "short": 390,
    "medium": 720,
    "long": 500,
}


def _resolve_timeframe(timeframe: str) -> tuple[str, int]:
    normalized = timeframe.strip().lower()
    mapped = _TIMEFRAME_PARAM_MAP.get(normalized)
    if mapped is None:
        raise HTTPException(status_code=422, detail="timeframe must be one of: short, medium, long")
    return mapped, _TIMEFRAME_LIMIT_MAP[normalized]


def _resolve_language_code(accept_language: str | None) -> str | None:
    if not accept_language:
        return None

    primary = accept_language.split(",", 1)[0].strip()
    if not primary:
        return None

    code = primary.split(";", 1)[0].strip()
    return code or None


@router.get("/me")
def me(
    subscription: str | None = Query(default=None, description="pro | basic"),
    claims: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    cognito_sub = claims.get("sub", "")
    if subscription is not None:
        sub_lower = subscription.strip().lower()
        if sub_lower not in {"pro", "basic"}:
            raise HTTPException(status_code=422, detail="subscription must be 'pro' or 'basic'")
        set_subscription(cognito_sub, sub_lower)
    profile_info = get_profile_info(cognito_sub)
    return {
        "sub":   cognito_sub,
        "email": claims.get("email"),
        "name":  claims.get("name") or claims.get("cognito:username") or claims.get("email"),
        **profile_info,
    }


@router.get("/stocks/popular", response_model=list[PopularStockItem])
def popular_stocks() -> list[PopularStockItem]:
    return get_popular_stocks()


@router.get("/stocks/search", response_model=SearchResultResponse)
def search_stock_frontend(
    q: str = Query(..., min_length=1),
) -> SearchResultResponse:
    return search_stocks(q)


@router.post("/stocks/{ticker}/track-search")
def track_stock_search(ticker: str) -> dict[str, Any]:
    """Increment search count for a ticker in the assets table."""
    increment_search_count(ticker.strip().upper())
    return {"ticker": ticker.strip().upper(), "tracked": True}


@router.get("/stocks/list", response_model=list[StockDirectoryItem])
def stock_directory() -> list[StockDirectoryItem]:
    return get_stock_directory()


@router.get("/candles/{instrument}", response_model=list[Candle])
def get_candles(
    instrument: str,
    timeframe: str = Query(
        "short",
        description="short | medium | long",
    ),
) -> list[Candle]:
    instrument_upper = instrument.upper()
    timeframe_normalized, limit = _resolve_timeframe(timeframe)

    cached_candles = get_candles_from_cache(instrument_upper, timeframe_normalized, limit)
    if cached_candles:
        return cached_candles

    db_candles = get_candles_from_db(instrument_upper, timeframe=timeframe_normalized, limit=limit)
    if not db_candles:
        raise HTTPException(
            status_code=404,
            detail=f"No candle data found for instrument '{instrument}'",
        )

    cache_candles(instrument_upper, timeframe_normalized, db_candles)
    return db_candles


@router.get("/stocks/{ticker}/analysis", response_model=StockAnalysisResponse)
def stock_analysis(
    ticker: str,
    mode: str = Query("short", description="short | medium | long  (or candlestick | chart | harmonic)"),
    accept_language: str | None = Header(default="en", alias="Accept-Language"),
) -> StockAnalysisResponse:
    """
    Frontend calls this with ?mode=short|medium|long
    'short'  → candlestick patterns
    'medium' → chart patterns
    'long'   → harmonic patterns
    Always free — data is served from DB cache. Credits are only deducted for live external analysis.
    """
    pattern_type = _MODE_PARAM_MAP.get(mode.lower(), ModeEnum.CANDLESTICK)

    result = get_stock_analysis(ticker, pattern_type)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {pattern_type.value} patterns found for {ticker.upper()}",
        )

    language_code = _resolve_language_code(accept_language)
    if language_code and language_code not in {"en", "en-us", "en-gb"}:
        try:
            return translate_stock_analysis_response(result, language_code=language_code)
        except (ValueError, RuntimeError) as exc:
            logger.warning("Analysis translation skipped for %s (%s): %s", ticker.upper(), language_code, exc)
    return result


@router.get("/stocks/{ticker}/context-score", response_model=TechnicalContextScoreResponse)
def stock_technical_context_score(ticker: str) -> TechnicalContextScoreResponse:
    """
    Returns the technical context score for a ticker across all 3 pattern categories.
    shortScore  = candlestick context score (-1 to +1)
    mediumScore = chart context score normalized to (-1 to +1)
    longScore   = harmonic context score (-1 to +1)
    technicalContextScore = average of all three
    """
    try:
        return get_technical_context_score(ticker)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stocks/{ticker}/export")
def export_stock_pattern_signals_csv(
    ticker: str,
    category: str = Query(
        "short",
        description="short | medium | long  (or candlestick | chart | harmonic)",
    ),
) -> StreamingResponse:
    mapped_mode = _MODE_PARAM_MAP.get(category.strip().lower())
    if mapped_mode is None:
        raise HTTPException(
            status_code=422,
            detail="category must be one of: short, medium, long, candlestick, chart, harmonic",
        )

    normalized_ticker = ticker.strip().upper()
    normalized_category = mapped_mode.value
    csv_content = build_pattern_signals_csv(
        ticker=normalized_ticker,
        category=normalized_category,
    )

    filename = f"{normalized_ticker}_{normalized_category}_signals.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([csv_content]), media_type="text/csv", headers=headers)


@router.get("/stocks/{ticker}/summary", response_model=StockSummaryResponse)
def generate_stock_ai_summary(
    ticker: str,
    category: str = Query(
        "short",
        description="short | medium | long  (or candlestick | chart | harmonic)",
    ),
    accept_language: str | None = Header(default="en", alias="Accept-Language"),
    claims: dict[str, Any] = Depends(get_current_user),
) -> StockSummaryResponse:
    mapped_mode = _MODE_PARAM_MAP.get(category.strip().lower())
    if mapped_mode is None:
        raise HTTPException(
            status_code=422,
            detail="category must be one of: short, medium, long, candlestick, chart, harmonic",
        )

    cognito_sub = claims.get("sub", "")
    normalized_ticker = ticker.strip().upper()

    # Generate first — only charge if data actually exists
    try:
        summaries = generate_stock_pattern_summaries(
            symbol=normalized_ticker,
            category=mapped_mode.value,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    cache_hit = get_stock_summary_from_cache(normalized_ticker, mapped_mode.value) is not None
    check_and_deduct_credit(
        cognito_sub=cognito_sub,
        ticker=normalized_ticker,
        analysis_type="summary",
        credit_cost=CREDIT_COST_SUMMARY,
        cache_hit=cache_hit,
    )

    language_code = _resolve_language_code(accept_language)
    if language_code and language_code.lower() not in {"en", "en-us", "en-gb"}:
        try:
            summaries = [{'pattern_name': translate_text(language_code, item['pattern_name']), 'summary': translate_text(language_code, item['summary'])} for item in summaries]
        except (ValueError, RuntimeError) as exc:
            # Fail open so summary endpoint still returns if translation is unavailable.
            logger.warning("Summary translation skipped for %s (%s): %s", normalized_ticker, language_code, exc)

    return StockSummaryResponse(
        ticker=normalized_ticker,
        category=mapped_mode,
        summaries=[PatternSummaryItem(pattern_name=item['pattern_name'], summary=item['summary']) for item in summaries],
    )


def _parse_rss_articles(feed_url: str, limit: int, headers: dict) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    try:
        resp = http_requests.get(feed_url, timeout=5, headers=headers)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            if len(articles) >= limit:
                break
            title = (item.findtext("title") or "").strip()
            url   = (item.findtext("link") or "").strip()
            pub   = (item.findtext("pubDate") or "").strip()
            desc  = (item.findtext("description") or "").strip()
            source_el = item.find("source")
            source = source_el.text.strip() if source_el is not None and source_el.text else feed_url.split("/")[2]
            if title and url:
                articles.append({"title": title, "url": url, "source": source, "publishedAt": pub, "summary": desc[:180] if desc else ""})
    except Exception as exc:
        logger.warning("RSS feed %s failed: %s", feed_url, exc)
    return articles


@router.get("/news/market")
def market_news(
    ticker: str | None = Query(default=None, description="Stock ticker for stock-specific news (e.g. AAPL). Omit for general market news."),
) -> list[dict[str, Any]]:
    """Return up to 5 recent news items. If ticker is provided, returns stock-specific news; otherwise returns general market news."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SafeguardBot/1.0)"}

    if ticker:
        ticker_upper = ticker.strip().upper()
        yahoo_feed = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker_upper}&region=US&lang=en-US"
        articles = _parse_rss_articles(yahoo_feed, limit=5, headers=headers)
        if articles:
            return articles
        # Fall back to general news filtered by ticker keyword if Yahoo returns nothing
        general_feeds = [
            "https://feeds.marketwatch.com/marketwatch/topstories/",
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
            "https://feeds.reuters.com/reuters/businessNews",
        ]
        filtered: list[dict[str, Any]] = []
        for feed_url in general_feeds:
            if len(filtered) >= 5:
                break
            for article in _parse_rss_articles(feed_url, limit=20, headers=headers):
                if ticker_upper.lower() in article["title"].lower() or ticker_upper.lower() in article["summary"].lower():
                    filtered.append(article)
                    if len(filtered) >= 5:
                        break
        return filtered[:5]

    # General market news
    general_feeds = [
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
        "https://feeds.reuters.com/reuters/businessNews",
    ]
    articles: list[dict[str, Any]] = []
    for feed_url in general_feeds:
        if len(articles) >= 5:
            break
        articles.extend(_parse_rss_articles(feed_url, limit=5 - len(articles), headers=headers))
    return articles[:5]


@router.post("/admin/set-subscription")
def admin_set_subscription(
    body: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Dev/test endpoint — set subscription_type and credits for the currently authenticated user.

    Body: { "subscription_type": "pro" | "basic", "credits": 10 }
    Credits value replaces existing credits, not adds to them.
    """
    from app.services.database_service import get_db_session
    from app.models.user_profile import UserProfile

    cognito_sub       = claims.get("sub", "")
    subscription_type = body.get("subscription_type")
    credits_value     = body.get("credits")

    if subscription_type is None:
        raise HTTPException(status_code=422, detail="subscription_type is required")
    if subscription_type not in {"pro", "basic"}:
        raise HTTPException(status_code=422, detail="subscription_type must be 'pro' or 'basic'")

    session = get_db_session()
    try:
        profile = session.get(UserProfile, cognito_sub)
        if profile is None:
            profile = UserProfile(cognito_sub=cognito_sub)
            session.add(profile)

        profile.subscription_type = subscription_type
        if credits_value is not None:
            profile.credits_remaining = int(credits_value)

        session.commit()
        return {
            "cognito_sub":             cognito_sub,
            "subscription_type":       profile.subscription_type,
            "credits_remaining":       profile.credits_remaining,
            "free_analyses_remaining": profile.free_analyses_remaining,
        }
    finally:
        session.close()


@router.post("/auth/login")
def login(body: dict[str, Any] = {}) -> dict[str, Any]:
    return {"detail": "Use Cognito Amplify SDK to authenticate"}


@router.post("/auth/register")
def register(body: dict[str, Any] = {}) -> dict[str, Any]:
    return {"detail": "Use Cognito Amplify SDK to register"}


@router.post("/stocks/run-analysis-external-stock")
def run_analysis_external_stock(
    body: dict[str, Any],
    claims: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Triggers live Kafka analysis for a stock not in the DB.
    Deducts 1 credit — only for genuinely external stocks (not preloaded).
    Tab switches never reach this endpoint so they are always free.
    """
    ticker = body.get("ticker", "")
    cognito_sub = claims.get("sub", "")

    try:
        result = external_stock_analysis_service.trigger_analysis(ticker)

        # Deduct credit if:
        # 1. Kafka was triggered (new external stock) — published
        # 2. Stock already in DB but marked is_external=True — skipped but still external
        # Preloaded/internal stocks (is_external=False) are always free
        status = result.get("status")
        if status == "published" or (
            status == "skipped" and external_stock_analysis_service.is_external_stock(ticker)
        ):
            check_and_deduct_credit(
                cognito_sub=cognito_sub,
                ticker=ticker,
                analysis_type="external_analysis",
                credit_cost=CREDIT_COST_ANALYSIS,
                cache_hit=False,
            )

        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
