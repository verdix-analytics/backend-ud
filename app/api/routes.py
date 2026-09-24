from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import (
    AnalysisResult,
    AnalyzeRequest,
    BatchAnalyzeRequest,
    BatchAnalyzeResponse,
    Candle,
    DetectedPatternResponse,
    DetectedPatternsListResponse,
    Pattern,
    StockSearchResponse,
)
from app.services.analysis_engine import run_analysis
from app.services.pattern_engine_adapter import get_pattern_catalog, get_pattern_engine_status
from app.services.ingestion_worker import periodic_ingestion_worker
from app.services.report_cache import get_latest_report_from_cache
from app.services.sample_data import generate_sample_candles
from app.services.store import analysis_store, latest_analysis_by_instrument
from app.services.database_service import get_financial_prices, get_detected_patterns, search_stock
from app.services.kafka_financial_consumer import financial_price_consumer
from app.services.kafka_pattern_consumer import pattern_consumer
from app.services.cache_service import (
    get_prices_from_cache,
    cache_prices,
    get_detected_patterns_from_cache,
    cache_detected_patterns,
)

router = APIRouter()


def _validate_timeframe(timeframe: str) -> str:
    normalized = timeframe.strip().lower()
    if normalized not in {"1h", "1m", "1y"}:
        raise HTTPException(status_code=422, detail="timeframe must be one of: 1h, 1m, 1y")
    return normalized


def _run_analysis(payload: AnalyzeRequest) -> AnalysisResult:
    try:
        return run_analysis(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/stocks/search", response_model=StockSearchResponse)
def search_stock_endpoint(query: str, timeframe: str = "1h") -> StockSearchResponse:
    """
    Search for a stock by ticker symbol.
    
    Query parameters:
    - query: Stock ticker symbol (e.g., "AAPL")
    
    Returns:
    - StockSearchResponse with ticker, companyName, exchange, and isValid fields
    
    Example: GET /api/stocks/search?query=AAPL
    """
    _KNOWN = {
        "AAPL": ("Apple Inc.", "NASDAQ"), "MSFT": ("Microsoft Corporation", "NASDAQ"),
        "GOOGL": ("Alphabet Inc.", "NASDAQ"), "GOOG": ("Alphabet Inc.", "NASDAQ"),
        "AMZN": ("Amazon.com Inc.", "NASDAQ"), "META": ("Meta Platforms Inc.", "NASDAQ"),
        "NVDA": ("NVIDIA Corporation", "NASDAQ"), "TSLA": ("Tesla Inc.", "NASDAQ"),
        "NFLX": ("Netflix Inc.", "NASDAQ"), "AMD": ("Advanced Micro Devices Inc.", "NASDAQ"),
        "INTC": ("Intel Corporation", "NASDAQ"), "CRM": ("Salesforce Inc.", "NYSE"),
        "ORCL": ("Oracle Corporation", "NYSE"), "IBM": ("IBM Corporation", "NYSE"),
        "JPM": ("JPMorgan Chase & Co.", "NYSE"), "BAC": ("Bank of America Corp.", "NYSE"),
        "GS": ("Goldman Sachs Group Inc.", "NYSE"), "V": ("Visa Inc.", "NYSE"),
        "MA": ("Mastercard Inc.", "NYSE"), "DIS": ("The Walt Disney Company", "NYSE"),
        "BTCUSD": ("Bitcoin USD", "CRYPTO"), "ETHUSD": ("Ethereum USD", "CRYPTO"),
    }

    ticker = query.strip().upper()
    static = _KNOWN.get(ticker)

    # Try DB first for any additional info
    timeframe_normalized = _validate_timeframe(timeframe)
    result = search_stock(query, timeframe=timeframe_normalized)

    if result is not None:
        # DB found it — enrich with static lookup if DB fields are missing
        return StockSearchResponse(
            ticker=result["ticker"],
            companyName=result["companyName"] if result["companyName"] != ticker else (static[0] if static else ticker),
            exchange=result["exchange"] if result["exchange"] != "UNKNOWN" else (static[1] if static else "UNKNOWN"),
            isValid=True,
        )

    # DB miss — check static known list
    if static:
        return StockSearchResponse(ticker=ticker, companyName=static[0], exchange=static[1], isValid=True)

    return StockSearchResponse(ticker=ticker, companyName="Unknown", exchange="UNKNOWN", isValid=False)


@router.post("/analyze", response_model=AnalysisResult)
def analyze(payload: AnalyzeRequest) -> AnalysisResult:
    return _run_analysis(payload)


@router.post("/batch", response_model=BatchAnalyzeResponse)
def batch_analyze(payload: BatchAnalyzeRequest) -> BatchAnalyzeResponse:
    results = [_run_analysis(item) for item in payload.analyses]
    return BatchAnalyzeResponse(results=results)


@router.get("/context/{analysis_id}", response_model=AnalysisResult)
def get_context(analysis_id: str) -> AnalysisResult:
    result = analysis_store.get(analysis_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis ID not found")
    return result


@router.get("/patterns/{instrument}", response_model=list[Pattern])
def get_patterns(instrument: str) -> list[Pattern]:
    # Try cache first
    cached = get_latest_report_from_cache(instrument)
    if cached is not None:
        return cached.patterns_detected

    # Fall back to in-memory store
    result = latest_analysis_by_instrument.get(instrument)
    if result is not None:
        return result.patterns_detected

    raise HTTPException(status_code=404, detail=f"Stock '{instrument}' is not available")


@router.get("/context/instrument/{instrument}", response_model=AnalysisResult)
def get_context_by_instrument(instrument: str) -> AnalysisResult:
    # Try cache first
    cached = get_latest_report_from_cache(instrument)
    if cached is not None:
        return cached

    # Fall back to in-memory store
    result = latest_analysis_by_instrument.get(instrument)
    if result is not None:
        return result

    raise HTTPException(status_code=404, detail=f"Stock '{instrument}' is not available")



@router.get("/financial-prices/{instrument}")
def get_prices(instrument: str, timeframe: str = "1h", limit: int = 100, offset: int = 0) -> dict:
    # Validate parameters
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=422, detail="Offset must be non-negative")
    
    instrument_upper = instrument.upper()
    timeframe_normalized = _validate_timeframe(timeframe)
    
    # Step 1: Try Redis cache (fastest - ~1ms)
    cached_prices = get_prices_from_cache(instrument_upper, timeframe_normalized, limit, offset)
    if cached_prices:
        return cached_prices
    
    # Step 2: Cache miss - fetch from database (~10-100ms)
    prices = get_financial_prices(
        symbol=instrument_upper,
        timeframe=timeframe_normalized,
        limit=limit,
        offset=offset,
    )
    if not prices:
        raise HTTPException(
            status_code=404,
            detail=f"No price data found for instrument '{instrument}'"
        )
    
    # Format response data
    response_data = {
        "instrument": instrument_upper,
        "timeframe": timeframe_normalized,
        "count": len(prices),
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": p.id,
                "symbol": (p.stock.symbol if getattr(p, "stock", None) else instrument_upper),
                "stock_name": (p.stock.stock_name if getattr(p, "stock", None) else None),
                "stock_exchange": (p.stock.stock_exchange if getattr(p, "stock", None) else None),
                "datetime": p.ts.isoformat(),
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "volume": p.volume,
            }
            for p in prices
        ]
    }
    
    # Step 3: Cache the result for future requests
    cache_prices(instrument_upper, timeframe_normalized, response_data)

    return response_data


