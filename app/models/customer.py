import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    __table_args__ = (
        UniqueConstraint("merchant_id", "email", name="uq_customers_merchant_email"),
        # Same email = different customer per merchant
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Denormalized counters for fraud scoring — avoids COUNT(*) aggregations at payment time
    total_transactions: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_disputed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    is_blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="customers", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="customer", lazy="selectin"
    )
    disputes: Mapped[list["Dispute"]] = relationship(  # type: ignore[name-defined]
        "Dispute", back_populates="customer", lazy="selectin"
    )
    fraud_scores: Mapped[list["FraudScore"]] = relationship(  # type: ignore[name-defined]
        "FraudScore", back_populates="customer", lazy="selectin"
    )
