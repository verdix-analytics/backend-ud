from __future__ import annotations

from typing import List

from app.models.schemas import Pattern, TechnicalContext, TrendDirection


def _context_sentence(context: TechnicalContext) -> str:
    if context == TechnicalContext.POSITIVE:
        return "Recent technical formations indicate constructive momentum and potential upside continuation."
    if context == TechnicalContext.NEGATIVE:
        return "Recent technical formations indicate weakening momentum and elevated downside risk."
    return "Recent technical formations are mixed, with no clear directional edge."


def _patterns_sentence(patterns: List[Pattern]) -> str:
    if not patterns:
        return "No high-confidence patterns were detected in the latest observation window."

    top = patterns[:3]
    labels = [f"{p.name} ({p.confidence:.1f}%)" for p in top]
    return "Detected patterns: " + ", ".join(labels) + "."


def _trend_sentence(pre: TrendDirection, post: TrendDirection) -> str:
    return f"Trend context shifted from {pre.value} pre-pattern behavior to {post.value} post-pattern behavior."


def build_interpretation(
    context: TechnicalContext,
    patterns: List[Pattern],
    pre_trend: TrendDirection,
    post_trend: TrendDirection,
) -> str:
    return " ".join([
        _context_sentence(context),
        _patterns_sentence(patterns),
        _trend_sentence(pre_trend, post_trend),
    ])
