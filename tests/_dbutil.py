"""Shared helpers for pointing server.database at a throwaway SQLite DB in tests.

Not collected by unittest (filename doesn't match test*.py). Two jobs:

1. Reset the module's cached `_conn` between tests — otherwise the first test's
   connection leaks into later tests that set a different DB_FILE.
2. Point LEGACY_DB_FILE at a non-existent path so the one-time JSON import never
   fires against (and renames!) the developer's real data/collection.json.
"""

import json
import tempfile
from pathlib import Path

import server.database as db_mod


def close_db():
    """Close + drop the cached connection so the next _connect() is fresh."""
    if db_mod._conn is not None:
        try:
            db_mod._conn.close()
        except Exception:
            pass
    db_mod._conn = None


def point_db(db_path: Path, legacy_path: Path | None = None):
    """Point server.database at db_path (fresh connection), with legacy import off."""
    close_db()
    db_mod.DB_FILE = db_path
    db_mod.LEGACY_DB_FILE = legacy_path or db_path.with_name("_no_legacy_.json")


def fresh_db() -> Path:
    """New temp .db in its own dir, connection reset, legacy import disabled.

    Returns the .db Path. Call in setUp; call close_db() in tearDown.
    """
    d = Path(tempfile.mkdtemp(prefix="morewax_test_"))
    db_path = d / "collection.db"
    point_db(db_path)
    return db_path


def seed(records):
    """Insert records into the current DB, preserving an explicit 'id' when given.

    Lets tests reproduce fixed ids (e.g. local record id 1) the way the old JSON
    fixtures did; db_add() alone would assign fresh autoincrement ids.
    """
    conn = db_mod._connect()
    for rec in records:
        rid = rec.get("id")
        if rid is not None:
            conn.execute(
                "INSERT INTO records(id, data) VALUES (?, json(?))",
                (rid, json.dumps(rec)),
            )
        else:
            conn.execute(
                "INSERT INTO records(data) VALUES (json(?))", (json.dumps(rec),)
            )
    conn.commit()
