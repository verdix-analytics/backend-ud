import logging
from typing import Dict, Any, Optional

import yfinance as yf
from datetime import datetime
import pandas as pd

from app.models.schemas import FundamentalsResponse, FundamentalsKeyStats, FundamentalsPriceTargets

logger = logging.getLogger(__name__)


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


def fetch_fundamentals(symbol: str) -> FundamentalsResponse:
    """Fetch all fundamental data for a given ticker symbol."""
    try:
        ticker = yf.Ticker(symbol)
        data: Dict[str, Any] = {}

        # ---------- 1. INCOME STATEMENTS ----------
        # .income_stmt -> annual, .quarterly_income_stmt -> quarterly
        try:
            income_annual_dict = ticker.income_stmt.to_dict() if ticker.income_stmt is not None else None
            data["income_annual"] = _convert_timestamps_to_strings(income_annual_dict)
        except Exception:
            data["income_annual"] = None

        try:
            income_quarterly_dict = ticker.quarterly_income_stmt.to_dict() if ticker.quarterly_income_stmt is not None else None
            data["income_quarterly"] = _convert_timestamps_to_strings(income_quarterly_dict)
        except Exception:
            data["income_quarterly"] = None

        # ---------- 2. BALANCE SHEETS ----------
        try:
            balance_annual_dict = ticker.balance_sheet.to_dict() if ticker.balance_sheet is not None else None
            data["balance_annual"] = _convert_timestamps_to_strings(balance_annual_dict)
        except Exception:
            data["balance_annual"] = None

        try:
            balance_quarterly_dict = ticker.quarterly_balance_sheet.to_dict() if ticker.quarterly_balance_sheet is not None else None
            data["balance_quarterly"] = _convert_timestamps_to_strings(balance_quarterly_dict)
        except Exception:
            data["balance_quarterly"] = None

        # ---------- 3. CASH FLOW STATEMENTS ----------
        try:
            cashflow_annual_dict = ticker.cashflow.to_dict() if ticker.cashflow is not None else None
            data["cashflow_annual"] = _convert_timestamps_to_strings(cashflow_annual_dict)
        except Exception:
            data["cashflow_annual"] = None

        try:
            cashflow_quarterly_dict = ticker.quarterly_cashflow.to_dict() if ticker.quarterly_cashflow is not None else None
            data["cashflow_quarterly"] = _convert_timestamps_to_strings(cashflow_quarterly_dict)
        except Exception:
            data["cashflow_quarterly"] = None

        # ---------- 4. KEY STATISTICS ----------
        info = ticker.info or {}

        key_stats = FundamentalsKeyStats(
            symbol=info.get("symbol"),
            longName=info.get("longName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            marketCap=info.get("marketCap"),
            enterpriseValue=info.get("enterpriseValue"),
            trailingPE=info.get("trailingPE"),
            forwardPE=info.get("forwardPE"),
            pegRatio=info.get("pegRatio"),
            priceToBook=info.get("priceToBook"),
            priceToSales=info.get("priceToSalesTrailing12Months"),
            trailingEps=info.get("trailingEps"),
            forwardEps=info.get("forwardEps"),
            beta=info.get("beta"),
            profitMargins=info.get("profitMargins"),
            grossMargins=info.get("grossMargins"),
            operatingMargins=info.get("operatingMargins"),
            ebitdaMargins=info.get("ebitdaMargins"),
            returnOnEquity=info.get("returnOnEquity"),
            returnOnAssets=info.get("returnOnAssets"),
            debtToEquity=info.get("debtToEquity"),
            currentRatio=info.get("currentRatio"),
            quickRatio=info.get("quickRatio"),
            totalCash=info.get("totalCash"),
            totalDebt=info.get("totalDebt"),
            totalRevenue=info.get("totalRevenue"),
            revenueGrowth=info.get("revenueGrowth"),
            earningsGrowth=info.get("earningsGrowth"),
            dividendYield=info.get("dividendYield"),
            payoutRatio=info.get("payoutRatio"),
            fiftyTwoWeekHigh=info.get("fiftyTwoWeekHigh"),
            fiftyTwoWeekLow=info.get("fiftyTwoWeekLow"),
            currentPrice=info.get("currentPrice"),
        )

        # ---------- 5. EARNINGS HISTORY & ESTIMATES ----------
        # Past EPS surprises (actual vs estimate)
        try:
            earnings_history_dict = ticker.earnings_history.to_dict() if ticker.earnings_history is not None else None
            data["earnings_history"] = _convert_timestamps_to_strings(earnings_history_dict)
        except Exception:
            data["earnings_history"] = None

        # Forward-looking analyst estimates
        try:
            earnings_estimate_dict = ticker.earnings_estimate.to_dict() if ticker.earnings_estimate is not None else None
            data["earnings_estimate"] = _convert_timestamps_to_strings(earnings_estimate_dict)
            revenue_estimate_dict = ticker.revenue_estimate.to_dict() if ticker.revenue_estimate is not None else None
            data["revenue_estimate"] = _convert_timestamps_to_strings(revenue_estimate_dict)
            eps_trend_dict = ticker.eps_trend.to_dict() if ticker.eps_trend is not None else None
            data["eps_trend"] = _convert_timestamps_to_strings(eps_trend_dict)
            eps_revisions_dict = ticker.eps_revisions.to_dict() if ticker.eps_revisions is not None else None
            data["eps_revisions"] = _convert_timestamps_to_strings(eps_revisions_dict)
            growth_estimates_dict = ticker.growth_estimates.to_dict() if ticker.growth_estimates is not None else None
            data["growth_estimates"] = _convert_timestamps_to_strings(growth_estimates_dict)
        except Exception:
            pass

        # Upcoming earnings dates
        try:
            earnings_dates_dict = ticker.earnings_dates.to_dict() if ticker.earnings_dates is not None else None
            data["earnings_dates"] = _convert_timestamps_to_strings(earnings_dates_dict)
            next_earnings = info.get("earningsTimestamp")
            if next_earnings:
                data["next_earnings_date"] = datetime.fromtimestamp(next_earnings).strftime("%Y-%m-%d %H:%M")
            else:
                data["next_earnings_date"] = None
        except Exception:
            data["earnings_dates"] = None
            data["next_earnings_date"] = None

        # ---------- 6. ANALYST RECOMMENDATIONS & PRICE TARGETS ----------
        try:
            recommendations_dict = ticker.recommendations.to_dict() if ticker.recommendations is not None else None
            data["recommendations"] = _convert_timestamps_to_strings(recommendations_dict)
            recommendations_summary_dict = ticker.recommendations_summary.to_dict() if ticker.recommendations_summary is not None else None
            data["recommendations_summary"] = _convert_timestamps_to_strings(recommendations_summary_dict)
            upgrades_downgrades_dict = ticker.upgrades_downgrades.to_dict() if ticker.upgrades_downgrades is not None else None
            data["upgrades_downgrades"] = _convert_timestamps_to_strings(upgrades_downgrades_dict)
        except Exception:
            pass

        price_targets = FundamentalsPriceTargets(
            targetMean=info.get("targetMeanPrice"),
            targetMedian=info.get("targetMedianPrice"),
            targetHigh=info.get("targetHighPrice"),
            targetLow=info.get("targetLowPrice"),
            numAnalysts=info.get("numberOfAnalystOpinions"),
            recommendationKey=info.get("recommendationKey"),
            recommendationMean=info.get("recommendationMean"),
        )

        return FundamentalsResponse(
            symbol=symbol.upper(),
            key_stats=key_stats,
            price_targets=price_targets,
            income_annual=data.get("income_annual"),
            income_quarterly=data.get("income_quarterly"),
            balance_annual=data.get("balance_annual"),
            balance_quarterly=data.get("balance_quarterly"),
            cashflow_annual=data.get("cashflow_annual"),
            cashflow_quarterly=data.get("cashflow_quarterly"),
            earnings_history=data.get("earnings_history"),
            earnings_estimate=data.get("earnings_estimate"),
            revenue_estimate=data.get("revenue_estimate"),
            eps_trend=data.get("eps_trend"),
            eps_revisions=data.get("eps_revisions"),
            growth_estimates=data.get("growth_estimates"),
            earnings_dates=data.get("earnings_dates"),
            next_earnings_date=data.get("next_earnings_date"),
            recommendations=data.get("recommendations"),
            recommendations_summary=data.get("recommendations_summary"),
            upgrades_downgrades=data.get("upgrades_downgrades"),
        )

    except Exception as exc:
        logger.error(f"Failed to fetch fundamentals for {symbol}: {exc}")
        raise ValueError(f"Unable to fetch fundamentals for symbol '{symbol}': {str(exc)}")


def get_fundamentals(symbol: str) -> FundamentalsResponse:
    """Get fundamentals for a stock symbol with validation."""
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string")

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise ValueError("Symbol cannot be empty after trimming")

    return fetch_fundamentals(symbol_upper)
