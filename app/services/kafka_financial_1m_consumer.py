from app.core.config import settings
from app.services.kafka_financial_base_consumer import BaseFinancialPriceConsumer


class FinancialPrice1MConsumer(BaseFinancialPriceConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_1m,
            group_id=settings.kafka_group_id_1m,
            timeframe="1m",
        )


financial_price_1m_consumer = FinancialPrice1MConsumer()

