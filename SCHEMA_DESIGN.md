# Payment Processing Infrastructure — Schema Design

> **What this document is:**
> Complete schema design reference for a Razorpay-like payment processing backend.
> Written for three audiences — a new chat session continuing this project, a future interviewer
> reading the GitHub repo, and the author returning after months away.
>
> **What this document is not:**
> Application code, API design, or deployment config. Those live in separate documents.

---

## Project Context

This is a payment processing infrastructure — the engine that sits behind payments, not a user wallet or dashboard. Think Razorpay's core backend, not the merchant's frontend.

**What it processes:**
- Merchant onboarding and KYC
- Customer payments with full state machine
- Double-entry ledger for every rupee movement
- Nightly settlement pipeline per merchant
- Dispute and refund lifecycle
- Fraud scoring per transaction
- JWT auth with token attenuation and cascade revocation

**What it deliberately excludes:**
- Frontend or UI
- Stripe/Razorpay integration (we are the infrastructure)
- User-facing wallet
- Admin dashboards

**Technology stack introduced progressively:**
```
Phase 2:   FastAPI, PostgreSQL, SQLAlchemy, Alembic, Docker
Phase 3:   AWS (S3, EC2, RDS, Lambda, IAM), Airflow, ETL pipelines
Phase 3-4: Kafka — transaction events driving downstream consumers
Phase 4:   Redis — idempotency, rate limiting, fraud score cache
Phase 5:   Partitioning, sharding, connection pooling, scale
```

---

## Schema Design Principles

Every decision in this schema follows these rules. If you're adding a table or column and can't map it to one of these — reconsider.

**1. The schema must demand the technology, not accommodate it.**
Kafka, Airflow, Redis — each was added because the data model required it. Not the other way around.

**2. Immutability for financial records.**
Ledger entries, audit logs, status histories — never updated, never deleted. Corrections create new rows that reference old ones. The past is permanent.

**3. Current state vs history are always separate.**
`payments` holds current status. `payment_status_history` holds every transition. Same pattern for settlements, disputes, refunds. One table per concern.

**4. Money is always NUMERIC(15,2), never FLOAT.**
Floating point has binary precision errors. `0.1 + 0.2` in float is `0.30000000000000004`. In a payment system that is a real bug. NUMERIC is exact decimal.

**5. Always TIMESTAMPTZ, never TIMESTAMP.**
Stores UTC internally, converts on read. When your server, database, and job scheduler are in different timezones — TIMESTAMP gives you wrong settlement windows. TIMESTAMPTZ doesn't.

**6. UUID primary keys, never serial integers.**
Sequential IDs are guessable and enumerable by attackers. UUIDs are random. Also — when you shard across multiple database servers, integers collide. UUIDs don't.

**7. Normalize until a join hurts performance, then reconsider.**
`ledger_entries` has no `payment_id` — it joins through `ledger_transactions`. That's correct normalization. `payment_id` on entries would be leaking a concern one level down.

**8. Constraints at the database level for financial rules.**
`UNIQUE(merchant_id, idempotency_key)` on payments. `UNIQUE(payment_id)` on settlement_payments. `CHECK (direction IN ('debit', 'credit'))`. The DB is the last line of defense when application logic fails.

---

## Why Certain Patterns Exist

### Double-Entry Ledger

A single `payments` table can say a payment succeeded. It cannot prove where the money is.

Double-entry proves it. Every debit has a matching credit. Sum of all debits must equal sum of all credits at all times. If they don't — money was created or destroyed somewhere. That's either a bug or fraud.

```
Customer pays ₹500 to merchant. Platform fee = 2% = ₹10.

DEBIT  customer         ₹500.00
CREDIT merchant         ₹490.00
CREDIT platform_revenue  ₹10.00

Sum of debits = Sum of credits = ₹500.00 ✓
```

This is how every regulated financial system in the world works.

### Bi-Temporal Ledger

Two timestamps on every financial event:

- `effective_at` — when the money movement economically happened (set from bank confirmation time)
- `recorded_at` — when your system wrote the row (always NOW())

