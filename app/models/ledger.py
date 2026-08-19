import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Numeric,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class LedgerTransaction(Base):
    """
    The financial event record — WHY money moved. One row per economic event.
    Bi-temporal: effective_at (when it economically happened) vs recorded_at (when we wrote it).

    Bi-temporal example:
      - A payment at 23:59:30 confirmed by bank at 00:00:45 next day.
        effective_at = 23:59:30 (belongs in today's settlement)
        recorded_at  = 00:00:45 (when our system wrote the row)
    """

    __tablename__ = "ledger_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("settlements.id"), nullable=True
    )

    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'payment', 'refund', 'fee', 'settlement', 'adjustment'

    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Bi-temporal timestamps
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # When the money movement economically happened (from bank confirmation)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    # When this system wrote the row (always NOW())

    # Prevents same financial event being recorded twice under retries
    idempotency_key: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    payment: Mapped["Payment | None"] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="ledger_transactions", lazy="noload"
    )
    settlement: Mapped["Settlement | None"] = relationship(  # type: ignore[name-defined]
        "Settlement", back_populates="ledger_transactions", lazy="noload"
    )
    entries: Mapped[list["LedgerEntry"]] = relationship(
        "LedgerEntry", back_populates="ledger_transaction", lazy="noload"
    )
    refunds: Mapped[list["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", back_populates="ledger_transaction", lazy="noload"
    )


class LedgerEntry(Base):
    """
    HOW money moved — the debit/credit lines. Multiple rows per LedgerTransaction.
    Always balanced: sum of debit amounts == sum of credit amounts per transaction.

    No payment_id here — entries don't know about payments.
    To get entries for a payment: JOIN through ledger_transactions.
    Normalization note: future entry types (settlement, adjustment) have no payment_id
    at all — putting it here would create nullable FKs on half the rows.
    """

    __tablename__ = "ledger_entries"

    __table_args__ = (
        CheckConstraint("direction IN ('debit', 'credit')", name="ck_direction_valid"),
        CheckConstraint("amount > 0", name="ck_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    ledger_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ledger_transactions.id"), nullable=False
    )
    # No payment_id — entries relate to ledger_transaction, not payments directly

    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 'customer', 'merchant', 'platform_cash', 'platform_revenue', 'gateway', 'bank'
    account_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'debit' or 'credit' — enforced by CHECK constraint above
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # Enforced > 0 by CHECK constraint above
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="INR"
    )

    running_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    # Balance snapshot at time of entry — enables point-in-time reconstruction

    # Reversal entries point back to what they're undoing
    is_reversal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    reversed_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_entries.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    # No updated_at. Ledger entries are permanent and immutable.

    # Relationships
    ledger_transaction: Mapped["LedgerTransaction"] = relationship(
        "LedgerTransaction", back_populates="entries", lazy="noload"
    )
    # Self-referential reversal link
    reversed_entry: Mapped["LedgerEntry | None"] = relationship(
        "LedgerEntry",
        foreign_keys=[reversed_entry_id],
        remote_side="LedgerEntry.id",
        lazy="noload",
    )
