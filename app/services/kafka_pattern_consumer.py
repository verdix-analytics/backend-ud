import logging

from app.services.kafka_pattern_candlestick_consumer import candlestick_pattern_consumer
from app.services.kafka_pattern_chart_consumer import chart_pattern_consumer
from app.services.kafka_pattern_harmonic_consumer import harmonic_pattern_consumer

logger = logging.getLogger(__name__)


class PatternConsumersManager:
    def __init__(self):
        self._consumers = {
            "candlestick": candlestick_pattern_consumer,
            "chart": chart_pattern_consumer,
            "harmonic": harmonic_pattern_consumer,
        }

    def start(self) -> None:
        for pattern_type, consumer in self._consumers.items():
            logger.info("Starting Kafka pattern consumer for type=%s", pattern_type)
            consumer.start()

    def stop(self) -> None:
        for pattern_type, consumer in self._consumers.items():
            logger.info("Stopping Kafka pattern consumer for type=%s", pattern_type)
            consumer.stop()

    def status(self) -> dict:
        per_type = {pattern_type: consumer.status() for pattern_type, consumer in self._consumers.items()}
        total_processed = sum(status["messages_processed"] for status in per_type.values())
        total_failed = sum(status["messages_failed"] for status in per_type.values())
        any_running = any(status["running"] for status in per_type.values())

        return {
            "running": any_running,
            "messages_processed": total_processed,
            "messages_failed": total_failed,
            "consumers": per_type,
            "last_error": next(
                (status["last_error"] for status in per_type.values() if status["last_error"]),
                None,
            ),
        }


pattern_consumer = PatternConsumersManager()