**Why they differ:**
- Bank confirms a 23:59:30 payment at 00:00:45 next day. Single timestamp puts it in tomorrow's settlement. Bi-temporal puts it in today's where it belongs.
- RBI audit finds a fee error from 3 months ago. Correction entry has `recorded_at = today`, `effective_at = 3 months ago`. Historical reports recalculate correctly. Current reports show the correction happened today. Both are true simultaneously.
- Dispute from 15 days ago. Query `WHERE recorded_at <= dispute_date` to see exactly what the system knew that day.

### Outbox Pattern

The failure scenario without it:

```python
db.insert(ledger_entry)           # succeeds
kafka.publish("payment.success")  # server crashes here
```

Ledger says success. Kafka event never fired. Fraud service never scored it. Settlement never picked it up. System is inconsistent.

You cannot wrap a DB write and a Kafka publish in one ACID transaction — they are different systems.

The fix — make Kafka publishing a DB write:

```python
# Both inside ONE database transaction
db.insert(ledger_entry)
db.insert(outbox_event)    # topic, payload stored in DB
# COMMIT — both or neither
```

A separate worker process reads pending outbox rows, publishes to Kafka, marks published. If it crashes before publishing — row survives, gets published on restart. At-least-once delivery guaranteed.

### Token Attenuation

A platform admin token can do everything. A merchant admin token can only operate within their merchant. A staff token can only do what the merchant admin allowed.

Rule: a token can never grant more permissions than its parent holds.

```
platform_admin  →  issues merchant_admin token (narrower scope)
merchant_admin  →  issues staff token (even narrower)
staff           →  cannot issue tokens
```

Stored as `parent_token_id` self-reference on the tokens table. The entire lineage tree in one column.

### Cascade Revocation via Recursive CTE

Token is compromised. Revoke it and every token it ever issued.

```sql
WITH RECURSIVE token_tree AS (
    SELECT id FROM tokens WHERE id = 'compromised_token_id'
    UNION ALL
    SELECT t.id FROM tokens t
    JOIN token_tree tt ON t.parent_token_id = tt.id
)
UPDATE tokens
SET is_revoked = TRUE, revoked_at = NOW()
WHERE id IN (SELECT id FROM token_tree);
```

PostgreSQL walks the tree iteratively — finds root, finds children, finds children's children — until nothing new is found. One query revokes the entire tree regardless of depth.

---

## Complete Schema

### merchants

Who can transact on the platform. Every payment, settlement, and fraud score references a merchant.

```sql
CREATE TABLE merchants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name       VARCHAR(255) NOT NULL,
    business_type       VARCHAR(50) NOT NULL,
    -- 'individual', 'private_ltd', 'partnership'
    gstin               VARCHAR(15) UNIQUE,
    pan                 VARCHAR(10) NOT NULL,
    email               VARCHAR(255) NOT NULL UNIQUE,
    phone               VARCHAR(15) NOT NULL,

    -- KYC — has this business proven it's real?
    kyc_status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'submitted', 'verified', 'rejected', 'suspended'
    kyc_verified_at     TIMESTAMPTZ,

    -- Operational status — can they transact right now?
    -- Separate from KYC: a merchant can be KYC verified but operationally suspended
    status              VARCHAR(20) NOT NULL DEFAULT 'inactive',
    -- 'inactive', 'active', 'suspended', 'terminated'

    -- Risk
    risk_category       VARCHAR(20) NOT NULL DEFAULT 'standard',
    -- 'low', 'standard', 'high'
    -- feeds fraud scoring — jewelry merchant scored differently than SaaS

    -- Per-merchant limits — not global config
    max_transaction_amt NUMERIC(15,2) NOT NULL DEFAULT 100000.00,
    daily_limit         NUMERIC(15,2) NOT NULL DEFAULT 1000000.00,

    -- Per-merchant fee — enterprise merchants negotiate custom rates
    fee_percentage      NUMERIC(5,4) NOT NULL DEFAULT 0.0200,
    settlement_cycle    INTEGER NOT NULL DEFAULT 1,
    -- T+1 = next day, T+2 = two days. Some large merchants get T+0.

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Key decisions:**
- `kyc_status` and `status` are separate — a merchant can be KYC verified but suspended for ToS violation. Merging them into one column loses that nuance.
- `fee_percentage` per merchant — settlement ETL reads this per row. Hardcoding in app config makes custom rates impossible.
- `risk_category` per merchant — fraud scoring weights this. Same ₹50,000 transaction looks different from a jewelry merchant vs a SaaS company.

---

### merchant_bank_accounts

Where settlement money actually goes. A merchant can have multiple accounts — one is primary.

```sql
CREATE TABLE merchant_bank_accounts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES merchants(id),

    account_holder_name VARCHAR(255) NOT NULL,
    account_number      VARCHAR(255) NOT NULL,
    -- encrypted at application layer before storing
    -- DB stores ciphertext. If breached, raw numbers not exposed.
    ifsc_code           VARCHAR(11) NOT NULL,
    bank_name           VARCHAR(100) NOT NULL,
    account_type        VARCHAR(20) NOT NULL,
    -- 'savings', 'current'

    -- Never send money to unverified account
    is_verified         BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at         TIMESTAMPTZ,
    verification_method VARCHAR(30),
    -- 'penny_drop', 'manual', 'bank_statement'

    is_primary          BOOLEAN NOT NULL DEFAULT FALSE,
    -- Settlement ETL filters: WHERE is_verified = TRUE AND is_primary = TRUE

    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Key decisions:**
