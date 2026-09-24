from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import Lock

from app.core.config import settings
from app.models.schemas import AnalysisResult

try:
    from redis import Redis  
except ImportError:  
    Redis = None  

logger = logging.getLogger(__name__)
_client = None
_lock = Lock()


def _get_client():
    global _client

    if not settings.redis_enabled:
        return None

    if Redis is None:
        logger.warning("Redis caching is enabled but redis package is not installed")
        return None

    if _client is not None:
        return _client

    with _lock:
        if _client is None:
            _client = Redis.from_url(settings.redis_url, decode_responses=True)

    return _client


def _report_key(instrument: str) -> str:
    return f"{settings.redis_report_key_prefix}:{instrument.upper()}"


def cache_analysis_report(result: AnalysisResult) -> None:
    client = _get_client()
    if client is None:
        return

    ts = int(result.timestamp.replace(tzinfo=timezone.utc).timestamp())
    cutoff = ts - settings.redis_report_window_seconds
    key = _report_key(result.instrument)

    payload = json.dumps(result.model_dump(mode="json"))

    try:
        client.zadd(key, {payload: ts})
        client.zremrangebyscore(key, 0, cutoff)
        client.expire(key, settings.redis_report_window_seconds + 3600)
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to write analysis report to Redis cache: %s", exc)


def get_latest_report_from_cache(instrument: str) -> AnalysisResult | None:
    client = _get_client()
    if client is None:
        return None

    now_ts = int(datetime.now(timezone.utc).timestamp())
    min_ts = now_ts - settings.redis_report_window_seconds
    key = _report_key(instrument)

    try:
        rows = client.zrevrangebyscore(key, now_ts, min_ts, start=0, num=1)
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to read analysis report from Redis cache: %s", exc)
        return None

    if not rows:
        return None

    try:
        return AnalysisResult.model_validate(json.loads(rows[0]))
    except Exception as exc:
        logger.warning("Invalid analysis payload in Redis cache: %s", exc)
        return None
