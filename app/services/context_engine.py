from __future__ import annotations

import math
from statistics import mean
from typing import Dict, List, Optional

from app.models.schemas import Pattern, PatternType, TechnicalContext, TrendDirection


# Harmonic patterns that signal bullish reversal at point D
_BULLISH_HARMONIC_HINTS = ("Gartley", "Bat", "Cypher")
# Harmonic patterns that signal bearish reversal / extension at point D
_BEARISH_HARMONIC_HINTS = ("Butterfly", "Crab", "Shark")

POSITIVE_NAME_HINTS = (
    "Bullish",
    "Double Bottom",
    "Morning Star",
    "Ascending Triangle",
    "Hammer",
    "Inverted Hammer",
)

NEGATIVE_NAME_HINTS = (
    "Bearish",
    "Double Top",
    "Evening Star",
    "Descending Triangle",
    "Shooting Star",
    "Head And Shoulders",
)


def _normalize(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return max(0.0, min(1.0, (value - lower) / (upper - lower)))


def _direction_multiplier(p: Pattern) -> float:
    if p.trend_alignment in (-1, 1):
        return float(p.trend_alignment)
    if any(hint in p.name for hint in POSITIVE_NAME_HINTS):
        return 1.0
    if any(hint in p.name for hint in NEGATIVE_NAME_HINTS):
        return -1.0
    if any(p.name == h for h in _BULLISH_HARMONIC_HINTS):
        return 1.0
    if any(p.name == h for h in _BEARISH_HARMONIC_HINTS):
        return -1.0
    return 0.0


def _score_bucket(patterns: List[Pattern], max_patterns: int) -> float:
    if not patterns:
        return 0.0
    recent = patterns[:max_patterns]
    score = 0.0
    for p in recent:
        score += (p.confidence / 100.0) * _direction_multiplier(p)
    return score


_PRE_TREND_SCORE: Dict[str, float] = {
    TrendDirection.UPTREND.value: 1.0,
    TrendDirection.DOWNTREND.value: -1.0,
    TrendDirection.SIDEWAYS.value: 0.0,
}


def classify_context(
    patterns: List[Pattern],
    max_patterns: int = 5,
    pre_trend: Optional[TrendDirection] = None,
) -> tuple[TechnicalContext, float, float, float, float]:
    """
    Buckets: s=candlestick, m=chart, l=harmonic
    long_score  = 0.5*l + 0.3*m + 0.2*s
    short_score = 0.5*s + 0.3*m + 0.2*l
    final = ceil((long_score + short_score) / 2) + pre_trend nudge
    """
    if not patterns:
        return TechnicalContext.NEUTRAL, 50.0, 0.0, 0.0, 0.0

    short_patterns  = [p for p in patterns if p.type == PatternType.CANDLESTICK]
    medium_patterns = [p for p in patterns if p.type == PatternType.CHART]
    long_patterns   = [p for p in patterns if p.type == PatternType.HARMONIC]

    s = _score_bucket(short_patterns,  max_patterns)
    m = _score_bucket(medium_patterns, max_patterns)
    l = _score_bucket(long_patterns,   max_patterns)

    long_score  = 0.5 * l + 0.3 * m + 0.2 * s
    short_score = 0.5 * s + 0.3 * m + 0.2 * l

    raw = (long_score + short_score) / 2.0

    if pre_trend is not None:
        raw += _PRE_TREND_SCORE.get(pre_trend.value, 0.0) * 0.5

    final_score = math.ceil(raw)
    normalized = _normalize(float(final_score), -5.0, 5.0)
    context_confidence = round(mean(p.confidence for p in patterns), 2)

    if normalized > 0.6:
        return TechnicalContext.POSITIVE, context_confidence, round(s, 4), round(m, 4), round(l, 4)
    if normalized < 0.4:
        return TechnicalContext.NEGATIVE, context_confidence, round(s, 4), round(m, 4), round(l, 4)
    return TechnicalContext.NEUTRAL, context_confidence, round(s, 4), round(m, 4), round(l, 4)