- `account_number` not unique — same bank account can belong to multiple merchant entities (one owner, two businesses).
- Encrypted at application layer — storing raw account numbers is a compliance violation.

---

### customers

Per-merchant customer identity. The same email is a different customer record per merchant — your transaction history with Swiggy is irrelevant to Zepto's fraud scoring.

```sql
CREATE TABLE customers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id),

    email           VARCHAR(255) NOT NULL,
    phone           VARCHAR(15),
    name            VARCHAR(255),

    -- Counters for fraud scoring — updated on each event
    -- Avoids COUNT(*) aggregation queries at payment time under load
    total_transactions  INTEGER NOT NULL DEFAULT 0,
    total_disputed      INTEGER NOT NULL DEFAULT 0,

    is_blocked          BOOLEAN NOT NULL DEFAULT FALSE,
    blocked_reason      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(merchant_id, email)
    -- Same email = different customer per merchant
);
```

**Key decisions:**
- `UNIQUE(merchant_id, email)` composite — not `UNIQUE(email)`. Multi-merchant platform fundamental.
- Denormalized counters `total_transactions`, `total_disputed` — fraud scoring reads two integers instead of running COUNT aggregations at 10,000 TPS.

---

### users

Everyone who logs in — platform admins and merchant staff.

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    phone           VARCHAR(15),
    name            VARCHAR(255),
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### merchant_users

Which user belongs to which merchant, and with what role. A user can work at multiple merchants with different roles at each.

```sql
CREATE TABLE merchant_users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id UUID NOT NULL REFERENCES merchants(id),
    user_id     UUID NOT NULL REFERENCES users(id),

    role        VARCHAR(30) NOT NULL,
    -- 'merchant_admin', 'staff', 'settlement_viewer', 'refund_manager'
    -- Fixed enum — no dynamic roles table needed for this system

    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    invited_by  UUID REFERENCES users(id),

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(merchant_id, user_id)
    -- One role per user per merchant
    -- Same user can have different roles at different merchants
);
```

**Key decisions:**
- No separate roles table — roles are a fixed enum. Full RBAC roles table adds joins for no benefit in this system.
- `UNIQUE(merchant_id, user_id)` — one user, one role per merchant. Multi-merchant is multiple rows.

---

### tokens

Every issued JWT tracked here. Enables revocation, attenuation lineage, and forensics.

