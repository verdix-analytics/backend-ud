from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.models.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    cognito_sub             = Column(String, primary_key=True)
    subscription_type       = Column(String, nullable=False, default="basic")   # "basic" | "pro"
    credits_remaining       = Column(Integer, nullable=False, default=0)
    free_analyses_remaining = Column(Integer, nullable=False, default=3)
    free_analyses_reset_at  = Column(DateTime(timezone=True), nullable=True)
    created_at              = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    cognito_sub   = Column(String, nullable=False, index=True)
    ticker        = Column(String, nullable=True)
    analysis_type = Column(String, nullable=True)   # "analysis" | "summary"
    credit_cost   = Column(Integer, nullable=False, default=1)
    deducted_from = Column(String, nullable=True)   # "free" | "credits" | "cache"
    cache_hit     = Column(Boolean, nullable=False, default=False)
    created_at    = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
