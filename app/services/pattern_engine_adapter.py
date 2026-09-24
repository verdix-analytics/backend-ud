from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import re
import sys
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.schemas import Candle, Pattern, PatternType

logger = logging.getLogger(__name__)
_version_warning_emitted = False

_CATEGORY_TO_PATTERN_TYPE: dict[str, PatternType] = {
    "chart": PatternType.CHART,
    "candlestick": PatternType.CANDLESTICK,
    "harmonic": PatternType.HARMONIC,
}

_CATEGORY_DEFAULT_WINDOWS: dict[str, int] = {
    "chart": 30,
    "candlestick": 3,
    "harmonic": 25,
}

_PRE_TREND_WINDOW = 20
_POST_TREND_WINDOW = 20

_POSITIVE_HINTS = {
    "Bullish",
    "Hammer",
    "Morning Star",
    "Ascending Triangle",
    "Double Bottom",
}

_NEGATIVE_HINTS = {
    "Bearish",
    "Shooting Star",
    "Evening Star",
    "Descending Triangle",
    "Head And Shoulders",
    "Double Top",
}


def _resolve_cs50_root() -> Path:
    if settings.cs50_engine_path:
        return Path(settings.cs50_engine_path).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[2]
    return (project_root / "CS50-analysis-main").resolve()


def _ensure_cs50_import_path(cs50_root: Path) -> None:
    root_str = str(cs50_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def _load_pattern_windows(cs50_root: Path) -> dict[str, int]:
    windows_path = cs50_root / "Utils_data" / "window_size.json"
    try:
        data = json.loads(windows_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Unable to load CS50 window_size.json: %s", exc)
        return {}

    patterns = data.get("patterns", {})
    if not isinstance(patterns, dict):
        return {}

    parsed: dict[str, int] = {}
    for key, value in patterns.items():
        if isinstance(key, str) and isinstance(value, int) and value > 0:
            parsed[key] = value
    return parsed


def _normalize_class_name(class_name: str) -> str:
    normalized = class_name
    for suffix in ("CandlestickPattern", "ChartPattern", "HarmonicPattern", "Pattern"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _humanize_name(class_name: str) -> str:
    token = _normalize_class_name(class_name)
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token)
    return token.strip()


def _humanize_file_stem(stem: str) -> str:
    token = stem
    for suffix in ("_Candlestick", "_Chart", "_Harmonic"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    token = token.replace("_", " ")
    token = re.sub(r"\s+", " ", token).strip()
    return token


def get_pattern_catalog() -> dict[str, list[str]]:
    cs50_root = _resolve_cs50_root()
    base = cs50_root / "stock_analysis"

    categories = {
        "candlestick": base / "candlestick_patterns",
        "chart": base / "chart_patterns",
        "harmonic": base / "harmonic_patterns",
    }

    catalog: dict[str, list[str]] = {"candlestick": [], "chart": [], "harmonic": []}
    for category, folder in categories.items():
        if not folder.exists():
            continue

        names: list[str] = []
        for path in sorted(folder.glob("*.py")):
            stem = path.stem
            if stem.startswith("__") or "dummy" in stem.lower():
                continue
            names.append(_humanize_file_stem(stem))

        catalog[category] = names

    return catalog


def get_pattern_engine_status() -> dict[str, Any]:
    cs50_root = _resolve_cs50_root()

    return {
        "enabled": settings.cs50_engine_enabled,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_compatible": sys.version_info >= (3, 10),
        "cs50_root": str(cs50_root),
        "cs50_root_exists": cs50_root.exists(),
    }


def _infer_alignment(name: str) -> int:
    if any(hint in name for hint in _POSITIVE_HINTS):
        return 1
    if any(hint in name for hint in _NEGATIVE_HINTS):
        return -1
    return 0


def _to_dataframe(candles: list[Candle]):
    import pandas as pd  # type: ignore[import-not-found]

    rows: list[dict[str, Any]] = []
    for c in candles:
        rows.append(
            {
                "Datetime": c.timestamp,
                "Open": c.open,
                "High": c.high,
                "Low": c.low,
                "Close": c.close,
                "Volume": c.volume,
            }
        )
    return pd.DataFrame(rows)


def _load_pattern_instances() -> list[Any]:
    base_module = importlib.import_module("stock_analysis.base")
    BasePattern = getattr(base_module, "BasePattern")

    instances: list[Any] = []
    packages = [
        "stock_analysis.chart_patterns",
        "stock_analysis.candlestick_patterns",
        "stock_analysis.harmonic_patterns",
    ]

    for package_name in packages:
        package = importlib.import_module(package_name)
        for _, module_name, _ in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package_name}.{module_name}")
            for attribute in dir(module):
                attr = getattr(module, attribute)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BasePattern)
                    and attr is not BasePattern
                    and getattr(attr, "enabled", False)
                ):
                    instances.append(attr())

    return instances


