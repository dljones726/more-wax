"""
Tests for the SQLite record store (server/database.py).
Each test gets a throwaway .db; the cached connection is reset between tests and
the legacy-JSON import is pointed at a non-existent path (see tests/_dbutil.py).
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path

import server.database as db_mod
from tests import _dbutil


class TestDatabase(unittest.TestCase):
    """CRUD + duplicate + export against the SQLite backend."""

    def setUp(self):
        _dbutil.fresh_db()

    def tearDown(self):
        _dbutil.close_db()

    # ── Add & List ──────────────────────────────────────────

    def test_add_and_list(self):
        rid = db_mod.db_add({"artist": "DJ Shadow", "title": "Endtroducing"})
        self.assertIsInstance(rid, int)
        records = db_mod.db_list()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["artist"], "DJ Shadow")
        self.assertEqual(records[0]["id"], rid)
        self.assertIn("added_at", records[0])

    def test_add_multiple_sorted(self):
        db_mod.db_add({"artist": "UNKLE", "title": "Psyence Fiction"})
        db_mod.db_add({"artist": "DJ Shadow", "title": "Endtroducing"})
        db_mod.db_add({"artist": "Attica Blues", "title": "Attica Blues"})
        artists = [r["artist"] for r in db_mod.db_list()]
        self.assertEqual(artists, ["Attica Blues", "DJ Shadow", "UNKLE"])

    def test_auto_increment_id(self):
        id1 = db_mod.db_add({"artist": "A"})
        id2 = db_mod.db_add({"artist": "B"})
        self.assertEqual(id2, id1 + 1)

    # ── Get ─────────────────────────────────────────────────

    def test_get_existing(self):
        rid = db_mod.db_add({"artist": "DJ Krush", "title": "Meiso"})
        rec = db_mod.db_get(rid)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["artist"], "DJ Krush")

    def test_get_nonexistent(self):
        self.assertIsNone(db_mod.db_get(9999))

    # ── Update ──────────────────────────────────────────────

    def test_update(self):
        rid = db_mod.db_add({"artist": "DJ Shadow", "title": "Endtroducing"})
        self.assertTrue(db_mod.db_update(rid, {"year": "1996", "label": "Mo'Wax"}))
        rec = db_mod.db_get(rid)
        self.assertEqual(rec["year"], "1996")
        self.assertEqual(rec["label"], "Mo'Wax")

    def test_update_nonexistent(self):
        self.assertFalse(db_mod.db_update(9999, {"year": "2000"}))

    # ── Delete ──────────────────────────────────────────────

    def test_delete(self):
        rid = db_mod.db_add({"artist": "DJ Shadow"})
        self.assertTrue(db_mod.db_delete(rid))
        self.assertIsNone(db_mod.db_get(rid))
        self.assertEqual(len(db_mod.db_list()), 0)

    def test_delete_nonexistent(self):
        self.assertFalse(db_mod.db_delete(9999))

    # ── Find duplicate ──────────────────────────────────────

    def test_find_duplicate_by_discogs_id(self):
        db_mod.db_add({"artist": "DJ Shadow", "discogs_id": "12345"})
        dup = db_mod.db_find_duplicate({"discogs_id": "12345"})
        self.assertIsNotNone(dup)
        self.assertEqual(dup["artist"], "DJ Shadow")

    def test_find_duplicate_by_discogs_id_as_int(self):
        """discogs_id stored as int should still match a string lookup."""
        db_mod.db_add({"artist": "DJ Shadow", "discogs_id": 12345})
        self.assertIsNotNone(db_mod.db_find_duplicate({"discogs_id": "12345"}))

    def test_find_duplicate_by_barcode(self):
        db_mod.db_add({"artist": "UNKLE", "barcode": "5021392052625"})
        self.assertIsNotNone(db_mod.db_find_duplicate({"barcode": "5021392052625"}))

    def test_find_no_duplicate(self):
        db_mod.db_add({"artist": "DJ Shadow", "discogs_id": "12345"})
        self.assertIsNone(db_mod.db_find_duplicate({"discogs_id": "99999"}))

    # ── Thread safety ───────────────────────────────────────

    def test_concurrent_adds(self):
        errors = []

        def add_record(i):
            try:
                db_mod.db_add({"artist": f"Artist {i}"})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=add_record, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        records = db_mod.db_list()
        self.assertEqual(len(records), 20)
        ids = [r["id"] for r in records]
        self.assertEqual(len(set(ids)), 20)  # all unique

    # ── Export ──────────────────────────────────────────────

    def test_export_returns_full_data(self):
        db_mod.db_add({"artist": "DJ Shadow", "title": "Endtroducing"})
        db_mod.db_add({"artist": "UNKLE", "title": "Psyence Fiction"})
        data = db_mod.db_export()
        self.assertIn("records", data)
        self.assertIn("schema_version", data)
        self.assertEqual(len(data["records"]), 2)

    def test_export_empty_db(self):
        self.assertEqual(len(db_mod.db_export()["records"]), 0)

    def test_export_includes_schema_version(self):
        data = db_mod.db_export()
        self.assertEqual(data["schema_version"], db_mod.EXPORT_SCHEMA_VERSION)

    # ── Partial / arbitrary fields ──────────────────────────

    def test_add_minimal_record(self):
        rid = db_mod.db_add({})
        self.assertIsInstance(rid, int)
        self.assertIsNotNone(db_mod.db_get(rid))

    def test_partial_fields_preserved(self):
        rid = db_mod.db_add({"artist": "Test", "custom_field": "value"})
        self.assertEqual(db_mod.db_get(rid).get("custom_field"), "value")

    def test_discogs_extra_stripped_from_list(self):
        rid = db_mod.db_add({"artist": "A", "discogs_id": "1"})
        db_mod.db_update(rid, {"discogs_extra": {"big": "blob"}})
        self.assertNotIn("discogs_extra", db_mod.db_list()[0])
        self.assertIn("discogs_extra", db_mod.db_get(rid))  # still on the single-get


class TestLegacyImport(unittest.TestCase):
    """One-time collection.json → SQLite import on first connect."""

    def tearDown(self):
        _dbutil.close_db()

    def test_imports_preserves_ids_and_renames(self):
        d = Path(tempfile.mkdtemp(prefix="morewax_test_"))
        legacy = d / "collection.json"
        legacy.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "records": [
                        {
                            "id": 5,
                            "artist": "DJ Shadow",
                            "title": "Endtro",
                            "discogs_id": "1",
                        },
                        {
                            "id": 9,
                            "artist": "UNKLE",
                            "title": "Psyence",
                            "discogs_id": "2",
                        },
                    ],
                }
            )
        )
        _dbutil.point_db(d / "collection.db", legacy)

        records = db_mod.db_list()
        self.assertEqual(len(records), 2)
        self.assertIsNotNone(db_mod.db_get(5))  # original ids preserved
        self.assertIsNotNone(db_mod.db_get(9))
        self.assertEqual(db_mod.db_get(5)["add_source"], "barcode")  # 1.0→1.1 default
        # Legacy file renamed so it won't re-import
        self.assertFalse(legacy.exists())
        self.assertTrue(legacy.with_suffix(".json.imported").exists())
        # Next insert continues past the max imported id
        self.assertGreater(db_mod.db_add({"artist": "New"}), 9)


class TestLikedTracks(unittest.TestCase):
    def setUp(self):
        _dbutil.fresh_db()
        self.rid = db_mod.db_add(
            {"title": "Test Album", "artist": "Test Artist", "discogs_id": "123"}
        )

    def tearDown(self):
        _dbutil.close_db()

    def test_liked_tracks_initially_absent(self):
        self.assertNotIn("liked_tracks", db_mod.db_get(self.rid))

    def test_update_liked_tracks(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1", "B2"]})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], ["A1", "B2"])

    def test_toggle_liked_track(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1", "B2"]})
        liked = db_mod.db_get(self.rid)["liked_tracks"]
        liked.remove("A1")
        db_mod.db_update(self.rid, {"liked_tracks": liked})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], ["B2"])

    def test_liked_tracks_empty_after_clearing(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1"]})
        db_mod.db_update(self.rid, {"liked_tracks": []})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], [])

    def test_liked_tracks_in_list_response(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1", "A2"]})
        r = next(x for x in db_mod.db_list() if x["id"] == self.rid)
        self.assertEqual(r["liked_tracks"], ["A1", "A2"])

    def test_liked_tracks_preserves_order(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["B2", "A1", "C3"]})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], ["B2", "A1", "C3"])

    def test_liked_tracks_allows_duplicates(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1", "A1"]})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], ["A1", "A1"])

    def test_liked_tracks_with_special_characters(self):
        tracks = ["A1", "Don't Stop", 'He Said "Hello"']
        db_mod.db_update(self.rid, {"liked_tracks": tracks})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], tracks)

    def test_liked_tracks_does_not_affect_other_fields(self):
        db_mod.db_update(self.rid, {"liked_tracks": ["A1"]})
        r = db_mod.db_get(self.rid)
        self.assertEqual(r["title"], "Test Album")
        self.assertEqual(r["artist"], "Test Artist")

    def test_liked_tracks_independent_per_record(self):
        rid2 = db_mod.db_add(
            {"title": "Album 2", "artist": "Artist 2", "discogs_id": "456"}
        )
        db_mod.db_update(self.rid, {"liked_tracks": ["A1"]})
        db_mod.db_update(rid2, {"liked_tracks": ["B1", "B2"]})
        self.assertEqual(db_mod.db_get(self.rid)["liked_tracks"], ["A1"])
        self.assertEqual(db_mod.db_get(rid2)["liked_tracks"], ["B1", "B2"])


if __name__ == "__main__":
    unittest.main()
