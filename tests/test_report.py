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
    def test_embedded_local_report_still_writes_hotlinked_publication_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = sample("nexus", "8", title="Embedded")
            mod["thumbnail"] = "https://images.example/8.png"
            tracker.atomic_write_json(root / "data/mods.json", [mod])

            tracker.generate_report(
                root,
                "2026-09-10T12:00:00Z",
                embed_thumbnails=True,
                game_name="PEAK",
                sources=("nexus",),
                update_filter=None,
                thumbnail_fetch=lambda url: b"\x89PNG\r\n\x1a\nimage",
            )

            self.assertIn("data:image/", (root / "report.html").read_text())
            self.assertNotIn(
                "data:image/", (root / "report-hotlinked.html").read_text()
            )

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

    def test_report_renders_uploaded_and_updated_as_aligned_rows(self):
        page = tracker.render_report(
            [sample("thunderstore", "A/B")],
            "2026-09-09T20:00:00Z",
        )

        self.assertIn(
            '<div class="dates"><div class="date-row"><span class="date-label">Updated</span><time datetime="2026-09-09T12:00:00Z">2026-09-09</time></div><div class="date-row"><span class="date-label">Uploaded</span><time datetime="2021-01-01T00:00:00Z">2021-01-01</time></div></div>',
            page,
        )
        self.assertNotIn(" · Uploaded ", page)
        self.assertIn(".dates{display:grid;gap:4px", page)
        self.assertIn(
            ".date-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px",
            page,
        )
        self.assertIn(".date-row time{white-space:nowrap}", page)
        self.assertIn(
            "@media(max-width:360px){.date-row{grid-template-columns:1fr;gap:0}}",
            page,
        )

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

    def test_report_uses_game_label_and_can_omit_valheim_v1_filter(self):
        page = tracker.render_report(
            [sample("nexus", "12", title="Retro Mod")],
            "2026-09-09T20:00:00Z",
            game_name="Retro Rewind - Video Store Simulator",
            sources=("nexus",),
            update_filter=None,
        )

        self.assertIn("<title>Retro Rewind - Video Store Simulator Mod Tracker</title>", page)
        self.assertIn("<h1>Retro Rewind - Video Store Simulator Mod Tracker</h1>", page)
        self.assertIn("on Nexus Mods.", page)
        self.assertNotIn('id="update-filter-toggle"', page)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(path, expected_cards=1, update_filter=None)
        self.assertTrue(result["ok"], result["errors"])

    def test_non_valheim_dual_source_report_names_both_sources(self):
        page = tracker.render_report(
            [sample("thunderstore", "A/B"), sample("nexus", "12")],
            "2026-09-09T20:00:00Z",
            game_name="PEAK",
            sources=("thunderstore", "nexus"),
            update_filter=None,
        )
        self.assertIn("PEAK mods across Thunderstore and Nexus Mods.", page)

    def test_nexus_only_report_does_not_claim_thunderstore(self):
        page = tracker.render_report(
            [sample("nexus", "12")],
            "2026-09-09T20:00:00Z",
            game_name="Retro Rewind - Video Store Simulator",
            sources=("nexus",),
            update_filter=None,
        )
        subtitle = page.split('<p class="subtitle">', 1)[1].split("</p>", 1)[0]
        self.assertIn("on Nexus Mods.", subtitle)
        self.assertNotIn("Thunderstore", subtitle)

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

    def test_shared_update_filter_uses_configured_label_and_inclusive_boundary(self):
        boundary = sample("nexus", "boundary", title="Boundary")
        boundary["updated_at"] = "2026-08-10T00:00:00Z"
        old = sample("thunderstore", "old", title="Old")
        old["updated_at"] = "2026-08-09T23:59:59Z"

        page = tracker.render_report(
            [boundary, old],
            "2026-09-09T20:00:00Z",
            game_name="PEAK",
            update_filter=tracker.GAME_CONFIGS["peak"]["update_filter"],
        )

        self.assertIn('id="update-filter-toggle"', page)
        self.assertIn('data-update-filter="true"', page)
        self.assertIn('data-update-filter="false"', page)
        self.assertIn(
            '<span title="Shows mods updated on or after Aug 10, 2026; not a semantic version filter.">v2.0 filter</span>',
            page,
        )
        self.assertIn("c.dataset.updateFilter==='true'", page)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path,
                expected_cards=2,
                update_filter=tracker.GAME_CONFIGS["peak"]["update_filter"],
            )
        self.assertTrue(result["ok"], result["errors"])

    def test_grouped_update_filter_uses_chronologically_latest_member(self):
        at_cutoff = sample("nexus", "79", title="At cutoff")
        at_cutoff["updated_at"] = "2026-08-09T20:00:00-04:00"
        before_cutoff = sample("thunderstore", "A/B", title="Before cutoff")
        before_cutoff["updated_at"] = "2026-08-09T23:59:59Z"
        for mod in (at_cutoff, before_cutoff):
            mod["canonical_group_id"] = "shared-offset-group"

        page = tracker.render_report(
            [at_cutoff, before_cutoff],
            "2026-09-09T20:00:00Z",
            update_filter=tracker.GAME_CONFIGS["peak"]["update_filter"],
        )

        self.assertEqual(page.count('class="mod-card'), 1)
        self.assertIn('data-update-filter="true"', page)
        self.assertIn('data-sort-updated="2026-08-09T20:00:00-04:00"', page)

    def test_shared_update_filter_compares_equivalent_utc_offsets(self):
        equivalent = sample("nexus", "equivalent", title="Equivalent")
        equivalent["updated_at"] = "2026-08-09T20:00:00-04:00"

        page = tracker.render_report(
            [equivalent],
            "2026-09-09T20:00:00Z",
            game_name="PEAK",
            update_filter=tracker.GAME_CONFIGS["peak"]["update_filter"],
        )

        self.assertIn('data-update-filter="true"', page)

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
        self.assertIn('id="update-filter-toggle"', page)
        self.assertIn('data-update-filter="true"', page)
        self.assertIn('data-update-filter="false"', page)
        self.assertIn('<span title="Shows mods updated on or after Sep 8, 2026; not a semantic version filter.">v1 filter</span>', page)
        self.assertIn('<p>Generated Sep 9, 2026 at 1:00 PM MST.</p>', page)
        self.assertNotIn('NSFW mods are hidden by default.', page)
        self.assertNotIn('The v1 filter means', page)

    def test_nsfw_toggle_can_override_static_default_hiding(self):
        adult = sample("nexus", "adult", title="Adult")
        adult["adult_content"] = True

        page = tracker.render_report([adult], "2026-09-09T20:00:00Z")

        self.assertIn('.show-nsfw .mod-card[data-nsfw="true"]{display:grid}', page)
        self.assertIn("document.body.classList.toggle('show-nsfw',nsfw.checked)", page)
        self.assertIn('<span class="results" id="results-count">0 results</span>', page)

    def test_report_cards_have_whole_card_source_tints(self):
        page = tracker.render_report([sample("thunderstore", "ts"), sample("nexus", "nx")], "2026-09-09T20:00:00Z")
        self.assertIn('.mod-card.source-thunderstore{background:var(--ts-bg)', page)
        self.assertIn('.mod-card.source-nexus{background:var(--nx-bg)', page)
        self.assertIn('.mod-card.source-both{background:linear-gradient', page)

    def test_report_formats_display_numbers_but_keeps_raw_sort_values(self):
        thunderstore = sample("thunderstore", "A/B", title="Shared")
        nexus = sample("nexus", "79", title="Shared")
        thunderstore.update(total_downloads=787350, endorsements=12345, likes=6789)
        nexus.update(total_downloads=33203, endorsements=2345, likes=0)
        for mod, match in ((thunderstore, "nexus:79"), (nexus, "thunderstore:A/B")):
            mod["canonical_group_id"] = "shared"
            mod["match"] = {"method": "manual", "matched_to": [match]}

        page = tracker.render_report([thunderstore, nexus], "2026-09-09T20:00:00Z")

        self.assertIn('<dt>Nexus Mods downloads</dt><dd>33,203</dd>', page)
        self.assertIn('<dt>Thunderstore downloads</dt><dd>787,350</dd>', page)
        self.assertIn('<dd>12,345 / 6,789</dd>', page)
        self.assertRegex(page, r'<dt>Combined lifetime / day</dt><dd>[0-9,]+\.\d</dd>')
        self.assertIn('data-sort-downloads="820553"', page)

    def test_mapped_card_combines_cross_source_rate_sort_values(self):
        thunderstore = sample("thunderstore", "A/B", title="Shared")
        nexus = sample("nexus", "79", title="Shared")
        thunderstore.update(total_downloads=2000, observations=[
            {"observed_at": "2026-09-08T20:00:00Z", "downloads": 1000, "version": "1.2"},
            {"observed_at": "2026-09-09T20:00:00Z", "downloads": 2000, "version": "1.2"},
        ])
        nexus.update(total_downloads=5000, observations=[
            {"observed_at": "2026-09-08T20:00:00Z", "downloads": 3000, "version": "1.2"},
            {"observed_at": "2026-09-09T20:00:00Z", "downloads": 5000, "version": "1.2"},
        ])
        for mod, match in ((thunderstore, "nexus:79"), (nexus, "thunderstore:A/B")):
            mod["canonical_group_id"] = "shared"
            mod["match"] = {"method": "manual", "matched_to": [match]}

        expected_lifetime = sum(
            tracker.compute_rates(mod, tracker.parse_datetime("2026-09-09T20:00:00Z"))["lifetime_downloads_per_day"]
            for mod in (thunderstore, nexus)
        )
        page = tracker.render_report([thunderstore, nexus], "2026-09-09T20:00:00Z")

        self.assertIn('data-sort-downloads="7000"', page)
        self.assertIn(f'data-sort-lifetime-rate="{expected_lifetime}"', page)
        self.assertIn('data-sort-version-rate="3000.0"', page)
        self.assertIn('<dt>Combined lifetime / day</dt>', page)

    def test_mobile_toggles_stay_inline_and_title_links_inherit_card_color(self):
        page = tracker.render_report([sample("nexus", "79", title="White title")], "2026-09-09T20:00:00Z")

        self.assertIn('<div class="toggle-row">', page)
        self.assertIn('<label class="toggle-control"><input id="nsfw-toggle" type="checkbox"><span>Show NSFW mods</span></label>', page)
        self.assertIn('<label class="toggle-control"><input id="update-filter-toggle" type="checkbox"><span title="Shows mods updated on or after Sep 8, 2026; not a semantic version filter.">v1 filter</span></label>', page)
        self.assertIn('.toggle-row{display:flex', page)
        self.assertIn('.toggle-control{display:flex;align-items:center', page)
        self.assertIn('.toggle-control input{width:18px;height:18px;min-height:0', page)
        self.assertIn('.body h2 a,.body h2 a:visited{color:var(--text)', page)
        self.assertIn('.body{padding:15px;min-width:0;overflow-wrap:anywhere}', page)
        self.assertIn('.mod-card{display:grid;grid-template-columns:minmax(0,1fr)', page)
        self.assertIn('.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))', page)
        self.assertIn('.mod-card{display:grid;grid-template-columns:88px minmax(0,1fr)', page)
        self.assertIn('.metrics{grid-column:1/-1;grid-template-columns:repeat(2,minmax(0,1fr))}', page)
        self.assertIn('.badges{display:flex;gap:6px;flex-wrap:wrap', page)
        self.assertIn('.tags{display:flex;flex-wrap:wrap;gap:4px}', page)
        self.assertIn('.tag{background:#252a31;color:var(--muted);margin:2px;max-width:100%;overflow-wrap:anywhere}', page)
        self.assertNotIn('.control,input{width:100%}', page)

    def test_all_configured_games_share_update_filter_renderer(self):
        cases = {
            "peak": ("2026-08-10T00:00:00Z", "2026-08-09T23:59:59Z", "Aug 10, 2026", "v2.0 filter"),
            "repo": ("2026-05-07T00:00:00Z", "2026-05-06T23:59:59Z", "May 7, 2026", "v0.4 filter"),
            "valheim": ("2026-09-08T00:00:00Z", "2026-09-07T23:59:59Z", "Sep 8, 2026", "v1 filter"),
        }
        for game, (boundary_at, old_at, display_date, label) in cases.items():
            with self.subTest(game=game):
                boundary = sample("nexus", f"{game}-boundary")
                boundary["updated_at"] = boundary_at
                old = sample("nexus", f"{game}-old")
                old["updated_at"] = old_at
                update_filter = tracker.GAME_CONFIGS[game]["update_filter"]
                page = tracker.render_report(
                    [boundary, old],
                    "2026-09-09T20:00:00Z",
                    update_filter=update_filter,
                )
                self.assertEqual(page.count('id="update-filter-toggle"'), 1)
                self.assertIn(f'>{label}</span>', page)
                self.assertIn(f"updated on or after {display_date}", page)
                self.assertEqual(page.count('data-update-filter="true"'), 1)
                self.assertEqual(page.count('data-update-filter="false"'), 1)

    def test_verifier_rejects_incorrect_update_filter_card_metadata(self):
        update_filter = tracker.GAME_CONFIGS["peak"]["update_filter"]
        page = tracker.render_report(
            [sample("nexus", "79")],
            "2026-09-09T20:00:00Z",
            update_filter=update_filter,
        ).replace('data-update-filter="true"', 'data-update-filter="false"', 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path, expected_cards=1, update_filter=update_filter
            )
        self.assertFalse(result["ok"])
        self.assertIn("1 cards have incorrect update-filter metadata", result["errors"])

    def test_verifier_rejects_update_filter_control_for_filterless_report(self):
        page = tracker.render_report(
            [sample("nexus", "79")],
            "2026-09-09T20:00:00Z",
            update_filter=None,
        )
        nsfw_control = '<label class="toggle-control"><input id="nsfw-toggle" type="checkbox"><span>Show NSFW mods</span></label>'
        page = page.replace(
            nsfw_control,
            nsfw_control
            + tracker.render_update_filter_control(
                tracker.GAME_CONFIGS["peak"]["update_filter"]
            ),
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path, expected_cards=1, update_filter=None
            )
        self.assertFalse(result["ok"])
        self.assertIn("unexpected update-filter control", result["errors"])

    def test_verifier_rejects_missing_shared_update_filter_javascript(self):
        update_filter = tracker.GAME_CONFIGS["repo"]["update_filter"]
        page = tracker.render_report(
            [sample("nexus", "79")],
            "2026-09-09T20:00:00Z",
            update_filter=update_filter,
        ).replace("c.dataset.updateFilter==='true'", "true")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path, expected_cards=1, update_filter=update_filter
            )
        self.assertFalse(result["ok"])
        self.assertIn("missing shared update-filter JavaScript", result["errors"])

    def test_verifier_rejects_mismatched_update_filter_metadata(self):
        update_filter = tracker.GAME_CONFIGS["peak"]["update_filter"]
        page = tracker.render_report(
            [sample("nexus", "79")],
            "2026-09-09T20:00:00Z",
            update_filter=update_filter,
        ).replace("v2.0 filter", "wrong filter")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path, expected_cards=1, update_filter=update_filter
            )

        self.assertFalse(result["ok"])
        self.assertIn("update-filter control does not match configuration", result["errors"])

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
