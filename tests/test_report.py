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

    def test_mapped_sources_render_as_one_both_card_with_two_links(self):
        thunderstore = sample("thunderstore", "A/B", title="Shared")
        nexus = sample("nexus", "79", title="Shared")
        for mod, group, match in ((thunderstore, "shared", "nexus:79"), (nexus, "shared", "thunderstore:A/B")):
            mod["canonical_group_id"] = group
            mod["match"] = {"method": "manual", "matched_to": [match]}

        page = tracker.render_report([thunderstore, nexus], "2026-09-09T20:00:00Z")

        self.assertEqual(page.count('class="mod-card'), 1)
        self.assertIn(">Both</span>", page)
        self.assertIn('>Thunderstore</a>', page)
        self.assertIn('>Nexus Mods</a>', page)

    def test_report_has_static_nsfw_default_and_v1_boundary_metadata(self):
        adult = sample("nexus", "adult", title="Adult")
        adult["adult_content"] = True
        boundary = sample("nexus", "boundary", title="Boundary")
        boundary["updated_at"] = "2026-09-08T00:00:00Z"
        old = sample("thunderstore", "old", title="Old")
        old["updated_at"] = "2026-09-07T23:59:59Z"
        page = tracker.render_report([adult, boundary, old], "2026-09-09T20:00:00Z")
        self.assertIn('.mod-card[data-nsfw="true"]{display:none}', page)
        self.assertIn('id="nsfw-toggle"', page)
        self.assertIn('id="v1-toggle"', page)
        self.assertIn('data-v1="true"', page)
        self.assertIn('data-v1="false"', page)
        self.assertIn('Updated Sep 8, 2026 or later', page)

    def test_nsfw_toggle_can_override_static_default_hiding(self):
        adult = sample("nexus", "adult", title="Adult")
        adult["adult_content"] = True

        page = tracker.render_report([adult], "2026-09-09T20:00:00Z")

        self.assertIn('.show-nsfw .mod-card[data-nsfw="true"]{display:grid}', page)
        self.assertIn("document.body.classList.toggle('show-nsfw',nsfw.checked)", page)

    def test_report_cards_have_whole_card_source_tints(self):
        page = tracker.render_report([sample("thunderstore", "ts"), sample("nexus", "nx")], "2026-09-09T20:00:00Z")
        self.assertIn('.mod-card.source-thunderstore{background:var(--ts-bg)', page)
        self.assertIn('.mod-card.source-nexus{background:var(--nx-bg)', page)
        self.assertIn('.mod-card.source-both{background:linear-gradient', page)

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
