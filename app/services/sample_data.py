from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import random

from app.models.schemas import Candle


def generate_sample_candles(count: int = 50, start_price: float = 100.0) -> list[Candle]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    candles: list[Candle] = []
    price = start_price

    for i in range(count):
        ts = now - timedelta(hours=count - i)
        drift = (random() - 0.45) * 1.2

        open_price = price
        close_price = max(1.0, open_price + drift)
        high_price = max(open_price, close_price) + random() * 0.6
        low_price = min(open_price, close_price) - random() * 0.6

        candles.append(
            Candle(
                timestamp=ts,
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=round(1000000 + random() * 300000, 2),
            )
        )
        price = close_price

    return candles
