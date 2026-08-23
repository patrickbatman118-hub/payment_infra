# Transaction Engine

> **Files:** `app/payments/service.py` · `app/payments/repository.py` · `app/core/exceptions.py`

The transaction engine is responsible for the full lifecycle of a payment — from pre-authorization checks through gateway processing to double-entry ledger settlement and event emission. It is designed around three principles: **strict state machine enforcement**, **atomic multi-table writes**, and **guaranteed event delivery** via the transactional outbox pattern.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Payment Lifecycle](#payment-lifecycle)
3. [service.py](#servicepy)
4. [repository.py](#repositorypy)
5. [Atomicity and Transaction Design](#atomicity-and-transaction-design)
6. [Double-Entry Ledger](#double-entry-ledger)
7. [Bi-Temporal Timestamps](#bi-temporal-timestamps)
8. [Exception Handling](#exception-handling)

---

## Architecture

The engine is split into two layers with a strict separation of concerns:

| Layer | File | Role |
|---|---|---|
| **Service** | `service.py` | Business rules, state machine transitions, orchestration |
| **Repository** | `repository.py` | All database writes — no business logic, no decisions |

The service layer decides *whether* and *when* to write. The repository layer decides *how* to write. This means the repository functions are unit-testable against a mocked session, and the service functions can be read as a plain-English description of what the system does at each step.

---

## Payment Lifecycle

A payment moves through a defined set of states. Each transition is recorded in `payment_status_history` — the `payments` table holds only the current state.

```
                 ┌───────────────────────────────────────┐
                 │                                       │
[Customer] ──▶  initiated ──▶  processing ──▶  success  │
                                    │                   │
                                    └──────▶  failed    │
                                                        │
                              (future: disputed, refunded)
```

The `initiated → processing` and `processing → success|failed` transitions happen in **separate database transactions**, with the gateway call between them. This design is covered in detail in [Atomicity and Transaction Design](#atomicity-and-transaction-design).

### Full Sequence: `initiate_payment` → `process_payment`

```
Customer          Router          service.py        repository.py        PostgreSQL        Gateway
   │                │                 │                   │                   │               │
   │─POST /initiate▶│                 │                   │                   │               │
   │                │─initiate_pay()─▶│                   │                   │               │
   │                │                 │─get_merchant()───▶│──SELECT────────▶  │               │
   │                │                 │─get_customer()───▶│──SELECT────────▶  │               │
   │                │                 │─get_payment()────▶│──SELECT────────▶  │               │
   │                │                 │─create_with_hist─▶│──INSERT+flush──▶  │               │
   │                │                 │                   │──INSERT+commit─▶  │               │
   │◀─200 Payment───│                 │                   │                   │               │
   │                │                 │                   │                   │               │
   │─POST /process─▶│                 │                   │                   │               │
   │                │─process_pay()──▶│                   │                   │               │
   │                │                 │── TX 1 BEGIN ─────────────────────────│               │
   │                │                 │─update_status────▶│──UPDATE────────▶  │               │
   │                │                 │─create_history───▶│──INSERT────────▶  │               │
   │                │                 │── TX 1 COMMIT ────────────────────────│               │
   │                │                 │                   │                   │               │
   │                │                 │────────────────── gateway call ───────────────────────▶
   │                │                 │◀─────────────────── response ─────────────────────────│
   │                │                 │                   │                   │               │
   │                │                 │── TX 2 BEGIN ─────────────────────────│               │
   │                │                 │─update_status────▶│──UPDATE────────▶  │               │
   │                │                 │─create_history───▶│──INSERT────────▶  │               │
   │                │                 │─get_balances×3───▶│──SELECT×3──────▶  │               │
   │                │                 │─create_ledger_tx─▶│──INSERT────────▶  │               │
   │                │                 │─create_entries───▶│──INSERT×3──────▶  │               │
   │                │                 │─create_outbox────▶│──INSERT────────▶  │               │
   │                │                 │── TX 2 COMMIT ────────────────────────│               │
   │◀─200 Payment───│                 │                   │                   │               │
```

---

## `service.py`

---

### `simulate_gateway_call`

```python
async def simulate_gateway_call(payment: Payment) -> dict
```

**What it does:**
Stubs the external payment gateway network call. Returns a response dict with a random success/failure outcome, a `gateway_payment_id` in `gw_<hex16>` format, a UTC `confirmed_at` timestamp, and a raw response code (`"00"` = approved, `"51"` = declined).

**Why it exists:**
The gateway call is a pluggable boundary — the surrounding code in `process_payment` consumes a standard response shape regardless of which gateway adapter sits underneath. When the real adapter is wired in, only this function changes. The `confirmed_at` field returned here becomes `LedgerTransaction.effective_at` — the bi-temporal anchor for settlement batching.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `payment` | `Payment` | The payment being processed; passed for context (amount, currency, merchant) available to a real gateway adapter |

**Returns:** `dict` — `{ status, gateway_payment_id, confirmed_at, raw_response }`

---

### `initiate_payment`

```python
async def initiate_payment(
    db: AsyncSession,
    merchant_id: uuid.UUID,
    customer_id: uuid.UUID,
    amount: decimal.Decimal,
    payment_method: str,
    idempotency_key: str,
    payment_method_meta: dict | None = None,
    currency: str = "INR"
) -> Payment
```

**What it does:**
Validates all pre-conditions for a new payment, then atomically creates the `Payment` record and its first `PaymentStatusHistory` row (`from_status=None → to_status="initiated"`). Returns the persisted `Payment` with its DB-assigned UUID.

**Why it exists:**
Initiation is separated from processing by design. Initiation is synchronous and fast — it validates inputs and commits a payment record the system can track. Processing involves a blocking gateway call that may take hundreds of milliseconds or time out. This split allows the API to return a stable `payment_id` immediately, supporting webhook-driven and async processing flows.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `AsyncSession` | SQLAlchemy async session; session lifecycle owned by the caller |
| `merchant_id` | `UUID` | Must exist, be `status="active"`, and have `kyc_status="verified"` |
| `customer_id` | `UUID` | Must belong to the merchant (enforced by composite `customer_id + merchant_id` lookup) and must not be blocked |
| `amount` | `Decimal` | Payment amount; validated against `merchant.max_transaction_amt` |
| `payment_method` | `str` | `"upi"`, `"card"`, `"netbanking"`, `"wallet"` |
| `idempotency_key` | `str` | Client-supplied key; uniqueness enforced by `(merchant_id, idempotency_key)` DB constraint |
| `payment_method_meta` | `dict \| None` | Card last 4 digits, UPI handle — never raw card numbers (PCI DSS) |
| `currency` | `str` | Defaults to `"INR"` |

**Returns:** `Payment` — persisted with `id`, `status="initiated"`, `initiated_at` set by `NOW()`.

**Exceptions:**

| Exception | HTTP | Condition |
|---|---|---|
| `MerchantNotFound` | 404 | `merchant_id` has no row |
| `MerchantNotActive` | 403 | `merchant.status != "active"` |
| `KYCNotApproved` | 403 | `merchant.kyc_status != "verified"` — legal requirement before live transactions |
| `TransactionLimitExceeded` | 422 | `amount > merchant.max_transaction_amt` |
| `CustomerNotFound` | 404 | No customer for `(customer_id, merchant_id)` |
| `CustomerBlocked` | 403 | `customer.is_blocked = True` |
| `DuplicatePayment` | 409 | `(merchant_id, idempotency_key)` already exists |

**Validation order:**
Merchant eligibility is checked before customer eligibility. A request from a suspended merchant is rejected at the merchant gate regardless of the customer's state — the more fundamental authorization failure surfaces first.

---

### `process_payment`

```python
async def process_payment(db: AsyncSession, payment_id: uuid.UUID) -> Payment
```

**What it does:**
Drives a payment through `initiated → processing → success|failed`. This is the core of the transaction engine — it owns two separate database transactions, a gateway call between them, and up to nine individual writes on the success path.

**Why it exists:**
The gateway call is an irreversible external side effect. Once the bank charges the customer, the local database must always be updated to reflect that — regardless of whether an earlier attempt partially succeeded. The two-transaction design ensures the database is always in a consistent state relative to whatever the gateway did, even in the presence of crashes or timeouts.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `db` | `AsyncSession` | Session shared across both transactions in this invocation |
| `payment_id` | `UUID` | Must identify a `Payment` in `status="initiated"` |

**Returns:** `Payment` — with final `status="success"` or `status="failed"`, and gateway fields populated.

**Exceptions:**

| Exception | HTTP | Condition |
|---|---|---|
| `PaymentNotFound` | 404 | No payment row for `payment_id` |
| `MerchantNotFound` | 404 | Merchant deleted after initiation |
| `InvalidPaymentStatus` | 502 | Payment is not in `"initiated"` state — state machine guard |
| `LedgerImbalanceError` | 500 | `total_debits != total_credits` before writing ledger entries |

**State machine guard:**
The check `payment.status != 'initiated'` prevents a retry of `process_payment` on an already-processed payment from issuing a second gateway charge and creating duplicate ledger entries. A `processing` payment cannot be re-entered from this path — recovery of stalled `processing` payments is handled by a dedicated recovery service.

---

## `repository.py`

---

### `get_merchant`

```python
async def get_merchant(merchant_id: uuid.UUID, db: AsyncSession) -> Merchant
```

**What it does:**
Fetches a `Merchant` by primary key via `db.get()`, which checks SQLAlchemy's identity map (session cache) before hitting the database. Raises `MerchantNotFound` if absent.

**Why it exists:**
Centralises merchant retrieval. Any change to the fetch strategy — for example adding `with_for_update()` for pessimistic locking during settlement — is made in one place with no call-site changes.

**Returns:** `Merchant`  
**Exceptions:** `MerchantNotFound` (404)

---

### `get_customer`

```python
async def get_customer(customer_id: uuid.UUID, merchant_id: uuid.UUID, db: AsyncSession) -> Customer
```

**What it does:**
Queries `customers` with a composite `WHERE customer_id = ? AND merchant_id = ?` filter.

**Why it exists:**
The `merchant_id` join enforces merchant-scoped data isolation at the data layer. A merchant cannot resolve another merchant's customer UUID even if it is known at the API layer — the authorization boundary is in the query, not just the route.

**Returns:** `Customer`  
**Exceptions:** `CustomerNotFound` (404)

---

### `get_payment`

```python
async def get_payment(merchant_id: uuid.UUID, idempotency_key: str, db: AsyncSession) -> Payment | None
```

**What it does:**
Looks up a `Payment` by `(merchant_id, idempotency_key)` — the same composite covered by the `uq_payments_merchant_idempotency` unique constraint. Returns `None` if not found.

**Why it exists:**
Application-layer idempotency check. The DB constraint is the final guarantee against concurrent duplicate inserts (raising `IntegrityError`), but this pre-check in `initiate_payment` allows a clean `DuplicatePayment` 409 to be returned to the client before attempting a conflicting insert.

**Returns:** `Payment | None`

---

### `create_payment_with_history`

```python
async def create_payment_with_history(payment: Payment, history: PaymentStatusHistory, db: AsyncSession) -> Payment
```

**What it does:**
Adds `Payment` to the session, flushes to materialise its DB-generated UUID, sets `history.payment_id`, adds `PaymentStatusHistory`, then commits both in a single transaction.

**Why it exists:**
`PaymentStatusHistory.payment_id` is a non-nullable foreign key. `flush()` sends the `Payment` INSERT to Postgres within the open transaction — without committing — so that the DB-assigned `id` is available to set on the history row before the final commit.

```
db.add(payment)
await db.flush()              ← INSERT reaches Postgres; payment.id is now a real UUID
history.payment_id = payment.id
db.add(history)
await db.commit()             ← both rows committed atomically
```

**Returns:** `Payment` — with `id` populated.

---

### `update_payment_status`

```python
async def update_payment_status(payment: Payment, new_status: str, db: AsyncSession)
```

**What it does:**
Mutates `payment.status` and stamps `payment.updated_at` with the current UTC time in-memory. SQLAlchemy's unit-of-work tracks the change and issues the `UPDATE` when the enclosing `db.begin()` block commits.

**Why it exists:**
Centralises `updated_at` stamping so no call site can omit it. Keeping the mutation in-session (no explicit `db.add()`) means the status change is part of the same transaction as the history row and outbox event written around it.

**Returns:** `None`

---

### `create_payment_status_history`

```python
async def create_payment_status_history(
    payment_id: uuid.UUID,
    from_status: str,
    to_status: str,
    triggered_by: str,
    reason: str,
    db: AsyncSession
)
```

**What it does:**
Constructs a `PaymentStatusHistory` row recording a single state transition and adds it to the session. Committed by the surrounding transaction block.

**Why it exists:**
`payments.status` holds only the current state. `PaymentStatusHistory` is the append-only audit trail — every transition is recorded with who triggered it, from what state, to what state, and why. This table provides the evidence chain for disputes and compliance audits: the exact actor, timestamp, and reason for each status change on every payment.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `payment_id` | `UUID` | FK to `payments.id` |
| `from_status` | `str` | Previous state |
| `to_status` | `str` | New state |
| `triggered_by` | `str` | `"customer"`, `"system"`, `"merchant"`, `"platform_admin"` |
| `reason` | `str` | Human-readable explanation for audit and dispute resolution |

**Returns:** `None`

---

### `create_ledger_transaction`

```python
async def create_ledger_transaction(
    payment_id: uuid.UUID,
    entry_type: str,
    description: str,
    effective_date: datetime,
    idempotency_key: str,
    db: AsyncSession
) -> LedgerTransaction
```

**What it does:**
Creates the parent `LedgerTransaction` row — the record of *why* money moved. Returns the object so child `LedgerEntry` rows can reference its `id`.

**Why it exists:**
The ledger is normalised into two tables: `LedgerTransaction` records the economic event; `LedgerEntry` records the debit/credit lines. This separation means future entry types (settlement, adjustment, refund) share the same entry structure without requiring payment-specific columns on the entry rows.

**`effective_at` — bi-temporal anchor:**
`effective_date` is the bank's confirmation timestamp from the gateway response. It becomes `LedgerTransaction.effective_at`, which determines which settlement batch this transaction belongs to. See [Bi-Temporal Timestamps](#bi-temporal-timestamps).

**Idempotency on the ledger:**
`idempotency_key` maps to a `UNIQUE` column on `LedgerTransaction`. A retry after a gateway success but before DB commit fails at this INSERT with a unique constraint violation rather than producing a duplicate ledger event — the final defense against double-crediting a merchant.

**Returns:** `LedgerTransaction` — `id` is the Python-level UUID from `default=uuid.uuid4`, usable as a FK reference within the same session before flush.

---

### `create_ledger_entry`

```python
async def create_ledger_entry(db: AsyncSession, ledger_entries: list[LedgerEntry]) -> None
```

**What it does:**
Bulk-adds all `LedgerEntry` rows to the session via `db.add_all()`. No flush or commit — entries are written with the surrounding transaction.

**Why it exists:**
The three entries of a payment's double-entry record must commit atomically with each other, the `LedgerTransaction`, the payment status update, and the outbox event. `add_all()` signals that these entries are a logical set.

**Returns:** `None`

---

### `create_outbox_event`

```python
async def create_outbox_event(
    topic: str,
    payload: dict,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    db: AsyncSession
) -> None
```

**What it does:**
Creates an `OutboxEvent` row with `status="pending"` inside the current transaction. A separate outbox worker polls `outbox_events WHERE status='pending'`, publishes to Kafka, then marks rows `status='published'`.

**Why it exists:**
This is the **Transactional Outbox Pattern** — the standard solution to the dual-write problem in event-driven systems. Writing the event inside the same transaction as the payment data means both commit together or roll back together. Kafka delivery is decoupled to the outbox worker, which retries independently of the payment flow. This eliminates the risk of a committed payment with no downstream event, or a Kafka event for a transaction that never committed.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `topic` | `str` | Kafka topic — `"payment.success"` or `"payment.failed"` |
| `payload` | `dict` | `{ payment_id, merchant_id, customer_id, amount, currency }` |
| `aggregate_type` | `str` | `"payment"` — domain object identifier for the outbox worker |
| `aggregate_id` | `UUID` | `payment.id` — downstream consumers use this to load full payment state |

**Returns:** `None`

---

### `get_last_running_balance`

```python
async def get_last_running_balance(db: AsyncSession, account_id: uuid.UUID) -> Decimal
```

**What it does:**
Queries `ledger_entries` for the most recent `running_balance` for a given `account_id`, ordered by `created_at DESC`, limit 1, with `SELECT ... FOR UPDATE` to prevent concurrent reads from racing on the same balance base. Returns `Decimal("0.00")` for accounts with no prior entries.

**Why it exists:**
`LedgerEntry.running_balance` is a denormalised balance snapshot — each entry stores the account balance after that entry is applied. Instead of summing all historical entries on every payment, each new entry reads the prior entry's balance and adjusts by its amount. This makes balance lookups O(1) while the full entry stream remains available for audit recomputation.

**Returns:** `Decimal` — the account's balance after its most recent entry, or `0.00` for new accounts.

---

### `get_payment_with_id`

```python
async def get_payment_with_id(db: AsyncSession, payment_id: uuid.UUID) -> Payment | None
```

**What it does:**
Fetches a `Payment` by primary key. Returns `None` if not found.

**Why it exists:**
Used by the `GET /payments/{id}` route, where returning `None` (handled as a 404 at the router) is the appropriate behaviour. The service layer uses `db.get()` directly in `process_payment` because it needs the payment object to construct a meaningful `PaymentNotFound`.

**Returns:** `Payment | None`

---

## Atomicity and Transaction Design

### Two-Transaction Architecture

`process_payment` uses two committed transactions with the gateway call between them:

```
TX 1: initiated → processing
        │
        └─ COMMIT  ←── payment is durable as "processing"
               │
               ▼  gateway call  (external network I/O, no DB transaction held)
               │
TX 2: processing → success | failed  (7 writes)
        │
        └─ COMMIT
```

**Why the gateway call must not hold a transaction open:**
A gateway call takes 200ms–2s under normal conditions and can stall much longer. Holding a Postgres transaction open for that duration locks the payment row, occupies a connection pool slot, and blocks every other operation touching that row. Under load, a wave of slow gateway calls fills the connection pool and cascades into unrelated payment failures.

**Why `processing` is a committed state:**
If the service crashes after the gateway confirms a charge but before TX 2 commits, the payment is durable in `processing`. A recovery service can query `WHERE status = 'processing' AND updated_at < NOW() - INTERVAL '5 minutes'` and use `gateway_payment_id` to check the gateway's record of the outcome. Without a committed `processing` row, a recovery job cannot distinguish *"gateway was never called — safe to retry"* from *"gateway charged the customer and we lost the response — must check before retrying."*

### The Nine Writes on the Success Path

| # | Table | Write | Transaction |
|---|---|---|---|
| 1 | `payments` | `status = 'processing'`, `updated_at = NOW()` | TX 1 |
| 2 | `payment_status_history` | `initiated → processing`, `triggered_by = system` | TX 1 |
| 3 | `payments` | `status = 'success'`, `gateway_payment_id`, `processed_at` | TX 2 |
| 4 | `payment_status_history` | `processing → success`, `triggered_by = system` | TX 2 |
| 5 | `ledger_transactions` | parent event row, `effective_at = gateway_confirmed_at` | TX 2 |
| 6 | `ledger_entries` | customer debit | TX 2 |
| 7 | `ledger_entries` | merchant credit | TX 2 |
| 8 | `ledger_entries` | platform fee credit | TX 2 |
| 9 | `outbox_events` | `topic = payment.success`, `status = pending` | TX 2 |

All seven writes in TX 2 are enclosed in a single `async with db.begin()` block. Postgres commits them together or rolls them all back — there is no state where the payment is `success` without ledger entries, or ledger entries exist without an outbox event.

---

## Double-Entry Ledger

Every successful payment produces exactly three `LedgerEntry` rows under one `LedgerTransaction`. The entries implement double-entry bookkeeping: every rupee leaving one account must arrive in another, with the platform fee as the split point.

### Fee Calculation

For a payment of ₹1,000 with `merchant.fee_percentage = 0.02` (2%):

```
platform_fee      = 1,000 × 0.02 = ₹20
merchant_receives = 1,000 − 20   = ₹980
```

### The Three Entries

| Entry | `account_type` | `direction` | `amount` | `running_balance` |
|---|---|---|---|---|
| 1 | `customer` | `debit` | ₹1,000 | `prev_customer_balance − 1,000` |
| 2 | `merchant` | `credit` | ₹980 | `prev_merchant_balance + 980` |
| 3 | `platform` | `credit` | ₹20 | `prev_platform_balance + 20` |

**Balance invariant:**
```
Total debits  = ₹1,000
Total credits = ₹980 + ₹20 = ₹1,000
∴ debits == credits  ✓
```

The engine asserts this before writing — a `LedgerImbalanceError` is raised and the entire TX 2 is rolled back if the invariant fails.

### Running Balance Construction

```python
customer_balance = await get_last_running_balance(db, payment.customer_id)

LedgerEntry(
    direction       = 'debit',
    amount          = payment.amount,
    running_balance = customer_balance - payment.amount   # computed before INSERT
)
```

Each entry's `running_balance` is the previous balance adjusted by the current entry's amount. This turns the ledger into a chain of balance snapshots — any point-in-time balance is readable by fetching the entry at that timestamp, without aggregating the full history.

### Schema Normalisation

`LedgerEntry` rows have no `payment_id` column. Entries reference `ledger_transaction_id`; `LedgerTransaction` references `payment_id`. To get all ledger entries for a payment:

```sql
SELECT le.*
FROM ledger_entries le
JOIN ledger_transactions lt ON lt.id = le.ledger_transaction_id
WHERE lt.payment_id = '<payment_uuid>';
```

This means future entry types — settlement transfers, fee adjustments, refund reversals — share the same entry structure with no nullable FKs and no schema changes.

---

## Bi-Temporal Timestamps

`LedgerTransaction` carries two timestamps with distinct meanings:

| Field | Set by | Meaning |
|---|---|---|
| `effective_at` | `response['confirmed_at']` — from the gateway | **When the money movement economically happened** — determines settlement batch |
| `recorded_at` | `server_default = NOW()` set by Postgres at INSERT | **When this system wrote the row** — system audit trail |

### Why Both Fields Are Required

Consider a payment completed at **23:59:30** that the gateway confirms at **00:00:45** the following day (common with interbank processing delays):

- `effective_at = 23:59:30` → belongs in **today's** T+1 settlement batch → merchant receives payout tomorrow
- `recorded_at = 00:00:45` → when the system recorded it

If only `recorded_at` existed, the settlement ETL would place this payment in the next day's batch — a full day's payout delay for the merchant on a payment that completed before midnight. `effective_at` anchors the economic event to the bank's confirmed time, ensuring correct settlement regardless of processing latency.

---

## Exception Handling

All domain errors in the payment engine are typed subclasses of `PaymentInfraException`. They are raised at the point of failure with full entity context, propagate unhandled through the service and repository layers, and are resolved by a single FastAPI exception handler registered in `main.py`.

### Class Hierarchy

```
Exception
└── PaymentInfraException          ← registered with FastAPI
    ├── MerchantNotFound
    ├── MerchantAlreadyExists
    ├── MerchantNotActive
    ├── KYCNotApproved
    ├── CustomerNotFound
    ├── CustomerBlocked
    ├── TransactionLimitExceeded
    ├── PaymentNotFound
    ├── DuplicatePayment
    ├── InvalidPaymentStatus
    └── LedgerImbalanceError
```

### HTTP Status Mapping

```python
# core/exceptions.py — payment_infra_exception_handler
status_codes = {
    MerchantNotFound:         404,   # entity does not exist
    MerchantAlreadyExists:    409,   # duplicate registration
    MerchantNotActive:        403,   # merchant operationally suspended
    KYCNotApproved:           403,   # KYC not complete — legal block
    CustomerNotFound:         404,
    CustomerBlocked:          403,   # compliance / fraud block
    TransactionLimitExceeded: 422,   # valid request, exceeds per-merchant risk ceiling
    PaymentNotFound:          404,
    DuplicatePayment:         409,   # same idempotency key submitted twice
    InvalidPaymentStatus:     502,   # payment not in the expected state
    LedgerImbalanceError:     500,   # debits ≠ credits — accounting invariant violated
}
```

### Response Envelope

Every domain error returns the same JSON structure:

```json
{ "Message": "Merchant abc-123 is not active" }
```

The message is `str(exc)`, which is the `super().__init__()` string set in each exception's constructor. The entity ID and failure reason are embedded at the raise site — nothing is hardcoded in the handler.

### Design Rationale

**No try/except in service or repository code.**
Service and repository functions raise and let exceptions propagate. The handler at the application boundary is the single catch point. Business logic stays free of error-handling boilerplate, and every exception path is traceable from raise site to HTTP response in one step.

**Context carried on the exception object.**
Each exception stores the relevant entity — `MerchantNotActive(merchant_id)` sets `self.merchant_id`, `TransactionLimitExceeded(merchant_id, amount)` sets both. Logging middleware and monitoring tools can inspect the exception object directly rather than parsing the message string.

**Unhandled exception fallback:**

```python
# main.py
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"message": "Internal server error"})
```

Any exception that is not a `PaymentInfraException` — database constraint violations, network failures, unexpected runtime errors — is caught here. The raw exception is logged for alerting and internal debugging. The client receives a generic 500 with no internal detail — stack traces, SQL, and schema information are never surfaced to API consumers.
