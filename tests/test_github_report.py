import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker


class GithubReportMilestone3RedContract(unittest.TestCase):
    """Milestone 3 report-link contract; intentionally RED against the frozen blob."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def mod(self, key="nexus:1", group=None, title="Example", summary="summary"):
        source, source_id = key.split(":", 1)
        return {
            "key": key, "source": source, "source_id": source_id,
            "title": title, "author": "Author", "summary": summary,
            "categories": [], "thumbnail": "",
            "canonical_url": "https://example.test/mod/" + source_id.replace("/", "-"),
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2026-09-09T12:00:00Z", "total_downloads": 1,
            "endorsements": 0, "likes": 0, "version": "1", "rank": 1,
            "ranks": {}, "pinned": False, "adult_content": False,
            "observations": [], "canonical_group_id": group, "match": None,
        }

    def decision(self, key="nexus:1", url="https://github.com/owner/repo",
                 game="valheim", status="approved", **overrides):
        item = {
            "status": status,
            "repository_url": url if status == "approved" else None,
            "reviewed_fingerprint": "sha256:" + "0" * 64,
            "evidence_urls": [url] if url else ["https://example.test/evidence"],
            "review_method": "manual",
            "rationale": "Reviewed from provider evidence.",
        }
        item.update(overrides)
        return {f"{game}:{key}": item}

    def state(self, records, relative="github-repositories.json"):
        return self.write_json(relative, {"version": 1, "records": records})

    def render(self, mods, decisions, *, game="valheim", summary=None):
        if summary:
            mods = [dict(mods[0], summary=summary)] + list(mods[1:])
        return tracker.render_report(
            mods, "2026-09-10T00:00:00Z", update_filter=None,
            sources=("nexus",), github_decisions=decisions, github_game=game,
        )

    def verify_page(self, page, expected, *, decisions=None, expected_cards=None):
        path = self.root / "report.html"
        path.write_text(page, encoding="utf-8")
        return tracker.verify_report(
            path, expected_cards=expected_cards or len(expected),
            update_filter=None, expected_github_links=expected,
            github_decisions=decisions,
        )

    def test_generate_and_verify_use_real_project_state_for_root_and_nested_game(self):
        valheim = self.mod("nexus:1")
        peak = self.mod("nexus:1", title="Peak mod")
        self.write_json("data/mods.json", [valheim])
        self.write_json("games/peak/data/mods.json", [peak])
        records = {}
        records.update(self.decision(url="https://github.com/valheim/repo"))
        records.update(self.decision(key="nexus:1", game="peak", url="https://github.com/peak/repo"))
        self.state(records)

        try:
            root_result = tracker.generate_report(self.root, "2026-09-10T00:00:00Z",
                                                  update_filter=None, sources=("nexus",),
                                                  github_game="valheim")
            nested_result = tracker.generate_report(
                self.root / "games/peak", "2026-09-10T00:00:00Z",
                update_filter=None, sources=("nexus",), game_name="PEAK", github_game="peak",
            )
        except Exception as exc:
            self.fail(f"report integration raised {type(exc).__name__}: {exc}")
        self.assertTrue(root_result["ok"])
        self.assertTrue(nested_result["ok"])
        self.assertIn("https://github.com/valheim/repo", (self.root / "report.html").read_text())
        self.assertIn("https://github.com/peak/repo", (self.root / "games/peak/report.html").read_text())
        self.assertTrue(tracker.verify_output(self.root, expected_thunderstore_pages=0,
                                              expected_nexus_pages=0, update_filter=None,
                                              require_reports=True, github_game="valheim")["ok"])
        self.assertTrue(tracker.verify_output(self.root / "games/peak",
                                              expected_thunderstore_pages=0, expected_nexus_pages=0,
                                              update_filter=None, require_reports=True,
                                              github_game="peak")["ok"])

    def test_state_schema_requires_exact_root_item_shapes_and_strict_values(self):
        valid = self.decision()["valheim:nexus:1"]
        cases = [
            ({"version": 1, "records": {}, "extra": True}, "root extra"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "extra": 1}}}, "item extra"),
            ({"version": 1, "records": {"bad": valid}}, "key shape"),
            ({"version": 1, "records": {"valheim:foo:1": valid}}, "source shape"),
            ({"version": 1, "records": {"valheim:nexus:x": valid}}, "nexus id shape"),
            ({"version": 1, "records": {"valheim:thunderstore:ns": valid}}, "package shape"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "repository_url": "http://github.com/a/b"}}}, "http"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "repository_url": "https://github.com/a/b/issues/1"}}}, "deep root"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "evidence_urls": []}}}, "empty evidence"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "evidence_urls": ["x", "x"]}}}, "duplicate evidence"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "reviewed_fingerprint": "sha256:" + "0" * 63}}}, "fingerprint"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "review_method": " "}}}, "method"),
            ({"version": 1, "records": {"valheim:nexus:1": {**valid, "rationale": " "}}}, "rationale"),
        ]
        for payload, label in cases:
            with self.subTest(label=label):
                path = self.root / (label + ".json")
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    tracker.load_github_repositories(path)

    def test_loader_rejects_unknown_game_prefix(self):
        path = self.state(
            self.decision(game="madeup", url="https://github.com/owner/repo")
        )
        with self.assertRaises(ValueError):
            tracker.load_github_repositories(path)

    def test_explicit_missing_state_path_fails_closed(self):
        self.write_json("data/mods.json", [self.mod()])
        with self.assertRaises(ValueError):
            tracker.generate_report(
                self.root,
                "2026-09-10T00:00:00Z",
                update_filter=None,
                sources=("nexus",),
                github_game="valheim",
                github_state_path=self.root / "missing.json",
            )

    def test_selected_game_state_keys_must_bind_to_existing_records(self):
        self.write_json("data/mods.json", [self.mod("nexus:1")])
        state_path = self.state(
            self.decision(key="nexus:999", url="https://github.com/ghost/repo")
        )
        with self.assertRaises(ValueError):
            tracker.generate_report(
                self.root,
                "2026-09-10T00:00:00Z",
                update_filter=None,
                sources=("nexus",),
                github_game="valheim",
                github_state_path=state_path,
            )

    def test_selected_game_keys_bind_to_records_but_stale_approval_remains_displayable(self):
        current = self.mod()
        stale = self.mod("nexus:2", title="Stale")
        self.write_json("data/mods.json", [current, stale])
        records = {}
        records.update(self.decision(url="https://github.com/current/repo"))
        records.update(self.decision(key="nexus:2", url="https://github.com/stale/repo",
                                     reviewed_fingerprint="sha256:" + "f" * 64,
                                     evidence_urls=["https://github.com/stale/repo/releases/v1"]))
        self.state(records)
        page = self.render([current, stale], records)
        self.assertEqual(page.count('class="github-link"'), 2)
        self.assertIn("https://github.com/stale/repo", page)
        result = self.verify_page(page, ["https://github.com/current/repo", "https://github.com/stale/repo"])
        self.assertTrue(result["ok"], result["errors"])

    def test_resolution_covers_current_stale_unreviewed_no_repository_mapped_dedupe_and_conflict(self):
        left = self.mod("nexus:1", "group")
        right = self.mod("thunderstore:Author/Mod", "group")
        approved = self.decision(url="https://github.com/a/repo")["valheim:nexus:1"]
        no_repo = self.decision(key="nexus:3", status="no_repository")["valheim:nexus:3"]
        self.assertEqual(tracker.resolve_github_repository([left], {"valheim:nexus:1": approved}), "https://github.com/a/repo")
        self.assertIsNone(tracker.resolve_github_repository([self.mod("nexus:3")], {"valheim:nexus:3": no_repo}))
        self.assertIsNone(tracker.resolve_github_repository([self.mod("nexus:4")], {}))
        one = {"valheim:nexus:1": approved}
        self.assertEqual(tracker.resolve_github_repository([left, right], one), "https://github.com/a/repo")
        both = dict(one, **{"valheim:thunderstore:Author/Mod": dict(approved)})
        self.assertEqual(tracker.resolve_github_repository([left, right], both), "https://github.com/a/repo")
        both["valheim:thunderstore:Author/Mod"]["repository_url"] = "https://github.com/b/repo"
        self.assertIsNone(tracker.resolve_github_repository([left, right], both))

    def test_expected_links_follow_pinned_then_regular_render_order(self):
        regular = self.mod("nexus:1", title="Regular")
        pinned = self.mod("nexus:2", title="Pinned")
        pinned["pinned"] = True
        decisions = {}
        decisions.update(self.decision(key="nexus:1", url="https://github.com/owner/regular"))
        decisions.update(self.decision(key="nexus:2", url="https://github.com/owner/pinned"))
        self.assertEqual(
            tracker.report_github_links(
                [regular, pinned], decisions, game_key="valheim"
            ),
            ["https://github.com/owner/pinned", "https://github.com/owner/regular"],
        )

    def test_verifier_rejects_each_strict_link_spoof_independently(self):
        mod = self.mod()
        decisions = self.decision()
        page = self.render([mod], decisions)
        cases = {
            "missing": page.replace('<a class="github-link" href="https://github.com/owner/repo">GitHub</a>', ""),
            "added": page.replace('</p><div class="dates">', '<a class="github-link" href="https://github.com/extra/repo">GitHub</a></p><div class="dates">'),
            "duplicate": page.replace('</a></p><div class="dates">', '</a><a class="github-link" href="https://github.com/owner/repo">GitHub</a></p><div class="dates">'),
            "wrong card swap": page.replace("https://github.com/owner/repo", "https://github.com/other/repo"),
            "altered href": page.replace("https://github.com/owner/repo", "https://github.com/owner/repo?x=1"),
            "deep path": page.replace("https://github.com/owner/repo", "https://github.com/owner/repo/issues/1"),
            "profile": page.replace("https://github.com/owner/repo", "https://github.com/owner"),
            "conflict": page.replace("https://github.com/owner/repo", "https://github.com/conflict/repo"),
            "wrong label": page.replace(">GitHub</a>", ">Source</a>"),
            "label-only": page.replace('<a class="github-link" href="https://github.com/owner/repo">GitHub</a>', '<span class="github-link">GitHub</span>'),
        }
        for label, spoof in cases.items():
            with self.subTest(label=label):
                result = self.verify_page(spoof, ["https://github.com/owner/repo"])
                self.assertFalse(result["ok"], result)

    def test_verifier_rejects_repository_swapped_between_distinct_cards(self):
        first, second = self.mod("nexus:1"), self.mod("nexus:2", title="Second")
        decisions = {}
        decisions.update(self.decision(key="nexus:1", url="https://github.com/one/repo"))
        decisions.update(self.decision(key="nexus:2", url="https://github.com/two/repo"))
        page = self.render([first, second], decisions)
        swapped = page.replace("https://github.com/one/repo", "TEMP")
        swapped = swapped.replace("https://github.com/two/repo", "https://github.com/one/repo")
        swapped = swapped.replace("TEMP", "https://github.com/two/repo")
        result = self.verify_page(
            swapped, ["https://github.com/one/repo", "https://github.com/two/repo"],
            expected_cards=2,
        )
        self.assertFalse(result["ok"], result)

    def test_verifier_requires_exact_github_link_class(self):
        page = self.render([self.mod()], self.decision())
        for replacement in ('class="other"', 'class="github-link extra"'):
            with self.subTest(replacement=replacement):
                spoof = page.replace('class="github-link"', replacement)
                result = self.verify_page(
                    spoof, ["https://github.com/owner/repo"], expected_cards=1
                )
                self.assertFalse(result["ok"], result)

    def test_plain_summary_word_github_without_reviewed_link_does_not_fail(self):
        page = self.render([self.mod()], {}, summary="GitHub is mentioned as ordinary documentation text.")
        result = self.verify_page(page, [None])
        self.assertTrue(result["ok"], result["errors"])

    def test_html_verifier_does_not_revalidate_candidate_provenance(self):
        page = self.render([self.mod()], self.decision())
        result = self.verify_page(
            page, ["https://github.com/owner/repo"],
            decisions={"valheim:nexus:1": {
                "status": "approved", "repository_url": "https://github.com/owner/repo",
                "reviewed_fingerprint": "sha256:" + "0" * 64,
                "evidence_urls": ["https://not-provider.example/fabricated"],
                "review_method": "manual", "rationale": "display-only verifier input",
            }},
        )
        self.assertTrue(result["ok"], result["errors"])

    def test_exact_link_is_only_static_provider_link_no_badge_icon_or_javascript_behavior(self):
        mod = self.mod()
        page = self.render([mod], self.decision())
        self.assertEqual(len(re.findall(r'<a class="github-link" href="[^"]+">GitHub</a>', page)), 1)
        self.assertEqual(page.count('class="source-link"'), 1)
        self.assertNotIn("github-link", tracker.REPORT_JAVASCRIPT)
        self.assertNotIn("github-link", page.split("<script>", 1)[1].split("</script>", 1)[0])
        self.assertNotIn('class="github', page.replace('class="github-link"', ""))

    def test_verifier_preserves_per_card_order_and_duplicate_association_without_global_set_fallback(self):
        first = self.mod("nexus:1", title="First")
        second = self.mod("nexus:2", title="Second")
        same = "https://github.com/shared/repo"
        decisions = {}
        decisions.update(self.decision(key="nexus:1", url=same))
        decisions.update(self.decision(key="nexus:2", url=same))
        page = self.render([first, second], decisions)
        result = self.verify_page(page, [same, same], decisions=decisions, expected_cards=2)
        self.assertTrue(result["ok"], result["errors"])

    def test_verify_output_uses_selected_game_state_and_temporary_fixture_for_saved_report_failure(self):
        mod = self.mod()
        self.write_json("data/mods.json", [mod])
        self.write_json("snapshots/latest.json", {"thunderstore_pages_per_sort": {}})
        self.state(self.decision())
        try:
            tracker.generate_report(self.root, "2026-09-10T00:00:00Z", update_filter=None,
                                    sources=("nexus",), github_game="valheim")
        except Exception as exc:
            self.fail(f"saved-data report command raised {type(exc).__name__}: {exc}")
        result = tracker.verify_output(self.root, expected_thunderstore_pages=0,
                                       expected_nexus_pages=0, update_filter=None,
                                       require_reports=True, github_game="valheim")
        self.assertTrue(result["ok"], result["errors"])


if __name__ == "__main__":
    unittest.main()