@router.get("/sample-candles", response_model=list[Candle])
def sample_candles() -> list[Candle]:
    return generate_sample_candles(50)


@router.get("/ingestion/status")
def ingestion_status() -> dict:
    return periodic_ingestion_worker.status()


@router.get("/kafka/status")
def kafka_status() -> dict:
    """Get Kafka consumer status"""
    if not settings.kafka_enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "message": "Kafka consumer is disabled"
        }
    
    financial_status = financial_price_consumer.status()
    pattern_status = pattern_consumer.status()
    return {
        "enabled": True,
        "running": financial_status["running"] or pattern_status["running"],
        "messages_processed": financial_status["messages_processed"] + pattern_status["messages_processed"],
        "messages_failed": financial_status["messages_failed"] + pattern_status["messages_failed"],
        "last_error": financial_status["last_error"] or pattern_status["last_error"],
        "consumers": {
            "financial": financial_status.get("consumers", {}),
            "pattern": pattern_status.get("consumers", {}),
        },
    }


@router.get("/engine/status")
def engine_status() -> dict:
    return {
        "service": settings.app_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pattern_engine_adapter": get_pattern_engine_status(),
        "pattern_catalog": get_pattern_catalog(),
        "max_patterns_for_context": settings.max_patterns_for_context,
    }


@router.post("/ingestion/run-now")
async def ingestion_run_now() -> dict:
    await periodic_ingestion_worker.run_once()
    return {
        "status": "ok",
        "message": "Ingestion cycle completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/patterns/{pattern_type}/{instrument}", response_model=DetectedPatternsListResponse)
