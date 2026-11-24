CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS email;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS gateway;

CREATE TABLE iam.users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE crm.accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    region TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'on_hold', 'closed')),
    notes TEXT
);

CREATE INDEX accounts_owner_user_id_idx ON crm.accounts (owner_user_id);

CREATE TABLE crm.contacts (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES crm.accounts(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    is_billing BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX contacts_account_id_idx ON crm.contacts (account_id);

-- At most one billing contact per account.
CREATE UNIQUE INDEX contacts_one_billing_per_account_idx
    ON crm.contacts (account_id)
    WHERE is_billing;

-- ---------------------------------------------------------------- finance

CREATE TABLE finance.invoices (
    id TEXT PRIMARY KEY,                       -- e.g. 'INV-1042'
    account_id TEXT NOT NULL REFERENCES crm.accounts(id) ON DELETE RESTRICT,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    due_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'paid', 'overdue')),
    bank_ref TEXT NOT NULL                     -- sensitive: redacted before the LLM
);

CREATE INDEX invoices_account_id_idx ON finance.invoices (account_id);

CREATE TABLE finance.credit_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id TEXT NOT NULL REFERENCES finance.invoices(id) ON DELETE RESTRICT,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0),
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_approval'
        CHECK (status IN ('pending_approval', 'approved', 'rejected')),
    requested_by UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    approved_by UUID REFERENCES iam.users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'approved' OR approved_by IS NOT NULL)
);

CREATE INDEX credit_notes_invoice_id_idx ON finance.credit_notes (invoice_id);
CREATE INDEX credit_notes_requested_by_idx ON finance.credit_notes (requested_by);
CREATE INDEX credit_notes_approved_by_idx ON finance.credit_notes (approved_by);

-- ---------------------------------------------------------------- knowledge

CREATE TABLE knowledge.documents (
    id TEXT PRIMARY KEY,                       -- e.g. 'DOC-001'
    title TEXT NOT NULL,
    classification TEXT NOT NULL
        CHECK (classification IN ('staff', 'finance', 'contractor', 'hr_confidential')),
    body TEXT NOT NULL
);

CREATE TABLE knowledge.chunks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- Chunks are derived from the document, so they go with it.
    document_id TEXT NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    -- BAAI/bge-small-en-v1.5 (384 dims). No ANN index: ~60 docs use exact search, which also
    -- keeps "filter by access, then rank" exact (ADR 0001).
    embedding VECTOR(384),
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX chunks_tsv_idx ON knowledge.chunks USING GIN (tsv);

CREATE TABLE knowledge.document_access (
    document_id TEXT NOT NULL REFERENCES knowledge.documents(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('sales_rep', 'finance_analyst', 'contractor')),
    PRIMARY KEY (document_id, role)
);

CREATE INDEX document_access_role_idx ON knowledge.document_access (role);

-- ---------------------------------------------------------------- email (mock)

CREATE TABLE email.outbox (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sender_user_id UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    to_address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX outbox_sender_user_id_idx ON email.outbox (sender_user_id);

-- ---------------------------------------------------------------- audit

-- Append-only is enforced in phase 6 (grants + trigger), not here.
CREATE TABLE audit.events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id UUID REFERENCES iam.users(id) ON DELETE RESTRICT,  -- NULL if the token was invalid
    tool TEXT NOT NULL,
    args_hash TEXT NOT NULL CHECK (args_hash ~ '^[0-9a-f]{64}$'),
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'pending_approval')),
    reason TEXT,
    trace_id TEXT,
    prev_hash TEXT CHECK (prev_hash ~ '^[0-9a-f]{64}$'),       -- NULL only for the first event
    hash TEXT NOT NULL UNIQUE CHECK (hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX events_user_id_idx ON audit.events (user_id);

-- ---------------------------------------------------------------- gateway

CREATE TABLE gateway.approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    tool TEXT NOT NULL,
    args_hash TEXT NOT NULL CHECK (args_hash ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    CHECK (expires_at > created_at),
    CHECK (used_at IS NULL OR used_at <= expires_at)
);

CREATE INDEX approvals_user_id_args_hash_idx ON gateway.approvals (user_id, args_hash);
