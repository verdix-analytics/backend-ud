import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.core.config import settings
from app.models.schemas import Candle

try:
    from redis import Redis
except ImportError:
    Redis = None

logger = logging.getLogger(__name__)

_SUMMARY_CACHE_TTL_SECONDS = 900

# Redis client instance
_redis_client: Optional[Redis] = None


def _get_redis_client() -> Optional[Redis]:
    global _redis_client
    
    if not settings.redis_enabled or Redis is None:
        return None
    
    if _redis_client is not None:
        return _redis_client
    
    try:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        _redis_client.ping()
        logger.info("Redis cache connected")
        return _redis_client
    except Exception as exc:
        logger.warning(f"Failed to connect to Redis: {exc}")
        return None


def _candles_cache_key(instrument: str, timeframe: str, limit: int) -> str:
    return f"safeguard:{timeframe.lower()}:candles:{instrument.upper()}:limit_{limit}"


def _prices_cache_key(instrument: str, timeframe: str, limit: int, offset: int) -> str:
    return f"safeguard:{timeframe.lower()}:prices:{instrument.upper()}:limit_{limit}:offset_{offset}"


def _patterns_cache_key(pattern_type: str, instrument: str, lookback_days: int, timeframe: str = "1h") -> str:
    return (
        f"safeguard:{timeframe.lower()}:patterns:{pattern_type.lower()}:"
        f"{instrument.upper()}:lookback_{lookback_days}"
    )


def _stock_directory_cache_key() -> str:
    return "safeguard:stocks:directory"


def _summary_cache_key(
    symbol: str,
    category: str,
) -> str:
    return f"safeguard:summary:{symbol.upper()}:category_{category.lower()}"


def cache_stock_summary(
    symbol: str,
    category: str,
    summary: str,
    ttl_seconds: int = _SUMMARY_CACHE_TTL_SECONDS,
) -> None:
    client = _get_redis_client()
    if client is None:
        return

    try:
        key = _summary_cache_key(symbol, category)
        client.setex(key, ttl_seconds, summary)
        logger.debug("Cached AI summary for %s (%s)", symbol, category)
    except Exception as exc:
        logger.warning("Failed to cache AI summary: %s", exc)


def get_stock_summary_from_cache(
    symbol: str,
    category: str,
) -> Optional[str]:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        key = _summary_cache_key(symbol, category)
        summary = client.get(key)
        if summary is None:
            logger.debug("Cache miss for AI summary %s (%s)", symbol, category)
            return None

        logger.debug("Cache hit for AI summary %s (%s)", symbol, category)
        return summary
    except Exception as exc:
        logger.warning("Failed to get AI summary from cache: %s", exc)
        return None


def cache_candles(
    instrument: str,
    timeframe: str,
    candles: list[Candle],
    ttl_seconds: int = 3600,
) -> None:
    client = _get_redis_client()
    if client is None:
        return
    
    try:
        key = _candles_cache_key(instrument, timeframe, len(candles))
        
        # Serialize candles to JSON
        data = json.dumps([c.model_dump(mode="json") for c in candles])
        
        # Set with TTL
        client.setex(key, ttl_seconds, data)
        
        logger.debug(f"Cached {len(candles)} candles for {instrument}")
    except Exception as exc:
        logger.warning(f"Failed to cache candles: {exc}")


def get_candles_from_cache(instrument: str, timeframe: str, limit: int) -> Optional[list[Candle]]:
    client = _get_redis_client()
    if client is None:
        return None
    
    try:
        key = _candles_cache_key(instrument, timeframe, limit)
        data = client.get(key)
        
        if data is None:
            logger.debug(f"Cache miss for {instrument} candles")
            return None
        
        # Deserialize JSON to Candles
        candles_data = json.loads(data)
        candles = [Candle(**c) for c in candles_data]
        
        logger.debug(f"Cache hit for {instrument} - {len(candles)} candles")
        return candles
    except Exception as exc:
        logger.warning(f"Failed to get candles from cache: {exc}")
        return None


def cache_prices(instrument: str, timeframe: str, prices: dict, ttl_seconds: int = 3600) -> None:
    client = _get_redis_client()
    if client is None:
        return
    
    try:
        # Use first price's limit and offset as key
        limit = prices.get("limit", 100)
        offset = prices.get("offset", 0)
        key = _prices_cache_key(instrument, timeframe, limit, offset)
        
        # Serialize to JSON
        data = json.dumps(prices)
        
        # Set with TTL
        client.setex(key, ttl_seconds, data)
        
        logger.debug(f"Cached prices for {instrument} (limit={limit}, offset={offset})")
    except Exception as exc:
        logger.warning(f"Failed to cache prices: {exc}")


