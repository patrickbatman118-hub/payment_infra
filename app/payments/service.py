from app.core.database import AsyncSession
from app.core.config import settings
from app.core.exceptions import MerchantNotFound, MerchantNotActive, KYCNotApproved, CustomerNotFound, CustomerBlocked, TransactionLimitExceeded, DuplicatePayment, PaymentNotFound, InvalidPaymentStatus, LedgerImbalanceError
from app.models.payment import Payment, PaymentStatusHistory
from app.models.ledger import LedgerEntry
from app.core.logging import logger
import uuid, decimal
from datetime import datetime,timezone
import random

from app.payments.repository import get_merchant, get_customer, get_payment, create_payment_with_history, update_payment_status, create_payment_status_history, get_last_running_balance, create_ledger_transaction, create_ledger_entry, create_outbox_event
async def simulate_gateway_call(payment: Payment) -> dict:
    success = random.choice([True, False])
    return {
        "status": "success" if success else "failed",
        "gateway_payment_id": f"gw_{uuid.uuid4().hex[:16]}",
        "confirmed_at": datetime.now(timezone.utc),
        "raw_response": {"code": "00" if success else "51"}
    }

async def initiate_payment(db: AsyncSession, merchant_id: uuid.UUID, customer_id: uuid.UUID, amount: decimal.Decimal, payment_method: str, idempotency_key: str, payment_method_meta: dict | None = None, currency: str = "INR") -> Payment:
    merchant = await get_merchant(merchant_id, db)
    if not merchant:
        logger.warning(f'Merchant {merchant_id} not found')
        raise MerchantNotFound(merchant_id)
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
    payment = await create_payment_with_history(payment, payment_history, db)
    logger.info(f"Payment initiated with id {payment.id} for Merchant {merchant_id} and Customer {customer_id}")
    return payment

async def process_payment(db: AsyncSession, payment_id: uuid.UUID):
    payment = await db.get(Payment, payment_id)
    if not payment:
        logger.warning(f"Payment {payment_id} not found for processing")
        raise PaymentNotFound(payment_id)
    merchant = await get_merchant(payment.merchant_id,db)
    if not merchant:
        logger.warning(f'Merchant {payment.merchant_id} not found')
        raise MerchantNotFound(payment.merchant_id)
    if payment.status != 'initiated':
        logger.warning(f'Payment is already {payment.status}')
        raise InvalidPaymentStatus(payment.id)
    async with db.begin():
        await update_payment_status(payment, 'processing')
        await create_payment_status_history(payment.id, 'initiated', 'processing', 'system', 'Payment processing started', db)
        logger.info(f'payment {payment.id} status changed from initiated to processing')

    response = await simulate_gateway_call(payment)

    payload = {
    "payment_id": str(payment.id),
    "merchant_id": str(payment.merchant_id),
    "customer_id": str(payment.customer_id),
    "amount": str(payment.amount),
    "currency": payment.currency,
    }

    async with db.begin():
        if response['status'] == 'success':
            payment.gateway_payment_id = response['gateway_payment_id']
            payment.gateway_response = response['raw_response']
            payment.processed_at = datetime.now(timezone.utc)

            await update_payment_status(payment, 'success')
            await create_payment_status_history(payment.id, 'processing', 'success', 'system', 'Gateway confirmed payment', db)

            platform_fee = payment.amount * merchant.fee_percentage
            merchant_receives = payment.amount - platform_fee

            customer_balance = await get_last_running_balance(db, payment.customer_id)
            merchant_balance = await get_last_running_balance(db, payment.merchant_id)
            platform_balance = await get_last_running_balance(db, settings.platform_account_id)

            ledger_tx = await create_ledger_transaction(payment.id, 'payment', 'Gateway confirmed payment', response['confirmed_at'], payment.idempotency_key, db)
            total_debits = payment.amount
            total_credits = merchant_receives + platform_fee

            if total_debits != total_credits:
                logger.error("Ledger imbalance detected", extra={"payment_id": str(payment.id),"total_debits": str(total_debits),"total_credits": str(total_credits)})
                raise LedgerImbalanceError(payment.id, total_debits, total_credits)

            entries = [
                LedgerEntry(
                    ledger_transaction_id = ledger_tx.id,
                    account_type = 'customer',
                    account_id = payment.customer_id,
                    direction = 'debit',
                    amount = payment.amount,
                    currency = payment.currency,
                    running_balance = customer_balance - payment.amount
                ),
                LedgerEntry(
                    ledger_transaction_id = ledger_tx.id,
                    account_type = 'merchant',
                    account_id = payment.merchant_id,
                    direction = 'credit',
                    amount = merchant_receives,
                    currency = payment.currency,
                    running_balance = merchant_balance + merchant_receives
                ),
                LedgerEntry(
                    ledger_transaction_id = ledger_tx.id,
                    account_type = 'platform',
                    account_id = settings.platform_account_id,
                    direction = 'credit',
                    amount = platform_fee,
                    currency = payment.currency,
                    running_balance = platform_balance + platform_fee
                )
            ]
            await create_ledger_entry(db, entries)
            await create_outbox_event('payment.success', payload, 'payment', payment.id, db)
            logger.info(f'payment successful with id: {payment.id}')
        else:
            await update_payment_status(payment, 'failed')
            await create_payment_status_history(payment.id, 'processing', 'failed', 'system', 'Gateway rejected payment', db)
            await create_outbox_event('payment.failed', payload, 'payment', payment.id, db)
            logger.info(f'payment failed with id: {payment.id}')
    return payment





