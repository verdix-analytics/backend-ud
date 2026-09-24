import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TypeAlias
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models import Base, DetectedPattern, FinancialData1H, FinancialData1M, FinancialData1Y, Asset
from app.models.schemas import Candle, Pattern, TrendDirection
from app.services.cache_service import clear_stock_directory_cache, clear_instrument_cache

logger = logging.getLogger(__name__)

# Database engine and session factory
engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

FinancialDataModel: TypeAlias = FinancialData1H | FinancialData1M | FinancialData1Y

DETECTED_PATTERN_DEDUPE_COLUMNS = (
    "instrument",
    "category",
    "timeframe",
    "pattern",
    "window_start",
    "window_end",
)


def _normalize_timeframe(timeframe: str) -> str:
    return timeframe.strip().lower()


def _get_financial_model_for_timeframe(timeframe: str):
    normalized = _normalize_timeframe(timeframe)
    if normalized == "1h":
        return FinancialData1H
    if normalized == "1m":
        return FinancialData1M
    if normalized == "1y":
        return FinancialData1Y
    raise ValueError("Unsupported timeframe. Expected one of: 1h, 1m, 1y")


def init_db() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully")
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc)
        raise


def get_db_session() -> Session:
    return SessionLocal()


def _normalize_symbol(symbol: str) -> str:
    """Normalize stock symbol to uppercase."""
    return str(symbol).strip().upper()


def insert_or_update_stock(
    symbol: str,
    name: Optional[str] = None,
    exchange: Optional[str] = None,
    asset_class: Optional[str] = None,
) -> Asset:
    """
    Insert or update a stock record. If stock with given symbol already exists, update it.
    Otherwise, create a new record.

    Returns the stock record (either newly created or updated).
    """
    session = get_db_session()
    try:
        symbol_upper = _normalize_symbol(symbol)

        # Try to find existing stock by symbol
        existing_stock = session.query(Asset).filter(Asset.symbol == symbol_upper).first()

        if existing_stock:
            # Update existing stock record
            if name is not None:
                existing_stock.name = name.strip() if name else None
            if exchange is not None:
                existing_stock.exchange = exchange.strip() if exchange else None
            if asset_class is not None:
                existing_stock.asset_class = asset_class.strip() if asset_class else None
            existing_stock.updated_at = datetime.now(timezone.utc)
            session.commit()
            clear_stock_directory_cache()
            logger.debug(f"Updated stock record for symbol={symbol_upper}")
            return existing_stock
        else:
            # Create new stock record
            new_stock = Asset(
                symbol=symbol_upper,
                name=name.strip() if name else None,
                exchange=exchange.strip() if exchange else None,
                asset_class=asset_class.strip() if asset_class else None,
            )
            session.add(new_stock)
            session.commit()
            clear_stock_directory_cache()
            logger.debug(f"Created new stock record for symbol={symbol_upper}")
            return new_stock
    except Exception as exc:
        session.rollback()
        logger.error("Error inserting or updating stock (%s): %s", symbol, exc)
        raise
    finally:
        session.close()


def get_stock_directory_rows() -> list[dict[str, str]]:
    session = get_db_session()
    try:
        stmt = select(Asset.symbol, Asset.name, Asset.exchange, Asset.asset_class).order_by(Asset.symbol.asc())
        rows = session.execute(stmt).all()
        return [
            {
                "ticker": symbol,
                "name": asset_name.strip() if isinstance(asset_name, str) and asset_name.strip() else symbol,
                "exchange": exchange.strip() if isinstance(exchange, str) and exchange.strip() else "UNKNOWN",
                "assetClass": asset_class.strip() if isinstance(asset_class, str) and asset_class.strip() else None,
            }
            for symbol, asset_name, exchange, asset_class in rows
        ]
    except Exception as exc:
        logger.error("Error fetching stock directory rows: %s", exc)
        return []
    finally:
        session.close()


