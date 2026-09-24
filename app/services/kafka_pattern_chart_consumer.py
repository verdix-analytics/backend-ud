from app.core.config import settings
from app.services.kafka_pattern_base_consumer import BasePatternConsumer


class ChartPatternConsumer(BasePatternConsumer):
    def __init__(self):
        super().__init__(
            topic=settings.kafka_topic_chart,
            group_id=settings.kafka_group_id_chart,
            pattern_type="chart",
        )


chart_pattern_consumer = ChartPatternConsumer()

