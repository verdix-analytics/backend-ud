from app.core.config import settings
from app.services.kafka_pattern_base_consumer import BasePatternConsumer


class HarmonicPatternConsumer(BasePatternConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_harmonic,
            group_id=settings.kafka_group_id_harmonic,
            pattern_type="harmonic",
        )


harmonic_pattern_consumer = HarmonicPatternConsumer()

