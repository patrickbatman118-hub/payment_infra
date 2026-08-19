import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    DateTime,
    Numeric,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class Payment(Base):
    __tablename__ = "payments"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "idempotency_key", name="uq_payments_merchant_idempotency"
        ),
        # Same payment request twice = second insert fails at DB level
        # Customer double-click cannot create two charges
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="INR"
    )

    # Current state only — full history in payment_status_history
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="initiated"
    )
    # 'initiated', 'processing', 'success', 'failed',
    # 'cancelled', 'pending_review', 'refunded', 'disputed'

    # Last line of defense against duplicate charges
    # Redis handles at API layer, DB constraint is the guarantee
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)

    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    # 'upi', 'card', 'netbanking', 'wallet'
    payment_method_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # card last 4 digits, UPI handle — never full card number (PCI violation)

    # Written by fraud service after scoring
    # Settlement ETL holds transactions above threshold
    risk_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    risk_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Bank/gateway tracking
    gateway_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    gateway_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Store raw — you don't know which fields you'll need 6 months later in a dispute

    initiated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="payments", lazy="noload"
    )
    customer: Mapped["Customer"] = relationship(  # type: ignore[name-defined]
        "Customer", back_populates="payments", lazy="noload"
    )
    status_history: Mapped[list["PaymentStatusHistory"]] = relationship(
        "PaymentStatusHistory", back_populates="payment", lazy="noload"
    )
    ledger_transactions: Mapped[list["LedgerTransaction"]] = relationship(  # type: ignore[name-defined]
        "LedgerTransaction", back_populates="payment", lazy="noload"
    )
    settlement_payment: Mapped["SettlementPayment | None"] = relationship(  # type: ignore[name-defined]
        "SettlementPayment", back_populates="payment", lazy="noload"
    )
    disputes: Mapped[list["Dispute"]] = relationship(  # type: ignore[name-defined]
        "Dispute", back_populates="payment", lazy="noload"
    )
    refunds: Mapped[list["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", back_populates="payment", lazy="noload"
    )
    fraud_scores: Mapped[list["FraudScore"]] = relationship(  # type: ignore[name-defined]
        "FraudScore", back_populates="payment", lazy="noload"
    )


class PaymentStatusHistory(Base):
    """
    Every state transition for a payment. Append-only — never updated.
    Preserves the full transition chain: from_status, to_status, reason, actor, timestamp.
    This table also drives Kafka — every insert fires an outbox event.
    """

    __tablename__ = "payment_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"), nullable=False
    )

    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # NULL on first entry (initiated)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'customer', 'system', 'merchant', 'platform_admin'
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    # No updated_at. State transitions are facts. Facts don't get edited.

    # Relationships
    payment: Mapped["Payment"] = relationship(
        "Payment", back_populates="status_history", lazy="noload"
    )
