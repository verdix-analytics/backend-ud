import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from confluent_kafka import Consumer, KafkaError

from app.core.config import settings
from app.services.cache_service import clear_instrument_cache
from app.services.database_service import bulk_insert_financial_prices

logger = logging.getLogger(__name__)


class BaseFinancialPriceConsumer:
    def __init__(self, topic: str, group_id: str, timeframe: str, batch_size: int = 50, flush_interval: float = 10.0):
        self.topic = topic
        self.group_id = group_id
        self.timeframe = timeframe
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
            self.timeframe,
            self.topic,
            self.group_id,
            self.batch_size,
            self.flush_interval,
        )

    def _message_metadata(self, msg) -> str:
        try:
            topic = msg.topic() if msg is not None else None
            partition = msg.partition() if msg is not None else None
            offset = msg.offset() if msg is not None else None
            key = msg.key() if msg is not None else None
            if isinstance(key, bytes):
                key = key.decode("utf-8", errors="replace")
            elif key is not None:
                key = str(key)
            return f"topic={topic}, partition={partition}, offset={offset}, key={key}"
        except Exception:
            return "topic=<unknown>, partition=<unknown>, offset=<unknown>, key=<unknown>"

    def _create_consumer(self) -> Consumer:
        conf = {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": settings.kafka_auto_offset_reset,
            "enable.auto.commit": True,
            "auto.commit.interval.ms": 5000,
            "session.timeout.ms": 30000,
        }

        logger.info(
            "Creating Kafka consumer for timeframe=%s bootstrap_servers=%s group_id=%s topic=%s auto_offset_reset=%s",
            self.timeframe,
            settings.kafka_bootstrap_servers,
            self.group_id,
            self.topic,
            settings.kafka_auto_offset_reset,
        )
        return Consumer(conf)

    def _process_message(self, msg_value: str) -> Optional[dict]:
        try:
            data = json.loads(msg_value)
            if "timestamp" not in data and "datetime" in data:
                data["timestamp"] = data["datetime"]

            required_fields = {"symbol", "open", "high", "low", "close", "volume"}
            if not required_fields.issubset(data.keys()):
                missing_fields = sorted(required_fields.difference(data.keys()))
                logger.warning(
                    "[%s] Message missing required fields=%s available_keys=%s",
                    self.timeframe,
                    missing_fields,
                    sorted(data.keys()),
                )
                return None

            if "timestamp" not in data:
                logger.warning("[%s] Message missing timestamp field", self.timeframe)
                return None

            try:
                timestamp = datetime.fromisoformat(str(data["timestamp"]).replace("Z", "+00:00"))

            except (ValueError, TypeError) as exc:
                logger.warning(
                    "[%s] Invalid timestamp format symbol=%s timestamp=%s error=%s",
                    self.timeframe,
                    data.get("symbol"),
                    data.get("timestamp"),
                    exc,
                )
                return None

            stock_name = data.get("name")
            if stock_name is not None:
                stock_name = str(stock_name).strip() or None

            stock_exchange = data.get("exchange")
            if stock_exchange is not None:
                stock_exchange = str(stock_exchange).strip() or None

            asset_class = data.get("asset_class")
            if asset_class is not None:
                asset_class = str(asset_class).strip() or None

            symbol = str(data["symbol"]).upper()
            open_price = float(data["open"])
            high_price = float(data["high"])
            low_price = float(data["low"])
            close_price = float(data["close"])

            return {
                "symbol": symbol,
                "datetime_val": timestamp,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": int(data["volume"]),
                "name": stock_name,
                "exchange": stock_exchange,
                "asset_class": asset_class,
            }

        except json.JSONDecodeError as exc:
            logger.error(
                "[%s] Failed to parse JSON message payload_preview=%s error=%s",
                self.timeframe,
                msg_value[:500] if msg_value else "<empty>",
                exc,
            )
            return None
        except (ValueError, TypeError) as exc:
            logger.error("[%s] Invalid data in message error=%s", self.timeframe, exc)
            return None
        except Exception as exc:
            logger.exception("[%s] Unexpected error processing message: %s", self.timeframe, exc)
            return None

    def _consume_loop(self) -> None:
        if self.consumer is None:
            logger.error("[%s] Consumer not initialized", self.timeframe)
            return

        import time

        batch = []
        last_flush_time = time.monotonic()
        try:
            self.consumer.subscribe([self.topic])
            logger.info("[%s] Subscribed to topic=%s", self.timeframe, self.topic)

            while self.running:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    if batch and (time.monotonic() - last_flush_time) >= self.flush_interval:
                        try:
                            bulk_insert_financial_prices(self.timeframe, batch)
                            batch.clear()
                            last_flush_time = time.monotonic()
                        except Exception as exc:
                            logger.error("[%s] Failed to flush partial batch: %s", self.timeframe, exc)
                            self.messages_failed += len(batch)
                            batch.clear()
                    continue

                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        error_msg = f"Consumer error: {msg.error()}"
                        logger.error("[%s] %s; %s", self.timeframe, error_msg, self._message_metadata(msg))
                        self.last_error = error_msg
                    continue

                raw_value = msg.value()
                if raw_value is None:
                    self.messages_failed += 1
                    continue

                try:
                    msg_value = raw_value.decode("utf-8")
                except UnicodeDecodeError as exc:
                    logger.error("[%s] utf-8 decode error=%s", self.timeframe, exc)
                    self.messages_failed += 1
                    continue

                parsed_data = self._process_message(msg_value)
                if parsed_data:
                    batch.append(parsed_data)
                    self.messages_processed += 1
                    last_flush_time = time.monotonic()
                    if len(batch) >= self.batch_size:
                        try:
                            bulk_insert_financial_prices(self.timeframe, batch)
                            batch.clear()
                        except Exception as exc:
                            logger.error("[%s] Failed to bulk insert batch: %s", self.timeframe, exc)
                            self.messages_failed += len(batch)
                            batch.clear()
                else:
                    self.messages_failed += 1

        except Exception as exc:
            error_msg = f"Error in consumption loop: {exc}"
            logger.exception("[%s] %s", self.timeframe, error_msg)
            self.last_error = error_msg
        finally:
            # Process remaining batch
            if batch:
                try:
                    bulk_insert_financial_prices(self.timeframe, batch)
                except Exception as exc:
                    logger.error("[%s] Failed to bulk insert remaining batch: %s", self.timeframe, exc)
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
            logger.info("[%s] Consumer started", self.timeframe)
        except Exception as exc:
            self.last_error = f"Failed to start consumer: {exc}"
            self.running = False
            logger.exception("[%s] %s", self.timeframe, self.last_error)

    def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)

        logger.info(
            "[%s] Consumer stopped processed=%s failed=%s",
            self.timeframe,
            self.messages_processed,
            self.messages_failed,
        )

    def status(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "topic": self.topic,
            "group_id": self.group_id,
            "running": self.running,
            "messages_processed": self.messages_processed,
            "messages_failed": self.messages_failed,
            "last_error": self.last_error,
        }
