import json
import logging
import threading
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from app.core.config import settings
from app.services.cache_service import clear_instrument_cache
from app.services.database_service import (
    insert_detected_patterns_from_kafka_payload,
    bulk_insert_detected_patterns_from_kafka_payloads,
)

logger = logging.getLogger(__name__)


class BasePatternConsumer:
    def __init__(self, topic: str, group_id: str, pattern_type: str, batch_size: int = 5, flush_interval: float = 10.0):
        self.topic = topic
        self.group_id = group_id
        self.pattern_type = pattern_type
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.consumer: Optional[Consumer] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None
        self.messages_processed = 0
        self.messages_failed = 0

        logger.info(
            "Initialized %s consumer for topic=%s group_id=%s batch_size=%s flush_interval=%ss",
            self.pattern_type,
            self.topic,
            self.group_id,
            self.batch_size,
            self.flush_interval,
        )

    def _create_consumer(self) -> Consumer:
        conf = {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": settings.kafka_auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
            "session.timeout.ms": 30000,
        }
        return Consumer(conf)

    def _process_message(self, msg_value: str) -> Optional[dict]:
        try:
            payload = json.loads(msg_value)
            if not isinstance(payload, dict):
                logger.warning("[%s] Expected JSON object payload", self.pattern_type)
                return None

            # Default category/type from consumer if producer does not send it.
            payload.setdefault("pattern_type", self.pattern_type)
            return payload
        except json.JSONDecodeError as exc:
            logger.error(
                "[%s] Failed to parse JSON payload_preview=%s error=%s",
                self.pattern_type,
                msg_value[:500] if msg_value else "<empty>",
                exc,
            )
            return None
        except Exception as exc:
            logger.exception("[%s] Unexpected error processing message: %s", self.pattern_type, exc)
            return None

    def _consume_loop(self) -> None:
        if self.consumer is None:
            logger.error("[%s] Consumer not initialized", self.pattern_type)
            return

        import time

        batch = []
        last_flush_time = time.monotonic()
        try:
            self.consumer.subscribe([self.topic])
            logger.info("[%s] Subscribed to topic=%s", self.pattern_type, self.topic)

            while self.running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    if batch and (time.monotonic() - last_flush_time) >= self.flush_interval:
                        try:
                            bulk_insert_detected_patterns_from_kafka_payloads(batch)
                            for payload in batch:
                                symbol = str(payload.get("stock_ticker") or payload.get("instrument") or "").strip().upper()
                                if symbol:
                                    clear_instrument_cache(symbol)
                            batch.clear()
                            last_flush_time = time.monotonic()
                        except Exception as exc:
                            logger.error("[%s] Failed to flush partial batch: %s", self.pattern_type, exc)
                            self.messages_failed += len(batch)
                            batch.clear()
                    continue

                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        error_msg = f"Consumer error: {msg.error()}"
                        logger.error("[%s] %s", self.pattern_type, error_msg)
                        self.last_error = error_msg
                    continue

                raw_value = msg.value()
                if raw_value is None:
                    self.messages_failed += 1
                    continue

                try:
                    msg_value = raw_value.decode("utf-8")
                except UnicodeDecodeError as exc:
                    logger.error("[%s] utf-8 decode error=%s", self.pattern_type, exc)
                    self.messages_failed += 1
                    continue

                parsed_payload = self._process_message(msg_value)
                if parsed_payload:
                    batch.append(parsed_payload)
                    self.messages_processed += 1
                    last_flush_time = time.monotonic()
                    if len(batch) >= self.batch_size:
                        try:
                            inserted = bulk_insert_detected_patterns_from_kafka_payloads(batch)
                            # Clear cache for all affected symbols in batch
                            for payload in batch:
                                symbol = str(payload.get("stock_ticker") or payload.get("instrument") or "").strip().upper()
                                if symbol:
                                    clear_instrument_cache(symbol)
                            batch.clear()
                        except Exception as exc:
                            logger.error("[%s] Failed to bulk insert batch: %s", self.pattern_type, exc)
                            self.messages_failed += len(batch)
                            batch.clear()
                else:
                    self.messages_failed += 1

        except Exception as exc:
            error_msg = f"Error in consumption loop: {exc}"
            logger.exception("[%s] %s", self.pattern_type, error_msg)
            self.last_error = error_msg
        finally:
            # Process remaining batch
            if batch:
                try:
                    inserted = bulk_insert_detected_patterns_from_kafka_payloads(batch)
                    # Clear cache for all affected symbols in batch
                    for payload in batch:
                        symbol = str(payload.get("stock_ticker") or payload.get("instrument") or "").strip().upper()
                        if symbol:
                            clear_instrument_cache(symbol)
                except Exception as exc:
                    logger.error("[%s] Failed to bulk insert remaining batch: %s", self.pattern_type, exc)
                    self.messages_failed += len(batch)
            if self.consumer:
                self.consumer.close()

    def start(self) -> None:
        if self.running:
            return

        try:
            self.consumer = self._create_consumer()
            self.running = True
            self.messages_processed = 0
            self.messages_failed = 0
            self.last_error = None

            self.thread = threading.Thread(target=self._consume_loop, daemon=True)
            self.thread.start()
            logger.info("[%s] Consumer started", self.pattern_type)
        except Exception as exc:
            self.last_error = f"Failed to start consumer: {exc}"
            self.running = False
            logger.exception("[%s] %s", self.pattern_type, self.last_error)

    def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)

        logger.info(
            "[%s] Consumer stopped processed=%s failed=%s",
            self.pattern_type,
            self.messages_processed,
            self.messages_failed,
        )

    def status(self) -> dict:
        return {
            "pattern_type": self.pattern_type,
            "topic": self.topic,
            "group_id": self.group_id,
            "running": self.running,
            "messages_processed": self.messages_processed,
            "messages_failed": self.messages_failed,
            "last_error": self.last_error,
        }

