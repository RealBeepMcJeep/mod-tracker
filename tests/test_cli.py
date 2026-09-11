import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker
from tests.test_report import sample
from tests.test_tracker import CARD_PAGE


class CliTests(unittest.TestCase):
    def test_registry_uses_mod_tracking_publication_tree(self):
        registry = tracker.load_game_registry()
        self.assertEqual(
            {config["publication"]["root"] for config in registry.values()},
            {"mod-tracking"},
        )
        self.assertEqual(
            {key: config["publication"]["path"] for key, config in registry.items()},
            {key: key for key in registry},
        )
        for config in registry.values():
            self.assertNotIn("section", config["publication"])
            self.assertNotIn("name", config["publication"])

    def test_registry_rejects_noncanonical_publication_root_or_path(self):
        for field, value in (("root", "other-root"), ("path", "not-peak")):
            with self.subTest(field=field):
                registry = json.loads(Path(tracker.GAME_CONFIG_PATH).read_text())
                registry["peak"]["publication"][field] = value
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "games.json"
                    path.write_text(json.dumps(registry), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "canonical publication"):
                        tracker.load_game_registry(path)

    def test_dual_source_collection_overlaps_provider_work(self):
        thunderstore_started = threading.Event()
        nexus_started = threading.Event()

        def collect_thunderstore(root, *args, **kwargs):
            thunderstore_started.set()
            self.assertTrue(
                nexus_started.wait(1),
                "Nexus collection did not overlap Thunderstore collection",
            )
            tracker.atomic_write_json(
                root / "raw/thunderstore/listings/manifest.json",
                {
                    "requested_pages_per_sort": 4,
                    "rankings": {
                        ordering: {
                            "fetched_pages": 4,
                            "terminal_http_status": None,
                        }
                        for ordering in ("last-updated", "most-downloaded")
                    },
                },
            )
            return []

        def collect_nexus(*args, **kwargs):
            nexus_started.set()
            self.assertTrue(
                thunderstore_started.wait(1),
                "Thunderstore collection did not overlap Nexus collection",
            )
            return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_file = root / "nexus-key"
            key_file.write_text("runtime-only")
            args = tracker.build_parser().parse_args([
                "collect",
                "--game",
                "peak",
                "--output-root",
                str(root),
                "--nexus-api-key-file",
                str(key_file),
            ])
            with patch.object(
                tracker, "collect_thunderstore", side_effect=collect_thunderstore
            ), patch.object(
                tracker, "collect_nexus", side_effect=collect_nexus
            ), patch.object(
                tracker, "generate_report", return_value={"cards": 0}
            ):
                result = tracker._run_game_collection(
                    args, "peak", "2026-09-10T19:00:00Z"
                )

        self.assertEqual(result["fresh_records"], 0)

    def test_dual_source_collection_aggregates_both_provider_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key_file = root / "nexus-key"
            key_file.write_text("runtime-only")
            args = tracker.build_parser().parse_args([
                "collect",
                "--game",
                "peak",
                "--output-root",
                str(root),
                "--nexus-api-key-file",
                str(key_file),
            ])
            with patch.object(
                tracker,
                "collect_thunderstore",
                side_effect=RuntimeError("Thunderstore unavailable"),
            ), patch.object(
                tracker,
                "collect_nexus",
                side_effect=RuntimeError("Nexus unavailable"),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    tracker._run_game_collection(
                        args, "peak", "2026-09-10T19:00:00Z"
                    )

        message = str(raised.exception)
        self.assertIn("thunderstore: Thunderstore unavailable", message)
        self.assertIn("nexus: Nexus unavailable", message)

    def test_provider_failure_does_not_partially_merge_or_render(self):
        def collect_thunderstore(root, *args, **kwargs):
            tracker.atomic_write_json(
                root / "raw/thunderstore/listings/manifest.json",
                {
                    "requested_pages_per_sort": 4,
                    "rankings": {
                        ordering: {
                            "fetched_pages": 4,
                            "terminal_http_status": None,
                        }
                        for ordering in ("last-updated", "most-downloaded")
                    },
                },
            )
            return [sample("thunderstore", "Example/SuccessfulRawResult")]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game_root = root / "games/peak"
            key_file = root / "nexus-key"
            key_file.write_text("runtime-only")
            protected = {
                game_root / "data/mods.json": b'[{"unchanged": true}]\n',
                game_root / "snapshots/latest.json": b'{"unchanged": true}\n',
                game_root / "report.html": b"old local report\n",
                game_root / "report-hotlinked.html": b"old public report\n",
            }
            for path, payload in protected.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            args = tracker.build_parser().parse_args([
                "collect",
                "--game",
                "peak",
                "--output-root",
                str(root),
                "--nexus-api-key-file",
                str(key_file),
            ])
            with patch.object(
                tracker, "collect_thunderstore", side_effect=collect_thunderstore
            ), patch.object(
                tracker, "collect_nexus", side_effect=RuntimeError("Nexus unavailable")
            ), patch.object(tracker, "generate_report") as generate_report:
                with self.assertRaises(RuntimeError):
                    tracker._run_game_collection(
                        args, "peak", "2026-09-10T19:00:00Z"
                    )
                generate_report.assert_not_called()
            for path, payload in protected.items():
                self.assertEqual(path.read_bytes(), payload)

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

    def test_registry_configures_per_game_update_filters(self):
        self.assertEqual(
            tracker.GAME_CONFIGS["peak"]["update_filter"],
            {"label": "v2.0 filter", "cutoff": "2026-08-10T00:00:00Z"},
        )
        self.assertEqual(
            tracker.GAME_CONFIGS["repo"]["update_filter"],
            {"label": "v0.4 filter", "cutoff": "2026-05-07T00:00:00Z"},
        )
        self.assertEqual(
            tracker.GAME_CONFIGS["valheim"]["update_filter"],
            {"label": "v1 filter", "cutoff": "2026-09-08T00:00:00Z"},
        )
        self.assertIsNone(tracker.GAME_CONFIGS["retro-rewind"]["update_filter"])
        self.assertIsNone(
            tracker.GAME_CONFIGS["tcg-card-shop-simulator"]["update_filter"]
        )

    def test_registry_enables_dynamic_author_tiers_for_all_games(self):
        expected = {
            "percentiles": {
                "uncommon": 60,
                "rare": 70,
                "epic": 80,
                "legendary": 90,
            },
            "mappings_file": "author-mappings.json",
        }
        for game in tracker.GAME_CONFIGS:
            with self.subTest(game=game):
                self.assertEqual(tracker.GAME_CONFIGS[game]["author_tiers"], expected)

    def test_report_path_passes_author_tiers_for_every_selected_game(self):
        args = tracker.build_parser().parse_args(["report", "--game", "all"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            tracker, "generate_report", return_value={"ok": True}
        ) as generate:
            tracker._generate_selected_reports(args, "2026-09-11T02:00:00Z")

        self.assertEqual(generate.call_count, len(tracker.GAME_CONFIGS))
        for call in generate.call_args_list:
            self.assertEqual(
                call.kwargs["author_tiers"],
                {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                 "mappings_file": "author-mappings.json"},
            )

    def test_verify_path_passes_author_tiers_for_every_selected_game(self):
        args = tracker.build_parser().parse_args(["verify", "--game", "all"])
        with patch.object(
            tracker, "verify_output", return_value={"ok": True}
        ) as verify:
            tracker._verify_selected_outputs(args)

        self.assertEqual(verify.call_count, len(tracker.GAME_CONFIGS))
        for call in verify.call_args_list:
            self.assertEqual(
                call.kwargs["author_tiers"],
                {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                 "mappings_file": "author-mappings.json"},
            )

    def test_registry_rejects_misordered_author_tier_percentiles(self):
        registry = json.loads(json.dumps(tracker.GAME_CONFIGS))
        registry["valheim"]["author_tiers"]["percentiles"] = {
            "uncommon": 60,
            "rare": 70,
            "epic": 80,
            "legendary": 75,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, "invalid author_tiers percentiles"):
                tracker.load_game_registry(path)

    def test_registry_rejects_escaping_author_mapping_path(self):
        registry = json.loads(json.dumps(tracker.GAME_CONFIGS))
        registry["valheim"]["author_tiers"]["mappings_file"] = "../authors.json"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, "invalid author_tiers mappings_file"):
                tracker.load_game_registry(path)

    def test_author_mapping_loader_accepts_reciprocal_source_identities(self):
        mappings = {
            "nexus:jere kuusela": {
                "canonical_author_id": "jere-kuusela",
                "matched_to": ["thunderstore:jerekuusela"],
                "method": "manual",
            },
            "thunderstore:jerekuusela": {
                "canonical_author_id": "jere-kuusela",
                "matched_to": ["nexus:jere kuusela"],
                "method": "manual",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "author-mappings.json"
            path.write_text(json.dumps(mappings))
            loaded = tracker.load_author_mappings(path)

        self.assertEqual(loaded, mappings)

    def test_author_mapping_loader_rejects_nonreciprocal_mapping(self):
        mappings = {
            "nexus:jere kuusela": {
                "canonical_author_id": "jere-kuusela",
                "matched_to": ["thunderstore:jerekuusela"],
                "method": "manual",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "author-mappings.json"
            path.write_text(json.dumps(mappings))
            with self.assertRaisesRegex(ValueError, "reciprocal"):
                tracker.load_author_mappings(path)

    def test_author_mapping_loader_rejects_invalid_source_identity(self):
        mappings = {
            "steam:author": {
                "canonical_author_id": "author",
                "matched_to": [],
                "method": "manual",
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "author-mappings.json"
            path.write_text(json.dumps(mappings))
            with self.assertRaisesRegex(ValueError, "source-scoped identity"):
                tracker.load_author_mappings(path)

    def test_author_mapping_loader_reports_unreadable_or_malformed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = root / "malformed.json"
            malformed.write_text("{not-json")
            for path in (root / "missing.json", malformed):
                with self.subTest(path=path.name):
                    with self.assertRaisesRegex(ValueError, "unable to load author mappings"):
                        tracker.load_author_mappings(path)

    def test_author_mapping_loader_rejects_same_provider_aliases(self):
        mappings = {
            "nexus:alice": {
                "canonical_author_id": "alice",
                "matched_to": ["nexus:alice-alt"],
                "method": "manual",
            },
            "nexus:alice-alt": {
                "canonical_author_id": "alice",
                "matched_to": ["nexus:alice"],
                "method": "manual",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "author-mappings.json"
            path.write_text(json.dumps(mappings))
            with self.assertRaisesRegex(ValueError, "cross-provider"):
                tracker.load_author_mappings(path)

    def test_author_mapping_loader_rejects_malformed_duplicate_or_conflicting_entries(self):
        valid_pair = {
            "nexus:alice": {
                "canonical_author_id": "alice",
                "matched_to": ["thunderstore:alice"],
                "method": "manual",
            },
            "thunderstore:alice": {
                "canonical_author_id": "alice",
                "matched_to": ["nexus:alice"],
                "method": "manual",
            },
        }
        cases = {}
        malformed = json.loads(json.dumps(valid_pair))
        del malformed["nexus:alice"]["method"]
        cases["malformed"] = malformed
        duplicate = json.loads(json.dumps(valid_pair))
        duplicate["nexus:alice"]["matched_to"].append("thunderstore:alice")
        cases["duplicate"] = duplicate
        invalid_canonical = json.loads(json.dumps(valid_pair))
        invalid_canonical["nexus:alice"]["canonical_author_id"] = "Invalid Canonical"
        cases["invalid canonical"] = invalid_canonical
        conflicting = json.loads(json.dumps(valid_pair))
        conflicting["thunderstore:alice"]["canonical_author_id"] = "other-alice"
        cases["conflicting"] = conflicting

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "author-mappings.json"
            for name, mappings in cases.items():
                with self.subTest(case=name):
                    path.write_text(json.dumps(mappings))
                    with self.assertRaises(ValueError):
                        tracker.load_author_mappings(path)

    def test_registry_rejects_update_filter_without_explicit_utc_cutoff(self):
        registry = json.loads(json.dumps(tracker.GAME_CONFIGS))
        registry["peak"]["update_filter"]["cutoff"] = "2026-08-10"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "games.json"
            path.write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, "invalid update_filter cutoff"):
                tracker.load_game_registry(path)

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
            destination = (config["publication"]["root"], config["publication"]["path"])
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

    def test_generate_report_persists_and_renders_author_reputation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = []
            for downloads in range(1, 101):
                mod = sample("nexus", str(downloads))
                mod.update(author=f"Author {downloads}", total_downloads=downloads)
                mods.append(mod)
            tracker.atomic_write_json(root / "data/mods.json", mods)
            tracker.atomic_write_json(root / "author-mappings.json", {})

            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                author_tiers={
                    "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                    "mappings_file": "author-mappings.json",
                },
            )

            reputation = json.loads((root / "data/author-reputation.json").read_text())
            page = (root / "report-hotlinked.html").read_text()

        self.assertEqual(
            reputation["cutoffs"],
            {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
        )
        self.assertEqual(reputation["generated_at"], "2026-09-11T02:00:00Z")
        self.assertIn('class="author author-tier-legendary"', page)

    def test_verify_output_rejects_missing_author_reputation_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = sample("nexus", "1")
            tracker.atomic_write_json(root / "data/mods.json", [mod])
            tracker.atomic_write_json(root / "author-mappings.json", {})
            config = {
                "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                "mappings_file": "author-mappings.json",
            }
            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                update_filter=None,
                author_tiers=config,
            )
            (root / "data/author-reputation.json").unlink()

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=0,
                update_filter=None,
                author_tiers=config,
                require_reports=True,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("author reputation" in error for error in result["errors"]))

    def test_verify_output_rejects_missing_author_metadata_on_one_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = sample("nexus", "1")
            first["author"] = "Alice"
            second = sample("nexus", "2")
            second["author"] = "Bob"
            tracker.atomic_write_json(root / "data/mods.json", [first, second])
            tracker.atomic_write_json(root / "author-mappings.json", {})
            config = {
                "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                "mappings_file": "author-mappings.json",
            }
            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                update_filter=None,
                author_tiers=config,
            )
            reputation = json.loads(
                (root / "data/author-reputation.json").read_text()
            )
            alice = tracker.render_author_name(first, reputation)
            for report_name in ("report.html", "report-hotlinked.html"):
                path = root / report_name
                path.write_text(path.read_text().replace(alice, "Alice", 1))

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=0,
                update_filter=None,
                author_tiers=config,
                require_reports=True,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("rendered author identities" in error for error in result["errors"]))

    def test_verify_output_rejects_tampered_reputation_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker.atomic_write_json(root / "data/mods.json", [sample("nexus", "1")])
            tracker.atomic_write_json(root / "author-mappings.json", {})
            config = {
                "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                "mappings_file": "author-mappings.json",
            }
            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                update_filter=None,
                author_tiers=config,
            )
            reputation_path = root / "data/author-reputation.json"
            original = json.loads(reputation_path.read_text())
            mutations = {
                "threshold": lambda data: data["cutoffs"].__setitem__("uncommon", 999),
                "generated_at": lambda data: data.__setitem__("generated_at", "not-a-time"),
            }
            for field, mutate in mutations.items():
                with self.subTest(field=field):
                    altered = json.loads(json.dumps(original))
                    mutate(altered)
                    tracker.atomic_write_json(reputation_path, altered)
                    result = tracker.verify_output(
                        root,
                        expected_thunderstore_pages=0,
                        expected_nexus_pages=0,
                        update_filter=None,
                        author_tiers=config,
                        require_reports=True,
                    )
                    self.assertFalse(result["ok"], field)
                    self.assertTrue(any("author reputation" in error for error in result["errors"]))

    def test_verify_output_accepts_valid_author_reputation_after_report_only_regeneration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker.atomic_write_json(root / "data/mods.json", [sample("nexus", "1")])
            tracker.atomic_write_json(root / "author-mappings.json", {})
            tracker.atomic_write_json(
                root / "snapshots/latest.json",
                {"collected_at": "2026-09-10T02:00:00Z"},
            )
            config = {
                "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                "mappings_file": "author-mappings.json",
            }
            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                update_filter=None,
                author_tiers=config,
            )

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=0,
                update_filter=None,
                author_tiers=config,
                require_reports=True,
            )

        self.assertTrue(result["ok"], result["errors"])

    def test_verify_output_rejects_valid_but_substituted_reputation_generation_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracker.atomic_write_json(root / "data/mods.json", [sample("nexus", "1")])
            tracker.atomic_write_json(root / "author-mappings.json", {})
            tracker.atomic_write_json(
                root / "snapshots/latest.json",
                {"collected_at": "2026-09-11T02:00:00Z"},
            )
            config = {
                "percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
                "mappings_file": "author-mappings.json",
            }
            tracker.generate_report(
                root,
                "2026-09-11T02:00:00Z",
                update_filter=None,
                author_tiers=config,
            )
            reputation_path = root / "data/author-reputation.json"
            reputation = json.loads(reputation_path.read_text())
            reputation["generated_at"] = "2026-09-12T02:00:00Z"
            tracker.atomic_write_json(reputation_path, reputation)

            result = tracker.verify_output(
                root,
                expected_thunderstore_pages=0,
                expected_nexus_pages=0,
                update_filter=None,
                author_tiers=config,
                require_reports=True,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("generated_at" in error for error in result["errors"]))

    def test_all_game_reports_isolate_author_pools_and_render_every_tier(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            expected_cutoffs = {}
            for game_index, game in enumerate(tracker.GAME_CONFIGS):
                root = tracker.game_output_root(output_root, game)
                base = game_index * 1000
                mods = []
                for downloads in range(1, 101):
                    mod = sample("nexus", f"{game_index}-{downloads}")
                    mod.update(
                        author=f"{game} Author {downloads}",
                        total_downloads=base + downloads,
                    )
                    mods.append(mod)
                tracker.atomic_write_json(root / "data/mods.json", mods)
                tracker.atomic_write_json(root / "author-mappings.json", {})
                expected_cutoffs[game] = {
                    "uncommon": base + 60,
                    "rare": base + 70,
                    "epic": base + 80,
                    "legendary": base + 90,
                }

            args = tracker.build_parser().parse_args(
                ["report", "--game", "all", "--output-root", str(output_root)]
            )
            result = tracker._generate_selected_reports(
                args, "2026-09-11T02:00:00Z"
            )

            self.assertTrue(result["ok"])
            for game in tracker.GAME_CONFIGS:
                root = tracker.game_output_root(output_root, game)
                reputation = json.loads(
                    (root / "data/author-reputation.json").read_text()
                )
                page = (root / "report-hotlinked.html").read_text()
                self.assertEqual(reputation["cutoffs"], expected_cutoffs[game])
                self.assertTrue(
                    all(
                        identity.startswith("nexus:" + game.casefold())
                        for identity in reputation["authors"]
                    )
                )
                for tier in ("common", "uncommon", "rare", "epic", "legendary"):
                    self.assertIn(f"author-tier-{tier}", page)

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
