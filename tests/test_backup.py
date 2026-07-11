"""
Tests for the Google Drive backup module (server/backup.py).
Pure logic only — no network. Uses a temp dir so tests never touch real data.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="morewax_backup_test_")


class TestBackup(unittest.TestCase):
    def setUp(self):
        import server.backup as bmod

        self.b = bmod
        self.dir = Path(_tmp)
        self.b.TOKEN_FILE = self.dir / "drive_backup.json"
        self.b.STATE_FILE = self.dir / "backup_state.json"
        self._db = self.dir / "collection.json"
        self._listens = self.dir / "listens.json"
        self.b.DB_FILE = self._db
        self.b.LISTENS_FILE = self._listens
        for f in (self.b.TOKEN_FILE, self.b.STATE_FILE, self._db, self._listens):
            if f.exists():
                f.unlink()
        self.b._access_cache.clear()

    # ── Retention ───────────────────────────────────────────

    def test_prune_nothing_when_under_limit(self):
        files = [{"id": str(i), "createdTime": f"2026-07-0{i}"} for i in range(1, 4)]
        self.assertEqual(self.b._files_to_prune(files, 14), [])

    def test_prune_keeps_newest(self):
        files = [
            {"id": str(i), "createdTime": f"2026-07-{i:02d}T00:00:00Z"}
            for i in range(1, 21)
        ]
        doomed = self.b._files_to_prune(files, 14)
        self.assertEqual(len(doomed), 6)
        doomed_ids = {f["id"] for f in doomed}
        self.assertEqual(doomed_ids, {"1", "2", "3", "4", "5", "6"})

    def test_prune_exact_limit(self):
        files = [
            {"id": str(i), "createdTime": f"2026-07-{i:02d}"} for i in range(1, 15)
        ]
        self.assertEqual(self.b._files_to_prune(files, 14), [])

    # ── Change detection ────────────────────────────────────

    def test_hash_stable_for_same_content(self):
        self._db.write_text('{"records": []}')
        self._listens.write_text('{"listens": []}')
        self.assertEqual(self.b._data_hash(), self.b._data_hash())

    def test_hash_changes_when_collection_changes(self):
        self._db.write_text('{"records": []}')
        self._listens.write_text('{"listens": []}')
        before = self.b._data_hash()
        self._db.write_text('{"records": [{"id": 1}]}')
        self.assertNotEqual(before, self.b._data_hash())

    def test_hash_changes_when_listens_change(self):
        self._db.write_text('{"records": []}')
        self._listens.write_text('{"listens": []}')
        before = self.b._data_hash()
        self._listens.write_text('{"listens": [{"id": 1}]}')
        self.assertNotEqual(before, self.b._data_hash())

    def test_hash_survives_missing_files(self):
        self.assertIsInstance(self.b._data_hash(), str)

    # ── Bundle ──────────────────────────────────────────────

    def test_bundle_contains_both_datasets(self):
        self._db.write_text('{"records": [{"id": 1}]}')
        self._listens.write_text('{"listens": [{"id": 9}]}')
        bundle = json.loads(self.b._build_bundle())
        self.assertEqual(bundle["collection"]["records"][0]["id"], 1)
        self.assertEqual(bundle["listens"]["listens"][0]["id"], 9)
        self.assertIn("backed_up_at", bundle)

    # ── Token lifecycle ─────────────────────────────────────

    def test_not_connected_initially(self):
        self.assertFalse(self.b.is_connected())

    def test_connected_after_token_saved(self):
        self.b._save_json(self.b.TOKEN_FILE, {"refresh_token": "r1"}, private=True)
        self.assertTrue(self.b.is_connected())
        mode = os.stat(self.b.TOKEN_FILE).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_disconnect_removes_token(self):
        self.b._save_json(self.b.TOKEN_FILE, {"refresh_token": "r1"}, private=True)
        self.b.disconnect()
        self.assertFalse(self.b.is_connected())
        self.assertFalse(self.b.TOKEN_FILE.exists())

    def test_disconnect_idempotent(self):
        self.b.disconnect()
        self.b.disconnect()
        self.assertFalse(self.b.is_connected())

    # ── Status ──────────────────────────────────────────────

    def test_status_not_connected(self):
        s = self.b.backup_status()
        self.assertFalse(s["connected"])
        self.assertEqual(s["email"], "")
        self.assertEqual(s["retention"], self.b.RETENTION)

    def test_status_pending_when_data_changed(self):
        self._db.write_text('{"records": []}')
        self._listens.write_text('{"listens": []}')
        self.b._save_json(
            self.b.TOKEN_FILE, {"refresh_token": "r1", "email": "a@b.c"}, private=True
        )
        self.b._save_json(self.b.STATE_FILE, {"last_hash": self.b._data_hash()})
        self.assertFalse(self.b.backup_status()["pending"])
        self._db.write_text('{"records": [{"id": 2}]}')
        self.assertTrue(self.b.backup_status()["pending"])

    def test_backup_now_without_connection_fails(self):
        result = self.b.backup_now()
        self.assertFalse(result["success"])
        self.assertIn("not connected", result["error"])


if __name__ == "__main__":
    unittest.main()
