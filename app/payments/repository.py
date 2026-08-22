from app.core.database import AsyncSession, get_db
from app.core.exceptions import CustomerNotFound, MerchantNotFound, PaymentNotFound
from app.models.payment import Payment, PaymentStatusHistory
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.core.logging import logger
from sqlalchemy import select
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from app.models.ledger import LedgerTransaction, LedgerEntry
from app.models.outbox import OutboxEvent


async def get_merchant(merchant_id: uuid.UUID, db: AsyncSession) -> Merchant | None:
    merchant = await db.get(Merchant, merchant_id)
    if not merchant:
        logger.warning(f"Merchant {merchant_id} not found in database")
        raise MerchantNotFound(merchant_id)
    return merchant


async def get_customer(customer_id: uuid.UUID, merchant_id: uuid.UUID, db: AsyncSession) -> Customer | None:
    result = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.merchant_id == merchant_id))
    customer = result.scalar_one_or_none()
    if not customer:
        logger.warning(
            f"Customer {customer_id} not found for Merchant {merchant_id}")
        raise CustomerNotFound(customer_id)
    return customer


async def get_payment(merchant_id: uuid.UUID, idempotency_key: uuid.UUID, db: AsyncSession) -> Payment | None:
    result = await db.execute(select(Payment).where(Payment.merchant_id == merchant_id, Payment.idempotency_key == idempotency_key))
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning(
            f"Payment with idempotency key {idempotency_key} not found for Merchant {merchant_id}")
        raise PaymentNotFound(merchant_id, idempotency_key)
    return payment


async def create_payment_with_history(payment, history, db: AsyncSession):
    db.add(payment)
    await db.flush()
    history.payment_id = payment.id
    db.add(history)
    await db.commit()
    logger.info(f"Created payment {payment.id} with history {history.id}")
    return payment


async def update_payment_status(payment: Payment, new_status: str, db: AsyncSession):
    if not payment:
        logger.warning(f"Payment {payment.id} not found for status update")
        raise PaymentNotFound(payment.id)
    payment.status = new_status
    payment.updated_at = datetime.now(timezone.utc)


async def create_payment_status_history(payment_id: uuid.UUID, from_status: str, to_status: str, triggered_by: str, reason: str, db: AsyncSession):
    history = PaymentStatusHistory(
        payment_id=payment_id,
        from_status=from_status,
        to_status=to_status,
        triggered_by=triggered_by,
        reason=reason
    )
    db.add(history)
    logger.info(f"Created payment status history {history.id} for payment {payment_id}")


async def create_ledger_transaction(payment_id: uuid.UUID, entry_type: str, description: str, effective_date: datetime | None, idempotency_key: str, db: AsyncSession):
    ledger_transaction = LedgerTransaction(
        payment_id=payment_id,
        entry_type=entry_type,
        description=description,
        effective_at=effective_date,
        idempotency_key=idempotency_key
    )
    db.add(ledger_transaction)
    logger.info(f"Created ledger transaction {ledger_transaction.id} for payment {payment_id}")
    return ledger_transaction

async def create_ledger_entry(db: AsyncSession, ledger_entries: list[LedgerEntry]):
    db.add_all(ledger_entries)
    logger.info(f"Created ledger entries for payment {ledger_entries[0].transaction_id} with {len(ledger_entries)} entries")

async def create_outbox_event(topic: str, payload: dict, aggregate_type: str, aggregate_id: uuid.UUID, db: AsyncSession):
    outbox_event = OutboxEvent(
        topic=topic,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id
    )
    db.add(outbox_event)
    db.flush()
    logger.info(f"Created outbox event {outbox_event.id} for aggregate {aggregate_type} with ID {aggregate_id}")

async def get_last_running_balance(db: AsyncSession, account_id: uuid.UUID) -> Decimal:
    result = await db.execute(
        select(LedgerEntry.running_balance)
        .where(LedgerEntry.account_id == account_id)
        .order_by(LedgerEntry.created_at.desc())
        .limit(1)
    )
    balance = result.scalar_one_or_none()
    return balance if balance is not None else Decimal("0.00")

async def get_payment_with_id(db: AsyncSession, payment_id: uuid.UUID):
    return await db.get(Payment,payment_id)