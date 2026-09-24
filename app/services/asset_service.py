from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from app.models import Asset
from app.models.financial_data import FinancialData1H
from app.models.schemas import (
    ModeEnum,
    Pattern,
    PatternSummary,
    PatternType,
    PopularStockItem,
    SearchResultResponse,
    StockAnalysisResponse,
    StockDirectoryItem,
)
from app.services.cache_service import (
    get_candles_from_cache,
    cache_candles,
    get_detected_patterns_from_cache,
    cache_detected_patterns,
    cache_stock_directory,
    get_stock_directory_from_cache,
)
from app.services.context_engine import classify_context
from app.services.context_score_service import compute_technical_context_score, direction_of_pattern
from app.services.database_service import get_db_session, get_detected_patterns, get_stock_directory_rows, search_stock
from app.core.config import settings

logger = logging.getLogger(__name__)

_KNOWN_STOCKS: dict[str, tuple[str, str]] = {
    "AAPL": ("Apple Inc.", "NASDAQ"),
    "MSFT": ("Microsoft Corporation", "NASDAQ"),
    "GOOGL": ("Alphabet Inc.", "NASDAQ"),
    "GOOG": ("Alphabet Inc.", "NASDAQ"),
    "AMZN": ("Amazon.com Inc.", "NASDAQ"),
    "META": ("Meta Platforms Inc.", "NASDAQ"),
    "NVDA": ("NVIDIA Corporation", "NASDAQ"),
    "TSLA": ("Tesla Inc.", "NASDAQ"),
    "NFLX": ("Netflix Inc.", "NASDAQ"),
    "AMD": ("Advanced Micro Devices Inc.", "NASDAQ"),
    "INTC": ("Intel Corporation", "NASDAQ"),
    "CRM": ("Salesforce Inc.", "NYSE"),
    "ORCL": ("Oracle Corporation", "NYSE"),
    "IBM": ("IBM Corporation", "NYSE"),
    "JPM": ("JPMorgan Chase & Co.", "NYSE"),
    "BAC": ("Bank of America Corp.", "NYSE"),
    "GS": ("Goldman Sachs Group Inc.", "NYSE"),
    "V": ("Visa Inc.", "NYSE"),
    "MA": ("Mastercard Inc.", "NYSE"),
    "DIS": ("The Walt Disney Company", "NYSE"),
    "BTCUSD": ("Bitcoin USD", "CRYPTO"),
    "ETHUSD": ("Ethereum USD", "CRYPTO"),
}

_POPULAR_TICKERS: list[str] = ["AAPL", "TSLA", "NVDA", "AMZN"]

_MODE_CONFIG: dict[ModeEnum, tuple[str, int]] = {
    ModeEnum.CANDLESTICK: ("candlestick", 100),
    ModeEnum.CHART: ("chart", 200),
    ModeEnum.HARMONIC: ("harmonic", 300),
}

_STATIC_CHANGES: dict[str, float] = {"AAPL": 0.187, "TSLA": -0.05, "NVDA": 0.234, "AMZN": 0.123}


def _get_company_name(ticker: str, db_name: Optional[str] = None) -> str:
    if db_name:
        return db_name
    info = _KNOWN_STOCKS.get(ticker.upper())
    return info[0] if info else ticker.upper()


def _get_exchange(ticker: str, db_exchange: Optional[str] = None) -> str:
    if db_exchange:
        return db_exchange

    ticker_upper = ticker.upper()
    session = get_db_session()
    try:
        exchange = session.execute(
            select(Asset.exchange).where(Asset.symbol == ticker_upper)
        ).scalar_one_or_none()
        if isinstance(exchange, str) and exchange.strip():
            return exchange.strip()
    except Exception as exc:
        logger.debug("Asset exchange lookup failed for %s: %s", ticker_upper, exc)
    finally:
        session.close()

    info = _KNOWN_STOCKS.get(ticker_upper)
    return info[1] if info else "UNKNOWN"


def _direction_of(pattern_name: str) -> float:
    return direction_of_pattern(pattern_name)


def _compute_technical_context_score(patterns: list) -> float:
    return compute_technical_context_score(patterns)