def detect_patterns_from_adapter(candles: list[Candle]) -> list[Pattern]:
    global _version_warning_emitted

    if not settings.cs50_engine_enabled:
        return []

    if sys.version_info < (3, 10):
        if not _version_warning_emitted:
            logger.warning("CS50 engine requires Python 3.10+; adapter unavailable")
            _version_warning_emitted = True
        return []

    cs50_root = _resolve_cs50_root()
    if not cs50_root.exists():
        logger.warning("CS50 engine path does not exist: %s", cs50_root)
        return []

    try:
        _ensure_cs50_import_path(cs50_root)
        df = _to_dataframe(candles)
        windows = _load_pattern_windows(cs50_root)
        instances = _load_pattern_instances()
    except ImportError as exc:
        logger.warning("CS50 engine dependencies unavailable: %s", exc)
        return []
    except Exception as exc:
        logger.warning("CS50 engine init failed: %s", exc)
        return []

    total = len(df)
    detections: list[Pattern] = []

    for pattern in instances:
        category = str(getattr(pattern, "category", "")).lower()
        pattern_type = _CATEGORY_TO_PATTERN_TYPE.get(category)
        if pattern_type is None:
            continue

        class_name = pattern.__class__.__name__
        if "Dummy" in class_name:
            continue

        window_size = windows.get(class_name, _CATEGORY_DEFAULT_WINDOWS.get(category, 20))

        required = _PRE_TREND_WINDOW + window_size + _POST_TREND_WINDOW
        if total < required:
            continue

        start = total - _POST_TREND_WINDOW - window_size
        end = total - _POST_TREND_WINDOW
        if start < 0 or end <= start:
            continue

        window_df = df.iloc[start:end].reset_index(drop=True)

        # Pre-trend slice (candles immediately before the pattern window)
        pre_start = max(0, start - _PRE_TREND_WINDOW)
        pre_df = df.iloc[pre_start:start].reset_index(drop=True)

        # Post-trend slice (candles immediately after the pattern window)
        post_end = min(total, end + _POST_TREND_WINDOW)
        post_df = df.iloc[end:post_end].reset_index(drop=True)

        pre_trend_dict: dict | None = None
        post_trend_dict: dict | None = None
        try:
            from stock_analysis.trendanalysis import TrendAnalysis as _TrendAnalysis
            _ta = _TrendAnalysis()
            if not pre_df.empty:
                pre_trend_dict = _ta.pre_trend_analysis(pre_df)
        except Exception as exc:
            logger.debug("TrendAnalysis unavailable: %s", exc)

        try:
            result = pattern.execute(window_df, pre_trend=pre_trend_dict)
        except Exception:
            continue

        if not result.confirmed:
            continue

        try:
            from stock_analysis.trendanalysis import TrendAnalysis as _TrendAnalysis
            _ta = _TrendAnalysis()
            if not post_df.empty:
                signal_dict = {"confirmed": result.confirmed, "confidence": result.confidence}
                post_trend_dict = _ta.post_trend_analysis(post_df, signal=signal_dict)
        except Exception as exc:
            logger.debug("Post TrendAnalysis unavailable: %s", exc)

        readable_name = _humanize_name(class_name)
        start_time = candles[start].timestamp
        end_time = candles[end - 1].timestamp

        detections.append(
            Pattern(
                name=readable_name,
                type=pattern_type,
                confidence=round(float(result.confidence), 2),
                start_time=start_time,
                end_time=end_time,
                trend_alignment=_infer_alignment(readable_name),
                metadata={
                    "source": "cs50",
                    "window_start": int(start),
                    "window_end": int(end),
                    "window_size": int(window_size),
                    "category": category,
                    "pretrend_label": pre_trend_dict.get("label") if pre_trend_dict else None,
                    "pretrend_strength": pre_trend_dict.get("strength") if pre_trend_dict else None,
                    "posttrend_label": post_trend_dict.get("label") if post_trend_dict else None,
                    "posttrend_strength": post_trend_dict.get("strength") if post_trend_dict else None,
                    "realized_move_pct": post_trend_dict.get("realized_move_pct") if post_trend_dict else None,
                },
            )
        )

    return sorted(detections, key=lambda p: (p.end_time, p.confidence), reverse=True)


# Backward-compatible wrappers (can be removed after downstream references are migrated)
def get_cs50_pattern_catalog() -> dict[str, list[str]]:
    return get_pattern_catalog()


def get_cs50_engine_status() -> dict[str, Any]:
    return get_pattern_engine_status()


def detect_patterns_cs50(candles: list[Candle]) -> list[Pattern]:
    return detect_patterns_from_adapter(candles)
