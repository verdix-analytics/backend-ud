from app.core.config import settings
from app.services.kafka_pattern_base_consumer import BasePatternConsumer


class CandlestickPatternConsumer(BasePatternConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_candlestick,
            group_id=settings.kafka_group_id_candlestick,
            pattern_type="candlestick",
        )


candlestick_pattern_consumer = CandlestickPatternConsumer()

