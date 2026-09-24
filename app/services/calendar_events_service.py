import logging
from typing import Dict, Any, Optional
from datetime import datetime

import yfinance as yf
import pandas as pd

from app.models.schemas import (
    CalendarEventsResponse,
    CalendarNextEarnings,
    CalendarDividendInfo,
)

logger = logging.getLogger(__name__)


def _ts_to_str(ts: Optional[int]) -> Optional[str]:
    """Convert a unix timestamp (or None) to YYYY-MM-DD string."""
    if ts is None or ts == 0:
        return None
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def _convert_timestamps_to_strings(obj: Any) -> Any:
    """Recursively convert pandas Timestamp objects to ISO strings."""
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    elif isinstance(obj, dict):
        return {_convert_timestamps_to_strings(k): _convert_timestamps_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_timestamps_to_strings(item) for item in obj]
    else:
        return obj


def parse_split_factor(value: Optional[str]) -> Optional[float]:
    """Parse split factor string like '4:1' into float (4.0)."""
    if value is None:
        return None
    try:
        parts = value.split(':')
        if len(parts) == 2:
            numerator = float(parts[0])
            denominator = float(parts[1])
            if denominator == 0:
                return None
            return numerator / denominator
        else:
            return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def fetch_calendar_events(symbol: str) -> CalendarEventsResponse:
    """Fetch all calendar/corporate-action events for a ticker."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        events: Dict[str, Any] = {}

        # ---------- 1. UPCOMING CALENDAR (earnings + dividends snapshot) ----------
        try:
            events["calendar"] = ticker.calendar
        except Exception:
            events["calendar"] = None

        # ---------- 2. EARNINGS DATES (past + upcoming) ----------
        # DataFrame indexed by date with columns: EPS Estimate, Reported EPS, Surprise(%)
        try:
            earnings_dates = ticker.earnings_dates
            if earnings_dates is not None:
                events["earnings_dates"] = _convert_timestamps_to_strings(earnings_dates.to_dict())
            else:
                events["earnings_dates"] = None
        except Exception:
            events["earnings_dates"] = None

        # ---------- 3. NEXT EARNINGS (from info dict) ----------
        next_ts = info.get("earningsTimestamp")
        next_start = info.get("earningsTimestampStart")
        next_end = info.get("earningsTimestampEnd")
        next_earnings = CalendarNextEarnings(
            earningsTimestamp=_ts_to_str(next_ts),
            earningsTimestampStart=_ts_to_str(next_start),
            earningsTimestampEnd=_ts_to_str(next_end),
            earningsCallTimestamp=_ts_to_str(info.get("earningsCallTimestampStart")),
        )

        # ---------- 4. DIVIDEND HISTORY ----------
        # Series indexed by date, value = dividend amount per share
        try:
            dividends = ticker.dividends
            if dividends is not None and not dividends.empty:
                events["dividends"] = _convert_timestamps_to_strings(dividends.to_dict())
            else:
                events["dividends"] = None
        except Exception:
            events["dividends"] = None

        # ---------- 5. STOCK SPLITS HISTORY ----------
        # Series indexed by date, value = split ratio (e.g. 4.0 = 4-for-1)
        try:
            splits = ticker.splits
            if splits is not None and not splits.empty:
                events["splits"] = _convert_timestamps_to_strings(splits.to_dict())
            else:
                events["splits"] = None
        except Exception:
            events["splits"] = None

        # ---------- 6. CAPITAL GAINS (mainly for funds/ETFs) ----------
        try:
            capital_gains = ticker.capital_gains
            if capital_gains is not None and not capital_gains.empty:
                events["capital_gains"] = _convert_timestamps_to_strings(capital_gains.to_dict())
            else:
                events["capital_gains"] = None
        except Exception:
            events["capital_gains"] = None

        # ---------- 7. ACTIONS (dividends + splits combined) ----------
        try:
            actions = ticker.actions
            if actions is not None and not actions.empty:
                events["actions"] = _convert_timestamps_to_strings(actions.to_dict())
            else:
                events["actions"] = None
        except Exception:
            events["actions"] = None

        # ---------- 8. DIVIDEND METADATA (from info) ----------
        dividend_info = CalendarDividendInfo(
            dividendRate=info.get("dividendRate"),
            dividendYield=info.get("dividendYield"),
            trailingAnnualDividendRate=info.get("trailingAnnualDividendRate"),
            trailingAnnualDividendYield=info.get("trailingAnnualDividendYield"),
            fiveYearAvgDividendYield=info.get("fiveYearAvgDividendYield"),
            payoutRatio=info.get("payoutRatio"),
            exDividendDate=_ts_to_str(info.get("exDividendDate")),
            lastDividendDate=_ts_to_str(info.get("lastDividendDate")),
            lastDividendValue=info.get("lastDividendValue"),
            lastSplitDate=_ts_to_str(info.get("lastSplitDate")),
            lastSplitFactor=parse_split_factor(info.get("lastSplitFactor")),
        )

        return CalendarEventsResponse(
            symbol=symbol.upper(),
            name=info.get("longName"),
            calendar=events.get("calendar"),
            earnings_dates=events.get("earnings_dates"),
            next_earnings=next_earnings,
            dividends=events.get("dividends"),
            splits=events.get("splits"),
            capital_gains=events.get("capital_gains"),
            actions=events.get("actions"),
            dividend_info=dividend_info,
        )

    except Exception as exc:
        logger.error(f"Failed to fetch calendar events for {symbol}: {exc}")
        raise ValueError(f"Unable to fetch calendar events for symbol '{symbol}': {str(exc)}")


def get_calendar_events(symbol: str) -> CalendarEventsResponse:
    """Get calendar events for a stock symbol with validation."""
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string")

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise ValueError("Symbol cannot be empty after trimming")

    return fetch_calendar_events(symbol_upper)
