import uuid
from datetime import datetime
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.core.database import Base


class OutboxEvent(Base):
    """
    Transactional outbox for guaranteed Kafka delivery.

    Written inside the SAME database transaction as the triggering data change.
    A separate worker process polls pending rows, publishes to Kafka, then marks published.
    If the worker crashes before publishing — the row survives and is retried on restart.
    At-least-once delivery guaranteed without distributed 2-phase commit.

    Pattern:
        # All inside ONE transaction — commit atomically or not at all
        db.add(PaymentStatusHistory(to_status="success"))
        db.add(LedgerTransaction(...))
        db.add(LedgerEntry(...))  # × 3 balanced entries
        db.add(OutboxEvent(topic="payment.success", aggregate_id=payment_id))
        await session.commit()

        # Separate outbox worker process
        events = await session.execute(select(OutboxEvent).where(status="pending"))
        for event in events:
            kafka.publish(event.topic, event.payload)
            event.status = "published"
            event.published_at = datetime.utcnow()
        await session.commit()
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    # 'payment.initiated', 'payment.success', 'payment.failed',
    # 'payment.disputed', 'settlement.completed',
    # 'dispute.raised', 'refund.processed'

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    # 'pending', 'published', 'failed'

    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'payment', 'settlement', 'dispute', 'refund'
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_attempted: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("NOW()")
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
