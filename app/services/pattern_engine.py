from __future__ import annotations

from statistics import mean

from app.models.schemas import Candle, Pattern, TrendDirection
from app.services.pattern_engine_adapter import detect_patterns_from_adapter, get_pattern_engine_status


def _trend_direction(candles: list[Candle], lookback: int = 10) -> TrendDirection:
    if lookback < 2:
        return TrendDirection.SIDEWAYS

    if len(candles) < lookback:
        return TrendDirection.SIDEWAYS

    closes = [c.close for c in candles[-lookback:]]
    slope = closes[-1] - closes[0]
    avg_move = mean(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))

    if slope > avg_move:
        return TrendDirection.UPTREND
    if slope < -avg_move:
        return TrendDirection.DOWNTREND
    return TrendDirection.SIDEWAYS


def detect_patterns(candles: list[Candle]) -> list[Pattern]:
    status = get_pattern_engine_status()
    if not status["enabled"]:
        raise ValueError("CS50 pattern engine is disabled")
    if not status["python_compatible"]:
        raise ValueError("CS50 pattern engine is unavailable: Python 3.10+ is required")
    if not status["cs50_root_exists"]:
        raise ValueError("CS50 pattern engine path is unavailable")

    return detect_patterns_from_adapter(candles)


def infer_pre_and_post_trend(candles: list[Candle]) -> tuple[TrendDirection, TrendDirection]:
    midpoint = max(len(candles) // 2, 1)
    pre = _trend_direction(candles[:midpoint], lookback=max(2, min(10, midpoint)))
    post = _trend_direction(candles[midpoint:], lookback=max(2, min(10, len(candles[midpoint:]))))
    return pre, post