def get_detected_patterns_by_type(pattern_type: str, instrument: str) -> DetectedPatternsListResponse:
    """
    Retrieve detected patterns from the database.
    
    Pattern types: candlestick, chart, harmonic
    Lookback periods are configurable via environment variables:
    - PATTERN_LOOKBACK_CANDLESTICK_DAYS (default: 1)
    - PATTERN_LOOKBACK_CHART_DAYS (default: 60)
    - PATTERN_LOOKBACK_HARMONIC_DAYS (default: 365)
    """
    pattern_type_lower = pattern_type.lower()
    
    # Validate pattern type
    valid_types = ["candlestick", "chart", "harmonic"]
    if pattern_type_lower not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid pattern_type. Must be one of: {', '.join(valid_types)}",
        )
    
    # Determine lookback days based on pattern type
    if pattern_type_lower == "candlestick":
        lookback_days = settings.pattern_lookback_candlestick_days
    elif pattern_type_lower == "chart":
        lookback_days = settings.pattern_lookback_chart_days
    else:  # harmonic
        lookback_days = settings.pattern_lookback_harmonic_days

    instrument_upper = instrument.upper()

    # Step 1: Try Redis cache first (stored in canonical Kafka format {stock_ticker, pattern_type, result:[...]})
    cached_payload = get_detected_patterns_from_cache(
        pattern_type=pattern_type_lower,
        instrument=instrument_upper,
        lookback_days=lookback_days,
    )
    if cached_payload is not None:
        result_items = cached_payload.get("result", [])
        cached_patterns = [
            DetectedPatternResponse(
                pattern=item.get("pattern", ""),
                category=item.get("category", pattern_type_lower),
                window_start=item.get("window_start"),
                window_end=item.get("window_end"),
                confidence=float(item.get("confidence", 0.0)),
                confirmed=bool(item.get("confirmed", False)),
                signal=item.get("signal") or {},
                pre_trend=item.get("pre_trend") or {},
                post_trend=item.get("post_trend") or {},
            )
            for item in result_items
        ]
        return DetectedPatternsListResponse(
            instrument=instrument_upper,
            category=pattern_type_lower,
            lookback_days=lookback_days,
            count=len(cached_patterns),
            patterns=cached_patterns,
        )

    # Step 2: Cache miss -> fetch from database
    patterns_db = get_detected_patterns(pattern_type_lower, instrument_upper)
    
    # Convert database records to response models
    pattern_responses = [
        DetectedPatternResponse(
            id=p.id,
            analysis_id=p.analysis_id,
            instrument=p.instrument,
            timeframe=p.timeframe,
            detected_at=p.detected_at,
            pattern=p.pattern,
            category=p.category,
            pattern_type=p.pattern_type,
            window_start=p.window_start,
            window_end=p.window_end,
            confidence=p.confidence,
            confirmed=p.confirmed,
            structure_detected=p.structure_detected,
            signal={
                "confirmed": (p.signal or {}).get("confirmed", p.confirmed),
                "structure_detected": (p.signal or {}).get("structure_detected", p.structure_detected),
                "confidence": (p.signal or {}).get("confidence", p.confidence),
                "confidence_breakdown": (p.signal or {}).get("confidence_breakdown", {}),
                "confidence_metadata": (p.signal or {}).get("confidence_metadata", {}),
                "pivots": (p.signal or {}).get("pivots"),
                "direction": (p.signal or {}).get("direction"),
            },
            pre_trend={
                "label": (p.pre_trend or {}).get("label", "sideways"),
                "strength": (p.pre_trend or {}).get("strength"),
                "realized_move_pct": (p.pre_trend or {}).get("realized_move_pct"),
            },
            post_trend={
                "label": (p.post_trend or {}).get("label", "sideways"),
                "strength": (p.post_trend or {}).get("strength"),
                "realized_move_pct": (p.post_trend or {}).get("realized_move_pct"),
            },
        )
        for p in patterns_db
    ]

    response = DetectedPatternsListResponse(
        instrument=instrument_upper,
        category=pattern_type_lower,
        lookback_days=lookback_days,
        count=len(pattern_responses),
        patterns=pattern_responses,
    )

    # Step 3: Cache in canonical Kafka format: {stock_ticker, pattern_type, result:[...]}
    payload_to_cache = {
        "stock_ticker": instrument_upper,
        "pattern_type": pattern_type_lower,
        "result": [
            {
                "pattern": p.pattern,
                "category": p.category,
                "window_start": p.window_start,
                "window_end": p.window_end,
                "confidence": p.confidence,
                "confirmed": p.confirmed,
                "signal": p.signal or {},
                "pre_trend": p.pre_trend or {},
                "post_trend": p.post_trend or {},
                "window_count": None,
            }
            for p in patterns_db
        ],
    }
    cache_detected_patterns(
        pattern_type=pattern_type_lower,
        instrument=instrument_upper,
        lookback_days=lookback_days,
        payload=payload_to_cache,
    )

    return response

