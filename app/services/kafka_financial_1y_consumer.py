from app.core.config import settings
from app.services.kafka_financial_base_consumer import BaseFinancialPriceConsumer


class FinancialPrice1YConsumer(BaseFinancialPriceConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_1y,
            group_id=settings.kafka_group_id_1y,
            timeframe="1y",
        )


financial_price_1y_consumer = FinancialPrice1YConsumer()

