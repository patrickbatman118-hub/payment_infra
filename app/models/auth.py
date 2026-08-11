import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
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
    merchant_users: Mapped[list["MerchantUser"]] = relationship(
        "MerchantUser",
        foreign_keys="MerchantUser.user_id",
        back_populates="user",
        lazy="selectin",
    )
    invitations_sent: Mapped[list["MerchantUser"]] = relationship(
        "MerchantUser",
        foreign_keys="MerchantUser.invited_by",
        back_populates="inviter",
        lazy="selectin",
    )
    tokens: Mapped[list["Token"]] = relationship(
        "Token",
        foreign_keys="Token.user_id",
        back_populates="user",
        lazy="selectin",
    )
    tokens_revoked: Mapped[list["Token"]] = relationship(
        "Token",
        foreign_keys="Token.revoked_by",
        back_populates="revoker",
        lazy="selectin",
    )
    refunds_initiated: Mapped[list["Refund"]] = relationship(  # type: ignore[name-defined]
        "Refund", back_populates="initiator", lazy="selectin"
    )
    fraud_reviews: Mapped[list["FraudScore"]] = relationship(  # type: ignore[name-defined]
        "FraudScore", back_populates="reviewer", lazy="selectin"
    )


class MerchantUser(Base):
    __tablename__ = "merchant_users"

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "user_id", name="uq_merchant_users_merchant_user"
        ),
        # One role per user per merchant
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    role: Mapped[str] = mapped_column(String(30), nullable=False)
    # 'merchant_admin', 'staff', 'settlement_viewer', 'refund_manager'
    # Fixed enum — no dynamic roles table needed for this system

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="merchant_users", lazy="selectin"
    )
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="merchant_users",
        lazy="selectin",
    )
    inviter: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[invited_by],
        back_populates="invitations_sent",
        lazy="selectin",
    )


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    jti: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # JWT ID claim — unique per token

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id"), nullable=True
    )
    # NULL for platform admins

    # Attenuation tree — entire lineage in one self-referential column
    parent_token_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tokens.id"), nullable=True
    )
    # NULL = root token

    # What this token can do — scoped per token, not just per role
    scopes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # e.g. ['payments:read', 'refunds:write', 'settlements:read']

    # Revocation
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="tokens",
        lazy="selectin",
    )
    merchant: Mapped["Merchant | None"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="tokens", lazy="selectin"
    )
    revoker: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[revoked_by],
        back_populates="tokens_revoked",
        lazy="selectin",
    )
    # Self-referential attenuation tree
    parent_token: Mapped["Token | None"] = relationship(
        "Token",
        foreign_keys=[parent_token_id],
        back_populates="child_tokens",
        remote_side="Token.id",
        lazy="selectin",
    )
    child_tokens: Mapped[list["Token"]] = relationship(
        "Token",
        foreign_keys=[parent_token_id],
        back_populates="parent_token",
        lazy="selectin",
    )
