from app.core.config import settings
from app.services.kafka_financial_base_consumer import BaseFinancialPriceConsumer


class FinancialPrice1HConsumer(BaseFinancialPriceConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_1h,
            group_id=settings.kafka_group_id_1h,
            timeframe="1h",
        )


financial_price_1h_consumer = FinancialPrice1HConsumer()

