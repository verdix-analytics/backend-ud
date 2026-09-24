import logging

from app.services.kafka_financial_1h_consumer import financial_price_1h_consumer
from app.services.kafka_financial_1m_consumer import financial_price_1m_consumer
from app.services.kafka_financial_1y_consumer import financial_price_1y_consumer

logger = logging.getLogger(__name__)


class FinancialPriceConsumersManager:
    def __init__(self):
        self._consumers = {
            "1h": financial_price_1h_consumer,
            "1m": financial_price_1m_consumer,
            "1y": financial_price_1y_consumer,
        }

    def start(self) -> None:
        for timeframe, consumer in self._consumers.items():
            logger.info("Starting Kafka consumer for timeframe=%s", timeframe)
            consumer.start()

    def stop(self) -> None:
        for timeframe, consumer in self._consumers.items():
            logger.info("Stopping Kafka consumer for timeframe=%s", timeframe)
            consumer.stop()

    def status(self) -> dict:
        per_timeframe = {timeframe: consumer.status() for timeframe, consumer in self._consumers.items()}
        total_processed = sum(status["messages_processed"] for status in per_timeframe.values())
        total_failed = sum(status["messages_failed"] for status in per_timeframe.values())
        any_running = any(status["running"] for status in per_timeframe.values())

        return {
            "running": any_running,
            "messages_processed": total_processed,
            "messages_failed": total_failed,
            "consumers": per_timeframe,
            "last_error": next(
                (status["last_error"] for status in per_timeframe.values() if status["last_error"]),
                None,
            ),
        }


financial_price_consumer = FinancialPriceConsumersManager()

