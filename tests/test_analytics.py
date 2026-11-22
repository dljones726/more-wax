"""Tests for server/analytics.py and the /api/analytics handler."""

import unittest

import server.database as db_mod
from server.analytics import _decade, _parse_list, compute_summary
from tests import _dbutil


class TestComputeSummary(unittest.TestCase):
    def test_empty(self):
        d = compute_summary([])
        self.assertEqual(d["count"], 0)
        self.assertEqual(
            d["value"], {"currency": "USD", "low": 0.0, "median": 0.0, "high": 0.0}
        )
        self.assertEqual(d["by_genre"], [])
        self.assertEqual(d["top_value"], [])

    def test_value_totals_and_currency(self):
        recs = [
            {
                "price_low": "10",
                "price_median": "20",
                "price_high": "30",
                "price_currency": "EUR",
            },
            {"price_low": "5", "price_median": "15", "price_high": "25"},
        ]
        self.assertEqual(
            compute_summary(recs)["value"],
            {"currency": "EUR", "low": 15.0, "median": 35.0, "high": 55.0},
        )

    def test_genre_aggregation_from_json_string(self):
        recs = [
            {"genres": '["Electronic","Hip Hop"]', "price_median": "10"},
            {"genres": '["Electronic"]', "price_median": "20"},
        ]
        by_genre = {g["name"]: g for g in compute_summary(recs)["by_genre"]}
        self.assertEqual(by_genre["Electronic"]["count"], 2)
        self.assertEqual(by_genre["Electronic"]["value"], 30.0)
        self.assertEqual(by_genre["Hip Hop"]["count"], 1)

    def test_decade_bucketing(self):
        recs = [
            {"year": "1996", "price_median": "10"},
            {"year": "2003", "price_median": "5"},
            {"year": ""},
        ]
        by_decade = {g["name"]: g for g in compute_summary(recs)["by_decade"]}
        self.assertIn("1990s", by_decade)
        self.assertIn("2000s", by_decade)
        self.assertEqual(by_decade["1990s"]["value"], 10.0)

    def test_top_value_sorted_desc_and_capped(self):
        recs = [{"id": i, "price_median": str(i)} for i in range(15)]
        top = compute_summary(recs)["top_value"]
        self.assertEqual(len(top), 10)
        self.assertEqual(top[0]["price_median"], 14.0)
        self.assertGreater(top[0]["price_median"], top[1]["price_median"])

    def test_rarest_filters_zero_and_ascending(self):
        recs = [
            {"id": 1, "num_for_sale": 5},
            {"id": 2, "num_for_sale": 1},
            {"id": 3, "num_for_sale": 0},  # excluded
            {"id": 4},  # excluded (missing)
        ]
        self.assertEqual([r["id"] for r in compute_summary(recs)["rarest"]], [2, 1])

    def test_highest_rated_filters_and_desc(self):
        recs = [
            {"id": 1, "rating_average": 3.0},
            {"id": 2, "rating_average": 4.5},
            {"id": 3, "rating_average": 0},  # excluded
        ]
        self.assertEqual(
            [r["id"] for r in compute_summary(recs)["highest_rated"]], [2, 1]
        )

    def test_missing_fields_do_not_crash(self):
        d = compute_summary([{}, {"artist": "x"}])
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["value"]["median"], 0.0)


class TestHelpers(unittest.TestCase):
    def test_parse_list(self):
        self.assertEqual(_parse_list('["a","b"]'), ["a", "b"])
        self.assertEqual(_parse_list(["a"]), ["a"])
        self.assertEqual(_parse_list(""), [])
        self.assertEqual(_parse_list(None), [])
        self.assertEqual(_parse_list("notjson"), ["notjson"])

    def test_decade(self):
        self.assertEqual(_decade("1996"), "1990s")
        self.assertEqual(_decade("2000"), "2000s")
        self.assertIsNone(_decade(""))
        self.assertIsNone(_decade(None))


class TestAnalyticsEndpoint(unittest.TestCase):
    def setUp(self):
        self._orig_db = db_mod.DB_FILE
        self._orig_legacy = db_mod.LEGACY_DB_FILE
        _dbutil.fresh_db()

    def tearDown(self):
        _dbutil.close_db()
        db_mod.DB_FILE = self._orig_db
        db_mod.LEGACY_DB_FILE = self._orig_legacy

    def test_summary_over_db(self):
        from server.api import analytics

        db_mod.db_add(
            {
                "artist": "DJ Shadow",
                "title": "Endtroducing",
                "genres": '["Electronic"]',
                "price_median": "35",
            }
        )
        status, payload = analytics.summary()
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["value"]["median"], 35.0)
        self.assertEqual(payload["by_genre"][0]["name"], "Electronic")


if __name__ == "__main__":
    unittest.main()
