from pydantic import BaseModel, Field
from uuid import UUID
from decimal import Decimal
from datetime import datetime

class PaymentInitiateRequest(BaseModel):
    merchant_id: UUID
    customer_id: UUID
    amount: Decimal
    currency: str = Field(default='INR')
    payment_method: str
    idempotency_key: str
    payment_method_meta: dict | None = None

class PaymentInitiateResponse(BaseModel):
    id: UUID = Field(alias='payment_id')
    merchant_id: UUID
    status: str
    amount: Decimal
    created_at: datetime

    class Config:
        from_attributes = True

class PaymentProcessRequest(BaseModel):
    payment_method_meta : dict | None = None

class PayemntProcessResponse(BaseModel):
    id: UUID
    status: str
    amount: Decimal
    currency: str
    processed_at: datetime

    class Config:
        from_attributes = True