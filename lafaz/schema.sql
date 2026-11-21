-- Lafaz storage. Later slices add tables with CREATE TABLE IF NOT EXISTS; nothing here is ever dropped.
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY,
    meeting_date TEXT NOT NULL,
    title TEXT,
    source TEXT NOT NULL CHECK (source IN ('wispr', 'transcript', 'sample')),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id),
    status TEXT NOT NULL DEFAULT 'started',
    mode TEXT NOT NULL DEFAULT 'live' CHECK (mode IN ('live', 'replay')),
    lang TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    tool TEXT NOT NULL,
    category TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    result_summary TEXT,
    ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    UNIQUE (run_id, seq)
);

-- Listen layer (B1). Rejected items are kept with their reason so the measured counts come from the database.
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected')),
    reason TEXT,
    kind TEXT,
    text TEXT,
    owner TEXT,
    speaker TEXT,
    due_phrase TEXT,
    due_date TEXT,
    confidence TEXT,
    quotes_json TEXT NOT NULL DEFAULT '[]',
    corrects_json TEXT,
    UNIQUE (run_id, seq)
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    seq INTEGER NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('model', 'code')),
    code TEXT,
    params_json TEXT,
    text TEXT,
    item_seq INTEGER,
    quote TEXT,
    UNIQUE (run_id, seq)
);

-- Agent loop and approvals (B2). The loop never runs an irreversible tool; it files an approval that only a person
-- can approve, and code then runs the action.
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    item_seq INTEGER,
    title TEXT NOT NULL,
    owner TEXT,
    due_date TEXT,
    quote TEXT,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done', 'undone')),
    published INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    person TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'discarded')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    step_seq INTEGER NOT NULL,
    tool TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    diff_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'skipped', 'failed')),
    edited INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    approval_id INTEGER REFERENCES approvals(id),
    tool TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
