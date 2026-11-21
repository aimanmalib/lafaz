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