```sql
CREATE TABLE tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jti             VARCHAR(255) NOT NULL UNIQUE,
    -- JWT ID claim — unique per token

    user_id         UUID NOT NULL REFERENCES users(id),
    merchant_id     UUID REFERENCES merchants(id),
    -- NULL for platform admins

    -- Attenuation tree — entire lineage in one self-referential column
    parent_token_id UUID REFERENCES tokens(id),
    -- NULL = root token

    -- What this token can do — scoped per token, not just per role
    scopes          JSONB NOT NULL,
    -- ['payments:read', 'refunds:write', 'settlements:read']
    -- merchant_admin can issue staff token with only 'payments:read'
    -- even if staff role normally has more

    -- Revocation
    is_revoked      BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID REFERENCES users(id),
    revocation_reason TEXT,

    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Key decisions:**
- `jti` — every JWT carries this claim. Audit logs store it. If a token is compromised, query `audit_logs WHERE token_jti = 'x'` to see everything it ever did.
- `parent_token_id` self-reference — cascade revocation via recursive CTE. No separate lineage table.
- `scopes` JSONB — permissions are per-token, not just per-role. A token can be narrower than the role it was issued from.

---

### payments

Current state of every payment. One row per payment intent.

```sql
CREATE TABLE payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES merchants(id),
    customer_id         UUID NOT NULL REFERENCES customers(id),

    amount              NUMERIC(15,2) NOT NULL,
    currency            VARCHAR(3) NOT NULL DEFAULT 'INR',

    -- Current state only — history in payment_status_history
    status              VARCHAR(30) NOT NULL DEFAULT 'initiated',
    -- 'initiated', 'processing', 'success', 'failed',
    -- 'cancelled', 'pending_review', 'refunded', 'disputed'

    -- Last line of defense against duplicate charges
    -- Redis handles at API layer, DB constraint is the guarantee
    idempotency_key     VARCHAR(255) NOT NULL,

    payment_method      VARCHAR(30) NOT NULL,
    -- 'upi', 'card', 'netbanking', 'wallet'
    payment_method_meta JSONB,
    -- card last 4 digits, UPI handle — never full card number (PCI violation)

    -- Written by fraud service after scoring
    -- Settlement ETL holds transactions above threshold
    risk_score          NUMERIC(5,2),
    risk_flags          JSONB,

    -- Bank/gateway tracking
    gateway_payment_id  VARCHAR(255),
    gateway_response    JSONB,
    -- Store raw — you don't know which fields you'll need 6 months later in a dispute

    initiated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(merchant_id, idempotency_key)
    -- Same payment request twice = second insert fails at DB level
    -- Customer double-click cannot create two charges
);
```

**Key decisions:**
- `UNIQUE(merchant_id, idempotency_key)` — DB-level duplicate prevention. Application logic can fail; this constraint cannot be bypassed.
- `payment_method_meta` JSONB — UPI, card, netbanking have structurally different metadata. JSONB without nullable columns everywhere.
- `risk_score` on payments — connection point between fraud system and settlement. Settlement ETL reads this column.

---

### payment_status_history

Every state transition. Append-only. Never updated.

```sql
CREATE TABLE payment_status_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id  UUID NOT NULL REFERENCES payments(id),

    from_status VARCHAR(30),
    -- NULL on first entry (initiated)
    to_status   VARCHAR(30) NOT NULL,

    reason      TEXT,
    triggered_by VARCHAR(20) NOT NULL,
    -- 'customer', 'system', 'merchant', 'platform_admin'
    actor_id    UUID,

    metadata    JSONB,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- No updated_at. State transitions are facts. Facts don't get edited.
);
```

**Why separate from payments:**
A payment that went `initiated → processing → failed → processing → success` — `updated_at` on the payments table only tells you the last change. The intermediate states, durations, and reasons are permanently lost. This table preserves the full chain for dispute resolution, fraud forensics, and audit.

This table also drives Kafka — every insert fires an outbox event. The history table IS the event log at the database level.

---

### ledger_transactions

The financial event record. WHY money moved. One row per event.

```sql
CREATE TABLE ledger_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    payment_id      UUID REFERENCES payments(id),
    settlement_id   UUID,
    -- populated when settlements table exists

    entry_type      VARCHAR(20) NOT NULL,
    -- 'payment', 'refund', 'fee', 'settlement', 'adjustment'

    description     TEXT NOT NULL,

    -- Bi-temporal
    effective_at    TIMESTAMPTZ NOT NULL,
    -- when the money movement economically happened (from bank confirmation)
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- when this system wrote the row (always NOW())

    -- Prevents same financial event recorded twice under retries
    idempotency_key VARCHAR(255) NOT NULL UNIQUE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### ledger_entries

HOW money moved. Multiple rows per ledger_transaction. Always balanced — sum of debits must equal sum of credits per transaction.

