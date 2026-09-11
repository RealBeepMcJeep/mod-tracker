import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/mapping_candidates.py"
SPEC = importlib.util.spec_from_file_location("mapping_candidates", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MappingCandidateTests(unittest.TestCase):
    def test_mapping_candidate_tool_exists(self):
        self.assertTrue(SCRIPT.is_file())

    def test_exposes_normalized_levenshtein_similarity(self):
        self.assertTrue(hasattr(MODULE, "levenshtein_similarity"))

    def test_exposes_cross_provider_candidate_ranking(self):
        self.assertTrue(hasattr(MODULE, "rank_candidates"))

    def test_blank_identity_records_are_not_candidates(self):
        mods = [
            {"key": "nexus:blank", "source": "nexus", "title": "", "author": ""},
            {"key": "thunderstore:blank", "source": "thunderstore", "title": "", "author": ""},
        ]

        self.assertEqual(MODULE.rank_candidates(mods, {}, min_score=0.0), [])

    def test_missing_title_identity_is_not_a_candidate(self):
        mods = [
            {"key": "nexus:missing-title", "source": "nexus", "author": "Author"},
            {"key": "thunderstore:identified", "source": "thunderstore", "title": "Mod", "author": "Author"},
        ]

        self.assertEqual(MODULE.rank_candidates(mods, {}, min_score=0.0), [])

    def test_output_replaces_symlink_without_following_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "games.json"
            registry.write_text(json.dumps({"single": {"output_subdir": "single", "sources": ["nexus"]}}), encoding="utf-8")
            (root / "single/data").mkdir(parents=True)
            (root / "single/data/mods.json").write_text("[]", encoding="utf-8")
            (root / "single/mappings.json").write_text("{}", encoding="utf-8")
            output = root / "shortlist.json"
            target = root / "outside-target"
            target.write_text("sentinel", encoding="utf-8")
            (root / ".shortlist.json.tmp-12345").symlink_to(target)

            argv = ["mapping_candidates.py", "--registry", str(registry), "--output", str(output)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(MODULE.os, "getpid", return_value=12345):
                self.assertEqual(MODULE.main(), 0)

            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")
            self.assertFalse(output.is_symlink())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["games"]["single"]["status"], "single-source")

    def test_output_rejects_symlinked_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "games.json"
            registry.write_text(
                json.dumps(
                    {
                        "single": {
                            "output_subdir": "single",
                            "sources": ["nexus"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "single/data").mkdir(parents=True)
            (root / "single/data/mods.json").write_text("[]", encoding="utf-8")
            (root / "single/mappings.json").write_text("{}", encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            alias = root / "alias"
            alias.symlink_to(outside, target_is_directory=True)

            argv = [
                "mapping_candidates.py",
                "--registry",
                str(registry),
                "--output",
                str(alias / "shortlist.json"),
            ]
            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as raised:
                    MODULE.main()

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse((outside / "shortlist.json").exists())

    def test_output_directory_swap_cannot_redirect_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "destination"
            destination.mkdir()
            original = root / "original"
            outside = root / "outside"
            outside.mkdir()

            def swap_parent(_length):
                destination.rename(original)
                destination.symlink_to(outside, target_is_directory=True)
                return "fixed-nonce"

            with mock.patch.object(
                MODULE.secrets, "token_hex", side_effect=swap_parent
            ):
                MODULE._atomic_write_text(destination / "result.json", "safe\n")

            self.assertEqual((original / "result.json").read_text(), "safe\n")
            self.assertFalse((outside / "result.json").exists())

    def test_input_directory_swap_cannot_redirect_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            (game / "data").mkdir(parents=True)
            expected = [{"key": "nexus:safe"}]
            (game / "data/mods.json").write_text(json.dumps(expected))
            outside = root / "outside"
            (outside / "data").mkdir(parents=True)
            (outside / "data/mods.json").write_text(
                json.dumps([{"key": "nexus:unsafe"}])
            )
            descriptor = MODULE._open_directory(game)
            original = root / "original"
            game.rename(original)
            game.symlink_to(outside, target_is_directory=True)
            try:
                actual = MODULE._load_json_at(
                    descriptor, Path("data/mods.json"), [], "mods"
                )
            finally:
                MODULE.os.close(descriptor)

            self.assertEqual(actual, expected)

    def test_cli_rejects_limit_above_documented_maximum(self):
        with mock.patch.object(sys, "argv", ["mapping_candidates.py", "--limit", "21"]):
            with self.assertRaises(SystemExit) as raised:
                MODULE.main()
        self.assertEqual(raised.exception.code, 2)

    def test_data_symlink_escape_is_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "outside"
            outside.mkdir()
            (outside / "mods.json").write_text("[]", encoding="utf-8")
            (outside / "mappings.json").write_text("{}", encoding="utf-8")
            game = root / "game"
            (game / "data").mkdir(parents=True)
            (game / "data/mods.json").symlink_to(outside / "mods.json")
            (game / "mappings.json").write_text("{}", encoding="utf-8")
            registry = root / "games.json"
            registry.write_text(json.dumps({"game": {"output_subdir": "game", "sources": ["nexus", "thunderstore"]}}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "escapes project root"):
                MODULE.build_report(registry, "game", 1, 0.45)

    def test_registry_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "games.json").write_text(
                json.dumps(
                    {
                        "single": {
                            "output_subdir": "single",
                            "sources": ["nexus"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (outside / "single/data").mkdir(parents=True)
            (outside / "single/data/mods.json").write_text("[]", encoding="utf-8")
            (outside / "single/mappings.json").write_text("{}", encoding="utf-8")
            registry_alias = root / "games.json"
            registry_alias.symlink_to(outside / "games.json")

            with self.assertRaises(OSError):
                MODULE.build_report(registry_alias, "all", 20, 0.45)

    def test_ranking_is_independent_of_input_order(self):
        mods = [
            {"key": "nexus:b", "source": "nexus", "title": "Beta", "author": "B"},
            {"key": "thunderstore:B/Beta", "source": "thunderstore", "title": "Beta", "author": "B"},
            {"key": "nexus:a", "source": "nexus", "title": "Alpha", "author": "A"},
            {"key": "thunderstore:A/Alpha", "source": "thunderstore", "title": "Alpha", "author": "A"},
        ]

        self.assertEqual(
            MODULE.rank_candidates(mods, {}, limit=2, min_score=0.0),
            MODULE.rank_candidates(list(reversed(mods)), {}, limit=2, min_score=0.0),
        )

    def test_ranks_only_unmapped_cross_provider_pairs_with_components(self):
        mods = [
            {
                "key": "nexus:1",
                "source": "nexus",
                "title": "Equipment and Quick Slots",
                "author": "Randy Knapp",
                "summary": "Adds equipment and quick slots.",
                "description": "Adds equipment and quick slots to Valheim.",
            },
            {
                "key": "thunderstore:RandyKnapp/EquipmentAndQuickSlots",
                "source": "thunderstore",
                "title": "EquipmentAndQuickSlots",
                "author": "RandyKnapp",
                "summary": "Adds equipment and quick slots.",
                "description": "Adds equipment and quick slots to Valheim.",
            },
            {
                "key": "nexus:2",
                "source": "nexus",
                "title": "Unrelated Nexus Mod",
                "author": "Someone",
                "summary": "Nothing alike",
                "description": "Nothing alike",
            },
            {
                "key": "thunderstore:Other/Other",
                "source": "thunderstore",
                "title": "Other Package",
                "author": "Other",
                "summary": "Different",
                "description": "Different",
            },
        ]
        mappings = {
            "nexus:2": {"matched_to": ["thunderstore:Other/Other"]},
            "thunderstore:Other/Other": {"matched_to": ["nexus:2"]},
        }

        candidates = MODULE.rank_candidates(mods, mappings, limit=1, min_score=0.40)

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["nexus_key"], "nexus:1")
        self.assertEqual(
            candidate["thunderstore_key"],
            "thunderstore:RandyKnapp/EquipmentAndQuickSlots",
        )
        self.assertEqual(
            set(candidate["components"]),
            {"title_levenshtein", "title_tokens", "description_tokens", "author_levenshtein"},
        )
        self.assertGreater(candidate["score"], 0.90)
        self.assertTrue(candidate["reasons"])

    def test_cli_emits_bounded_all_game_report_with_single_source_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = {
                "dual": {"output_subdir": "dual", "sources": ["thunderstore", "nexus"]},
                "single": {"output_subdir": "single", "sources": ["nexus"]},
            }
            (root / "games.json").write_text(json.dumps(registry), encoding="utf-8")
            for game in registry:
                (root / game / "data").mkdir(parents=True)
                (root / game / "mappings.json").write_text("{}", encoding="utf-8")
            dual_mods = [
                {"key": "nexus:1", "source": "nexus", "title": "Same Mod", "author": "Author", "summary": "Same feature"},
                {"key": "thunderstore:Author/SameMod", "source": "thunderstore", "title": "SameMod", "author": "Author", "summary": "Same feature"},
            ]
            (root / "dual/data/mods.json").write_text(json.dumps(dual_mods), encoding="utf-8")
            (root / "single/data/mods.json").write_text(
                json.dumps([dual_mods[0]]), encoding="utf-8"
            )
            output = root / "shortlist.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--registry",
                    str(root / "games.json"),
                    "--game",
                    "all",
                    "--limit",
                    "1",
                    "--min-score",
                    "0.4",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output.is_file())
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["games"]["dual"]["candidate_count"], 1)
            self.assertEqual(len(report["games"]["dual"]["candidates"]), 1)
            self.assertEqual(report["games"]["single"]["status"], "single-source")
            self.assertEqual(report["games"]["single"]["candidates"], [])


if __name__ == "__main__":
    unittest.main()
