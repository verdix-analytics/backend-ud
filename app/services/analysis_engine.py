from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import AnalysisResult, AnalyzeRequest, TrendAnalysis
from app.services.context_engine import classify_context
from app.services.pattern_engine import detect_patterns, infer_pre_and_post_trend
from app.services.database_service import insert_detected_patterns
from app.services.report_cache import cache_analysis_report
from app.services.report_generator import build_interpretation
from app.services.sample_data import generate_sample_candles
from app.services.store import analysis_store, latest_analysis_by_instrument



def run_analysis(payload: AnalyzeRequest) -> AnalysisResult:
    candles = payload.candles
    if payload.use_sample_data:
        candles = generate_sample_candles(payload.sample_count)

    if len(candles) < 20:
        raise ValueError("At least 20 candles are required")

    patterns = detect_patterns(candles)
    pre_trend, post_trend = infer_pre_and_post_trend(candles)

    technical_context, confidence, *_ = classify_context(
        patterns=patterns,
        max_patterns=settings.max_patterns_for_context,
    )

    analysis_id = str(uuid4())
    interpretation = build_interpretation(
        context=technical_context,
        patterns=patterns,
        pre_trend=pre_trend,
        post_trend=post_trend,
    )

    ordered_patterns = sorted(patterns, key=lambda p: p.confidence, reverse=True)

    result = AnalysisResult(
        analysis_id=analysis_id,
        instrument=payload.instrument,
        timestamp=datetime.now(timezone.utc),
        timeframe=payload.timeframe,
        technical_context=technical_context,
        confidence=confidence,
        patterns_detected=ordered_patterns,
        interpretation=interpretation,
        trend_analysis=TrendAnalysis(pre_pattern=pre_trend, post_pattern=post_trend),
    )

    analysis_store[analysis_id] = result
    latest_analysis_by_instrument[payload.instrument] = result

    cache_analysis_report(result)

    if patterns:
        try:
            insert_detected_patterns(
                analysis_id=analysis_id,
                instrument=payload.instrument,
                timeframe=payload.timeframe,
                patterns=patterns,
                pre_trend=pre_trend,
                post_trend=post_trend,
            )
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Failed to persist detected patterns for %s: %s", payload.instrument, exc
            )

    return result