```sql
CREATE TABLE ledger_entries (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    ledger_transaction_id   UUID NOT NULL REFERENCES ledger_transactions(id),
    -- No payment_id here — entries don't know about payments
    -- That's ledger_transaction's concern
    -- To get entries for a payment: JOIN through ledger_transactions

    account_type    VARCHAR(30) NOT NULL,
    -- 'customer', 'merchant', 'platform_cash',
    -- 'platform_revenue', 'gateway', 'bank'
    account_id      UUID NOT NULL,

    direction       VARCHAR(10) NOT NULL CHECK (direction IN ('debit', 'credit')),
    amount          NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    currency        VARCHAR(3) NOT NULL DEFAULT 'INR',

    running_balance NUMERIC(15,2) NOT NULL,
    -- Balance snapshot at time of entry — enables point-in-time reconstruction

    -- Refund/correction entries point back to what they're reversing
    is_reversal         BOOLEAN NOT NULL DEFAULT FALSE,
    reversed_entry_id   UUID REFERENCES ledger_entries(id),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- No updated_at. Ledger entries are permanent and immutable.
);
```

**What one payment creates:**

```
Payment: customer pays ₹500, platform fee 2% = ₹10

ledger_transactions: 1 row (entry_type='payment')

ledger_entries: 3 rows
  DEBIT  customer          ₹500.00
  CREDIT merchant          ₹490.00
  CREDIT platform_revenue   ₹10.00

Validation: ₹500 = ₹490 + ₹10 ✓

Refund issued later:
ledger_transactions: 1 row (entry_type='refund')

ledger_entries: 3 reversal rows
  DEBIT  merchant          ₹490.00  is_reversal=true
  DEBIT  platform_revenue   ₹10.00  is_reversal=true
  CREDIT customer          ₹500.00  is_reversal=true

Original entries untouched. Reversal entries cancel them out.
```

**Normalization note:** `ledger_entries` has no `payment_id`. Its relationship is with `ledger_transaction`, not with payments directly. Putting `payment_id` on entries would leak a concern one level down — and future entry types like `settlement` or `adjustment` have no payment_id at all, creating nullable foreign keys on half the rows.

---

### settlements

Nightly payout computation per merchant. One row per merchant per settlement run.

```sql
CREATE TABLE settlements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id),
    bank_account_id UUID REFERENCES merchant_bank_accounts(id),

    -- The window this settlement covers
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,

    -- Computed amounts
    gross_amount    NUMERIC(15,2) NOT NULL,
    fee_deducted    NUMERIC(15,2) NOT NULL,
    disputed_hold   NUMERIC(15,2) NOT NULL DEFAULT 0,
    net_payout      NUMERIC(15,2) NOT NULL,
    currency        VARCHAR(3) NOT NULL DEFAULT 'INR',

    status          VARCHAR(30) NOT NULL DEFAULT 'pending',
    -- 'pending', 'processing', 'completed', 'failed', 'on_hold'

    -- Reconciliation result
    reconciliation_status   VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'matched', 'mismatched', 'manual_review'
    reconciliation_delta    NUMERIC(15,2),
    -- Difference between ledger sum and computed net_payout
    -- Zero = perfect. Non-zero = investigation required.
    -- Query: WHERE reconciliation_delta != 0 to find every bad settlement

    -- Bank transfer tracking
    bank_reference  VARCHAR(255),
    transferred_at  TIMESTAMPTZ,

    -- S3 report — store key only, not full URL
    -- Full URL constructed at read time from config
    -- Bucket names can change; keys don't
    report_s3_key   TEXT,
    -- 'settlements/2024/01/15/merchant_{uuid}.json'

    -- Airflow retry state
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    last_attempted_at   TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ,
    -- Exponential backoff: 5min → 30min → 2hrs
    -- Airflow reads this to decide whether to retry in current run
    failure_reason      TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### settlement_payments

Which payments were included in which settlement. Many-to-one.

```sql
CREATE TABLE settlement_payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id   UUID NOT NULL REFERENCES settlements(id),
    payment_id      UUID NOT NULL REFERENCES payments(id),
    amount          NUMERIC(15,2) NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(payment_id)
    -- A payment appears in exactly one settlement. Ever.
    -- Without this: Airflow bug could include same payment twice.
    -- Merchant gets paid twice. Real class of production bug.
);
```

**Why junction table not foreign key on payments:**
A foreign key `payments.settlement_id` would mean a payment can only ever associate with one settlement even if the first run failed and needed correction. Junction table preserves full history and handles reruns cleanly.

---

### settlement_status_history

```sql
CREATE TABLE settlement_status_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id   UUID NOT NULL REFERENCES settlements(id),

    from_status     VARCHAR(30),
    to_status       VARCHAR(30) NOT NULL,
    reason          TEXT,
    triggered_by    VARCHAR(20) NOT NULL,
    -- 'airflow', 'platform_admin', 'system'

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### disputes

