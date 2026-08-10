# Import all models here so that:
# 1. Alembic autogenerate sees every table in Base.metadata
# 2. SQLAlchemy can resolve all cross-model relationship string references at mapper config time
# Import order follows foreign key dependency graph (referenced tables before referencing tables)

from app.models.merchant import Merchant, MerchantBankAccount  # noqa: F401
from app.models.customer import Customer  # noqa: F401
from app.models.auth import User, MerchantUser, Token  # noqa: F401
from app.models.payment import Payment, PaymentStatusHistory  # noqa: F401
from app.models.ledger import LedgerTransaction, LedgerEntry  # noqa: F401
from app.models.settlement import Settlement, SettlementPayment, SettlementStatusHistory  # noqa: F401
from app.models.dispute import Dispute, DisputeStatusHistory  # noqa: F401
from app.models.refund import Refund, RefundStatusHistory  # noqa: F401
from app.models.fraud import FraudScore  # noqa: F401
from app.models.outbox import OutboxEvent  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401

__all__ = [
    # Merchant
    "Merchant",
    "MerchantBankAccount",
    # Customer
    "Customer",
    # Auth
    "User",
    "MerchantUser",
    "Token",
    # Payment lifecycle
    "Payment",
    "PaymentStatusHistory",
    # Ledger (double-entry, bi-temporal)
    "LedgerTransaction",
    "LedgerEntry",
    # Settlement pipeline
    "Settlement",
    "SettlementPayment",
    "SettlementStatusHistory",
    # Disputes
    "Dispute",
    "DisputeStatusHistory",
    # Refunds
    "Refund",
    "RefundStatusHistory",
    # Supporting systems
    "FraudScore",
    "OutboxEvent",
    "AuditLog",
]