def _extract_context_score_fields(context_score: object) -> tuple[Optional[float], Optional[str]]:
    if not isinstance(context_score, dict):
        return None, None

    score_raw = context_score.get("score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None

    bias_raw = context_score.get("bias")
    bias = str(bias_raw).strip() if bias_raw is not None else ""
    return score, (bias or None)


def _get_category_context_score(ticker: str, category: str) -> float:
    """Fetch the most recent context_score.score for a ticker+category from DB.
    Chart scores are on a 0-100 scale so the neutral default is 50.0.
    Candlestick and harmonic scores are on a -1 to +1 scale so neutral default is 0.0.
    """
    patterns = get_detected_patterns(category, ticker)
    if patterns:
        p = patterns[0]
        if p.context_score and isinstance(p.context_score, dict):
            raw = p.context_score.get("score")
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return 50.0 if category == "chart" else 0.0


def _get_category_technical_analysis(ticker: str, category: str) -> Optional[dict]:
    """Fetch the technical_analysis block from the most recent context_score for a ticker+category."""
    patterns = get_detected_patterns(category, ticker)
    if patterns:
        p = patterns[0]
        if p.context_score and isinstance(p.context_score, dict):
            ta = p.context_score.get("technical_analysis")
            if isinstance(ta, dict) and ta:
                return ta
    return None


def _format_pattern_name(raw: str) -> str:
    """
    Convert CS50 engine class names to human-readable display names.
    Examples:
      'DojiCandlestickPattern'              -> 'Doji Candlestick'
      'BatHarmonicPattern'                  -> 'Bat Harmonic'
      'CypherHarmonicPattern'               -> 'Cypher Harmonic'
      'AscendingTriangleChartPattern'       -> 'Ascending Triangle Chart'
      'BullishEngulfingCandlestickPattern'  -> 'Bullish Engulfing Candlestick'
    """
    # Strip trailing "Pattern" only
    name = re.sub(r'Pattern$', '', raw)
    # Split CamelCase into individual words
    words = re.findall(r'[A-Z][a-z]+', name)
    return ' '.join(words) if words else raw


def _format_trend(raw: str) -> str:
    """Convert internal trend value to display-ready label."""
    mapping = {"up": "Bullish", "down": "Bearish", "neutral": "Neutral"}
    return mapping.get(raw.lower(), raw.capitalize())


def _static_popular(ticker: str) -> PopularStockItem:
    info = _KNOWN_STOCKS.get(ticker, (ticker, "UNKNOWN"))
    return PopularStockItem(
        ticker=ticker,
        companyName=info[0],
        exchange=info[1],
        lastPrice=0.0,
        dailyChange=_STATIC_CHANGES.get(ticker, 0.0),
    )


def increment_search_count(ticker: str) -> None:
    """Increment search_count for a ticker in the assets table. Upserts the asset row if missing."""
    ticker_upper = ticker.strip().upper()
    session = get_db_session()
    try:
        asset = session.execute(
            select(Asset).where(Asset.symbol == ticker_upper)
        ).scalar_one_or_none()
        if asset is not None:
            asset.search_count = (asset.search_count or 0) + 1
            session.commit()
        else:
            # Asset not yet in DB — insert it with search_count=1
            new_asset = Asset(
                symbol=ticker_upper,
                name=_get_company_name(ticker_upper),
                exchange=_KNOWN_STOCKS.get(ticker_upper, (None, "UNKNOWN"))[1],
                search_count=1,
            )
            session.add(new_asset)
            session.commit()
    except Exception as exc:
        logger.warning("increment_search_count failed for %s: %s", ticker_upper, exc)
        session.rollback()
    finally:
        session.close()

    # Invalidate popular_stocks cache so next fetch reflects the new count
    try:
        from app.services.cache_service import _get_redis_client
        client = _get_redis_client()
        if client is not None:
            client.delete("safeguard:popular_stocks")
    except Exception:
        pass


def get_popular_stocks() -> list[PopularStockItem]:
    """Return top 4 most-searched stocks (by search_count in assets table).
    Falls back to static list if no search data exists yet."""
    from app.services.cache_service import _get_redis_client
    import json
    client = _get_redis_client()
    cache_key = "safeguard:popular_stocks"
    if client is not None:
        try:
            cached = client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return [PopularStockItem(**item) for item in data]
        except Exception as exc:
            logger.warning("Redis popular_stocks cache read failed: %s", exc)

    # Fetch top 4 tickers by search_count from assets table
    popular_tickers = _POPULAR_TICKERS  # fallback
    session = get_db_session()
    try:
        top_assets = session.execute(
            select(Asset.symbol)
            .where(Asset.search_count > 0)
            .order_by(Asset.search_count.desc())
            .limit(4)
        ).scalars().all()
        if top_assets:
            popular_tickers = list(top_assets)
    except Exception as exc:
        logger.warning("get_popular_stocks search_count query failed: %s", exc)
    finally:
        session.close()

    items: list[PopularStockItem] = []
    session = get_db_session()
    try:
        for ticker in popular_tickers:
            stmt = (
                select(FinancialData1H)
                .options(joinedload(FinancialData1H.stock))
                .join(Asset, FinancialData1H.asset_id == Asset.id)
                .where(Asset.symbol == ticker)
                .order_by(FinancialData1H.ts.desc())
                .limit(2)
            )
            rows = session.execute(stmt).scalars().all()
            if len(rows) >= 2:
                current, previous = rows[0], rows[1]
                current_stock = current.stock or None
                change = (
                    (current.close - previous.close) / previous.close
                    if previous.close
                    else 0.0
                )
                items.append(PopularStockItem(
                    ticker=ticker,
                    companyName=_get_company_name(ticker, current_stock.name if current_stock else None),
                    exchange=_get_exchange(ticker, current_stock.exchange if current_stock else None),
                    lastPrice=current.close,
                    dailyChange=round(change, 4),
                ))
            elif len(rows) == 1:
                current = rows[0]
                current_stock = current.stock or None
                items.append(PopularStockItem(
                    ticker=ticker,
                    companyName=_get_company_name(ticker, current_stock.name if current_stock else None),
                    exchange=_get_exchange(ticker, current_stock.exchange if current_stock else None),
                    lastPrice=current.close,
                    dailyChange=0.0,
                ))
            else:
                items.append(_static_popular(ticker))
    except Exception as exc:
        logger.warning("get_popular_stocks DB query failed: %s", exc)
        items = []
    finally:
        session.close()

    result = items if items else [_static_popular(t) for t in popular_tickers]

    if client is not None:
        try:
            client.setex(cache_key, 5, json.dumps([i.model_dump() for i in result]))
        except Exception as exc:
            logger.warning("Redis popular_stocks cache write failed: %s", exc)

    return result


def get_stock_directory() -> list[StockDirectoryItem]:
    cached_items = get_stock_directory_from_cache()
    if cached_items is not None:
        normalized_items: list[dict[str, object]] = []
        for item in cached_items:
            ticker = str(item.get("ticker", "")).upper()
            name = item.get("name") or item.get("stockName") or ticker
            exchange = item.get("exchange") or _get_exchange(ticker)
            normalized_items.append(
                {
                    "ticker": ticker,
                    "name": str(name),
                    "exchange": str(exchange),
                    "assetClass": item.get("assetClass"),
                }
            )
        return [StockDirectoryItem(**item) for item in normalized_items]

    rows = get_stock_directory_rows()
    directory = [StockDirectoryItem(**row) for row in rows]
    cache_stock_directory([item.model_dump() for item in directory], ttl_seconds=300)
    return directory


def get_stock_analysis(ticker: str, pattern_type: ModeEnum) -> Optional[StockAnalysisResponse]:
    category, _ = _MODE_CONFIG.get(pattern_type, ("candlestick", 100))
    ticker_upper = ticker.upper()

    # Determine lookback days (mirrors routes.py logic)
    if category == "candlestick":
        lookback_days = settings.pattern_lookback_candlestick_days
    elif category == "chart":
        lookback_days = settings.pattern_lookback_chart_days
    else:
        lookback_days = settings.pattern_lookback_harmonic_days

    # Step 1: Try Redis cache (canonical Kafka format: {stock_ticker, pattern_type, result:[...]})
    cached_payload = get_detected_patterns_from_cache(
        pattern_type=category,
        instrument=ticker_upper,
        lookback_days=lookback_days,
    )
    if cached_payload is not None:
        result_items = cached_payload.get("result", [])
        if not result_items:
            return None
        # Convert cached result items to lightweight objects for downstream logic
        class _P:
            def __init__(self, d: dict):
                self.pattern = d.get("pattern", "")
                self.category = d.get("category", category)
                self.confidence = float(d.get("confidence", 0))
                self.confirmed = bool(d.get("confirmed", False))
                self.detected_at = None
                self.window_start = d.get("window_start")
                self.window_end = d.get("window_end")
                self.signal = d.get("signal") or {}
                self.context_score = d.get("context_score")
                self.pre_trend = d.get("pre_trend") or {}
                self.post_trend = d.get("post_trend") or {}
        db_patterns = [_P(item) for item in result_items]
    else:
        # Step 2: DB
        db_patterns = get_detected_patterns(category, ticker_upper)
        # Step 3: cache in canonical Kafka format: {stock_ticker, pattern_type, result:[...]}
        if db_patterns:
            try:
                payload_to_cache = {
                    "stock_ticker": ticker_upper,
                    "pattern_type": category,
                    "result": [
                        {
                            "pattern": p.pattern,
                            "category": p.category,
                            "window_start": getattr(p, "window_start", None),
                            "window_end": getattr(p, "window_end", None),
                            "confidence": p.confidence,
                            "confirmed": getattr(p, "confirmed", False),
                            "signal": p.signal or {},
                            "context_score": getattr(p, "context_score", None),
                            "pre_trend": p.pre_trend or {},
                            "post_trend": p.post_trend or {},
                            "window_count": None,
                        }
                        for p in db_patterns
                    ],
                }
                cache_detected_patterns(
                    pattern_type=category,
                    instrument=ticker_upper,
                    lookback_days=lookback_days,
                    payload=payload_to_cache,
                )
            except Exception as exc:
                logger.warning("Failed to cache patterns for %s: %s", ticker_upper, exc)
    if not db_patterns:
        return None

    now = datetime.now(timezone.utc)
    pattern_objs: list[Pattern] = []
    for p in db_patterns:
        try:
            pattern_objs.append(Pattern(
                name=p.pattern,
                type=PatternType(p.category),
                confidence=float(p.confidence),
                start_time=p.detected_at or now,
                end_time=p.detected_at or now,
                trend_alignment=0,
                metadata=dict(p.signal or {}),
            ))
        except Exception:
            continue

    if not pattern_objs:
        return None

    _, _, short_score, medium_score, long_score = classify_context(pattern_objs)

    short_ctx  = _get_category_context_score(ticker_upper, "candlestick")
    medium_ctx = _get_category_context_score(ticker_upper, "chart")
    long_ctx   = _get_category_context_score(ticker_upper, "harmonic")
    technical_context_score = round((short_ctx + (medium_ctx - 50.0) / 50.0 + long_ctx) / 3.0, 3)

    top = db_patterns[0]
    pre_label = (top.pre_trend or {}).get("label", "sideways")
    post_label = (top.post_trend or {}).get("label", "sideways")
    combined = f"{pre_label} {post_label}".lower()
    if "uptrend" in combined or "up" in combined:
        trend = "up"
    elif "downtrend" in combined or "down" in combined:
        trend = "down"
    else:
        trend = "neutral"

    return StockAnalysisResponse(
        ticker=ticker_upper,
        companyName=_get_company_name(ticker_upper),
        exchange=_get_exchange(ticker_upper),
        pattern_type=pattern_type,
        patterns=[
            PatternSummary(
                name=_format_pattern_name(p.pattern),
                confidence=float(p.confidence),
                contextScore=_extract_context_score_fields(getattr(p, "context_score", None))[0],
                contextBias=_extract_context_score_fields(getattr(p, "context_score", None))[1],
                signal=dict(p.signal or {}),
                pre_trend=dict(p.pre_trend or {}),
                post_trend=dict(p.post_trend or {}),
                detected_at=p.detected_at if pattern_type == ModeEnum.CANDLESTICK else None,
            )
            for p in db_patterns[:5]
        ],
        patternName=[_format_pattern_name(p.pattern) for p in db_patterns[:5]],
        confidenceScore=[p.confidence for p in db_patterns[:5]],
        trend=_format_trend(trend),
        interpretation=(top.signal or {}).get(
            "interpretation",
            f"{category.capitalize()} pattern detected for {ticker_upper}",
        ),
        shortScore=round(short_score, 4),
        mediumScore=round(medium_score, 4),
        longScore=round(long_score, 4),
    )


def get_technical_context_score(ticker: str):
    """Return the technical context score for a ticker across all 3 categories."""
    from app.models.schemas import TechnicalContextScoreResponse
    ticker_upper = ticker.strip().upper()
    short_ctx  = _get_category_context_score(ticker_upper, "candlestick")
    medium_ctx = _get_category_context_score(ticker_upper, "chart")
    long_ctx   = _get_category_context_score(ticker_upper, "harmonic")
    score = round((short_ctx + (medium_ctx - 50.0) / 50.0 + long_ctx) / 3.0, 3)
    return TechnicalContextScoreResponse(
        ticker=ticker_upper,
        technicalContextScore=score,
        shortScore=round(short_ctx, 3),
        mediumScore=round((medium_ctx - 50.0) / 50.0, 3),
        longScore=round(long_ctx, 3),
        shortTechnicalAnalysis=_get_category_technical_analysis(ticker_upper, "candlestick"),
        mediumTechnicalAnalysis=_get_category_technical_analysis(ticker_upper, "chart"),
        longTechnicalAnalysis=_get_category_technical_analysis(ticker_upper, "harmonic"),
    )


def search_stocks(query: str) -> SearchResultResponse:
    ticker = query.strip().upper()
    db_result = search_stock(ticker)
    if db_result is not None:
        return SearchResultResponse(**db_result)

    info = _KNOWN_STOCKS.get(ticker)
    return SearchResultResponse(
        ticker=ticker,
        companyName=info[0] if info else ticker,
        exchange=info[1] if info else "UNKNOWN",
        isValid=info is not None,
    )

