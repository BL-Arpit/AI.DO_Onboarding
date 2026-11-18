CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'hr_admin', 'employee')),
    password TEXT NOT NULL,
    must_change INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    temp_expires DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    expires DOUBLE PRECISION NOT NULL,
    last_seen DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_sessions_user ON auth_sessions(user_id);
CREATE TABLE IF NOT EXISTS auth_attempts (
    subject TEXT NOT NULL,
    created DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_auth_attempts ON auth_attempts(subject, created);
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    position BIGINT GENERATED ALWAYS AS IDENTITY,
    user_id TEXT UNIQUE REFERENCES users(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT NOT NULL,
    client TEXT NOT NULL,
    track TEXT NOT NULL,
    status TEXT NOT NULL,
    fields TEXT NOT NULL DEFAULT '{}',
    verification TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    deleted_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_employees_name ON employees(lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_employees_status ON employees(status, position) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    position BIGINT GENERATED ALWAYS AS IDENTITY,
    employee_id TEXT NOT NULL REFERENCES employees(id),
    kind TEXT NOT NULL,
    classification TEXT NOT NULL,
    extraction TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_documents_employee ON documents(employee_id, position);
CREATE TABLE IF NOT EXISTS document_uploads (
    doc_id TEXT PRIMARY KEY REFERENCES documents(id),
    content BYTEA NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    employee_id TEXT REFERENCES employees(id),
    actor TEXT REFERENCES users(id),
    action TEXT NOT NULL,
    details TEXT,
    created TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_audit_employee ON audit(employee_id, id);
