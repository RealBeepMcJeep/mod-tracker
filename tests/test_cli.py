import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker
from tests.test_report import sample


class CliTests(unittest.TestCase):
    def test_collect_defaults_match_required_scope(self):
        args = tracker.build_parser().parse_args(["collect"])
        self.assertEqual(args.thunderstore_pages, 10)
        self.assertEqual(args.nexus_pages, 1)
        self.assertEqual(args.sources, "all")

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

    def test_verify_output_counts_one_nexus_page_and_thunderstore_appearances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mods = [sample("nexus", str(index)) for index in range(80)]
            for mod in mods:
                mod["observations"] = []
            (root / "data").mkdir(parents=True)
            (root / "data/mods.json").write_text(json.dumps(mods))
            payload = {"data": {"mods": {"nodes": [{"modId": x} for x in range(80)]}}}
            target = root / "raw/nexus/listing-page-1.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload))
            result = tracker.verify_output(root, expected_thunderstore_pages=0, expected_nexus_pages=1)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["nexus_appearances"], 80)

    def test_verify_output_rejects_duplicate_nexus_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nodes = [{"modId": index} for index in range(79)] + [{"modId": 0}]
            target = root / "raw/nexus/listing-page-1.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"data": {"mods": {"nodes": nodes}}}))
            result = tracker.verify_output(
                root, expected_thunderstore_pages=0, expected_nexus_pages=1
            )
        self.assertFalse(result["ok"])
        self.assertTrue(any("distinct" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
