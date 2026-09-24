from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class DetectedPattern(Base):
    __tablename__ = "detected_patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, nullable=False)
    analysis_id = Column(String, nullable=False)
    instrument = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    pattern = Column(String, nullable=False)
    category = Column(String, nullable=False)
    pattern_type = Column(String, nullable=True)

    window_start = Column(Integer, nullable=False)
    window_end = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    confirmed = Column(Boolean, nullable=False, default=True)
    structure_detected = Column(Boolean, nullable=False, default=True)

    signal = Column(JSON, nullable=False, default=dict)
    context_score = Column(JSON, nullable=True)
    pre_trend = Column(JSON, nullable=False, default=dict)
    post_trend = Column(JSON, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "instrument",
            "category",
            "timeframe",
            "pattern",
            "window_start",
            "window_end",
            name="uq_detected_patterns_dedupe_key",
        ),
        Index("idx_detected_patterns_instrument_detected_at", "instrument", "detected_at"),
        Index("idx_detected_patterns_analysis_id", "analysis_id"),
        Index("idx_detected_patterns_category", "category"),
    )

