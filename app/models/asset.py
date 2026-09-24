from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, Column, Integer, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, nullable=False)
    symbol = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=True)
    exchange = Column(String, nullable=True)
    asset_class = Column(String, nullable=True)
    is_external = Column(Boolean, nullable=False, default=False, server_default="false")
    search_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), server_default=func.now())
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )


