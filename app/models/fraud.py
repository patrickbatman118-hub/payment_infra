import uuid
from sqlalchemy import (
    DateTime,
    Numeric,
    String,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from app.core.database import Base


class FraudScore(Base):
    """
    Per-payment fraud scoring history. Redis caches the current score for fast reads
    during processing. This table stores the permanent audit trail.

    model_version is required — a score of 75 from v1.0 and v1.1 may not be comparable
    if the scoring algorithm changed. Version tag makes the history queryable by model.

    signals JSONB evolves over model versions without schema migrations:
      {
        "velocity_score": 45,         # multiple payments in short window
        "amount_score": 30,           # unusually large for this merchant category
        "category_score": 20,         # high risk merchant type
        "customer_history_score": 5   # prior disputes on this customer
      }
    """

    __tablename__ = "fraud_scores"

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

    score: Mapped[Numeric] = mapped_column(Numeric(5, 2), nullable=False)
    # 0.00 to 100.00. Above threshold = auto-hold.

    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    # 'low', 'medium', 'high', 'critical'

    # What drove the score — JSONB because scoring signals evolve across model versions
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False)

    action_taken: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'allowed', 'held', 'blocked'
    # Score of 60 might allow for one merchant, hold for another
    # action_taken is what matters for audit — not just the score

    # Human review if flagged
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    review_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 'approved', 'rejected', 'escalated'
    reviewed_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # 'v1.0', 'v1.1' — scoring logic changes over time

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )

    # Relationships
    payment: Mapped["Payment"] = relationship(  # type: ignore[name-defined]
        "Payment", back_populates="fraud_scores", lazy="selectin"
    )
    merchant: Mapped["Merchant"] = relationship(  # type: ignore[name-defined]
        "Merchant", back_populates="fraud_scores", lazy="selectin"
    )
    customer: Mapped["Customer"] = relationship(  # type: ignore[name-defined]
        "Customer", back_populates="fraud_scores", lazy="selectin"
    )
    reviewer: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="fraud_reviews", lazy="selectin"
    )
