import json
import logging
from typing import Any, Optional

from confluent_kafka import Producer, KafkaError

from app.core.config import settings

logger = logging.getLogger(__name__)


class KafkaProducerService:

    def __init__(self):
        self.producer: Optional[Producer] = None
        self._initialize_producer()

    def _initialize_producer(self) -> None:
        if not settings.kafka_enabled:
            logger.warning("Kafka is disabled in settings")
            return

        try:
            conf = {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
            }
            self.producer = Producer(conf)
            logger.info("Kafka producer initialized with bootstrap_servers=%s", settings.kafka_bootstrap_servers)
        except Exception as exc:
            logger.error("Failed to initialize Kafka producer: %s", exc)
            self.producer = None

    def produce_message(
        self,
        topic: str,
        value: dict[str, Any],
        key: Optional[str] = None,
    ) -> bool:
        if not settings.kafka_enabled:
            logger.warning("Kafka is disabled, skipping message production")
            return False

        if self.producer is None:
            logger.error("Kafka producer not initialized")
            return False

        try:
            message_value = json.dumps(value)
            self.producer.produce(
                topic=topic,
                value=message_value.encode("utf-8"),
                key=key.encode("utf-8") if key else None,
                callback=self._delivery_report,
            )
            self.producer.flush()
            logger.debug("Produced message to topic=%s with key=%s", topic, key)
            return True
        except Exception as exc:
            logger.error("Error producing message to topic=%s: %s", topic, exc)
            return False

    @staticmethod
    def _delivery_report(err: Optional[KafkaError], msg) -> None:
        if err is not None:
            logger.error("Message delivery failed: %s", err)
        else:
            logger.debug("Message delivered to %s [%d]", msg.topic(), msg.partition())


kafka_producer = KafkaProducerService()