Customer chargebacks. Adversarial process — customer tells their bank the charge was wrong. Bank contacts us. We mediate between customer and merchant.

```sql
CREATE TABLE disputes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id  UUID NOT NULL REFERENCES payments(id),
    merchant_id UUID NOT NULL REFERENCES merchants(id),
    customer_id UUID NOT NULL REFERENCES customers(id),

    reason          VARCHAR(50) NOT NULL,
    -- 'fraudulent', 'duplicate', 'product_not_received',
    -- 'product_unacceptable', 'credit_not_processed'
    reason_detail   TEXT,

    disputed_amount NUMERIC(15,2) NOT NULL,
    resolved_amount NUMERIC(15,2),
    -- Separate columns — customer disputes ₹500, platform resolves ₹300.
    -- Almost always different. One column can't express partial resolution.

    status          VARCHAR(30) NOT NULL DEFAULT 'raised',
    -- 'raised', 'under_review', 'merchant_responded',
    -- 'resolved_merchant', 'resolved_customer', 'escalated'

    -- Merchant submits proof — delivery receipts, communications, tracking
    merchant_evidence   JSONB,
    platform_decision   TEXT,
    resolved_by         UUID,
    -- platform_admin who made the final call

    raised_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    respond_by      TIMESTAMPTZ NOT NULL,
    -- Deadline for merchant evidence. Scheduled job checks daily.
    -- After deadline: auto-resolves in customer favor.
    resolved_at     TIMESTAMPTZ,

    -- Settlement impact
    held_from_settlement    BOOLEAN NOT NULL DEFAULT TRUE,
    -- Settlement ETL reads this when computing disputed_hold
    recovery_settlement_id  UUID REFERENCES settlements(id),
    -- Which future settlement deducted the disputed amount from merchant

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Dispute vs Refund — the hard line:**

| | Dispute | Refund |
|---|---|---|
| Initiated by | Customer (via their bank) | Merchant or platform admin |
| Process | Adversarial — bank mediates | Cooperative — voluntary |
| Bank involvement | Yes | No |
| Ledger | Reversal entries created | Reversal entries created |
| Settlement impact | `disputed_hold` on next run | Reduces future balance |

Same table would mean nulls everywhere and logic impossible to reason about.

---

### dispute_status_history

```sql
CREATE TABLE dispute_status_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dispute_id  UUID NOT NULL REFERENCES disputes(id),

    from_status VARCHAR(30),
    to_status   VARCHAR(30) NOT NULL,
    reason      TEXT,
    triggered_by VARCHAR(20) NOT NULL,
    -- 'customer', 'merchant', 'platform_admin', 'system'
    actor_id    UUID,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### refunds

Merchant voluntarily returns money. Or platform admin forces it. Never initiated by customer — that's a dispute.

