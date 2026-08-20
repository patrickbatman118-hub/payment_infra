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
    payment_id: UUID
    status: str
    amount: Decimal
    created_at: datetime

    class config:
        from_attributes = True