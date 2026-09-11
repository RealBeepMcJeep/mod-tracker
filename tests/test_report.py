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
    def test_author_rarity_uses_dynamic_per_game_percentiles(self):
        mods = []
        for downloads in range(1, 101):
            mod = sample("nexus", str(downloads))
            mod["author"] = f"Author {downloads}"
            mod["total_downloads"] = downloads
            mods.append(mod)

        reputation = tracker.build_author_reputation(
            mods,
            {
                "percentiles": {
                    "uncommon": 60,
                    "rare": 70,
                    "epic": 80,
                    "legendary": 90,
                }
            },
            {},
        )

        self.assertEqual(
            reputation["cutoffs"],
            {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90},
        )
        self.assertEqual(reputation["authors"]["nexus:author 59"]["tier"], "common")
        self.assertEqual(reputation["authors"]["nexus:author 60"]["tier"], "uncommon")
        self.assertEqual(reputation["authors"]["nexus:author 69"]["tier"], "uncommon")
        self.assertEqual(reputation["authors"]["nexus:author 70"]["tier"], "rare")
        self.assertEqual(reputation["authors"]["nexus:author 79"]["tier"], "rare")
        self.assertEqual(reputation["authors"]["nexus:author 80"]["tier"], "epic")
        self.assertEqual(reputation["authors"]["nexus:author 89"]["tier"], "epic")
        self.assertEqual(reputation["authors"]["nexus:author 90"]["tier"], "legendary")

    def test_author_reputation_sums_raw_downloads_per_source_scoped_identity(self):
        nexus_one = sample("nexus", "1")
        nexus_one.update(author="Shared Name", total_downloads=100)
        nexus_two = sample("nexus", "2")
        nexus_two.update(author=" shared   name ", total_downloads=250)
        thunderstore = sample("thunderstore", "Team/Package")
        thunderstore.update(author="Shared Name", total_downloads=900)

        reputation = tracker.build_author_reputation(
            [nexus_one, nexus_two, thunderstore],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )

        self.assertEqual(reputation["authors"]["nexus:shared name"]["downloads"], 350)
        self.assertEqual(
            reputation["authors"]["thunderstore:shared name"]["downloads"], 900
        )

    def test_author_reputation_combines_only_explicitly_mapped_identities(self):
        nexus = sample("nexus", "1")
        nexus.update(author="Shared Name", total_downloads=350)
        thunderstore = sample("thunderstore", "Team/Package")
        thunderstore.update(author="SharedName", total_downloads=900)
        mappings = {
            "nexus:shared name": {
                "canonical_author_id": "shared-author",
                "matched_to": ["thunderstore:sharedname"],
                "method": "manual",
            },
            "thunderstore:sharedname": {
                "canonical_author_id": "shared-author",
                "matched_to": ["nexus:shared name"],
                "method": "manual",
            },
        }

        reputation = tracker.build_author_reputation(
            [nexus, thunderstore],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            mappings,
        )

        self.assertEqual(reputation["authors"]["nexus:shared name"]["downloads"], 1250)
        self.assertEqual(
            reputation["authors"]["thunderstore:sharedname"],
            reputation["authors"]["nexus:shared name"],
        )
        self.assertEqual(
            reputation["authors"]["nexus:shared name"]["canonical_author_id"],
            "shared-author",
        )

    def test_author_reputation_tracks_distinct_mod_count_and_first_publication(self):
        nexus = sample("nexus", "1")
        nexus.update(
            author="Shared Name",
            canonical_group_id="shared-mod",
            created_at="2022-01-01T00:00:00Z",
            total_downloads=100,
        )
        thunderstore = sample("thunderstore", "Team/Package")
        thunderstore.update(
            author="SharedName",
            canonical_group_id="shared-mod",
            created_at="2021-12-31T17:00:00-07:00",
            total_downloads=200,
        )
        second = sample("nexus", "2")
        second.update(
            author=" shared   name ",
            created_at="2020-06-01T12:30:00Z",
            total_downloads=300,
        )
        mappings = {
            "nexus:shared name": {
                "canonical_author_id": "shared-author",
                "matched_to": ["thunderstore:sharedname"],
                "method": "manual",
            },
            "thunderstore:sharedname": {
                "canonical_author_id": "shared-author",
                "matched_to": ["nexus:shared name"],
                "method": "manual",
            },
        }

        reputation = tracker.build_author_reputation(
            [nexus, thunderstore, second],
            {
                "percentiles": {
                    "uncommon": 60,
                    "rare": 70,
                    "epic": 80,
                    "legendary": 90,
                }
            },
            mappings,
        )

        assert reputation is not None
        profile = reputation["authors"]["nexus:shared name"]
        self.assertEqual(profile["downloads"], 600)
        self.assertEqual(profile["mod_count"], 2)
        self.assertEqual(profile["first_mod_published_at"], "2020-06-01T12:30:00Z")
        self.assertEqual(
            profile,
            reputation["authors"]["thunderstore:sharedname"],
        )

    def test_author_reputation_rejects_invalid_download_totals(self):
        config = {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}}
        for invalid in (True, "not-a-number"):
            with self.subTest(invalid=invalid):
                mod = sample("nexus", "1")
                mod["total_downloads"] = invalid
                with self.assertRaisesRegex(ValueError, "total_downloads"):
                    tracker.build_author_reputation([mod], config, {})

    def test_author_reputation_empty_pool_has_no_profiles(self):
        reputation = tracker.build_author_reputation(
            [],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        assert reputation is not None
        self.assertEqual(reputation["authors"], {})
        self.assertEqual(
            reputation["cutoffs"],
            {"uncommon": 0, "rare": 0, "epic": 0, "legendary": 0},
        )

    def test_author_reputation_one_author_is_legendary(self):
        mod = sample("nexus", "1")
        mod.update(author="Solo", total_downloads=10)
        reputation = tracker.build_author_reputation(
            [mod],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        assert reputation is not None
        self.assertEqual(
            reputation["cutoffs"],
            {"uncommon": 10, "rare": 10, "epic": 10, "legendary": 10},
        )
        self.assertEqual(reputation["authors"]["nexus:solo"]["tier"], "legendary")

    def test_author_reputation_promotes_all_ties_at_a_cutoff(self):
        totals = (1, 10, 10, 20, 30)
        mods = []
        for index, downloads in enumerate(totals):
            mod = sample("nexus", str(index))
            mod.update(author=f"Author {index}", total_downloads=downloads)
            mods.append(mod)
        reputation = tracker.build_author_reputation(
            mods,
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        assert reputation is not None
        self.assertEqual(reputation["cutoffs"]["uncommon"], 10)
        self.assertEqual(reputation["authors"]["nexus:author 1"]["tier"], "uncommon")
        self.assertEqual(reputation["authors"]["nexus:author 2"]["tier"], "uncommon")

    def test_author_reputation_skips_missing_authors_and_clamps_negative_totals(self):
        missing = sample("nexus", "1")
        missing.update(author="", total_downloads=500)
        negative = sample("nexus", "2")
        negative.update(author="Known", total_downloads=-50)
        absent = sample("nexus", "3")
        absent.update(author="Known", total_downloads=None)
        reputation = tracker.build_author_reputation(
            [missing, negative, absent],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        assert reputation is not None
        self.assertEqual(set(reputation["authors"]), {"nexus:known"})
        self.assertEqual(reputation["authors"]["nexus:known"]["downloads"], 0)

    def test_grouped_card_uses_primary_source_identity_with_explicit_combined_author_total(self):
        nexus = sample("nexus", "1")
        nexus.update(
            author="Alice Nexus",
            total_downloads=100,
            canonical_group_id="shared-mod",
            updated_at="2026-09-11T00:00:00Z",
        )
        thunderstore = sample("thunderstore", "Alice/Mod")
        thunderstore.update(
            author="Alice TS",
            total_downloads=200,
            canonical_group_id="shared-mod",
            updated_at="2026-09-10T00:00:00Z",
        )
        mappings = {
            "nexus:alice nexus": {
                "canonical_author_id": "alice",
                "matched_to": ["thunderstore:alice ts"],
                "method": "manual",
            },
            "thunderstore:alice ts": {
                "canonical_author_id": "alice",
                "matched_to": ["nexus:alice nexus"],
                "method": "manual",
            },
        }
        reputation = tracker.build_author_reputation(
            [nexus, thunderstore],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            mappings,
        )
        page = tracker.render_report(
            [nexus, thunderstore],
            "2026-09-11T02:00:00Z",
            author_reputation=reputation,
        )

        self.assertEqual(page.count('class="mod-card'), 1)
        self.assertIn('data-author-key="nexus:alice nexus"', page)
        self.assertIn('data-author-canonical="alice"', page)
        self.assertIn('data-author-downloads="300"', page)
        self.assertEqual(
            tracker.report_author_keys([nexus, thunderstore], reputation),
            ["nexus:alice nexus"],
        )

    def test_report_colors_author_names_by_dynamic_rarity(self):
        mods = []
        for downloads in range(1, 101):
            mod = sample("nexus", str(downloads))
            mod["author"] = f"Author {downloads}"
            mod["total_downloads"] = downloads
            mods.append(mod)
        config = {
            "percentiles": {
                "uncommon": 60,
                "rare": 70,
                "epic": 80,
                "legendary": 90,
            }
        }
        reputation = tracker.build_author_reputation(mods, config, {})

        page = tracker.render_report(
            mods,
            "2026-09-11T02:00:00Z",
            author_reputation=reputation,
        )

        for tier, author, downloads in (
            ("common", "Author 59", 59),
            ("uncommon", "Author 60", 60),
            ("rare", "Author 70", 70),
            ("epic", "Author 80", 80),
            ("legendary", "Author 90", 90),
        ):
            self.assertIn(
                f'class="author author-tier-{tier}" data-author-tier="{tier}"',
                page,
            )
            self.assertIn(
                f'{tier.title()} author · {downloads:,} lifetime downloads',
                page,
            )
            self.assertIn(f'>{author}</span>', page)
        self.assertIn("--author-common:#f2f4f7", page)
        self.assertIn("--author-uncommon:#4ade80", page)
        self.assertIn("--author-rare:#4da3ff", page)
        self.assertIn("--author-epic:#c084fc", page)
        self.assertIn("--author-legendary:#fb923c", page)
        for tier in ("common", "uncommon", "rare", "epic", "legendary"):
            self.assertIn(f".author-tier-{tier}{{color:var(--author-{tier})", page)

    def test_author_tooltip_lists_known_mod_count_and_first_publication(self):
        mod = sample("nexus", "1")
        reputation = {
            "authors": {
                "nexus:author": {
                    "canonical_author_id": "nexus:author",
                    "downloads": 1234,
                    "mod_count": 2,
                    "first_mod_published_at": "2020-06-01T12:30:00Z",
                    "tier": "rare",
                }
            }
        }

        rendered = tracker.render_author_name(mod, reputation)

        self.assertIn(
            'title="Rare author · 1,234 lifetime downloads · 2 known mods · '
            'first known mod published Jun 1, 2020"',
            rendered,
        )
        self.assertIn(
            'aria-label="Author, Rare author, 1,234 lifetime downloads, 2 known mods, '
            'first known mod published Jun 1, 2020"',
            rendered,
        )
        self.assertIn('data-author-mod-count="2"', rendered)
        self.assertIn(
            'data-author-first-published="2020-06-01T12:30:00Z"',
            rendered,
        )

    def test_author_tooltip_uses_singular_known_mod(self):
        mod = sample("nexus", "1")
        reputation = {
            "authors": {
                "nexus:author": {
                    "canonical_author_id": "nexus:author",
                    "downloads": 10,
                    "mod_count": 1,
                    "first_mod_published_at": "2020-06-01T12:30:00Z",
                    "tier": "common",
                }
            }
        }

        rendered = tracker.render_author_name(mod, reputation)

        self.assertIn("1 known mod ·", rendered)
        self.assertNotIn("1 known mods", rendered)

    def test_author_tooltip_handles_unknown_first_publication(self):
        mod = sample("nexus", "1")
        reputation = {
            "authors": {
                "nexus:author": {
                    "canonical_author_id": "nexus:author",
                    "downloads": 10,
                    "mod_count": 1,
                    "first_mod_published_at": None,
                    "tier": "common",
                }
            }
        }

        rendered = tracker.render_author_name(mod, reputation)

        self.assertIn("first known mod publication unknown", rendered)
        self.assertIn('data-author-first-published=""', rendered)

    def test_author_rendering_escapes_identity_text_and_canonical_metadata(self):
        mod = sample("nexus", "1")
        mod["author"] = 'Alice <Admin> & "Team"'
        identity = 'nexus:alice <admin> & "team"'
        mappings = {
            identity: {
                "canonical_author_id": "alice-team",
                "matched_to": ["thunderstore:alice-team"],
                "method": "manual",
            },
            "thunderstore:alice-team": {
                "canonical_author_id": "alice-team",
                "matched_to": [identity],
                "method": "manual",
            },
        }
        reputation = tracker.build_author_reputation(
            [mod],
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            mappings,
        )

        rendered = tracker.render_author_name(mod, reputation)

        self.assertIn("Alice &lt;Admin&gt; &amp; &quot;Team&quot;", rendered)
        self.assertIn(
            'data-author-key="nexus:alice &lt;admin&gt; &amp; &quot;team&quot;"',
            rendered,
        )
        self.assertIn('data-author-canonical="alice-team"', rendered)

    def test_author_rarity_report_includes_accessible_legend(self):
        mod = sample("nexus", "1")
        reputation = tracker.build_author_reputation(
            [mod],
            {
                "percentiles": {
                    "uncommon": 60,
                    "rare": 70,
                    "epic": 80,
                    "legendary": 90,
                }
            },
            {},
        )

        page = tracker.render_report(
            [mod],
            "2026-09-11T02:00:00Z",
            author_reputation=reputation,
        )

        self.assertIn('class="author-legend" aria-label="Author rarity legend"', page)
        self.assertIn(".author-legend{display:flex", page)
        for tier in ("Common", "Uncommon", "Rare", "Epic", "Legendary"):
            self.assertIn(f'>{tier}</span>', page)
        self.assertNotIn(">Normal</span>", page)
        self.assertNotIn(">Magic</span>", page)

    def test_verifier_rejects_missing_author_metadata_for_one_card(self):
        first = sample("nexus", "1")
        first["author"] = "Alice"
        second = sample("nexus", "2")
        second["author"] = "Bob"
        mods = [first, second]
        reputation = tracker.build_author_reputation(
            mods,
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        page = tracker.render_report(
            mods,
            "2026-09-11T02:00:00Z",
            author_reputation=reputation,
        )
        page = page.replace(tracker.render_author_name(first, reputation), "Alice", 1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path,
                expected_cards=2,
                expected_author_reputation=reputation,
                expected_author_keys=["nexus:alice", "nexus:bob"],
            )

        self.assertFalse(result["ok"])
        self.assertIn("rendered author identities do not match report cards", result["errors"])

    def test_verifier_rejects_tampered_author_reputation_metadata(self):
        mods = [sample("nexus", "1")]
        mods[0].update(author="Alice", total_downloads=100)
        config = {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}}
        reputation = tracker.build_author_reputation(mods, config, {})
        assert reputation is not None
        reputation["generated_at"] = "2026-09-11T02:00:00Z"
        page = tracker.render_report(
            mods,
            "2026-09-11T02:00:00Z",
            author_reputation=reputation,
        )
        changes = {
            "tier": ('data-author-tier="legendary"', 'data-author-tier="common"'),
            "downloads": ('data-author-downloads="100"', 'data-author-downloads="999"'),
            "mod count": ('data-author-mod-count="1"', 'data-author-mod-count="9"'),
            "first publication": (
                'data-author-first-published="2021-01-01T00:00:00Z"',
                'data-author-first-published="2025-01-01T00:00:00Z"',
            ),
            "identity": ('data-author-key="nexus:alice"', 'data-author-key="nexus:mallory"'),
            "canonical": ('data-author-canonical="nexus:alice"', 'data-author-canonical="nexus:mallory"'),
            "class": ('class="author author-tier-legendary"', 'class="author author-tier-common"'),
            "tooltip": ('title="Legendary author', 'title="Common author'),
            "aria": ('aria-label="Alice, Legendary author', 'aria-label="Alice, Common author'),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            for field, (old, new) in changes.items():
                with self.subTest(field=field):
                    tampered = page.replace(old, new, 1)
                    self.assertNotEqual(tampered, page)
                    path.write_text(tampered)
                    result = tracker.verify_report(
                        path,
                        expected_cards=1,
                        update_filter=tracker.DEFAULT_UPDATE_FILTER,
                        expected_author_reputation=reputation,
                        expected_author_keys=["nexus:alice"],
                    )
                    self.assertFalse(result["ok"], field)
                    self.assertTrue(any("author" in error for error in result["errors"]))

    def test_verifier_rejects_author_metadata_moved_and_duplicated_between_same_author_cards(self):
        first = sample("nexus", "1")
        second = sample("nexus", "2")
        first["author"] = second["author"] = "Alice"
        mods = [first, second]
        reputation = tracker.build_author_reputation(
            mods,
            {"percentiles": {"uncommon": 60, "rare": 70, "epic": 80, "legendary": 90}},
            {},
        )
        page = tracker.render_report(
            mods, "2026-09-11T02:00:00Z", author_reputation=reputation
        )
        author_html = tracker.render_author_name(first, reputation)
        tampered = page.replace(author_html, "", 1)
        tampered = tampered.replace(author_html, author_html + author_html, 1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(tampered)
            result = tracker.verify_report(
                path,
                expected_cards=2,
                expected_author_reputation=reputation,
                expected_author_keys=["nexus:alice", "nexus:alice"],
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("author metadata" in error for error in result["errors"]))

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

    def test_report_paginates_the_filtered_single_file_card_set_by_100(self):
        mods = [sample("thunderstore", "Team/Pinned", True, "Pinned")]
        mods.extend(sample("nexus", str(index), False, f"Mod {index}") for index in range(100))

        page = tracker.render_report(mods, "2026-09-09T20:00:00Z")

        self.assertEqual(page.count('class="mod-card'), 101)
        self.assertIn('id="pagination"', page)
        self.assertIn('id="previous-page"', page)
        self.assertIn('id="next-page"', page)
        self.assertIn('id="page-indicator"', page)
        self.assertIn('aria-live="polite"', page)
        self.assertIn("const pageSize=100", page)
        self.assertIn("const totalPages=Math.ceil(matching.length/pageSize)", page)
        self.assertIn("const pageCards=matching.slice(start,start+pageSize)", page)
        self.assertIn("pinnedSection.hidden=!pageCards.some(c=>c.parentElement===pinnedGroup)", page)
        self.assertIn("regularSection.hidden=!pageCards.some(c=>c.parentElement===regularGroup)", page)
        self.assertIn("currentPage=1;update()", page)
        self.assertIn("Page '+(totalPages?currentPage:0)+' of '+totalPages", page)

    def test_verifier_rejects_missing_or_tampered_pagination_contract(self):
        page = tracker.render_report(
            [sample("nexus", str(index), False, f"Mod {index}") for index in range(101)],
            "2026-09-09T20:00:00Z",
        )
        mutations = {
            "controls": ('id="next-page"', 'id="next-page-broken"'),
            "navigation landmark": (
                '<nav class="pagination" id="pagination" aria-label="Report pages">',
                '<div class="pagination" id="pagination" aria-label="Report pages">',
            ),
            "previous button type": (
                '<button type="button" id="previous-page">Previous</button>',
                '<button id="previous-page">Previous</button>',
            ),
            "next button element": (
                '<button type="button" id="next-page">Next</button>',
                '<div id="next-page">Next</div>',
            ),
            "page indicator live region": (
                '<span class="page-indicator" id="page-indicator" aria-live="polite">',
                '<span class="page-indicator" id="page-indicator" aria-live="off">',
            ),
            "page size": ("const pageSize=100", "const pageSize=101"),
            "filtered slice": (
                "matching.slice(start,start+pageSize)",
                "matching.slice(start+1,start+pageSize)",
            ),
            "filter reset": ("currentPage=1;update()", "update()"),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            for field, (old, new) in mutations.items():
                with self.subTest(field=field):
                    self.assertIn(old, page)
                    path.write_text(page.replace(old, new, 1))
                    result = tracker.verify_report(path, expected_cards=101)
                    self.assertFalse(result["ok"], field)
                    self.assertTrue(
                        any("pagination" in error for error in result["errors"]),
                        result["errors"],
                    )

    def test_report_category_filter_lists_unique_escaped_categories(self):
        first = sample("nexus", "1")
        first["categories"] = ["Utility", 'A&B <Tools>']
        second = sample("thunderstore", "Team/Two")
        second["categories"] = ["utility", "Libraries"]

        page = tracker.render_report([first, second], "2026-09-09T20:00:00Z")

        self.assertIn(
            '<select id="category-filter"><option value="">All categories</option>',
            page,
        )
        self.assertIn(
            '<option value="a&amp;b &lt;tools&gt;">A&amp;B &lt;Tools&gt;</option>',
            page,
        )
        self.assertIn('<option value="libraries">Libraries</option>', page)
        self.assertEqual(page.count('<option value="utility">'), 1)

    def test_category_filter_composes_with_every_existing_filter(self):
        mod = sample("nexus", "1")
        mod["categories"] = ["Utility", "Libraries"]

        page = tracker.render_report([mod], "2026-09-09T20:00:00Z")

        self.assertIn(
            'data-categories="[&quot;libraries&quot;,&quot;utility&quot;]"',
            page,
        )
        self.assertIn("category=document.querySelector('#category-filter')", page)
        self.assertIn(
            "(!category.value||JSON.parse(c.dataset.categories).includes(category.value))",
            page,
        )
        self.assertIn(
            "[search,source,category,sort,nsfw,...(updateFilter?[updateFilter]:[])]",
            page,
        )

    def test_category_tags_are_buttons_that_activate_the_category_filter(self):
        mod = sample("nexus", "1")
        mod["categories"] = ['A&B <Tools>']

        page = tracker.render_report([mod], "2026-09-09T20:00:00Z")

        self.assertIn(
            '<button type="button" class="tag" data-category="a&amp;b &lt;tools&gt;">A&amp;B &lt;Tools&gt;</button>',
            page,
        )
        self.assertIn("const tags=[...document.querySelectorAll('.tag[data-category]')]", page)
        self.assertIn(
            "e.stopPropagation();category.value=tag.dataset.category;currentPage=1;update();category.focus()",
            page,
        )
        self.assertIn("if(!e.target.closest('a,button,input,select'))", page)

    def test_report_controls_stick_to_viewport_without_mobile_obstruction(self):
        page = tracker.render_report(
            [sample("nexus", "1")], "2026-09-09T20:00:00Z"
        )

        self.assertIn('</header><div class="toolbar" role="region" aria-label="Mod filters">', page)
        header = page.split("</header>", 1)[0]
        self.assertNotIn('class="toolbar"', header)
        self.assertIn(
            ".toolbar{position:sticky;top:0;z-index:20;display:flex",
            page,
        )
        self.assertIn("background:var(--bg);border-bottom:1px solid var(--line)", page)
        self.assertIn(
            "@media(max-width:520px){header,main{padding:18px 14px}.toolbar{position:static;padding:10px 14px;max-height:none;overflow:visible",
            page,
        )
        self.assertNotIn("max-height:50vh;overflow-y:auto", page)

    def test_verifier_rejects_tampered_category_and_sticky_contracts(self):
        mod = sample("nexus", "1")
        mod["categories"] = ["Utility", "Libraries"]
        page = tracker.render_report([mod], "2026-09-09T20:00:00Z")
        expected_categories = [["libraries", "utility"]]
        mutations = {
            "control": ('id="category-filter"', 'id="category-filter-broken"'),
            "card metadata": (
                'data-categories="[&quot;libraries&quot;,&quot;utility&quot;]"',
                'data-categories="[]"',
            ),
            "tag binding": ('data-category="libraries"', 'data-category="other"'),
            "predicate": (
                "(!category.value||JSON.parse(c.dataset.categories).includes(category.value))",
                "true",
            ),
            "predicate hidden in comment": (
                "(!category.value||JSON.parse(c.dataset.categories).includes(category.value))",
                "true/*(!category.value||JSON.parse(c.dataset.categories).includes(category.value))*/",
            ),
            "tag handler": (
                "e.stopPropagation();category.value=tag.dataset.category;currentPage=1;update();category.focus()",
                "e.stopPropagation()",
            ),
            "mobile toolbar made sticky": (
                "position:static;padding:10px 14px;max-height:none;overflow:visible",
                "position:sticky;padding:10px 14px;max-height:none;overflow:visible",
            ),
            "sticky toolbar": ("position:sticky;top:0;z-index:20", "position:static"),
            "active sticky override": (
                "position:sticky;top:0;z-index:20",
                "position:sticky;top:0;z-index:20;position:static",
            ),
            "sticky toolbar hidden in comment": (
                "position:sticky;top:0;z-index:20",
                "position:static/*position:sticky;top:0;z-index:20*/",
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            for field, (old, new) in mutations.items():
                with self.subTest(field=field):
                    self.assertIn(old, page)
                    path.write_text(page.replace(old, new, 1))
                    result = tracker.verify_report(
                        path,
                        expected_cards=1,
                        expected_card_categories=expected_categories,
                    )
                    self.assertFalse(result["ok"], field)
                    self.assertTrue(any("category" in error or "sticky" in error for error in result["errors"]))

    def test_card_categories_deduplicate_case_variants_before_render_and_verify(self):
        mod = sample("nexus", "1")
        mod["categories"] = ["Utility", "utility"]

        page = tracker.render_report([mod], "2026-09-09T20:00:00Z")
        self.assertEqual(page.count('data-category="utility"'), 1)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path,
                expected_cards=1,
                expected_card_categories=[["utility"]],
            )
        self.assertTrue(result["ok"], result["errors"])

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

    def test_report_shows_latest_mod_update_by_datetime_not_lexical_order(self):
        later_instant = sample("nexus", "1")
        later_instant["updated_at"] = "2026-09-10T23:30:00-07:00"
        lexically_later = sample("nexus", "2")
        lexically_later["updated_at"] = "2026-09-11T06:00:00Z"

        page = tracker.render_report(
            [later_instant, lexically_later],
            "2026-09-11T14:00:00Z",
            update_filter=None,
        )

        self.assertIn("Generated Sep 11, 2026 at 7:00 AM MST.", page)
        self.assertIn("Data last updated at Sep 10, 2026 at 11:30 PM MST.", page)
        self.assertIn(
            '<meta name="report-data-last-updated-at" '
            'content="2026-09-11T06:30:00Z">',
            page,
        )

    def test_verifier_rejects_tampered_data_last_updated_timestamp(self):
        mod = sample("nexus", "1")
        mod["updated_at"] = "2026-09-11T06:30:00Z"
        page = tracker.render_report(
            [mod],
            "2026-09-11T14:00:00Z",
            update_filter=None,
        ).replace(
            'name="report-data-last-updated-at" content="2026-09-11T06:30:00Z"',
            'name="report-data-last-updated-at" content="2020-01-01T00:00:00Z"',
            1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            path.write_text(page)
            result = tracker.verify_report(
                path,
                expected_cards=1,
                update_filter=None,
            )

        self.assertFalse(result["ok"])
        self.assertIn("data last updated timestamp is missing or invalid", result["errors"])

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
        self.assertIn('.tag{background:#252a31;color:var(--muted);border:0;font:inherit;font-size:11px;font-weight:750;margin:2px;max-width:100%;overflow-wrap:anywhere;cursor:pointer}', page)
        self.assertIn('.tag:focus-visible{outline:2px solid #7cb7ff;outline-offset:2px}', page)
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