```sql
CREATE TABLE refunds (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id  UUID NOT NULL REFERENCES payments(id),
    merchant_id UUID NOT NULL REFERENCES merchants(id),

    initiated_by    VARCHAR(20) NOT NULL,
    -- 'merchant', 'platform_admin'
    -- Never 'customer' — customers raise disputes
    initiator_id    UUID NOT NULL REFERENCES users(id),

    refund_amount   NUMERIC(15,2) NOT NULL,
    -- Partial refunds allowed — merchant refunds ₹200 of ₹500 payment
    -- Application enforces: sum(refund_amount) <= payment.amount
    -- Schema stores facts, application enforces business rule

    status          VARCHAR(30) NOT NULL DEFAULT 'initiated',
    -- 'initiated', 'processing', 'success', 'failed'

    reason          VARCHAR(50) NOT NULL,
    -- 'duplicate', 'fraudulent', 'customer_request',
    -- 'product_issue', 'order_cancelled'
    reason_detail   TEXT,

    -- Populated when reversal ledger entries are created
    -- Links refund decision → exact ledger movement
    ledger_transaction_id UUID REFERENCES ledger_transactions(id),

    gateway_refund_id   VARCHAR(255),
    gateway_response    JSONB,

    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### refund_status_history

```sql
CREATE TABLE refund_status_history (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refund_id   UUID NOT NULL REFERENCES refunds(id),

    from_status VARCHAR(30),
    to_status   VARCHAR(30) NOT NULL,
    reason      TEXT,
    triggered_by VARCHAR(20) NOT NULL,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### fraud_scores

Per-payment scoring history. Redis caches the current score for fast reads during processing. This table stores the permanent history for pattern analysis and audit.

```sql
CREATE TABLE fraud_scores (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payment_id  UUID NOT NULL REFERENCES payments(id),
    merchant_id UUID NOT NULL REFERENCES merchants(id),
    customer_id UUID NOT NULL REFERENCES customers(id),

    score       NUMERIC(5,2) NOT NULL,
    -- 0.00 to 100.00. Above threshold = auto-hold.

    risk_level  VARCHAR(10) NOT NULL,
    -- 'low', 'medium', 'high', 'critical'

    -- What drove the score — JSONB because scoring signals evolve over versions
    signals     JSONB NOT NULL,
    -- {
    --   "velocity_score": 45,         multiple payments in short window
    --   "amount_score": 30,           unusually large for this merchant category
    --   "category_score": 20,         high risk merchant type
    --   "customer_history_score": 5   prior disputes on this customer
    -- }

    action_taken    VARCHAR(20) NOT NULL,
    -- 'allowed', 'held', 'blocked'
    -- Score of 60 might allow for one merchant, hold for another
    -- Action taken is what matters for audit — not just the score

    -- Human review if flagged
    reviewed_by     UUID REFERENCES users(id),
    review_decision VARCHAR(20),
    -- 'approved', 'rejected', 'escalated'
    reviewed_at     TIMESTAMPTZ,

    model_version   VARCHAR(20) NOT NULL,
    -- 'v1.0', 'v1.1'
    -- Scoring logic changes over time
    -- Without versioning: score of 75 from 6 months ago
    -- may not mean the same as 75 today

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### outbox_events

Guaranteed Kafka delivery. Every event that needs to reach downstream services is written here inside the same DB transaction that created the triggering data.

```sql
CREATE TABLE outbox_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    topic           VARCHAR(100) NOT NULL,
    -- 'payment.initiated', 'payment.success', 'payment.failed',
    -- 'payment.disputed', 'settlement.completed',
    -- 'dispute.raised', 'refund.processed'

    payload         JSONB NOT NULL,

    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'published', 'failed'

    aggregate_type  VARCHAR(50) NOT NULL,
    -- 'payment', 'settlement', 'dispute', 'refund'
    aggregate_id    UUID NOT NULL,

    attempt_count   INTEGER NOT NULL DEFAULT 0,
    last_attempted  TIMESTAMPTZ,
    error_message   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at    TIMESTAMPTZ
);
```

**How it works:**

```
Payment succeeds. Inside ONE database transaction:

  INSERT INTO payment_status_history (to_status='success')
  INSERT INTO ledger_transactions    (entry_type='payment')
  INSERT INTO ledger_entries         (3 rows, balanced)
  INSERT INTO outbox_events          (topic='payment.success')

  COMMIT — all four or none.

Outbox worker (separate process):
  SELECT * FROM outbox_events WHERE status='pending'
  → publish to Kafka
  → UPDATE status='published', published_at=NOW()

If worker crashes before publishing:
  Row still pending. Gets published on restart.
  At-least-once delivery guaranteed.
