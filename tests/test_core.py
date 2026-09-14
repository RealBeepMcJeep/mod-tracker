import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker


NOW = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)


class CoreModelTests(unittest.TestCase):
    def test_merge_preserves_manual_fields_when_fresh_record_has_none(self):
        old = [{"key": "nexus:79", "canonical_group_id": "group-1",
                "credited_author": "nexus:randy", "match": {"method": "manual"},
                "description": "old", "total_downloads": 1}]
        fresh = [{"key": "nexus:79", "canonical_group_id": None,
                  "credited_author": None, "match": None,
                  "description": "new", "total_downloads": 2}]
        merged = tracker.merge_mods(old, fresh, "2026-09-09T20:00:00Z")[0]
        self.assertEqual(merged["canonical_group_id"], "group-1")
        self.assertEqual(merged["credited_author"], "nexus:randy")
        self.assertEqual(merged["match"], {"method": "manual"})
        self.assertEqual(merged["description"], "new")
        self.assertEqual(merged["total_downloads"], 2)

    def test_merge_keeps_explicit_empty_mapping_fields_on_new_record(self):
        fresh = [{"key": "nexus:79", "canonical_group_id": None,
                  "credited_author": None, "match": None,
                  "description": "new", "total_downloads": 2}]
        merged = tracker.merge_mods([], fresh, "2026-09-09T20:00:00Z")[0]
        self.assertIn("canonical_group_id", merged)
        self.assertIn("credited_author", merged)
        self.assertIn("match", merged)
        self.assertIsNone(merged["canonical_group_id"])
        self.assertIsNone(merged["credited_author"])
        self.assertIsNone(merged["match"])
    def test_normalizes_nexus_graphql_and_detail_fields(self):
        node = {
            "modId": 79, "name": "Improved Dverger Circlet", "summary": "White light",
            "author": "RandyKnapp", "downloads": 10737, "endorsements": 699,
            "adultContent": False, "createdAt": "2021-02-22T06:04:51Z",
            "updatedAt": "2026-09-09T19:23:08Z", "version": "1.0.7",
            "fileSize": 349, "category": "Gameplay",
            "pictureUrl": "https://staticdelivery.nexusmods.com/79.png",
        }
        detail = {"unique_downloads": 7059, "views": 61114, "description": "Full text"}

        mod = tracker.normalize_nexus(node, detail, rank=2, collected_at="2026-09-09T20:00:00Z")

        self.assertEqual(mod["source"], "nexus")
        self.assertEqual(mod["source_id"], "79")
        self.assertEqual(mod["canonical_url"], "https://www.nexusmods.com/valheim/mods/79")
        self.assertEqual(mod["categories"], ["Gameplay"])
        self.assertEqual(mod["total_downloads"], 10737)
        self.assertEqual(mod["unique_downloads"], 7059)
        self.assertEqual(mod["views"], 61114)
        self.assertEqual(mod["rank"], 2)
        self.assertFalse(mod["pinned"])
        self.assertEqual(mod["raw_page_capture"]["status"], "unavailable")

    def test_normalizes_nexus_url_for_selected_game(self):
        node = {
            "modId": 12,
            "name": "Retro Mod",
            "createdAt": "2026-09-01T00:00:00Z",
            "updatedAt": "2026-09-09T00:00:00Z",
        }

        mod = tracker.normalize_nexus(
            node,
            {},
            rank=1,
            collected_at="2026-09-09T20:00:00Z",
            game_domain="retrorewindvideostoresimulator",
        )

        self.assertEqual(
            mod["canonical_url"],
            "https://www.nexusmods.com/retrorewindvideostoresimulator/mods/12",
        )

    def test_rates_use_lifetime_and_observed_current_version_delta(self):
        mod = {
            "created_at": "2026-09-04T20:00:00Z", "updated_at": "2026-09-07T20:00:00Z",
            "total_downloads": 1000, "version": "2.0",
            "observations": [
                {"observed_at": "2026-09-07T20:00:00Z", "downloads": 700, "version": "2.0"},
                {"observed_at": "2026-09-09T20:00:00Z", "downloads": 1000, "version": "2.0"},
            ],
        }

        rates = tracker.compute_rates(mod, NOW)

        self.assertEqual(rates["lifetime_downloads_per_day"], 200.0)
        self.assertEqual(rates["current_version_observed_downloads_per_day"], 150.0)
        self.assertEqual(rates["current_version_observed_delta"], 300)
        self.assertEqual(rates["current_version_baseline_at"], "2026-09-07T20:00:00Z")

    def test_lifetime_rate_rounds_age_up_to_full_days(self):
        cases = (
            ("2026-09-09T18:00:00Z", 510, 510.0),
            ("2026-09-08T20:00:00Z", 510, 510.0),
            ("2026-09-08T19:59:59Z", 510, 255.0),
            ("2026-09-01T15:00:00Z", 90, 10.0),
        )
        for created_at, downloads, expected in cases:
            with self.subTest(created_at=created_at):
                mod = {
                    "created_at": created_at,
                    "total_downloads": downloads,
                    "version": "1.0",
                    "observations": [],
                }
                self.assertEqual(
                    tracker.compute_rates(mod, NOW)["lifetime_downloads_per_day"],
                    expected,
                )

    def test_rate_is_unknown_until_two_current_version_observations_exist(self):
        mod = {
            "created_at": "2026-09-04T20:00:00Z", "updated_at": "2026-09-09T19:00:00Z",
            "total_downloads": 100, "version": "1.0",
            "observations": [
                {"observed_at": "2026-09-09T20:00:00Z", "downloads": 100, "version": "1.0"},
            ],
        }
        self.assertIsNone(tracker.compute_rates(mod, NOW)["current_version_observed_downloads_per_day"])

    def test_merge_adds_one_observation_per_snapshot_and_atomic_json_roundtrips(self):
        old = [{
            "key": "nexus:79", "source": "nexus", "source_id": "79", "version": "1.0.6",
            "total_downloads": 100, "observations": [
                {"observed_at": "2026-09-08T20:00:00Z", "downloads": 100, "version": "1.0.6"}
            ],
        }]
        fresh = [{"key": "nexus:79", "source": "nexus", "source_id": "79", "version": "1.0.7", "total_downloads": 120}]

        merged = tracker.merge_mods(old, fresh, "2026-09-09T20:00:00Z")
        again = tracker.merge_mods(merged, fresh, "2026-09-09T20:00:00Z")

        self.assertEqual(len(merged[0]["observations"]), 2)
        self.assertEqual(len(again[0]["observations"]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "mods.json"
            tracker.atomic_write_json(path, merged)
            self.assertEqual(json.loads(path.read_text()), merged)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
