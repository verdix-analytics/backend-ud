import csv
import io
import logging
from datetime import datetime
from typing import Any

from app.services.context_score_service import compute_technical_context_score
from app.services.database_service import get_pattern_signals_by_ticker_and_category

logger = logging.getLogger(__name__)

_CSV_HEADERS = [
    "stock_ticker",
    "stock_name",
    "pattern_category",
    "pattern_name",
    "signal_direction",
    "confidence_score",
    "context_score",
    "found_at",
]


def _format_found_at(value: Any) -> str:
    if value is None:
        return ""

    parsed_dt: datetime | None = None
    if isinstance(value, datetime):
        parsed_dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        try:
            parsed_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
    else:
        return str(value)

    return parsed_dt.strftime("%Y-%m-%d %H:%M:%S")


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_HEADERS)
    writer.writeheader()
    context_score = compute_technical_context_score(rows)

    for row in rows:
        writer.writerow(
            {
                "stock_ticker": row.get("stock_ticker", ""),
                "stock_name": row.get("stock_name", ""),
                "pattern_category": row.get("pattern_category", ""),
                "pattern_name": row.get("pattern_name", ""),
                "signal_direction": row.get("signal_direction", ""),
                "confidence_score": row.get("confidence_score", ""),
                "context_score": context_score,
                "found_at": _format_found_at(
                    row.get("found_at", row.get("created_at", ""))
                ),
            }
        )

    return output.getvalue()


def build_pattern_signals_csv(ticker: str, category: str) -> str:
    """Fetch pattern signals and return a CSV document as a string."""
    rows = get_pattern_signals_by_ticker_and_category(ticker=ticker, category=category)
    logger.debug(
        "Prepared CSV export rows=%d ticker=%s category=%s",
        len(rows),
        ticker,
        category,
    )
    return _rows_to_csv(rows)
