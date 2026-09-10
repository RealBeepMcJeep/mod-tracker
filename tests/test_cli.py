import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker
from tests.test_report import sample
from tests.test_tracker import CARD_PAGE


class CliTests(unittest.TestCase):
    def test_collect_defaults_match_required_scope(self):
        args = tracker.build_parser().parse_args(["collect"])
        self.assertIsNone(args.thunderstore_pages)
        self.assertIsNone(args.nexus_pages)
        self.assertEqual(args.sources, "all")
        self.assertEqual(args.game, "valheim")
        self.assertEqual(tracker.game_page_counts(tracker.GAME_CONFIGS["valheim"], args), (4, 2))

    def test_cli_page_flags_override_registry_defaults(self):
        args = tracker.build_parser().parse_args(
            ["collect", "--thunderstore-pages", "3", "--nexus-pages", "1"]
        )
        self.assertEqual(tracker.game_page_counts(tracker.GAME_CONFIGS["valheim"], args), (3, 1))

    def test_cli_accepts_retro_rewind_and_all_game_selection(self):
        retro = tracker.build_parser().parse_args(["collect", "--game", "retro-rewind"])
        all_games = tracker.build_parser().parse_args(["collect", "--game", "all"])

        self.assertEqual(retro.game, "retro-rewind")
        self.assertEqual(all_games.game, "all")

    def test_registry_contains_required_five_games_and_publication_routes(self):
        self.assertEqual(
            set(tracker.GAME_CONFIGS),
            {"valheim", "repo", "peak", "retro-rewind", "tcg-card-shop-simulator"},
        )
        destinations = set()
        for key, config in tracker.GAME_CONFIGS.items():
            self.assertIn("display_name", config)
            self.assertIn("sources", config)
            self.assertIn("output_subdir", config)
            self.assertIn("publication", config)
            self.assertIn("nexus_pages", config)
            if "thunderstore" in config["sources"]:
                self.assertIn("thunderstore_community", config)
                self.assertIn("thunderstore_pages", config)
            destination = (config["publication"]["section"], config["publication"]["name"])
            self.assertNotIn(destination, destinations)
            destinations.add(destination)

    def test_registry_allows_terminal_short_nexus_pages_for_peak_and_repo(self):
        self.assertFalse(tracker.GAME_CONFIGS["peak"]["require_full_nexus_pages"])
        self.assertFalse(tracker.GAME_CONFIGS["repo"]["require_full_nexus_pages"])

    def test_registry_rejects_escaping_output_path(self):
        registry = json.loads(Path(tracker.GAME_CONFIG_PATH).read_text())
        registry["repo"]["output_subdir"] = "../escape"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, "output_subdir"):
                tracker.load_game_registry(path)

    def test_game_root_preserves_valheim_and_isolates_retro_rewind(self):
        root = Path("/tmp/example")
        self.assertEqual(tracker.game_output_root(root, "valheim"), root)
        self.assertEqual(
            tracker.game_output_root(root, "retro-rewind"),
            root / "games/retro-rewind",
        )

    def test_all_non_valheim_games_have_isolated_roots(self):
        root = Path("/tmp/example")
        for key in set(tracker.GAME_CONFIGS) - {"valheim"}:
            resolved = tracker.game_output_root(root, key)
            self.assertNotEqual(resolved, root)
            self.assertTrue(resolved.is_relative_to(root))

    def test_netscape_cookie_jar_becomes_runtime_header(self):
        jar = "# Netscape HTTP Cookie File\n.nexusmods.com\tTRUE\t/\tTRUE\t1999999999\tsession\tprivate\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cookies.txt"
            path.write_text(jar)
            header = tracker.load_cookie_header(path)
        self.assertEqual(header, "session=private")

    def test_generate_report_writes_artifact_and_rates_to_flat_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = [sample("nexus", "79")]
            (root / "data").mkdir()
            (root / "data/mods.json").write_text(json.dumps(mods))

            result = tracker.generate_report(root, "2026-09-09T20:00:00Z")

            self.assertTrue((root / "report.html").exists())
            saved = json.loads((root / "data/mods.json").read_text())
            self.assertIn("rates", saved[0])
            self.assertEqual(result["cards"], 1)

    def test_collection_snapshot_records_actual_thunderstore_page_counts(self):
        actual_counts = {"last-updated": 2, "most-downloaded": 2}

        def collect_thunderstore(root, *args, **kwargs):
            tracker.atomic_write_json(
                root / "raw/thunderstore/listings/manifest.json",
                {
                    "requested_pages_per_sort": 4,
                    "rankings": {
                        ordering: {
                            "fetched_pages": count,
                            "terminal_http_status": 404,
                        }
                        for ordering, count in actual_counts.items()
                    },
                },
            )
            return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_file = root / "nexus-key"
            key_file.write_text("runtime-only")
            args = tracker.build_parser().parse_args([
                "collect",
                "--game",
                "tcg-card-shop-simulator",
                "--output-root",
                str(root),
                "--nexus-api-key-file",
                str(key_file),
            ])
            with patch.object(
                tracker, "collect_thunderstore", side_effect=collect_thunderstore
            ), patch.object(tracker, "collect_nexus", return_value=[]), patch.object(
                tracker, "generate_report", return_value={"cards": 0}
            ):
                result = tracker._run_game_collection(
                    args,
                    "tcg-card-shop-simulator",
                    "2026-09-10T00:00:00Z",
                )
            snapshot = json.loads(
                (
                    root
                    / "games/tcg-card-shop-simulator/snapshots/latest.json"
                ).read_text()
            )

        self.assertEqual(result["thunderstore_pages_per_sort"], actual_counts)
        self.assertEqual(snapshot["thunderstore_pages_per_sort"], actual_counts)

    def test_verify_output_counts_two_nexus_pages_and_thunderstore_appearances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = [sample("nexus", str(index)) for index in range(160)]
            for mod in mods:
                mod["observations"] = []
            (root / "data").mkdir(parents=True)
            (root / "data/mods.json").write_text(json.dumps(mods))
            for page in (1, 2):
                start = (page - 1) * 80
                payload = {"data": {"mods": {"nodes": [{"modId": x} for x in range(start, start + 80)]}}}
                target = root / f"raw/nexus/listing-page-{page}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(payload))
            result = tracker.verify_output(root, expected_thunderstore_pages=0, expected_nexus_pages=2)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["nexus_appearances"], 160)
        self.assertEqual(result["nexus_distinct"], 160)

    def test_verify_output_rejects_duplicate_nexus_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = [{"modId": index} for index in range(80)]
            second = [{"modId": index} for index in range(80, 159)] + [{"modId": 0}]
            for page, nodes in ((1, first), (2, second)):
                target = root / f"raw/nexus/listing-page-{page}.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"data": {"mods": {"nodes": nodes}}}))
            result = tracker.verify_output(
                root, expected_thunderstore_pages=0, expected_nexus_pages=2
            )
        self.assertFalse(result["ok"])
        self.assertTrue(any("distinct" in error for error in result["errors"]))

    def test_verify_output_accepts_terminal_short_page_for_small_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = [sample("nexus", "12")]
            mods[0]["observations"] = []
            (root / "data").mkdir(parents=True)
            (root / "data/mods.json").write_text(json.dumps(mods))
            target = root / "raw/nexus/listing-page-1.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({
                "data": {"mods": {"nodes": [{"modId": 12}]}}
            }))

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=2,
                require_full_nexus_pages=False,
            )

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["nexus_appearances"], 1)
        self.assertEqual(result["nexus_distinct"], 1)

    def test_verify_output_accepts_peak_and_repo_terminal_short_nexus_pages(self):
        cases = {
            "peak": [72],
            "repo": [80, 63],
        }
        for game, page_sizes in cases.items():
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tracker.atomic_write_json(root / "data/mods.json", [])
                next_id = 1
                for page, size in enumerate(page_sizes, 1):
                    nodes = [{"modId": value} for value in range(next_id, next_id + size)]
                    next_id += size
                    tracker.atomic_write_json(
                        root / f"raw/nexus/listing-page-{page}.json",
                        {"data": {"mods": {"nodes": nodes}}},
                    )

                result = tracker.verify_output(
                    root,
                    expected_thunderstore_pages=0,
                    expected_nexus_pages=2,
                    require_full_nexus_pages=tracker.GAME_CONFIGS[game][
                        "require_full_nexus_pages"
                    ],
                )

                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["nexus_appearances"], sum(page_sizes))
                self.assertEqual(result["nexus_distinct"], sum(page_sizes))

    def test_verify_output_accepts_recorded_thunderstore_terminal_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rankings = {}
            for ordering in ("last-updated", "most-downloaded"):
                directory = root / "raw/thunderstore/listings" / ordering
                directory.mkdir(parents=True)
                (directory / "page-1.html").write_text(CARD_PAGE, encoding="utf-8")
                rankings[ordering] = {
                    "fetched_pages": 1,
                    "terminal_http_status": 404,
                }
            tracker.atomic_write_json(
                root / "raw/thunderstore/listings/manifest.json",
                {"requested_pages_per_sort": 4, "rankings": rankings},
            )
            tracker.atomic_write_json(
                root / "snapshots/latest.json",
                {
                    "thunderstore_pages_per_sort": {
                        "last-updated": 1,
                        "most-downloaded": 1,
                    }
                },
            )
            tracker.atomic_write_json(root / "data/mods.json", [])

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=4,
                expected_nexus_pages=0,
            )

        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["thunderstore_appearances"], 2)
        self.assertEqual(
            result["thunderstore_pages_per_sort"],
            {"last-updated": 1, "most-downloaded": 1},
        )

    def test_verify_rejects_stale_pages_beyond_configured_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ordering in ("last-updated", "most-downloaded"):
                directory = root / "raw/thunderstore/listings" / ordering
                directory.mkdir(parents=True)
                (directory / "page-1.html").write_text(CARD_PAGE, encoding="utf-8")
                (directory / "page-2.html").write_text(
                    CARD_PAGE, encoding="utf-8"
                )
            tracker.atomic_write_json(root / "data/mods.json", [])

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=1,
                expected_nexus_pages=0,
            )

            self.assertFalse(result["ok"])
            self.assertTrue(any(
                "unexpected raw/thunderstore" in item for item in result["errors"]
            ))

    def test_all_source_compatibility_is_checked_before_collection(self):
        args = tracker.build_parser().parse_args([
            "collect", "--game", "all", "--sources", "thunderstore",
        ])
        with patch.object(tracker, "_run_game_collection") as run_game:
            with self.assertRaisesRegex(ValueError, "retro-rewind"):
                tracker.run_collection(args)
        run_game.assert_not_called()

    def test_strict_verify_requires_both_report_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/mods.json").write_text("[]")
            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=0,
                require_reports=True,
            )
        self.assertFalse(result["ok"])
        self.assertTrue(any("report.html" in error for error in result["errors"]))
        self.assertTrue(any("report-hotlinked.html" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
