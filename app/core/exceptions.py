
from uuid import UUID
from fastapi import Request
from fastapi.responses import JSONResponse


class PaymentInfraException(Exception):
    pass

class MerchantNotFound(PaymentInfraException):
    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} not found")

class MerchantAlreadyExists(PaymentInfraException):
    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Merchant with email {email} already exists")

class MerchantNotActive(PaymentInfraException):
    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} is not active")

class KYCNotApproved(PaymentInfraException):
    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} KYC not approved")

class CustomerNotFound(PaymentInfraException):
    def __init__(self, customer_id: UUID):
        self.customer_id = customer_id
        super().__init__(f"Customer {customer_id} not found")

class CustomerBlocked(PaymentInfraException):
    def __init__(self, customer_id: UUID):
        self.customer_id = customer_id
        super().__init__(f"Customer {customer_id} is blocked")

class TransactionLimitExceeded(PaymentInfraException):
    def __init__(self, merchant_id: UUID, amount: float):
        self.merchant_id = merchant_id
        self.amount = amount
        super().__init__(f"Transaction amount {amount} exceeds limit for merchant {merchant_id}")

class PaymentNotFound(PaymentInfraException):
    def __init__(self, merchant_id: UUID, idempotency_key: UUID):
        self.merchant_id = merchant_id
        self.idempotency_key = idempotency_key
        super().__init__(f"Payment with idempotency key {idempotency_key} not found for Merchant {merchant_id}")

class DuplicatePayment(PaymentInfraException):
    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f"Duplicate payment {payment_id}")

class InvalidPaymentStatus(PaymentInfraException):
    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f'Invalid status for {payment_id}')


async def payment_infra_exception_handler(request: Request, exc: PaymentInfraException):
    status_codes = {
        MerchantNotFound: 404,
        MerchantAlreadyExists: 409,
        MerchantNotActive: 403,
        KYCNotApproved: 403,
        CustomerNotFound: 404,
        CustomerBlocked: 403,
        TransactionLimitExceeded: 422,
        PaymentNotFound: 404,
        DuplicatePayment: 409,
        InvalidPaymentStatus: 502
    }
    
    status_code = status_codes.get(type(exc), 500)
    
    return JSONResponse(
        status_code=status_code,
        content={"Message": str(exc)}
    )

