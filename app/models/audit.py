import uuid
from sqlalchemy import (
    DateTime,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import Base


class AuditLog(Base):
    """
    Immutable record of every system decision. Append-only — never updated or deleted.

    One table for everything — not per-entity audit tables.
    A fraud investigator tracing a case needs one query across all entities
    that touched merchant X, payment Y, token Z.
    Separate tables make that a multi-join nightmare.

    token_jti links to tokens.jti. If a token is compromised:
        SELECT * FROM audit_logs WHERE token_jti = 'compromised_jti'
    Returns everything that token ever did — authorizations, data access, state changes.

    Denials are logged too — 50 denials in 5 minutes is a fraud/brute-force pattern.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # What was touched
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'merchant', 'transaction', 'settlement', 'dispute', 'token'
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    # What happened
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # 'kyc_status_changed', 'payment_held', 'token_revoked'
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Who did it
    actor_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'merchant_admin', 'platform_admin', 'system'
    token_jti: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Which exact JWT was used — links to tokens.jti
    # If token compromised: query here to see everything it did

    # Why it was allowed or denied
    policy_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'allowed', 'denied'
    policy_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Denials logged too — 50 denials in 5 minutes is a fraud pattern

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    # No updated_at. Audit logs are immutable.
    # If someone needs to "correct" an audit log — that's a new log entry.

    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