def insert_financial_price(
    timeframe: str,
    symbol: str,
    datetime_val: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: int,
    name: Optional[str] = None,
    exchange: Optional[str] = None,
    asset_class: Optional[str] = None,
) -> Optional[FinancialDataModel]:
    """
    Insert or update financial price data. Automatically creates or updates the associated stock record.
    """
    model = _get_financial_model_for_timeframe(timeframe)
    session = get_db_session()
    price: Optional[FinancialDataModel] = None
    try:
        symbol_upper = _normalize_symbol(symbol)

        # Insert or update stock first
        stock = insert_or_update_stock(
            symbol=symbol_upper,
            name=name,
            exchange=exchange,
            asset_class=asset_class,
        )

        # Check if record already exists
        existing = session.query(model).filter(
            model.asset_id == stock.id,
            model.ts == datetime_val,
        ).first()

        if existing:
            # Update existing record
            existing.open = open_price
            existing.high = high_price
            existing.low = low_price
            existing.close = close_price
            existing.volume = volume
            logger.debug(f"Updated financial price for {symbol_upper} at {datetime_val}")
        else:
            # Create new record
            price = model(
                asset_id=stock.id,
                ts=datetime_val,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
            session.add(price)
            logger.debug(
                "Inserted new financial price for %s at %s (%s)",
                symbol_upper,
                datetime_val,
                _normalize_timeframe(timeframe),
            )

        session.commit()
        if existing is not None:
            return existing
        if price is None:
            raise RuntimeError("Financial price insert did not produce a record")
        return price
    except Exception as exc:
        session.rollback()
        logger.error("Error inserting financial price (%s): %s", timeframe, exc)
        raise
    finally:
        session.close()


def bulk_insert_financial_prices(
    timeframe: str,
    data_list: list[dict[str, Any]],
) -> int:
    """
    Bulk insert or update financial price data. Automatically creates or updates associated stock records.
    Deduplicates entries based on (symbol, datetime_val) to prevent ON CONFLICT errors with duplicate rows.
    """
    if not data_list:
        return 0

    model = _get_financial_model_for_timeframe(timeframe)
    session = get_db_session()
    try:
        # Deduplicate data by (symbol, datetime_val) - keep the last occurrence
        seen = {}
        deduplicated_data = []
        for d in data_list:
            symbol = _normalize_symbol(d["symbol"])
            dt = d["datetime_val"]
            key = (symbol, dt)
            if key in seen:
                # Replace the previous occurrence with newer data
                deduplicated_data[seen[key]] = d
            else:
                seen[key] = len(deduplicated_data)
                deduplicated_data.append(d)

        # Collect unique symbols and their metadata
        symbol_metadata = {}
        for d in deduplicated_data:
            symbol = _normalize_symbol(d["symbol"])
            if symbol not in symbol_metadata:
                symbol_metadata[symbol] = {
                    "name": d.get("name"),
                    "exchange": d.get("exchange"),
                    "asset_class": d.get("asset_class"),
                }

        # Insert or update stocks
        stocks = {}
        for symbol, meta in symbol_metadata.items():
            stock = insert_or_update_stock(
                symbol=symbol,
                name=meta["name"],
                exchange=meta["exchange"],
                asset_class=meta["asset_class"],
            )
            stocks[symbol] = stock

        # Prepare rows for bulk insert
        rows = []
        for d in deduplicated_data:
            symbol = _normalize_symbol(d["symbol"])
            stock = stocks[symbol]
            rows.append({
                "asset_id": stock.id,
                "ts": d["datetime_val"],
                "open": d["open_price"],
                "high": d["high_price"],
                "low": d["low_price"],
                "close": d["close_price"],
                "volume": d["volume"],
            })

        if not rows:
            return 0

        # Perform bulk insert and ignore conflicts (do NOT update existing rows)
        table = model.__table__
        insert_stmt = pg_insert(table).values(rows)
        # On conflict of (asset_id, ts) do nothing -> skip existing records
        upsert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=["asset_id", "ts"])
        result = session.execute(upsert_stmt)
        session.commit()

        # Determine how many rows were actually inserted. rowcount may be -1/None
        # in some DBAPI implementations, so fall back to attempted count.
        try:
            inserted_count = int(result.rowcount) if result is not None and result.rowcount is not None and result.rowcount >= 0 else len(rows)
        except Exception:
            inserted_count = len(rows)

        # Clear cache for affected symbols
        for symbol in stocks.keys():
            clear_instrument_cache(symbol)

        logger.debug(
            "Bulk inserted %d financial prices for timeframe %s (attempted %d, deduplicated from %d)",
            inserted_count,
            _normalize_timeframe(timeframe),
            len(rows),
            len(data_list),
        )
        return inserted_count
    except Exception as exc:
        session.rollback()
        logger.error("Error bulk inserting financial prices (%s): %s", timeframe, exc)
        raise
    finally:
        session.close()


