from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import ValidationError

from app.core.config import settings
from app.models.schemas import AnalyzeRequest, Candle
from app.services.analysis_engine import run_analysis
from app.services.database_service import get_candles_from_db, delete_old_prices, insert_financial_price
from app.services.sample_data import generate_sample_candles

logger = logging.getLogger(__name__)


class PeriodicIngestionWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self.last_run_at: Optional[datetime] = None
        self.last_success_at: Optional[datetime] = None
        self.last_error: Optional[str] = None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": settings.scheduler_enabled,
            "running": self._task is not None and not self._task.done(),
            "interval_minutes": settings.scheduler_interval_minutes,
            "instruments": settings.scheduler_instruments,
            "last_run_at": self.last_run_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }

    async def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("Periodic ingestion scheduler is disabled")
            return

        if self._task and not self._task.done():
            return

        self._task = asyncio.create_task(self._run_loop(), name="periodic-ingestion-worker")
        logger.info("Started periodic ingestion scheduler")

    async def stop(self) -> None:
        if not self._task:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("Stopped periodic ingestion scheduler")

    async def run_once(self) -> None:
        self.last_run_at = datetime.now(timezone.utc)

        for instrument in settings.scheduler_instruments:
            candles = await self._get_candles(instrument)

            # Persist OHLC candles to DB (financial_1h table)
            for candle in candles:
                try:
                    await asyncio.to_thread(
                        insert_financial_price,
                        "1h",
                        instrument,
                        candle.timestamp,
                        candle.open,
                        candle.high,
                        candle.low,
                        candle.close,
                        int(candle.volume or 0),
                    )
                except Exception as exc:
                    logger.warning("Failed to persist candle for %s at %s: %s", instrument, candle.timestamp, exc)

            request = AnalyzeRequest(
                instrument=instrument,
                timeframe=settings.timeframe,
                candles=candles,
                use_sample_data=False,
            )
            run_analysis(request)
            try:
                delete_old_prices(instrument, timeframe="1h")
            except Exception as exc:
                logger.warning("delete_old_prices failed for %s: %s", instrument, exc)

        self.last_success_at = datetime.now(timezone.utc)
        self.last_error = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception as exc:  # pragma: no cover
                self.last_error = str(exc)
                logger.exception("Periodic ingestion cycle failed: %s", exc)

            await asyncio.sleep(max(settings.scheduler_interval_minutes, 1) * 60)

    async def _get_candles(self, instrument: str) -> list[Candle]:
        # Priority 1: live data already ingested into DB via Kafka
        if not settings.scheduler_use_sample_data:
            try:
                db_candles = await asyncio.to_thread(
                    get_candles_from_db, instrument, "1h", settings.scheduler_sample_count
                )
                if len(db_candles) >= 20:
                    logger.debug(
                        "Using %d candles from DB for %s", len(db_candles), instrument
                    )
                    return db_candles
            except Exception as exc:
                logger.warning("DB candle fetch failed for %s: %s", instrument, exc)

        # Priority 2: external API
        if not settings.scheduler_use_sample_data and settings.source_api_url:
            try:
                return await asyncio.to_thread(self._fetch_candles_from_api, instrument)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch candles from API for %s. Falling back to sample data. Error: %s",
                    instrument,
                    exc,
                )

        # Priority 3: sample data fallback
        return generate_sample_candles(settings.scheduler_sample_count)

    def _fetch_candles_from_api(self, instrument: str) -> list[Candle]:
        query = urlencode(
            {
                "instrument": instrument,
                "timeframe": settings.timeframe,
                "limit": settings.scheduler_sample_count,
            }
        )
        url = f"{settings.source_api_url}?{query}"

        with urlopen(url, timeout=settings.source_api_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        raw_candles = payload.get("candles") if isinstance(payload, dict) else payload
        if not isinstance(raw_candles, list):
            raise ValueError("Source API response must contain a candle list")

        candles: list[Candle] = []
        for item in raw_candles:
            try:
                candles.append(Candle.model_validate(item))
            except ValidationError as exc:
                raise ValueError(f"Invalid candle payload: {exc}") from exc

        if len(candles) < 20:
            raise ValueError("Source API returned fewer than 20 candles")

        return candles


periodic_ingestion_worker = PeriodicIngestionWorker()