```

---

### audit_logs

Immutable record of every system decision. Every state change, every access denial, every admin action.

```sql
CREATE TABLE audit_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was touched
    entity_type VARCHAR(50) NOT NULL,
    -- 'merchant', 'transaction', 'settlement', 'dispute', 'token'
    entity_id   UUID NOT NULL,

    -- What happened
    action      VARCHAR(100) NOT NULL,
    -- 'kyc_status_changed', 'payment_held', 'token_revoked'
    old_value   JSONB,
    new_value   JSONB,

    -- Who did it
    actor_id    UUID NOT NULL,
    actor_type  VARCHAR(20) NOT NULL,
    -- 'merchant_admin', 'platform_admin', 'system'
    token_jti   VARCHAR(255),
    -- Which exact JWT was used — links to tokens.jti
    -- If token compromised: query here to see everything it did

    -- Why it was allowed or denied
    policy_decision VARCHAR(20) NOT NULL,
    -- 'allowed', 'denied'
    policy_reason   TEXT,
    -- Denials logged too — 50 denials in 5 minutes is a fraud pattern

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- No updated_at. Audit logs are immutable.
    -- If someone needs to "correct" an audit log — that's a new log entry.

    ip_address  INET,
    user_agent  TEXT
);
```

**One table for everything** — not per-entity audit tables. A fraud investigator tracing a case needs one query across everything that touched merchant X, payment Y, token Z. Separate tables make that a multi-join nightmare.

---

## Complete Table List

```
Core entities
├── merchants                  who can transact, limits, fee structure
├── merchant_bank_accounts     verified payout destinations
├── customers                  per-merchant identity, fraud counters
├── users                      platform and merchant staff login
├── merchant_users             user↔merchant relationship and role
└── tokens                     JWT tracking, attenuation tree, revocation

Payment lifecycle
├── payments                   current state of every payment
└── payment_status_history     full immutable transition log

Ledger (double-entry)
├── ledger_transactions        what financial event happened (bi-temporal)
└── ledger_entries             how money moved, always balanced

Settlement pipeline
├── settlements                nightly payout per merchant
├── settlement_payments        payment↔settlement mapping
└── settlement_status_history  settlement state transitions

Disputes and refunds
├── disputes                   customer chargebacks, evidence, resolution
├── dispute_status_history     dispute state transitions
├── refunds                    voluntary merchant refunds
└── refund_status_history      refund state transitions

Supporting systems
├── fraud_scores               per-payment scoring history and signals
├── outbox_events              guaranteed Kafka delivery via DB atomicity
└── audit_logs                 every system decision, immutable

Total: 20 tables
```

---

## How Each Technology Connects to This Schema

### Kafka
- `outbox_events` — the bridge. Every insert here (inside a DB transaction) becomes a Kafka message.
- `payment_status_history` — every row insert triggers an outbox event.
- Downstream consumers: fraud scoring, notifications, reporting, settlement eligibility.

### Airflow
- Reads `settlements` for `next_retry_at` to decide retry timing.
- Reads `payments` + `settlement_payments` to find unprocessed eligible payments.
- Writes `settlements`, `settlement_payments`, `ledger_transactions`, `ledger_entries`, `outbox_events` in one job run.
- Uploads report to S3, stores key in `settlements.report_s3_key`.

### Redis
- Caches `fraud_scores` current score — DB stores permanent history.
- Idempotency at API layer — `payments.idempotency_key` is the DB guarantee beneath it.
- Rate limiting per merchant — no DB table needed, purely Redis.

### AWS S3
- `settlements.report_s3_key` — nightly settlement reports stored here.
- Key pattern: `settlements/{year}/{month}/{day}/merchant_{uuid}.json`

### Partitioning (Phase 5)
- `payments` — partition by `created_at` monthly. Billion-row table needs it.
- `ledger_entries` — same. Settlement ETL queries by date range become partition scans.
- `audit_logs` — same. Compliance queries always have a date range.

### Sharding (Phase 5)
- `merchant_id` is the natural shard key. It appears on every table.
- All queries for one merchant hit one shard. No cross-shard joins for operational queries.

---

## State Machines

### Payment States

```
initiated
    ↓
processing
    ↓           ↓
success       failed ──→ processing (retry)
    ↓
settled
    ↓
disputed ──→ refunded
    ↓
pending_review (fraud hold — human reviews)

cancelled (created but never attempted)
```

### Settlement States

```
pending → processing → completed
              ↓
            failed → pending (retry after next_retry_at)
              ↓
           on_hold (manual intervention required)
```

### Dispute States

```
raised → under_review → merchant_responded → resolved_merchant
                                           → resolved_customer
                                           → escalated
```

---

