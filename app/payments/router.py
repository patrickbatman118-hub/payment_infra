from fastapi import APIRouter, Depends, Body
from app.core.database import AsyncSession, get_db
from app.payments.service import initiate_payment, process_payment
from app.schemas.payments import PaymentInitiateRequest, PaymentInitiateResponse, PaymentProcessRequest, \
    PayemntProcessResponse
from app.payments.repository import get_payment_with_id
from app.core.logging import logger
import uuid

router = APIRouter(tags=['Payments'])


@router.post('/payments/initiate', response_model=PaymentInitiateResponse)
async def initiate_payment_endpoint(request: PaymentInitiateRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f"Initiating payment for Merchant {request.merchant_id} and Customer {request.customer_id}")
    return await initiate_payment(
        merchant_id=request.merchant_id,
        customer_id=request.customer_id,
        amount=request.amount,
        payment_method=request.payment_method,
        idempotency_key=request.idempotency_key,
        payment_method_meta=request.payment_method_meta,
        currency=request.currency,
        db=db
    )


@router.post('/payments/{payment_id}/process', response_model=PayemntProcessResponse)
async def process_payment_request(payment_id: uuid.UUID, request: PaymentProcessRequest | None = Body(default=None),
                                  db: AsyncSession = Depends(get_db)):
    logger.info(f'Processing payment for payment: {payment_id}')
    return await process_payment(db, payment_id)


@router.get('/payments/{payment_id}', response_model=PayemntProcessResponse)
async def get_payment_details(payment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await get_payment_with_id(db, payment_id)