def get_financial_prices(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
    offset: int = 0,
) -> list[FinancialDataModel]:
    model = _get_financial_model_for_timeframe(timeframe)
    session = get_db_session()
    try:
        symbol_upper = _normalize_symbol(symbol)

        # Find stock by symbol
        stock = session.query(Asset).filter(Asset.symbol == symbol_upper).first()
        if stock is None:
            logger.debug("Stock not found for symbol=%s", symbol_upper)
            return []

        stmt = (
            select(model)
            .where(model.asset_id == stock.id)
            .order_by(model.ts.desc())
            .limit(limit)
            .offset(offset)
        )
        results = session.execute(stmt).scalars().all()
        # Reverse to get chronological order
        return list(reversed(results))
    except Exception as exc:
        logger.error("Error fetching financial prices for %s (%s): %s", symbol, timeframe, exc)
        return []
    finally:
        session.close()


def get_candles_from_db(symbol: str, timeframe: str = "1h", limit: int = 100) -> list[Candle]:
    financial_prices = get_financial_prices(symbol=symbol, timeframe=timeframe, limit=limit)
    return [
        Candle(
            timestamp=fp.ts,
            open=fp.open,
            high=fp.high,
            low=fp.low,
            close=fp.close,
            volume=float(fp.volume),
        )
        for fp in financial_prices
    ]


def delete_old_prices(symbol: str, timeframe: str = "1h", keep_days: int = 365) -> int:
    model = _get_financial_model_for_timeframe(timeframe)
    session = get_db_session()
    try:
        symbol_upper = _normalize_symbol(symbol)

        # Find stock by symbol
        stock = session.query(Asset).filter(Asset.symbol == symbol_upper).first()
        if stock is None:
            logger.debug("Stock not found for symbol=%s", symbol_upper)
            return 0

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=keep_days)
        stmt = select(model).where(
            model.asset_id == stock.id,
            model.ts < cutoff_date,
        )
        records = session.execute(stmt).scalars().all()
        for record in records:
            session.delete(record)
        session.commit()
        logger.info(
            "Deleted %d records for %s (%s) older than %d days",
            len(records),
            symbol,
            _normalize_timeframe(timeframe),
            keep_days,
        )
        return len(records)
    except Exception as exc:
        session.rollback()
        logger.error("Error deleting old prices for %s (%s): %s", symbol, timeframe, exc)
        return 0
    finally:
        session.close()


def _derive_pattern_type(pattern_name: str) -> str:
    lowered = pattern_name.lower()
    if "bullish" in lowered:
        return "bullish"
    if "bearish" in lowered:
        return "bearish"
    return pattern_name.split(" ", 1)[0].lower()


