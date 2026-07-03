"""SQLite helpers for the whisper-api admin UI."""
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


MIGRATIONS_PATH = Path(__file__).resolve().parent.parent / "migrations.sql"


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        with open(MIGRATIONS_PATH) as f:
            conn.executescript(f.read())
        conn.commit()
        # Lightweight column migrations for DBs created before the columns
        # existed — same pattern as the web-app: ADD COLUMN and ignore the
        # "duplicate column name" error.
        for ddl in (
            "ALTER TABLE instances ADD COLUMN timeout_secs INTEGER NOT NULL DEFAULT 600",
            "ALTER TABLE instances ADD COLUMN idle_unload_secs INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE instances ADD COLUMN last_used_at INTEGER",
        ):
            try:
                conn.execute(ddl)
                conn.commit()
            except sqlite3.OperationalError:
                pass


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# --- api_keys ---------------------------------------------------------------
def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_api_key(db_path: str, label: str, raw_key: str) -> int:
    with connect(db_path) as c:
        cur = c.execute(
            "INSERT INTO api_keys (label, key_hash, key_prefix, created_at) VALUES (?, ?, ?, ?)",
            (label, _hash_key(raw_key), raw_key[:12], int(time.time())),
        )
        c.commit()
        return cur.lastrowid


def revoke_api_key(db_path: str, key_id: int) -> None:
    with connect(db_path) as c:
        c.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ?", (int(time.time()), key_id))
        c.commit()


def list_api_keys(db_path: str) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute(
            "SELECT id, label, key_prefix, created_at, last_used_at, revoked_at "
            "FROM api_keys ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def key_is_active(db_path: str, raw_key: str) -> bool:
    if not raw_key:
        return False
    with connect(db_path) as c:
        row = c.execute(
            "SELECT id FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (_hash_key(raw_key),),
        ).fetchone()
        return row is not None


def touch_api_key_last_used(db_path: str, raw_key: str) -> None:
    with connect(db_path) as c:
        c.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ?",
            (int(time.time()), _hash_key(raw_key)),
        )
        c.commit()


def count_active_keys(db_path: str) -> int:
    with connect(db_path) as c:
        row = c.execute("SELECT COUNT(*) AS n FROM api_keys WHERE revoked_at IS NULL").fetchone()
        return row["n"] if row else 0


# --- instances --------------------------------------------------------------
def create_instance(db_path: str, *, name: str, engine: str, model: str, purpose: str,
                    device: str, compute_type: str, port: int, enabled: int = 1,
                    timeout_secs: int = 600, idle_unload_secs: int = 0) -> int:
    with connect(db_path) as c:
        cur = c.execute(
            "INSERT INTO instances (name, engine, model, purpose, device, compute_type, port, enabled, created_at, timeout_secs, idle_unload_secs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, engine, model, purpose, device, compute_type, port, enabled, int(time.time()),
             int(timeout_secs), int(idle_unload_secs)),
        )
        c.commit()
        return cur.lastrowid


def update_instance_settings(db_path: str, instance_id: int, *,
                             timeout_secs: int, idle_unload_secs: int) -> None:
    with connect(db_path) as c:
        c.execute(
            "UPDATE instances SET timeout_secs = ?, idle_unload_secs = ? WHERE id = ?",
            (int(timeout_secs), int(idle_unload_secs), instance_id),
        )
        c.commit()


def touch_instance_last_used(db_path: str, instance_id: int) -> None:
    with connect(db_path) as c:
        c.execute("UPDATE instances SET last_used_at = ? WHERE id = ?",
                  (int(time.time()), instance_id))
        c.commit()


def list_instances(db_path: str, enabled_only: bool = False) -> list[dict]:
    with connect(db_path) as c:
        q = "SELECT * FROM instances"
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY port"
        return [dict(r) for r in c.execute(q).fetchall()]


def get_instance(db_path: str, instance_id: int) -> dict | None:
    with connect(db_path) as c:
        row = c.execute("SELECT * FROM instances WHERE id = ?", (instance_id,)).fetchone()
        return dict(row) if row else None


def update_instance_pid(db_path: str, instance_id: int, pid: int | None) -> None:
    with connect(db_path) as c:
        c.execute("UPDATE instances SET pid = ? WHERE id = ?", (pid, instance_id))
        c.commit()


def update_instance_enabled(db_path: str, instance_id: int, enabled: bool) -> None:
    with connect(db_path) as c:
        c.execute("UPDATE instances SET enabled = ? WHERE id = ?", (1 if enabled else 0, instance_id))
        c.commit()


def delete_instance(db_path: str, instance_id: int) -> None:
    with connect(db_path) as c:
        c.execute("DELETE FROM instances WHERE id = ?", (instance_id,))
        c.commit()


def used_ports(db_path: str) -> set[int]:
    with connect(db_path) as c:
        return {r["port"] for r in c.execute("SELECT port FROM instances").fetchall()}


# --- downloads --------------------------------------------------------------
def create_download(db_path: str, repo_id: str, kind: str) -> int:
    with connect(db_path) as c:
        cur = c.execute(
            "INSERT INTO model_downloads (repo_id, kind, status, started_at) VALUES (?, ?, 'pending', ?)",
            (repo_id, kind, int(time.time())),
        )
        c.commit()
        return cur.lastrowid


def update_download(db_path: str, download_id: int, **fields) -> None:
    if not fields:
        return
    allowed = {"status", "progress", "bytes_done", "bytes_total", "error", "finished_at"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    values = [fields[c] for c in cols] + [download_id]
    with connect(db_path) as c:
        c.execute(f"UPDATE model_downloads SET {set_clause} WHERE id = ?", values)
        c.commit()


def get_download(db_path: str, download_id: int) -> dict | None:
    with connect(db_path) as c:
        row = c.execute("SELECT * FROM model_downloads WHERE id = ?", (download_id,)).fetchone()
        return dict(row) if row else None


def list_downloads(db_path: str, limit: int = 50) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute(
            "SELECT * FROM model_downloads ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# --- key/value (admin_kv) ---------------------------------------------------
def kv_get(db_path: str, key: str, default: str | None = None) -> str | None:
    with connect(db_path) as c:
        row = c.execute("SELECT value FROM admin_kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(db_path: str, key: str, value: str) -> None:
    with connect(db_path) as c:
        c.execute(
            "INSERT INTO admin_kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        c.commit()


def kv_get_json(db_path: str, key: str, default=None):
    raw = kv_get(db_path, key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return default


def kv_set_json(db_path: str, key: str, value) -> None:
    kv_set(db_path, key, json.dumps(value))


def active_download_for_repo(db_path: str, repo_id: str) -> dict | None:
    with connect(db_path) as c:
        row = c.execute(
            "SELECT * FROM model_downloads WHERE repo_id = ? AND status IN ('pending', 'downloading') "
            "ORDER BY id DESC LIMIT 1",
            (repo_id,),
        ).fetchone()
        return dict(row) if row else None
