import uuid
from datetime import datetime
from decimal import Decimal
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


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'individual', 'private_ltd', 'partnership'
    gstin: Mapped[str | None] = mapped_column(String(15), unique=True, nullable=True)
    pan: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)

    # KYC — has this business proven it's real?
    kyc_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    # 'pending', 'submitted', 'verified', 'rejected', 'suspended'
    kyc_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Operational status — can they transact right now?
    # Separate from KYC: a merchant can be KYC verified but operationally suspended
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="inactive"
    )
    # 'inactive', 'active', 'suspended', 'terminated'

    # Risk — feeds fraud scoring
    risk_category: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="standard"
    )
    # 'low', 'standard', 'high'

    # Per-merchant limits — not global config
    max_transaction_amt: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, server_default="100000.00"
    )
    daily_limit: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, server_default="1000000.00"
    )

    # Per-merchant fee — enterprise merchants negotiate custom rates
    fee_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default="0.0200"
    )
    settlement_cycle: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    # T+1 = next day, T+2 = two days

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    bank_accounts: Mapped[list["MerchantBankAccount"]] = relationship(
        "MerchantBankAccount", back_populates="merchant", lazy="noload"
    )
    customers: Mapped[list["Customer"]] = relationship(  # type: ignore[name-defined]
        "Customer", back_populates="merchant", lazy="noload"
    )
    merchant_users: Mapped[list["MerchantUser"]] = relationship(  # type: ignore[name-defined]
        "MerchantUser", back_populates="merchant", lazy="noload"
    )
    tokens: Mapped[list["Token"]] = relationship(  # type: ignore[name-defined]
        "Token", back_populates="merchant", lazy="noload"
    )
    payments: Mapped[list["Payment"]] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="merchant", lazy="noload"
    )
    settlements: Mapped[list["Settlement"]] = relationship(  # type: ignore[name-defined]
        "Settlement", back_populates="merchant", lazy="noload"
    )
    disputes: Mapped[list["Dispute"]] = relationship(  # type: ignore[name-defined]
        "Dispute", back_populates="merchant", lazy="noload"
    )
    refunds: Mapped[list["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", back_populates="merchant", lazy="noload"
    )
    fraud_scores: Mapped[list["FraudScore"]] = relationship(  # type: ignore[name-defined]
        "FraudScore", back_populates="merchant", lazy="noload"
    )


class MerchantBankAccount(Base):
    __tablename__ = "merchant_bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )

    account_holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str] = mapped_column(String(255), nullable=False)
    # Encrypted at application layer before storing
    ifsc_code: Mapped[str] = mapped_column(String(11), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'savings', 'current'

    # Never send money to unverified account
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_method: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    # 'penny_drop', 'manual', 'bank_statement'

    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # Settlement ETL filters: WHERE is_verified = TRUE AND is_primary = TRUE

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship(
        "Merchant", back_populates="bank_accounts", lazy="noload"
    )
    settlements: Mapped[list["Settlement"]] = relationship(  # type: ignore[name-defined]
        "Settlement", back_populates="bank_account", lazy="noload"
    )
