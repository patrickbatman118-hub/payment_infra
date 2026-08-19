from app.core.database import AsyncSession, get_db
from app.core.exceptions import CustomerNotFound, MerchantNotFound, PaymentNotFound
from app.models.payment import Payment, PaymentStatusHistory
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.core.logging import logger
from sqlalchemy import select
import uuid


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
    db.add(history)
    await db.commit()
    logger.info(f"Created payment {payment.id} with history {history.id}")
    return payment
