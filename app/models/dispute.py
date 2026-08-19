import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    DateTime,
    Numeric,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class Dispute(Base):
    """
    Customer chargebacks — adversarial process initiated by customer via their bank.
    Distinct from refunds (merchant-initiated, cooperative) — see schema design for full comparison.

    Settlement impact: held_from_settlement=True contributes to settlements.disputed_hold
    and blocks that amount from being paid out until resolved.
    """

    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False
    )

    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'fraudulent', 'duplicate', 'product_not_received',
    # 'product_unacceptable', 'credit_not_processed'
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    disputed_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    resolved_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    # Separate columns — customer disputes ₹500, platform may resolve at ₹300.
    # Almost always different. One column can't express partial resolution.

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="raised"
    )
    # 'raised', 'under_review', 'merchant_responded',
    # 'resolved_merchant', 'resolved_customer', 'escalated'

    # Merchant submits proof — delivery receipts, communications, tracking
    merchant_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    platform_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # platform_admin UUID who made the final call

    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    respond_by: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Deadline for merchant evidence. Scheduled job checks daily.
    # After deadline: auto-resolves in customer favor.
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Settlement impact
    held_from_settlement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Settlement ETL reads this when computing disputed_hold
    recovery_settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("settlements.id"), nullable=True
    )
    # Which future settlement deducted the disputed amount from merchant

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    payment: Mapped["Payment"] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="disputes", lazy="selectin"
    )
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="disputes", lazy="selectin"
    )
    customer: Mapped["Customer"] = relationship(  # type: ignore[name-defined]
        "Customer", back_populates="disputes", lazy="selectin"
    )
    recovery_settlement: Mapped["Settlement | None"] = relationship(  # type: ignore[name-defined]
        "Settlement",
        foreign_keys=[recovery_settlement_id],
        back_populates="recovered_disputes",
        lazy="selectin",
    )
    status_history: Mapped[list["DisputeStatusHistory"]] = relationship(
        "DisputeStatusHistory", back_populates="dispute", lazy="selectin"
    )


class DisputeStatusHistory(Base):
    """Append-only dispute state transition log."""

    __tablename__ = "dispute_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    dispute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("disputes.id"), nullable=False
    )

    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'customer', 'merchant', 'platform_admin', 'system'
    actor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    dispute: Mapped["Dispute"] = relationship(
        "Dispute", back_populates="status_history", lazy="noload"
    )