def get_prices_from_cache(instrument: str, timeframe: str, limit: int, offset: int) -> Optional[dict]:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        key = _prices_cache_key(instrument, timeframe, limit, offset)
        data = client.get(key)

        if data is None:
            logger.debug(f"Cache miss for {instrument} prices")
            return None

        prices = json.loads(data)
        logger.debug(f"Cache hit for {instrument} prices")
        return prices
    except Exception as exc:
        logger.warning(f"Failed to get prices from cache: {exc}")
        return None


def cache_detected_patterns(
    pattern_type: str,
    instrument: str,
    lookback_days: int,
    payload: dict,
    ttl_seconds: int = 900,
    timeframe: str = "1h",
) -> None:
    client = _get_redis_client()
    if client is None:
        return

    try:
        key = _patterns_cache_key(pattern_type, instrument, lookback_days, timeframe)
        client.setex(key, ttl_seconds, json.dumps(payload))
        logger.debug(
            "Cached detected patterns for %s (%s, %s, %d days)",
            instrument,
            pattern_type,
            timeframe,
            lookback_days,
        )
    except Exception as exc:
        logger.warning("Failed to cache detected patterns: %s", exc)


def get_detected_patterns_from_cache(
    pattern_type: str,
    instrument: str,
    lookback_days: int,
    timeframe: str = "1h",
) -> Optional[dict]:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        key = _patterns_cache_key(pattern_type, instrument, lookback_days, timeframe)
        data = client.get(key)
        if data is None:
            logger.debug(
                "Cache miss for detected patterns %s (%s, %s, %d days)",
                instrument,
                pattern_type,
                timeframe,
                lookback_days,
            )
            return None

        logger.debug(
            "Cache hit for detected patterns %s (%s, %s, %d days)",
            instrument,
            pattern_type,
            timeframe,
            lookback_days,
        )
        return json.loads(data)
    except Exception as exc:
        logger.warning("Failed to get detected patterns from cache: %s", exc)
        return None


def cache_stock_directory(items: list[dict[str, Any]], ttl_seconds: int = 300) -> None:
    client = _get_redis_client()
    if client is None:
        return

    try:
        client.setex(_stock_directory_cache_key(), ttl_seconds, json.dumps(items))
        logger.debug("Cached %d stock directory entries", len(items))
    except Exception as exc:
        logger.warning("Failed to cache stock directory: %s", exc)


def get_stock_directory_from_cache() -> Optional[list[dict[str, Any]]]:
    client = _get_redis_client()
    if client is None:
        return None

    try:
        data = client.get(_stock_directory_cache_key())
        if data is None:
            logger.debug("Cache miss for stock directory")
            return None

        logger.debug("Cache hit for stock directory")
        return json.loads(data)
    except Exception as exc:
        logger.warning("Failed to get stock directory from cache: %s", exc)
        return None


def clear_stock_directory_cache() -> None:
    client = _get_redis_client()
    if client is None:
        return

    try:
        client.delete(_stock_directory_cache_key())
        logger.debug("Cleared stock directory cache")
    except Exception as exc:
        logger.warning("Failed to clear stock directory cache: %s", exc)


def clear_instrument_cache(instrument: str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    
    try:
        # Match all timeframe namespaces: safeguard:1h:*:AAPL:*, safeguard:1m:*:AAPL:*, etc.
        keys: list = []
        for tf in ("1h", "1m", "1y"):
            keys.extend(client.keys(f"safeguard:{tf}:*:{instrument.upper()}:*"))
        
        if keys:
            client.delete(*keys)
            logger.info("Cleared %d cache entries for %s", len(keys), instrument)
    except Exception as exc:
        logger.warning("Failed to clear cache for %s: %s", instrument, exc)


def clear_all_cache() -> None:
    client = _get_redis_client()
    if client is None:
        return
    
    try:
        pattern = "safeguard:*"
        keys = client.keys(pattern)
        
        if keys:
            client.delete(*keys)
            logger.info(f"Cleared all {len(keys)} cache entries")
    except Exception as exc:
        logger.warning(f"Failed to clear all cache: {exc}")

