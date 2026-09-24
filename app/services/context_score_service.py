from __future__ import annotations

from typing import Any

_POSITIVE_HINTS = (
    "Bullish",
    "Double Bottom",
    "Morning Star",
    "Ascending",
    "Hammer",
    "Inverted Hammer",
    "Cup",
)
_NEGATIVE_HINTS = (
    "Bearish",
    "Double Top",
    "Evening Star",
    "Descending",
    "Shooting Star",
    "Head And Shoulders",
)


def direction_of_pattern(pattern_name: str) -> float:
    if any(h in pattern_name for h in _POSITIVE_HINTS):
        return 1.0
    if any(h in pattern_name for h in _NEGATIVE_HINTS):
        return -1.0
    return 0.0


def _value(item: Any, *keys: str) -> Any:
    if isinstance(item, dict):
        for key in keys:
            if key in item:
                return item[key]
        return None
    for key in keys:
        if hasattr(item, key):
            return getattr(item, key)
    return None


def compute_technical_context_score(patterns: list[Any]) -> float:
    """Shared technical context score logic used by stock analysis and CSV export."""
    if not patterns:
        return 0.0

    total = 0.0
    for item in patterns:
        pattern_name = str(_value(item, "pattern", "pattern_name") or "")
        confidence_raw = _value(item, "confidence", "confidence_score")
        try:
            confidence = float(confidence_raw or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        total += (confidence / 100.0) * direction_of_pattern(pattern_name)

    return round(total / len(patterns), 3)

