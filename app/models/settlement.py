import uuid
from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class Settlement(Base):
    """
    Nightly payout computation per merchant. One row per merchant per settlement run.
    Airflow reads next_retry_at to schedule retries with exponential backoff.
    """

    __tablename__ = "settlements"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchant_bank_accounts.id"), nullable=True
    )

    # The window this settlement covers
    period_start: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Computed amounts — all Numeric(15,2), never float
    gross_amount: Mapped[Numeric] = mapped_column(Numeric(15, 2), nullable=False)
    fee_deducted: Mapped[Numeric] = mapped_column(Numeric(15, 2), nullable=False)
    disputed_hold: Mapped[Numeric] = mapped_column(
        Numeric(15, 2), nullable=False, server_default="0"
    )
    net_payout: Mapped[Numeric] = mapped_column(Numeric(15, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="INR"
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="pending"
    )
    # 'pending', 'processing', 'completed', 'failed', 'on_hold'

    # Reconciliation result
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    # 'pending', 'matched', 'mismatched', 'manual_review'
    reconciliation_delta: Mapped[Numeric | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    # Difference between ledger sum and computed net_payout
    # Zero = perfect. Non-zero = investigation required.

    # Bank transfer tracking
    bank_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transferred_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # S3 report — store key only, not full URL
    # Full URL constructed at read time from config. Bucket names can change; keys don't.
    report_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. 'settlements/2024/01/15/merchant_{uuid}.json'

    # Airflow retry state — exponential backoff: 5min → 30min → 2hrs
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_attempted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_retry_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="settlements", lazy="selectin"
    )
    bank_account: Mapped["MerchantBankAccount | None"] = relationship(  # type: ignore[name-defined]
        "MerchantBankAccount", back_populates="settlements", lazy="selectin"
    )
    settlement_payments: Mapped[list["SettlementPayment"]] = relationship(
        "SettlementPayment", back_populates="settlement", lazy="selectin"
    )
    status_history: Mapped[list["SettlementStatusHistory"]] = relationship(
        "SettlementStatusHistory", back_populates="settlement", lazy="selectin"
    )
    ledger_transactions: Mapped[list["LedgerTransaction"]] = relationship(  # type: ignore[name-defined]
        "LedgerTransaction", back_populates="settlement", lazy="selectin"
    )
    # Disputes recovered via this settlement
    recovered_disputes: Mapped[list["Dispute"]] = relationship(  # type: ignore[name-defined]
        "Dispute",
        foreign_keys="Dispute.recovery_settlement_id",
        back_populates="recovery_settlement",
        lazy="selectin",
    )


class SettlementPayment(Base):
    """
    Junction table: which payments were included in which settlement.
    UNIQUE(payment_id) — a payment appears in exactly one settlement, ever.
    Without this constraint: an Airflow bug could double-pay a merchant.
    """

    __tablename__ = "settlement_payments"

    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_settlement_payments_payment"),
        # A payment appears in exactly one settlement. Ever.
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("settlements.id"), nullable=False
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"), nullable=False
    )
    amount: Mapped[Numeric] = mapped_column(Numeric(15, 2), nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    settlement: Mapped["Settlement"] = relationship(
        "Settlement", back_populates="settlement_payments", lazy="selectin"
    )
    payment: Mapped["Payment"] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="settlement_payment", lazy="selectin"
    )


class SettlementStatusHistory(Base):
    """Append-only settlement state transition log."""

    __tablename__ = "settlement_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    settlement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("settlements.id"), nullable=False
    )

    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'airflow', 'platform_admin', 'system'

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    settlement: Mapped["Settlement"] = relationship(
        "Settlement", back_populates="status_history", lazy="selectin"
    )
