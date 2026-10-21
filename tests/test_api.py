"""
Direct tests for the extracted server.api.* handlers.

These call the handler functions with plain inputs and assert on the returned
(status, payload) tuple — no HTTP socket needed, which is the point of the
extraction from the Handler class.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import server.config as _config


class TestCollectionHandlers(unittest.TestCase):
    def setUp(self):
        import server.database as db_mod

        self._db_mod = db_mod
        self._orig_cfg_db = _config.DB_FILE
        self._orig_mod_db = db_mod.DB_FILE
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.db_file = Path(path)
        _config.DB_FILE = self.db_file
        db_mod.DB_FILE = self.db_file
        with open(self.db_file, "w") as f:
            json.dump({"schema_version": "1.1", "records": [], "next_id": 1}, f)

    def tearDown(self):
        # Restore the module-level DB_FILE so later test modules aren't affected.
        _config.DB_FILE = self._orig_cfg_db
        self._db_mod.DB_FILE = self._orig_mod_db
        if self.db_file.exists():
            self.db_file.unlink()

    def test_add_get_update_delete_roundtrip(self):
        from server.api import collection

        status, payload = collection.add(
            {"title": "Discovery", "artist": "Daft Punk", "discogs_id": "111"}
        )
        self.assertEqual(status, 201)
        rid = payload["id"]

        status, rec = collection.get(rid)
        self.assertEqual(status, 200)
        self.assertEqual(rec["title"], "Discovery")

        status, payload = collection.update(rid, {"title": "Homework"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(collection.get(rid)[1]["title"], "Homework")

        status, listing = collection.list()
        self.assertEqual(status, 200)
        self.assertEqual(len(listing), 1)

        status, payload = collection.delete(rid)
        self.assertTrue(payload["success"])
        self.assertEqual(collection.get(rid), (404, {"error": "Not found"}))

    def test_add_only_allowlisted_fields(self):
        from server.api import collection

        _, payload = collection.add(
            {"title": "X", "artist": "Y", "evil": "DROP TABLE", "discogs_id": "9"}
        )
        _, rec = collection.get(payload["id"])
        self.assertNotIn("evil", rec)

    def test_duplicate_returns_409(self):
        from server.api import collection

        collection.add({"title": "A", "artist": "B", "discogs_id": "500"})
        status, payload = collection.add(
            {"title": "A2", "artist": "B2", "discogs_id": "500"}
        )
        self.assertEqual(status, 409)
        self.assertTrue(payload["duplicate"])


class TestValidationBranches(unittest.TestCase):
    """Pure validation paths that never touch the network."""

    def test_listens_list_bad_record_id(self):
        from server.api import listens

        self.assertEqual(
            listens.list("not-an-int"),
            (400, {"error": "record_id must be an integer"}),
        )

    def test_listens_add_missing_record_id(self):
        from server.api import listens

        status, payload = listens.add({})
        self.assertEqual(status, 400)

    def test_sync_import_no_selection(self):
        from server.api import sync

        status, payload = sync.import_({"selected": []})
        self.assertEqual(status, 400)

    def test_setup_validate_no_token(self):
        from server.api import settings

        self.assertEqual(
            settings.setup_validate({}),
            (400, {"valid": False, "error": "No token provided"}),
        )

    def test_convert_image_empty(self):
        from server.api import media

        status, payload = media.convert_image({})
        self.assertEqual(status, 500)
        self.assertFalse(payload["success"])

    def test_discogs_search_no_query(self):
        from server.api import discogs

        status, payload = discogs.search("", "")
        self.assertEqual(status, 400)

    def test_discogs_release_invalid_id(self):
        from server.api import discogs

        self.assertEqual(discogs.release("abc"), (400, {"error": "Invalid release ID"}))

    def test_settings_mask(self):
        from server.api.settings import _mask

        self.assertEqual(_mask("abcdefgh"), "••••efgh")
        self.assertEqual(_mask("abc"), "")


if __name__ == "__main__":
    unittest.main()
