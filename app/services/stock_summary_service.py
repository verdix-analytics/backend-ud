from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from app.services.asset_service import _format_pattern_name
from app.services.cache_service import cache_stock_summary, get_stock_summary_from_cache
from app.services.circuit_breaker_service import call_with_circuit_breaker
from app.services.database_service import get_detected_patterns, search_stock
from app.services.llm_service import generate_llm_response

_ALLOWED_CATEGORIES = {"candlestick", "chart", "harmonic"}

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockPatternSummaryContext:
	symbol: str
	stock_name: str
	exchange: str
	category: str
	confidence_score: float
	context_score: float
	pattern_name: str
	pattern_category: str
	trend: str
	pattern_rows: list[str]


def _normalize_symbol(symbol: str) -> str:
	return symbol.strip().upper()


def _normalize_category(category: str) -> str:
	normalized = category.strip().lower()
	if normalized not in _ALLOWED_CATEGORIES:
		raise ValueError("category must be one of: candlestick, chart, harmonic")
	return normalized


def _get_stock_name_and_exchange(symbol: str) -> tuple[str, str]:
	stock = search_stock(symbol)
	if stock is None:
		return symbol, "UNKNOWN"
	return stock.get("companyName") or symbol, stock.get("exchange") or "UNKNOWN"


def _trend_from_pattern(pattern: object) -> str:
	signal = getattr(pattern, "signal", None) or {}
	direction = str(signal.get("direction") or "").strip().lower()
	if direction in {"bullish", "bearish", "neutral"}:
		return direction
	return "neutral"


def _context_score_from_pattern(pattern: object) -> float:
	context_score = getattr(pattern, "context_score", None)
	if not isinstance(context_score, dict):
		return 0.0

	score = context_score.get("score")
	try:
		return float(score)
	except (TypeError, ValueError):
		return 0.0


def _build_pattern_rows(patterns: list[object], max_patterns: int) -> list[str]:
	rows: list[str] = []
	for index, pattern in enumerate(patterns[:max_patterns], start=1):
		name = getattr(pattern, "pattern", "") or "Unknown Pattern"
		category = getattr(pattern, "category", "") or "unknown"
		confidence = float(getattr(pattern, "confidence", 0.0) or 0.0)
		context_score = _context_score_from_pattern(pattern)
		trend = _trend_from_pattern(pattern)
		rows.append(
			f"{index}. pattern_name={name}; pattern_category={category}; confidence_score={confidence:.2f}; "
			f"context_score={context_score:.3f}; trend={trend}"
		)
	return rows


def build_stock_pattern_summary_context(
	symbol: str,
	category: str,
	pattern: object,
) -> StockPatternSummaryContext:
	symbol_upper = _normalize_symbol(symbol)
	category_lower = _normalize_category(category)

	stock_name, exchange = _get_stock_name_and_exchange(symbol_upper)
	pattern_rows = _build_pattern_rows([pattern], 1)

	return StockPatternSummaryContext(
		symbol=symbol_upper,
		stock_name=stock_name,
		exchange=exchange,
		category=category_lower,
		confidence_score=float(getattr(pattern, "confidence", 0.0) or 0.0),
		context_score=_context_score_from_pattern(pattern),
		pattern_name=_format_pattern_name(str(getattr(pattern, "pattern", "Unknown Pattern") or "Unknown Pattern")),
		pattern_category=str(getattr(pattern, "category", category_lower) or category_lower),
		trend=_trend_from_pattern(pattern),
		pattern_rows=pattern_rows,
	)


def build_stock_pattern_summary_prompt(context: StockPatternSummaryContext) -> str:
	return (
		"Role: Senior market analyst writing for beginner retail investors.\n"
		"Task: Summarize a detected technical pattern and its market implications.\n\n"
		"Stock\n"
		f"Company: {context.stock_name}\n"
		f"Ticker: {context.symbol}\n"
		f"Exchange: {context.exchange}\n\n"
		"Pattern Details\n"
		f"Pattern Name: {context.pattern_name}\n"
		f"Category: {context.pattern_category}\n"
		f"Trend Direction: {context.trend}\n"
		f"Confidence Score: {context.confidence_score:.2f}\n"
		f"Context Score: {context.context_score:.3f}\n\n"
		"Output rules\n"
		"- Return up to 4 lines total (1 to 4), each a full sentence ending with a period.\n"
		"- Content should cover: what pattern was detected, what it typically signals, reliability "
		"based on confidence/context scores, and the overall bullish/bearish/neutral outlook.\n"
		"- Use simple language suitable for beginner investors, neutral tone, no financial advice.\n"
		"- Do not invent prices, percentages, dates, news, or price targets.\n"
		"- Return plain text only (no headings, markdown, bullets, or formatting)."
	)


def _generate_single_pattern_summary(
	symbol: str,
	category: str,
	pattern: object,
) -> dict[str, str]:
	"""Generate summary for a single pattern."""
	context = build_stock_pattern_summary_context(
		symbol=symbol,
		category=category,
		pattern=pattern,
	)
	prompt = build_stock_pattern_summary_prompt(context)
	try:
		summary = call_with_circuit_breaker(generate_llm_response, prompt)
	except Exception as exc:
		logger.warning("LLM summary generation failed for %s (%s), using static fallback: %s", symbol, category, exc)
		summary = build_static_stock_pattern_summary(context)
	return {'pattern_name': _format_pattern_name(context.pattern_name), 'summary': summary}


def generate_stock_pattern_summaries(
	symbol: str,
	category: str,
	days_lookback: Optional[int] = None,
	max_patterns: int = 5,
) -> list[dict[str, str]]:
	symbol_upper = _normalize_symbol(symbol)
	category_lower = _normalize_category(category)

	cached_summary = get_stock_summary_from_cache(
		symbol=symbol_upper,
		category=category_lower,
	)
	if cached_summary:
		return json.loads(cached_summary)

	patterns = get_detected_patterns(category_lower, symbol_upper, days_lookback=days_lookback)

	if not patterns:
		raise LookupError(f"No detected patterns found for {symbol_upper} ({category_lower})")

	selected_patterns = patterns[:max_patterns]

	# Use ThreadPoolExecutor to generate summaries in parallel
	with ThreadPoolExecutor(max_workers=min(len(selected_patterns), 5)) as executor:
		summaries = list(executor.map(
			lambda p: _generate_single_pattern_summary(symbol_upper, category_lower, p),
			selected_patterns
		))

	cache_stock_summary(
		symbol=symbol_upper,
		category=category_lower,
		summary=json.dumps(summaries),
	)
	return summaries


def build_static_stock_pattern_summary(context: StockPatternSummaryContext) -> str:
	"""
	Builds a static fallback summary when AI generation fails.
	Returns up to 4 lines of plain text summary.
	"""
	lines = [
		f"The {context.pattern_name} pattern in the {context.pattern_category} category was detected for {context.stock_name} ({context.symbol}) on the {context.exchange}.",
		f"This pattern has a confidence score of {context.confidence_score:.2f} and a context score of {context.context_score:.3f}.",
		f"It indicates a {context.trend} trend.",
		f"Overall, this suggests a {context.trend.upper()} signal for the stock."
	]
	return "\n".join(lines[:4])  # Ensure no more than 4 lines
