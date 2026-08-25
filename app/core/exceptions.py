from uuid import UUID
from fastapi import Request
from fastapi.responses import JSONResponse
from decimal import Decimal


class PaymentInfraException(Exception):
    status_code: int = 500


class MerchantNotFound(PaymentInfraException):
    status_code: int = 404

    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} not found")


class MerchantAlreadyExists(PaymentInfraException):
    status_code: int = 409

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Merchant with email {email} already exists")


class MerchantNotActive(PaymentInfraException):
    status_code: int = 403

    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} is not active")


class KYCNotApproved(PaymentInfraException):
    status_code: int = 403

    def __init__(self, merchant_id: UUID):
        self.merchant_id = merchant_id
        super().__init__(f"Merchant {merchant_id} KYC not approved")


class CustomerNotFound(PaymentInfraException):
    status_code: int = 404

    def __init__(self, customer_id: UUID):
        self.customer_id = customer_id
        super().__init__(f"Customer {customer_id} not found")


class CustomerBlocked(PaymentInfraException):
    status_code: int = 403

    def __init__(self, customer_id: UUID):
        self.customer_id = customer_id
        super().__init__(f"Customer {customer_id} is blocked")


class TransactionLimitExceeded(PaymentInfraException):
    status_code: int = 422

    def __init__(self, merchant_id: UUID, amount: Decimal):
        self.merchant_id = merchant_id
        self.amount = amount
        super().__init__(f"Transaction amount {amount} exceeds limit for merchant {merchant_id}")


class PaymentNotFound(PaymentInfraException):
    status_code: int = 404

    def __init__(self, payment_id):
        self.payment_id = payment_id
        super().__init__(f"Payment with id {payment_id} not found")


class DuplicatePayment(PaymentInfraException):
    status_code: int = 409

    def __init__(self, idempotency_key: str):
        self.idempotency_key = idempotency_key
        super().__init__(f"Duplicate payment {idempotency_key}")


class InvalidPaymentStatus(PaymentInfraException):
    status_code: int = 409

    def __init__(self, payment_id: UUID):
        self.payment_id = payment_id
        super().__init__(f'Invalid status for {payment_id}')


class LedgerImbalanceError(PaymentInfraException):
    status_code: int = 500

    def __init__(self, payment_id: UUID, total_debits: Decimal, total_credits: Decimal):
        self.payment_id = payment_id
        self.total_debits = total_debits
        self.total_credits = total_credits
        super().__init__(
            f'Ledger Imbalance Detected, Payment:{payment_id}, Total_Debits: {total_debits}, Total_Credits: {total_credits}')


async def payment_infra_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=getattr(exc, 'status_code', 500),
        content={"Message": str(exc)}
    )


class AuthException(Exception):
    status_code = 401
    pass


class UserEmailAlreadyExists(AuthException):
    status_code = 409

    def __init__(self, email: str):
        self.email = email
        super().__init__(f'User with email {email} already exists')


class UserNotFound(AuthException):
    status_code = 404
    detail = 'User not found'


class InvalidCredentials(AuthException):
    status_code = 401
    detail = 'Invalid credentials'


class TokenNotFound(AuthException):
    status_code = 404
    detail = 'Token not found'


async def auth_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=getattr(exc, 'status_code', 401),
        content={'Message': getattr(exc, 'detail', str(exc))}
    )
