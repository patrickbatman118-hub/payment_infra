from app.core.database import AsyncSession, get_db
from app.core.exceptions import MerchantNotFound, MerchantNotActive, KYCNotApproved, CustomerNotFound, CustomerBlocked, TransactionLimitExceeded, DuplicatePayment, PaymentNotFound, InvalidPaymentStatus
from app.models.payment import Payment, PaymentStatusHistory
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.core.logging import logger
from sqlalchemy import select
import uuid, decimal
from random import randint

from app.payments.repository import get_merchant, get_customer, get_payment, create_payment_with_history, update_payment_status, create_payment_status_history


async def initiate_payment(db: AsyncSession, merchant_id: uuid.UUID, customer_id: uuid.UUID, amount: decimal.Decimal, payment_method: str, idempotency_key: str, payment_method_meta: dict | None = None, currency: str = "INR") -> Payment:
    merchant = await get_merchant(merchant_id, db)
    if merchant.status != "active":
        logger.warning(f"Merchant {merchant_id} is not active")
        raise MerchantNotActive(merchant_id)
    if merchant.kyc_status != "verified":
        logger.warning(f"Merchant {merchant_id} KYC not approved")
        raise KYCNotApproved(merchant_id)
    if amount > merchant.max_transaction_amt:
        logger.warning(f"Transaction amount {amount} exceeds limit for merchant {merchant_id}")
        raise TransactionLimitExceeded(merchant_id, amount)
    customer = await get_customer(customer_id, merchant_id, db)
    if customer.is_blocked:
        logger.warning(f'Customer {customer_id} is blocked')
        raise CustomerBlocked(customer_id)
    if await get_payment(merchant_id, idempotency_key, db):
        logger.warning(f'Duplicate payment with idempotency key {idempotency_key} for Merchant {merchant_id}')
        raise DuplicatePayment(idempotency_key)
    payment = Payment(
                    merchant_id=merchant_id,
                    customer_id=customer_id,
                    amount=amount,
                    currency=currency,
                    status="initiated",
                    idempotency_key=idempotency_key,
                    payment_method=payment_method,
                    payment_method_meta=payment_method_meta
                )

    payment_history = PaymentStatusHistory(
        from_status=None,
        to_status="initiated",
        triggered_by="customer",
        reason="Payment initiated"
    )
    pay = await create_payment_with_history(payment, payment_history, db)
    logger.info(f"Payment initiated with id {pay.id} for Merchant {merchant_id} and Customer {customer_id}")
    return pay

async def process_payment(db: AsyncSession, payment_id: uuid.UUID):
    payment = await db.get(Payment, payment_id)
    if not payment:
        logger.warning(f"Payment {payment_id} not found for processing")
        raise PaymentNotFound(payment_id)
    merchant = await get_merchant(payment.merchant_id,db)
    if not merchant:
        logger.warning(f'Merchant {payment.merchant_id} not found')
        raise MerchantNotFound
    if payment.status != 'initiated':
        logger.warning(f'Payment is already {payment.status}')
        raise InvalidPaymentStatus
    async with db.begin():
        await update_payment_status(payment, 'processing')
        await create_payment_status_history(payment.id, 'initiated', 'processing', 'customer', 'payment', db)
        await db.commit()

    def gateway_call():
        output = ['success','failure']
        response = output[randint(0,1)]
        return response
    res = gateway_call()

    async with db.beign():
        if res == 'success':
            update_payment_status(payment, 'success')
            create_payment_status_history(payment.id, 'processing', 'success', 'customer', 'payment', db)
            platform_fee = payment.amount * merchant.fee_percentage
            merchant_receives = payment.amount - platform_fee



