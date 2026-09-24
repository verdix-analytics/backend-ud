import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.config import settings
from app.services.database_service import search_stock, get_db_session
from app.services.kafka_producer_service import kafka_producer

logger = logging.getLogger(__name__)


class ExternalStockAnalysisService:

    @staticmethod
    def validate_ticker(ticker: str) -> str:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("Ticker must not be empty")
        return normalized

    @staticmethod
    def check_stock_exists(ticker: str) -> Optional[dict]:
        return search_stock(ticker)

    @staticmethod
    def _create_analysis_payload(ticker: str) -> dict:
        return {
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def publish_to_kafka(ticker: str) -> bool:
        if not settings.kafka_enabled:
            raise RuntimeError("Kafka is not enabled")

        payload = ExternalStockAnalysisService._create_analysis_payload(ticker)

        success = kafka_producer.produce_message(
            topic=settings.kafka_topic_run_external_stock_analysis,
            value=payload,
            key=ticker,
        )

        if not success:
            logger.error("Failed to publish stock %s to Kafka", ticker)
            raise RuntimeError(f"Failed to publish stock {ticker} to Kafka")

        logger.info("Successfully published stock %s to Kafka topic", ticker)
        return True

    @staticmethod
    def mark_as_external(ticker: str) -> None:
        """Insert or update the asset row to flag it as externally triggered."""
        from app.models.asset import Asset
        session = get_db_session()
        try:
            asset = session.query(Asset).filter(Asset.symbol == ticker).first()
            if asset is None:
                asset = Asset(symbol=ticker, is_external=True)
                session.add(asset)
            else:
                asset.is_external = True
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("Failed to mark %s as external: %s", ticker, exc)
        finally:
            session.close()

    @staticmethod
    def is_external_stock(ticker: str) -> bool:
        """Return True if the stock is marked as externally triggered in the DB."""
        from app.models.asset import Asset
        session = get_db_session()
        try:
            asset = session.query(Asset).filter(Asset.symbol == ticker).first()
            return asset is not None and asset.is_external is True
        finally:
            session.close()

    @staticmethod
    def trigger_analysis(ticker: str) -> dict:
        normalized_ticker = ExternalStockAnalysisService.validate_ticker(ticker)

        stock_info = ExternalStockAnalysisService.check_stock_exists(normalized_ticker)

        if stock_info is not None:
            logger.info("Stock %s already exists in database, skipping analysis", normalized_ticker)
            return {
                "status": "skipped",
                "message": f"Stock {normalized_ticker} already exists",
            }

        ExternalStockAnalysisService.publish_to_kafka(normalized_ticker)
        ExternalStockAnalysisService.mark_as_external(normalized_ticker)

        logger.info("Stock %s published for analysis and marked as external", normalized_ticker)
        return {
            "status": "published",
            "message": f"Stock {normalized_ticker} analysis started",
        }

external_stock_analysis_service = ExternalStockAnalysisService()


