CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS records_kind_status_idx ON records(kind, status);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    record_id UNINDEXED,
    title,
    body,
    kind UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS commitments (
    record_id TEXT PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    due_date TEXT,
    due_time TEXT,
    timezone TEXT NOT NULL,
    due_precision TEXT NOT NULL,
    notify INTEGER NOT NULL CHECK (notify IN (0, 1)),
    notified_at TEXT
);

CREATE INDEX IF NOT EXISTS commitments_due_idx
    ON commitments(status, due_date, due_time);
