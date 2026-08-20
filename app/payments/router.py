from fastapi import APIRouter, Depends
from app.core.database import AsyncSession, get_db
from app.payments.service import initiate_payment
from app.schemas.payments import PaymentInitiateRequest, PaymentInitiateResponse
from app.core.logging import logger

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