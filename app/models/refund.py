import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
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


class Refund(Base):
    """
    Merchant voluntarily returns money. Or platform admin forces it.
    Never initiated by customer — customers raise disputes, not refunds.

    Partial refunds allowed — merchant can refund ₹200 of a ₹500 payment.
    Application enforces: sum(refund_amount) <= payment.amount.
    Schema stores facts; application enforces the business rule.
    """

    __tablename__ = "refunds"

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

    initiated_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'merchant', 'platform_admin' — never 'customer' (customers raise disputes)
    initiator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    refund_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="initiated"
    )
    # 'initiated', 'processing', 'success', 'failed'

    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'duplicate', 'fraudulent', 'customer_request', 'product_issue', 'order_cancelled'
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated when reversal ledger entries are created
    # Links refund decision → exact ledger movement
    ledger_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=True
    )

    gateway_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gateway_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    payment: Mapped["Payment"] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="refunds", lazy="selectin"
    )
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="refunds", lazy="selectin"
    )
    initiator: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="refunds_initiated", lazy="selectin"
    )
    ledger_transaction: Mapped["LedgerTransaction | None"] = relationship(  # type: ignore[name-defined]
        "LedgerTransaction", back_populates="refunds", lazy="selectin"
    )
    status_history: Mapped[list["RefundStatusHistory"]] = relationship(
        "RefundStatusHistory", back_populates="refund", lazy="selectin"
    )


class RefundStatusHistory(Base):
    """Append-only refund state transition log."""

    __tablename__ = "refund_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    refund_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("refunds.id"), nullable=False
    )

    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    refund: Mapped["Refund"] = relationship(
        "Refund", back_populates="status_history", lazy="selectin"
    )
