from uuid import uuid4

from sqlalchemy import Column, Float, ForeignKey, Index, Integer, TIMESTAMP, UniqueConstraint, func, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declared_attr, relationship

from app.models.base import Base
from app.models.asset import Asset


class _FinancialDataBase(Base):
    __abstract__ = True

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4, nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    ts = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    @declared_attr
    def stock(cls):
        return relationship("Asset", lazy="joined")


class FinancialData1H(_FinancialDataBase):
    __tablename__ = "financial_1h"
    __table_args__ = (
        UniqueConstraint("asset_id", "ts", name="uq_financial_1h_asset_id_ts"),
        Index("idx_financial_1h_asset_id_ts", "asset_id", "ts"),
    )


class FinancialData1M(_FinancialDataBase):
    __tablename__ = "financial_1m"
    __table_args__ = (
        UniqueConstraint("asset_id", "ts", name="uq_financial_1m_asset_id_ts"),
        Index("idx_financial_1m_asset_id_ts", "asset_id", "ts"),
    )


class FinancialData1Y(_FinancialDataBase):
    __tablename__ = "financial_1y"
    __table_args__ = (
        UniqueConstraint("asset_id", "ts", name="uq_financial_1y_asset_id_ts"),
        Index("idx_financial_1y_asset_id_ts", "asset_id", "ts"),
    )