def _dedupe_detected_pattern_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate rows by detected-pattern conflict key while keeping batch order stable."""
    seen_indexes: dict[tuple[Any, ...], int] = {}
    deduped_rows: list[dict[str, Any]] = []

    for row in rows:
        key = tuple(row.get(column) for column in DETECTED_PATTERN_DEDUPE_COLUMNS)
        existing_index = seen_indexes.get(key)
        if existing_index is None:
            seen_indexes[key] = len(deduped_rows)
            deduped_rows.append(row)
        else:
            # Last row wins for duplicate keys in the same upsert batch.
            deduped_rows[existing_index] = row

    return deduped_rows


def _upsert_detected_patterns_rows(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    deduped_rows = _dedupe_detected_pattern_rows(rows)
    if not deduped_rows:
        return 0

    table = DetectedPattern.__table__
    insert_stmt = pg_insert(table).values(deduped_rows)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=list(DETECTED_PATTERN_DEDUPE_COLUMNS),
        set_={
            "analysis_id": insert_stmt.excluded.analysis_id,
            "detected_at": insert_stmt.excluded.detected_at,
            "pattern_type": insert_stmt.excluded.pattern_type,
            "confidence": insert_stmt.excluded.confidence,
            "confirmed": insert_stmt.excluded.confirmed,
            "structure_detected": insert_stmt.excluded.structure_detected,
            "signal": insert_stmt.excluded.signal,
            # Preserve existing context_score if new value is NULL
            "context_score": func.coalesce(insert_stmt.excluded.context_score, table.c.context_score),
            "pre_trend": insert_stmt.excluded.pre_trend,
            "post_trend": insert_stmt.excluded.post_trend,
        },
    )
    session.execute(upsert_stmt)
    return len(deduped_rows)


def insert_detected_patterns(
    analysis_id: str,
    instrument: str,
    timeframe: str,
    patterns: list[Pattern],
    pre_trend: TrendDirection,
    post_trend: TrendDirection,
) -> int:
    if not patterns:
        return 0

    session = get_db_session()
    try:
        rows: list[dict[str, Any]] = []
        for pattern in patterns:
            category = str(pattern.type.value)
            window_start = int(pattern.metadata.get("window_start", 0))
            window_end = int(pattern.metadata.get("window_end", window_start))
            confidence = float(pattern.confidence)
            confirmed = bool(pattern.metadata.get("confirmed", True))
            structure_detected = bool(pattern.metadata.get("structure_detected", confirmed))
            pattern_type = str(pattern.metadata.get("pattern_type", _derive_pattern_type(pattern.name)))

            signal_payload = {
                "confirmed": confirmed,
                "structure_detected": structure_detected,
                "confidence": confidence,
                "confidence_breakdown": pattern.metadata.get("confidence_breakdown", {}),
                "confidence_metadata": pattern.metadata.get("confidence_metadata", {}),
            }
            context_score_payload = pattern.metadata.get("context_score")
            if not isinstance(context_score_payload, dict):
                context_score_payload = None

            pre_trend_payload = {
                "label": pattern.metadata.get("pretrend_label") or pre_trend.value,
                "strength": pattern.metadata.get("pretrend_strength"),
            }
            post_trend_payload = {
                "label": pattern.metadata.get("posttrend_label") or post_trend.value,
                "strength": pattern.metadata.get("post_trend_strength"),
                "realized_move_pct": pattern.metadata.get("realized_move_pct"),
            }

            rows.append(
                {
                    "analysis_id": analysis_id,
                    "instrument": instrument,
                    "timeframe": timeframe,
                    "detected_at": pattern.end_time,
                    "pattern": pattern.name,
                    "category": category,
                    "pattern_type": pattern_type,
                    "window_start": window_start,
                    "window_end": window_end,
                    "confidence": confidence,
                    "confirmed": confirmed,
                    "structure_detected": structure_detected,
                    "signal": signal_payload,
                    "context_score": context_score_payload,
                    "pre_trend": pre_trend_payload,
                    "post_trend": post_trend_payload,
                }
            )

        upserted_count = _upsert_detected_patterns_rows(session, rows)
        session.commit()
        logger.debug("Upserted %d detected patterns for %s", upserted_count, instrument)
        return upserted_count
    except Exception as exc:
        session.rollback()
        logger.error("Error inserting detected patterns: %s", exc)
        raise
    finally:
        session.close()


def _parse_detected_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _default_pattern_timeframe_for_category(category: str) -> str:
    normalized = category.strip().lower()
    if normalized == "harmonic":
        return "1y"
    if normalized == "chart":
        return "1h"
    if normalized == "candlestick":
        return "1m"
    return "1h"


def insert_detected_patterns_from_kafka_payload(payload: dict[str, Any]) -> int:
    instrument = str(payload.get("stock_ticker") or payload.get("instrument") or "").strip().upper()
    if not instrument:
        raise ValueError("Kafka pattern payload missing stock_ticker/instrument")

    category = str(payload.get("pattern_type") or payload.get("category") or "").strip().lower()
    if not category:
        raise ValueError("Kafka pattern payload missing pattern_type/category")

    result = payload.get("result")
    if not isinstance(result, dict):
        logger.debug("Pattern payload for %s has no valid result payload", instrument)
        return 0

    default_analysis_id = str(payload.get("analysis_id") or f"kafka-{category}-{uuid4().hex}")
    root_context_score = payload.get("context_score") if isinstance(payload.get("context_score"), dict) else None

    session = get_db_session()
    try:
        pattern_name = str(result.get("pattern") or "").strip()
        if not pattern_name:
            logger.warning("Skipping pattern result without pattern name for %s", instrument)
            return 0

        entry_category = str(result.get("category") or category).strip().lower() or category
        entry_timeframe = _default_pattern_timeframe_for_category(entry_category)
        signal_payload = result.get("signal") if isinstance(result.get("signal"), dict) else {}
        context_score_payload = root_context_score
        pre_trend_payload = result.get("pre_trend") if isinstance(result.get("pre_trend"), dict) else {}
        post_trend_payload = result.get("post_trend") if isinstance(result.get("post_trend"), dict) else {}

        confirmed = bool(result.get("confirmed", signal_payload.get("confirmed", True)))
        confidence = float(result.get("confidence", signal_payload.get("confidence", 0.0)))
        structure_detected = bool(signal_payload.get("structure_detected", confirmed))

        window_start_raw = result.get("window_start", 0)
        window_end_raw = result.get("window_end", window_start_raw if window_start_raw is not None else 0)

        window_start = int(window_start_raw) if window_start_raw is not None else 0
        window_end = int(window_end_raw) if window_end_raw is not None else window_start

        row_analysis_id = str(result.get("analysis_id") or default_analysis_id)
        detected_at = _parse_detected_at(
            result.get("detected_at")
            or result.get("timestamp")
            or payload.get("detected_at")
            or payload.get("timestamp")
        )

        row = {
            "analysis_id": row_analysis_id,
            "instrument": instrument,
            "timeframe": entry_timeframe,
            "detected_at": detected_at,
            "pattern": pattern_name,
            "category": entry_category,
            "pattern_type": str(result.get("pattern_type") or category),
            "window_start": window_start,
            "window_end": window_end,
            "confidence": confidence,
            "confirmed": confirmed,
            "structure_detected": structure_detected,
            "signal": signal_payload,
            "context_score": context_score_payload,
            "pre_trend": pre_trend_payload,
            "post_trend": post_trend_payload,
        }

        upserted_count = _upsert_detected_patterns_rows(session, [row])
        session.commit()
        logger.debug("Upserted %d kafka detected patterns for %s (%s)", upserted_count, instrument, category)
        return upserted_count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def bulk_insert_detected_patterns_from_kafka_payloads(payloads: list[dict[str, Any]]) -> int:
    """
    Bulk insert detected patterns from Kafka payloads.
    """
    if not payloads:
        return 0

    session = get_db_session()
    try:
        rows: list[dict[str, Any]] = []
        for payload in payloads:
            instrument = str(payload.get("stock_ticker") or payload.get("instrument") or "").strip().upper()
            if not instrument:
                logger.warning("Skipping pattern payload missing stock_ticker/instrument")
                continue

            category = str(payload.get("pattern_type") or payload.get("category") or "").strip().lower()
            if not category:
                logger.warning("Skipping pattern payload missing pattern_type/category for %s", instrument)
                continue

            result = payload.get("result")
            if not isinstance(result, dict):
                logger.debug("Pattern payload for %s has no valid result payload", instrument)
                continue

            pattern_name = str(result.get("pattern") or "").strip()
            if not pattern_name:
                logger.warning("Skipping pattern result without pattern name for %s", instrument)
                continue

            default_analysis_id = str(payload.get("analysis_id") or f"kafka-{category}-{uuid4().hex}")
            root_context_score = payload.get("context_score") if isinstance(payload.get("context_score"), dict) else None

            entry_category = str(result.get("category") or category).strip().lower() or category
            entry_timeframe = _default_pattern_timeframe_for_category(entry_category)
            signal_payload = result.get("signal") if isinstance(result.get("signal"), dict) else {}
            context_score_payload = root_context_score
            pre_trend_payload = result.get("pre_trend") if isinstance(result.get("pre_trend"), dict) else {}
            post_trend_payload = result.get("post_trend") if isinstance(result.get("post_trend"), dict) else {}

            confirmed = bool(result.get("confirmed", signal_payload.get("confirmed", True)))
            confidence = float(result.get("confidence", signal_payload.get("confidence", 0.0)))
            structure_detected = bool(signal_payload.get("structure_detected", confirmed))

            window_start_raw = result.get("window_start", 0)
            window_end_raw = result.get("window_end", window_start_raw if window_start_raw is not None else 0)

            window_start = int(window_start_raw) if window_start_raw is not None else 0
            window_end = int(window_end_raw) if window_end_raw is not None else window_start

            row_analysis_id = str(result.get("analysis_id") or default_analysis_id)
            detected_at = _parse_detected_at(
                result.get("detected_at")
                or result.get("timestamp")
                or payload.get("detected_at")
                or payload.get("timestamp")
            )

            rows.append({
                "analysis_id": row_analysis_id,
                "instrument": instrument,
                "timeframe": entry_timeframe,
                "detected_at": detected_at,
                "pattern": pattern_name,
                "category": entry_category,
                "pattern_type": str(result.get("pattern_type") or category),
                "window_start": window_start,
                "window_end": window_end,
                "confidence": confidence,
                "confirmed": confirmed,
                "structure_detected": structure_detected,
                "signal": signal_payload,
                "context_score": context_score_payload,
                "pre_trend": pre_trend_payload,
                "post_trend": post_trend_payload,
            })

        if rows:
            upserted_count = _upsert_detected_patterns_rows(session, rows)
            session.commit()
            logger.debug("Bulk upserted %d kafka detected patterns", upserted_count)
            return upserted_count
        return 0
    except Exception as exc:
        session.rollback()
        logger.error("Error bulk inserting detected patterns: %s", exc)
        raise
    finally:
        session.close()


def get_detected_patterns(
    category: str, instrument: str, days_lookback: Optional[int] = None
) -> list[DetectedPattern]:
    if days_lookback is None:
        category_lower = category.lower()
        if category_lower == "candlestick":
            days_lookback = settings.pattern_lookback_candlestick_days
        elif category_lower == "chart":
            days_lookback = settings.pattern_lookback_chart_days
        elif category_lower == "harmonic":
            days_lookback = settings.pattern_lookback_harmonic_days
        else:
            days_lookback = 30

    session = get_db_session()
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_lookback)
        stmt = (
            select(DetectedPattern)
            .where(
                DetectedPattern.instrument == instrument.upper(),
                DetectedPattern.category == category.lower(),
                DetectedPattern.detected_at >= cutoff_date,
            )
            .order_by(DetectedPattern.detected_at.desc())
        )
        results = session.execute(stmt).scalars().all()
        logger.debug(
            "Retrieved %d detected patterns for %s (%s) from last %d days",
            len(results),
            instrument,
            category,
            days_lookback,
        )
        return results
    except Exception as exc:
        logger.error(
            "Error fetching detected patterns for %s (%s): %s", instrument, category, exc
        )
        return []
    finally:
        session.close()


def search_stock(query: str, timeframe: str = "1h") -> Optional[dict]:
    """
    Search for a stock by ticker symbol.
    Returns stock information if found, None otherwise.
    """
    if not query:
        return None

    session = get_db_session()
    try:
        symbol_upper = query.upper().strip()
        
        # Query for the stock by symbol
        stock = session.query(Asset).filter(Asset.symbol == symbol_upper).first()

        if stock is None:
            logger.debug("Stock search: %s not found", symbol_upper)
            return None
        
        # Return stock information
        stock_info = {
            "ticker": stock.symbol,
            "companyName": stock.name or symbol_upper,
            "exchange": stock.exchange or "UNKNOWN",
            "isValid": True,
        }
        
        logger.debug(
            "Stock search: Found %s - %s",
            symbol_upper,
            stock.name,
        )
        return stock_info
    except Exception as exc:
        logger.error("Error searching for stock %s: %s", query, exc)
        return None
    finally:
        session.close()


def get_pattern_signals_by_ticker_and_category(
    ticker: str,
    category: str,
) -> list[dict[str, Any]]:
    """
    Fetch pattern signal rows for a ticker/category pair.

    Returned keys per row:
    - stock_ticker
    - stock_name
    - pattern_name
    - pattern_category
    - signal_direction
    - confidence_score
    - created_at
    """
    ticker_upper = ticker.strip().upper()
    category_lower = category.strip().lower()
    if not ticker_upper or not category_lower:
        return []

    session = get_db_session()
    try:
        stmt = text(
            """
            SELECT
                dp.instrument AS stock_ticker,
                COALESCE(s.name, dp.instrument) AS stock_name,
                dp.pattern AS pattern_name,
                dp.category AS pattern_category,
                COALESCE(
                    dp.signal ->> 'direction',
                    NULLIF(dp.pattern_type, ''),
                    CASE
                        WHEN LOWER(dp.pattern) LIKE '%bullish%' THEN 'bullish'
                        WHEN LOWER(dp.pattern) LIKE '%bearish%' THEN 'bearish'
                        ELSE 'neutral'
                    END
                ) AS signal_direction,
                dp.confidence AS confidence_score,
                dp.detected_at AS created_at
            FROM detected_patterns AS dp
            LEFT JOIN assets AS s
                ON s.symbol = dp.instrument
            WHERE dp.instrument = :ticker
              AND dp.category = :category
            ORDER BY dp.detected_at DESC
            """
        )

        rows = session.execute(
            stmt,
            {
                "ticker": ticker_upper,
                "category": category_lower,
            },
        ).mappings().all()

        return [dict(row) for row in rows]
    except Exception as exc:
        logger.error(
            "Error fetching pattern signals for %s (%s): %s",
            ticker_upper,
            category_lower,
            exc,
        )
        return []
    finally:
        session.close()
