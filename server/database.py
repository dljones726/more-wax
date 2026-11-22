import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import cast

from server.config import DB_FILE, LEGACY_DB_FILE

_lock = threading.Lock()

# Bump + add a _migrate() branch when the schema changes.
CURRENT_USER_VERSION = 1
# Kept as the legacy string so exported files look unchanged.
EXPORT_SCHEMA_VERSION = "1.1"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data        TEXT NOT NULL,
    discogs_id  TEXT GENERATED ALWAYS AS (json_extract(data, '$.discogs_id')) VIRTUAL,
    barcode     TEXT GENERATED ALWAYS AS (json_extract(data, '$.barcode'))    VIRTUAL,
    artist      TEXT GENERATED ALWAYS AS (lower(json_extract(data, '$.artist'))) VIRTUAL,
    title       TEXT GENERATED ALWAYS AS (lower(json_extract(data, '$.title')))  VIRTUAL
);
CREATE INDEX IF NOT EXISTS idx_records_discogs_id ON records(discogs_id);
CREATE INDEX IF NOT EXISTS idx_records_barcode    ON records(barcode);
CREATE INDEX IF NOT EXISTS idx_records_sort       ON records(artist, title);
"""

_conn = None


# ── connection / schema ───────────────────────────────────────────


def _connect():
    """Return the shared connection"""
    global _conn
    if _conn is None:
        conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(conn)
        _maybe_import_legacy_json(conn)
        _conn = conn
    return _conn


def _init_schema(conn):
    conn.executescript(_SCHEMA_SQL)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != CURRENT_USER_VERSION:
        _migrate(conn, version)


def _migrate(conn, from_version):
    """Run ordered migrations"""
    # f-string is safe: CURRENT_USER_VERSION is an int constant (PRAGMA can't be bound).
    conn.execute(f"PRAGMA user_version = {CURRENT_USER_VERSION}")
    conn.commit()


def _maybe_import_legacy_json(conn):
    """One-time: if the table is empty and collection.json exists, import it, then
    rename the JSON so it isn't re-imported."""
    if conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]:
        return
    if not LEGACY_DB_FILE.exists():
        return
    try:
        data = json.loads(LEGACY_DB_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠️ [db] Could not import {LEGACY_DB_FILE}: {e}")
        return
    records = data.get("records", []) if isinstance(data, dict) else []
    for rec in records:
        rec.setdefault("add_source", "barcode")  # replicate the old 1.0→1.1 migration
        rid = rec.get("id")
        if rid is not None:
            # Preserve ids so listens.record_id and cover_<id>.jpg stay valid.
            conn.execute(
                "INSERT INTO records(id, data) VALUES (?, json(?))",
                (rid, json.dumps(rec)),
            )
        else:
            conn.execute(
                "INSERT INTO records(data) VALUES (json(?))", (json.dumps(rec),)
            )
    conn.commit()
    LEGACY_DB_FILE.rename(LEGACY_DB_FILE.with_suffix(".json.imported"))
    print(
        f"  📦 [db] Imported {len(records)} records from {LEGACY_DB_FILE.name} → SQLite"
    )


def _row_to_record(row) -> dict:
    """Deserialize a row into a record dict"""
    rec = json.loads(row["data"])
    rec["id"] = row["id"]
    return rec


def db_list() -> list:
    with _lock:
        rows = (
            _connect()
            .execute("SELECT id, data FROM records ORDER BY artist, title")
            .fetchall()
        )
    records = [_row_to_record(r) for r in rows]
    for r in records:
        r.pop("discogs_extra", None)
    return records


def db_get(rid: int):
    with _lock:
        row = (
            _connect()
            .execute("SELECT id, data FROM records WHERE id=?", (rid,))
            .fetchone()
        )
    return _row_to_record(row) if row else None


def db_find_duplicate(record: dict):
    """Existing record that duplicates `record`, or None"""
    conn = _connect()
    discogs_id = str(record.get("discogs_id", "")).strip()
    barcode = str(record.get("barcode", "")).strip()
    if discogs_id:
        row = conn.execute(
            "SELECT id, data FROM records WHERE discogs_id=? LIMIT 1", (discogs_id,)
        ).fetchone()
        if row:
            return _row_to_record(row)
    if barcode:
        row = conn.execute(
            "SELECT id, data FROM records WHERE barcode=? LIMIT 1", (barcode,)
        ).fetchone()
        if row:
            return _row_to_record(row)
    return None


def db_add(record: dict) -> int:
    with _lock:
        return _db_add_unlocked(record)


def _db_add_unlocked(record: dict) -> int:
    """Add a record — caller MUST already hold _lock. Does NOT re-acquire it."""
    conn = _connect()
    record["added_at"] = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO records(data) VALUES (json(?))", (json.dumps(record),)
    )
    conn.commit()
    record["id"] = cur.lastrowid
    return cast(int, cur.lastrowid)


def db_update(rid: int, fields: dict) -> bool:
    """Merge `fields` into the stored JSON. Returns True if the record existed."""
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT data FROM records WHERE id=?", (rid,)).fetchone()
        if not row:
            return False
        rec = json.loads(row["data"])
        rec.update(fields)
        conn.execute(
            "UPDATE records SET data=json(?) WHERE id=?", (json.dumps(rec), rid)
        )
        conn.commit()
        return True


def db_delete(rid: int) -> bool:
    with _lock:
        conn = _connect()
        cur = conn.execute("DELETE FROM records WHERE id=?", (rid,))
        conn.commit()
        return cur.rowcount > 0


def db_export() -> dict:
    """Full database in the legacy {schema_version, records} shape (export + backup)."""
    with _lock:
        rows = _connect().execute("SELECT id, data FROM records ORDER BY id").fetchall()
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "records": [_row_to_record(r) for r in rows],
    }
