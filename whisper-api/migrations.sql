CREATE TABLE IF NOT EXISTS api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    key_prefix  TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    last_used_at INTEGER,
    revoked_at  INTEGER
);

CREATE TABLE IF NOT EXISTS instances (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    engine       TEXT NOT NULL,
    model        TEXT NOT NULL,
    purpose      TEXT NOT NULL DEFAULT 'transcription',
    device       TEXT NOT NULL,
    compute_type TEXT NOT NULL,
    port         INTEGER NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 1,
    pid          INTEGER,
    created_at   INTEGER NOT NULL,
    timeout_secs     INTEGER NOT NULL DEFAULT 600,  -- 0 = unbegrenzt
    idle_unload_secs INTEGER NOT NULL DEFAULT 0,    -- 0 = dauerhaft im RAM
    last_used_at     INTEGER
);
-- Spalten-Nachrüstung für bestehende DBs passiert in db.init_db() via
-- fehlertolerante ALTER TABLE (Spalte existiert bereits -> ignoriert).

CREATE TABLE IF NOT EXISTS model_downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    progress    REAL NOT NULL DEFAULT 0,
    bytes_done  INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER
);

CREATE TABLE IF NOT EXISTS admin_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
