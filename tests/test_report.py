import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker


def sample(source, source_id, pinned=False, title="Mod"):
    return {
        "key": f"{source}:{source_id}", "source": source, "source_id": source_id,
        "title": title, "author": "Author", "summary": "Useful searchable summary",
        "categories": ["Gameplay"], "thumbnail": "https://cdn.example/icon.png",
        "canonical_url": f"https://example.test/{source_id}",
        "created_at": "2021-01-01T00:00:00Z", "updated_at": "2026-09-09T12:00:00Z",
        "total_downloads": 1000, "endorsements": 12, "likes": 3, "version": "1.2",
        "rank": 1, "ranks": {"last-updated": 1}, "pinned": pinned,
        "adult_content": False, "observations": [], "canonical_group_id": None,
        "match": None,
    }


class ReportTests(unittest.TestCase):
    def test_report_has_source_badges_clickable_cards_fixed_pins_and_sort_controls(self):
        mods = [sample("thunderstore", "A/Pinned", True, "Pinned"), sample("nexus", "79", False, "Nexus")]

        page = tracker.render_report(mods, "2026-09-09T20:00:00Z")

        self.assertEqual(page.count('class="mod-card'), 2)
        self.assertIn(">Thunderstore</span>", page)
        self.assertIn(">Nexus Mods</span>", page)
        self.assertIn('data-url="https://example.test/A/Pinned"', page)
        self.assertIn('id="pinned-group"', page)
        self.assertIn('id="regular-group"', page)
        self.assertIn('data-sort-lifetime-rate=', page)
        self.assertIn('data-sort-version-rate=', page)
        self.assertIn('data-sort-updated=', page)
        self.assertIn('data-sort-downloads=', page)
        self.assertIn('id="search"', page)
        self.assertIn('id="source-filter"', page)
        self.assertIn('id="results-count"', page)
        self.assertIn('class="media"', page)
        self.assertIn('class="tag"', page)
        self.assertIn("Uploaded", page)
        self.assertIn("Endorsements / likes", page)
        self.assertIn("minmax(280px,1fr)", page)
        self.assertIn("min-height:44px", page)
        self.assertIn("@media(max-width:520px)", page)
        self.assertIn("location.href", page)

    def test_report_escapes_fields_and_can_embed_thumbnails(self):
        mod = sample("nexus", "1", title='<script>alert("x")</script>')

        page = tracker.render_report(
            [mod], "2026-09-09T20:00:00Z",
            embed_thumbnails=True,
            thumbnail_fetch=lambda url: b"\x89PNG\r\n\x1a\nimage",
        )

        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("data:image/png;base64,", page)

    def test_manual_mapping_only_applies_explicit_metadata(self):
        mods = [sample("nexus", "79")]
        mappings = {"nexus:79": {"canonical_group_id": "circlet", "matched_to": ["thunderstore:A/B"], "method": "manual"}}

        mapped = tracker.apply_manual_mappings(mods, mappings)

        self.assertEqual(mapped[0]["canonical_group_id"], "circlet")
        self.assertEqual(mapped[0]["match"]["method"], "manual")
        self.assertIsNone(mods[0]["canonical_group_id"])

    def test_verifier_checks_card_count_groups_and_sort_attributes(self):
        page = tracker.render_report([sample("nexus", "79")], "2026-09-09T20:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(path, expected_cards=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["cards"], 1)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
