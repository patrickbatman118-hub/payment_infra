
from uuid import UUID
from fastapi import Request
from fastapi.responses import JSONResponse
from decimal import Decimal

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
    def __init__(self, payment_id):
        self.payment_id = payment_id
        super().__init__(f"Payment with id {payment_id} not found")

class DuplicatePayment(PaymentInfraException):
    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f"Duplicate payment {payment_id}")

class InvalidPaymentStatus(PaymentInfraException):
    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f'Invalid status for {payment_id}')

class LedgerImbalanceError(PaymentInfraException):
    def __init__(self, payment_id: UUID, total_debits: Decimal, total_credits: Decimal):
        self.payment_id = payment_id
        self.total_debits = total_debits
        self.total_credits = total_credits
        super().__init__(f'Ledger Imbalance Detected, Payment:{payment_id}, Total_Debits: {total_debits}, Total_Credits: {total_credits}')

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
        InvalidPaymentStatus: 409,
        LedgerImbalanceError: 500,
    }
    
    status_code = status_codes.get(type(exc), 500)
    
    return JSONResponse(
        status_code=status_code,
        content={"Message": str(exc)}
    )

