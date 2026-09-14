import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/github-review.py"
_spec = importlib.util.spec_from_file_location("github_review", _SCRIPT)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


class GithubReviewContract(unittest.TestCase):
    """Milestone 2 RED contract; these tests describe the offline tool boundary."""

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

    def game(self, name="valheim", subdir="."):
        self.write_json("games.json", {name: {"output_subdir": subdir}})

    def records(self, values, subdir="."):
        return self.write_json(Path(subdir) / "data/mods.json", values)

    def state(self, value=None):
        return self.write_json(
            "github-repositories.json",
            {"version": 1, "records": {}} if value is None else value,
        )

    def record(self, key="nexus:1", source="nexus", url="https://github.com/owner/repo", **extra):
        value = {"key": key, "source": source, "summary": url, "description": ""}
        value.update(extra)
        return value

    def decision(self, game="valheim", key="nexus:1", record=None, **overrides):
        record = record or self.record(key=key)
        evidence = M.record_evidence(record)
        exact_url = evidence["candidates"][0]["occurrences"][0]["exact_url"]
        value = {
            "game": game,
            "key": key,
            "status": "approved",
            "repository_url": evidence["candidates"][0]["repository_url"],
            "reviewed_fingerprint": evidence["fingerprint"],
            "confidence": "high",
            "evidence_urls": [exact_url],
            "review_method": "llm-high-confidence",
            "rationale": "The provider evidence identifies the mod source.",
        }
        value.update(overrides)
        return value

    def test_export_uses_configured_single_game_output_subdir_and_rejects_unknown_game(self):
        self.game("solo", "games/solo")
        self.records([self.record()], "games/solo")
        output = self.root / "batch.json"
        try:
            result = M.export_project(self.root, "solo", output)
        except Exception as exc:
            self.fail(f"configured output_subdir raised {type(exc).__name__}")
        self.assertEqual(result["candidates"], 1)
        self.assertEqual(json.loads(output.read_text())["batches"][0][0]["game"], "solo")
        try:
            M.export_project(self.root, "missing", self.root / "missing.json")
        except Exception as exc:
            self.assertIsInstance(exc, ValueError, f"unknown game raised {type(exc).__name__}")
        else:
            self.fail("unknown game was accepted")

    def test_export_rejects_batch_size_above_hard_maximum_25(self):
        self.game(); self.records([self.record()])
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", self.root / "batch.json", batch_size=26)

    def test_export_fails_on_malformed_or_missing_configured_game_data(self):
        self.write_json("games.json", {"valheim": {"output_subdir": "games/v"}, "peak": {"output_subdir": "games/p"}})
        self.write_json("games/v/data/mods.json", {"not": "a list"})
        with self.assertRaises(ValueError):
            M.export_project(self.root, "all", self.root / "batch.json")
        (self.root / "games/v/data/mods.json").unlink()
        with self.assertRaises(ValueError):
            M.export_project(self.root, "all", self.root / "batch.json")

    def test_backfill_rejects_malformed_and_null_records_with_index(self):
        for index, value in ((1, None), (2, {"key": "x"})):
            with self.subTest(index=index):
                self.records([self.record(source="thunderstore", key="thunderstore:ns/pkg"), value] if index == 1 else [self.record(source="thunderstore", key="thunderstore:ns/pkg"), {"key": "x"}, None])
                try:
                    M.backfill_game(self.root)
                except Exception as exc:
                    self.assertIsInstance(exc, ValueError, f"malformed record raised {type(exc).__name__}")
                    self.assertIn(f"index {index}", str(exc))
                else:
                    self.fail(f"malformed record at index {index} was skipped")

    def test_backfill_validates_exact_source_id_and_key_components(self):
        bad = [
            "../pkg", "ns/../pkg", "ns//pkg", "/ns/pkg", "ns/pkg/extra",
            "ns/pkg.html", "ns\\pkg", "ns/.", "./pkg", "ns/.", "ns/..",
        ]
        for source_id in bad:
            with self.subTest(source_id=source_id):
                self.records([self.record(source="thunderstore", key="thunderstore:" + source_id, source_id=source_id)])
                with self.assertRaises(ValueError):
                    M.backfill_game(self.root)
        self.records([self.record(
            source="thunderstore", key="thunderstore:other/pkg", source_id="ns/pkg"
        )])
        with self.assertRaises(ValueError):
            M.backfill_game(self.root)

    def test_backfill_rejects_symlinked_capture_or_parent_without_reading_outside_root(self):
        outside = self.root.parent / "outside-capture.html"
        outside.write_text('<div class="markdown-body"><p>secret</p></div>', encoding="utf-8")
        capture_dir = self.root / "raw/thunderstore/packages/ns"
        capture_dir.mkdir(parents=True)
        (capture_dir / "pkg.html").symlink_to(outside)
        self.records([self.record(source="thunderstore", key="thunderstore:ns/pkg", source_id="ns/pkg", description="keep")])
        with self.assertRaises(ValueError):
            M.backfill_game(self.root)
        self.assertEqual(json.loads((self.root / "data/mods.json").read_text())[0]["description"], "keep")

    def test_backfill_counts_empty_parse_as_failure_and_preserves_nonempty_description(self):
        self.records([self.record(source="thunderstore", key="thunderstore:ns/pkg", source_id="ns/pkg", description="old")])
        capture = self.root / "raw/thunderstore/packages/ns/pkg.html"
        capture.parent.mkdir(parents=True)
        capture.write_text("<html>no readme</html>", encoding="utf-8")
        with mock.patch.object(M.tracker, "parse_thunderstore_detail", return_value={"readme_html": ""}):
            result = M.backfill_game(self.root)
        self.assertEqual(result["parse_failed"], 1)
        self.assertEqual(json.loads((self.root / "data/mods.json").read_text())[0]["description"], "old")

    def test_backfill_dry_run_preserves_exact_bytes_and_second_run_is_idempotent(self):
        path = self.records([self.record(source="thunderstore", key="thunderstore:ns/pkg", source_id="ns/pkg", description="old")])
        capture = self.root / "raw/thunderstore/packages/ns/pkg.html"
        capture.parent.mkdir(parents=True)
        capture.write_text('<div class="markdown-body"><p>new</p></div>', encoding="utf-8")
        before = path.read_bytes()
        M.backfill_game(self.root, dry_run=True)
        self.assertEqual(path.read_bytes(), before)
        first = M.backfill_game(self.root)
        after_first = path.read_bytes()
        second = M.backfill_game(self.root)
        self.assertEqual(first["repaired"], 1)
        self.assertEqual(second["repaired"], 0)
        self.assertEqual(after_first, path.read_bytes())

    def test_apply_dry_run_preserves_state_bytes(self):
        self.game(); rec = self.record(); self.records([rec]); path = self.state(); before = path.read_bytes()
        result = M.apply_decisions(self.root, {"decisions": [self.decision(record=rec)]}, state_path=path, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(path.read_bytes(), before)

    def test_apply_rejects_duplicate_decisions_before_any_write(self):
        self.game(); self.records([self.record()]); path = self.state(); before = path.read_bytes()
        payload = {"decisions": [self.decision(), self.decision(rationale="duplicate") ]}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            M.apply_decisions(self.root, payload, state_path=path)
        self.assertEqual(path.read_bytes(), before)

    def test_strict_state_schema_rejects_invalid_root_version_records_and_items(self):
        self.game(); self.records([self.record()])
        cases = [[], {"version": 2, "records": {}}, {"version": 1, "records": []},
                 {"version": 1, "records": {"bad": []}}, {"version": 1, "records": {"valheim:nexus:1": {"status": "bad"}}}]
        for value in cases:
            with self.subTest(value=value):
                path = self.state(value)
                try:
                    M.apply_decisions(self.root, {"decisions": []}, state_path=path)
                except Exception as exc:
                    self.assertIsInstance(exc, ValueError, f"invalid state raised {type(exc).__name__}")
                else:
                    self.fail("invalid state schema was accepted")

    def test_current_fingerprint_state_must_bind_to_current_repository_and_evidence(self):
        self.game(); rec = self.record(); self.records([rec])
        evidence = M.record_evidence(rec)
        bad = {"version": 1, "records": {"valheim:nexus:1": {
            "status": "approved",
            "repository_url": "https://github.com/invented/repository",
            "reviewed_fingerprint": evidence["fingerprint"],
            "evidence_urls": ["https://github.com/invented/repository"],
            "review_method": "llm-high-confidence",
            "rationale": "invented current state",
        }}}
        path = self.state(bad); output = self.root / "batch.json"
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", output)
        self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            M.apply_decisions(self.root, {"decisions": []}, state_path=path)
        self.assertFalse((self.root / "PENDING_GITHUB_REVIEW.md").exists())

    def test_export_rejects_well_formed_state_for_nonexistent_record(self):
        self.game(); self.records([self.record()])
        self.state({"version": 1, "records": {"valheim:nexus:ghost": {
            "status": "approved",
            "repository_url": "https://github.com/old/repository",
            "reviewed_fingerprint": "sha256:" + "0" * 64,
            "evidence_urls": ["https://github.com/old/repository"],
            "review_method": "manual",
            "rationale": "well formed but unbound",
        }}})
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", self.root / "batch.json")

    def test_nested_state_and_decision_types_raise_controlled_value_error(self):
        self.game(); rec = self.record(); self.records([rec])
        malformed_state = {"version": 1, "records": {"valheim:nexus:1": {
            "status": "approved",
            "repository_url": "https://github.com/owner/repo",
            "reviewed_fingerprint": M.record_evidence(rec)["fingerprint"],
            "evidence_urls": [["not", "a", "url"]],
            "review_method": "manual",
            "rationale": "bad nested type",
        }}}
        path = self.state(malformed_state)
        with self.assertRaises(ValueError):
            M.apply_decisions(self.root, {"decisions": []}, state_path=path)
        self.state()
        for change in ({"confidence": []}, {"review_method": []}, {"evidence_urls": [["bad"]]}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    M.apply_decisions(
                        self.root,
                        {"decisions": [self.decision(record=rec, **change)]},
                    )

    def test_strict_decision_schema_rejects_missing_or_wrong_fields(self):
        self.game(); rec = self.record(); self.records([rec]); self.state()
        required = ["game", "key", "status", "repository_url", "reviewed_fingerprint", "confidence", "evidence_urls", "review_method", "rationale"]
        base = self.decision(record=rec)
        for field in required:
            with self.subTest(field=field):
                bad = dict(base); bad.pop(field)
                try:
                    M.apply_decisions(self.root, {"decisions": [bad]})
                except Exception as exc:
                    self.assertIsInstance(exc, ValueError, f"invalid field raised {type(exc).__name__}")
                else:
                    self.fail(f"missing field {field} was accepted")

    def test_decision_validation_rejects_unknown_confidence_or_review_method(self):
        self.game(); rec = self.record(); self.records([rec]); self.state()
        for confidence, method in (("unknown", "llm-high-confidence"), ("high", "automatic")):
            with self.subTest(confidence=confidence, method=method):
                try:
                    M.apply_decisions(self.root, {"decisions": [self.decision(record=rec, confidence=confidence, review_method=method)]})
                except Exception as exc:
                    self.assertIsInstance(exc, ValueError, f"invalid confidence/method raised {type(exc).__name__}")
                else:
                    self.fail("invalid confidence or review method was accepted")

    def test_manual_high_confidence_decision_is_authoritative(self):
        self.game(); rec = self.record(); self.records([rec]); path = self.state()
        result = M.apply_decisions(
            self.root,
            {"decisions": [self.decision(record=rec, review_method="manual")]},
        )
        self.assertEqual(result["approved"], 1)
        self.assertEqual(
            json.loads(path.read_text())["records"]["valheim:nexus:1"]["review_method"],
            "manual",
        )

    def test_low_medium_or_explicit_ambiguous_decision_is_queued_not_authoritative(self):
        self.game(); rec = self.record(); self.records([rec]); path = self.state()
        for confidence, extra in (("low", {}), ("medium", {}), ("high", {"ambiguous": True})):
            with self.subTest(confidence=confidence):
                try:
                    result = M.apply_decisions(self.root, {"decisions": [self.decision(record=rec, confidence=confidence, **extra)]})
                except Exception as exc:
                    self.fail(f"ambiguous decision raised {type(exc).__name__} instead of being queued")
                self.assertEqual(result["approved"], 0)
                self.assertEqual(json.loads(path.read_text())["records"], {})
                self.assertIn("nexus:1", (self.root / "PENDING_GITHUB_REVIEW.md").read_text())

    def test_invented_or_stale_evidence_raises_atomically(self):
        self.game(); rec = self.record(); self.records([rec]); path = self.state(); before = path.read_bytes()
        for change in ({"repository_url": "https://github.com/invented/repo"}, {"repository_url": "https://github.com/owner/invented"}, {"reviewed_fingerprint": "sha256:stale"}, {"evidence_urls": ["https://github.com/other/evidence"]}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    M.apply_decisions(self.root, {"decisions": [self.decision(record=rec, **change)]}, state_path=path)
                self.assertEqual(path.read_bytes(), before)

    def test_stale_approved_is_retained_and_queued_with_prior_context_and_urls(self):
        self.game(); rec = self.record(); self.records([rec]); old = {"version": 1, "records": {"valheim:nexus:1": {"status": "approved", "repository_url": "https://github.com/old/repo", "reviewed_fingerprint": "sha256:" + "0" * 64, "evidence_urls": ["https://github.com/old/repo/releases/v1"], "review_method": "llm-high-confidence", "rationale": "prior"}}}; path = self.state(old)
        M.apply_decisions(self.root, {"decisions": []}, state_path=path)
        got = json.loads(path.read_text())["records"]["valheim:nexus:1"]
        self.assertEqual(got["repository_url"], "https://github.com/old/repo")
        queue = (self.root / "PENDING_GITHUB_REVIEW.md").read_text()
        self.assertIn("old/repo", queue); self.assertIn("old/repo/releases/v1", queue); self.assertIn("prior", queue)

    def test_stale_no_repository_is_queued_for_reconsideration(self):
        self.game(); rec = self.record(); self.records([rec]); self.state({"version": 1, "records": {"valheim:nexus:1": {"status": "no_repository", "repository_url": None, "reviewed_fingerprint": "sha256:" + "0" * 64, "evidence_urls": ["https://github.com/owner/repo"], "review_method": "llm-high-confidence", "rationale": "prior"}}})
        M.apply_decisions(self.root, {"decisions": []})
        self.assertIn("stale", (self.root / "PENDING_GITHUB_REVIEW.md").read_text())

    def test_no_repository_without_candidates_is_not_authoritative_record(self):
        self.game(); rec = self.record(url="https://example.com/no-github"); self.records([rec]); path = self.state()
        result = M.apply_decisions(self.root, {"decisions": []}, state_path=path)
        self.assertEqual(result["no_repository"], 0)
        self.assertEqual(json.loads(path.read_text())["records"], {})

    def test_mapped_conflicts_are_scoped_by_game(self):
        self.write_json("games.json", {"a": {"output_subdir": "a"}, "b": {"output_subdir": "b"}})
        for game in ("a", "b"):
            self.records([self.record(key="nexus:1", url=f"https://github.com/{game}/repo", canonical_group_id="same")], game)
        path = self.state({"version": 1, "records": {"a:nexus:1": {"status": "approved", "repository_url": "https://github.com/a/repo", "reviewed_fingerprint": M.record_evidence(self.record(url="https://github.com/a/repo", canonical_group_id="same"))["fingerprint"], "evidence_urls": ["https://github.com/a/repo"], "review_method": "llm-high-confidence", "rationale": "a"}, "b:nexus:1": {"status": "approved", "repository_url": "https://github.com/b/repo", "reviewed_fingerprint": M.record_evidence(self.record(url="https://github.com/b/repo", canonical_group_id="same"))["fingerprint"], "evidence_urls": ["https://github.com/b/repo"], "review_method": "llm-high-confidence", "rationale": "b"}}})
        M.apply_decisions(self.root, {"decisions": []}, state_path=path)
        self.assertNotIn("mapped approved repository conflict", (self.root / "PENDING_GITHUB_REVIEW.md").read_text())

    def test_apply_dry_run_predicts_mapped_conflicts_without_writing(self):
        self.game()
        records = [
            self.record(key="nexus:1", url="https://github.com/a/repo", canonical_group_id="group"),
            self.record(key="nexus:2", url="https://github.com/b/repo", canonical_group_id="group"),
        ]
        self.records(records); state_path = self.state(); before = state_path.read_bytes()
        result = M.apply_decisions(
            self.root,
            {"decisions": [
                self.decision(key="nexus:1", record=records[0]),
                self.decision(key="nexus:2", record=records[1]),
            ]},
            dry_run=True,
        )
        self.assertEqual(result["queued_conflict"], 1)
        self.assertEqual(result["queued_total"], 1)
        self.assertEqual(state_path.read_bytes(), before)
        self.assertFalse((self.root / "PENDING_GITHUB_REVIEW.md").exists())

    def test_queue_has_stable_ids_and_readable_context(self):
        self.game(); rec = self.record(description="Official source context https://github.com/owner/repo/releases/tag/v1"); self.records([rec]); self.state()
        M.apply_decisions(self.root, {"decisions": []})
        first = (self.root / "PENDING_GITHUB_REVIEW.md").read_text()
        M.apply_decisions(self.root, {"decisions": []})
        self.assertEqual(first, (self.root / "PENDING_GITHUB_REVIEW.md").read_text())
        self.assertFalse(first.endswith("\n\n"))
        self.assertRegex(first, r"## [0-9a-f]{16}"); self.assertIn("owner/repo", first); self.assertIn("Official source context", first)

    def test_state_is_unchanged_if_queue_write_fails(self):
        self.game(); rec = self.record(); self.records([rec]); path = self.state(); before = path.read_bytes()
        with mock.patch.object(M, "reconcile_pending", side_effect=OSError("queue unavailable")):
            with self.assertRaises(OSError):
                M.apply_decisions(self.root, {"decisions": [self.decision(record=rec)]}, state_path=path)
        self.assertEqual(path.read_bytes(), before)

    def test_export_apply_backfill_counts_reconcile_exactly(self):
        self.game(); recs = [self.record(key=f"nexus:{i}", url=f"https://github.com/owner/repo{i}") for i in range(3)]
        self.records(recs); state_path = self.state(); batch = self.root / "batch.json"
        exported = M.export_project(self.root, "valheim", batch, batch_size=25)
        decisions = [self.decision(key=r["key"], record=r) for r in recs]
        try:
            applied = M.apply_decisions(self.root, {"decisions": decisions})
        except Exception as exc:
            self.fail(f"valid exported decisions raised {type(exc).__name__}")
        self.assertEqual(exported["candidates"], len(decisions))
        self.assertEqual(applied["approved"] + applied["no_repository"] + applied["rejected"], exported["candidates"])
        self.assertEqual(len(json.loads(state_path.read_text())["records"]), exported["candidates"])

    def test_review_tool_is_not_invoked_by_tracker_or_automation(self):
        project = Path(__file__).resolve().parents[1]
        for relative in ("tracker.py", "scripts/manual-pass.py", "scripts/unattended_run.py"):
            text = (project / relative).read_text(encoding="utf-8")
            self.assertNotIn("github-review", text)
            self.assertNotIn("github_review", text)

    def test_output_subdir_rejects_any_parent_component_and_symlinked_inputs(self):
        for subdir in ("..", "games/../escape"):
            with self.subTest(subdir=subdir):
                self.game("valheim", subdir)
                with self.assertRaises(ValueError):
                    M.export_project(self.root, "valheim", self.root / "batch.json")
        self.game("valheim", "games/v")
        outside = self.root / "outside-game"
        outside.mkdir(exist_ok=True)
        (self.root / "games").mkdir()
        (self.root / "games/v").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", self.root / "batch.json")

        self.game("valheim", ".")
        data = self.root / "data"
        outside_data = self.root / "outside-data"
        outside_data.mkdir(exist_ok=True)
        data.symlink_to(outside_data, target_is_directory=True)
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", self.root / "batch.json")
        data.unlink()
        data.mkdir()
        outside_mods = self.root / "outside-mods.json"
        outside_mods.write_text("[]", encoding="utf-8")
        (data / "mods.json").symlink_to(outside_mods)
        with self.assertRaises(ValueError):
            M.export_project(self.root, "valheim", self.root / "batch.json")

    def test_state_schema_is_exact_and_validates_record_values(self):
        self.game(); self.records([self.record()])
        valid = self.decision()
        item = {k: valid[k] for k in ("status", "repository_url", "reviewed_fingerprint", "evidence_urls", "review_method", "rationale")}
        cases = [
            {"version": 1, "records": {}, "extra": True},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "extra": True}}},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "reviewed_fingerprint": "sha256:ABC"}}},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "review_method": "automatic"}}},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "evidence_urls": [item["evidence_urls"][0]] * 2}}},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "rationale": " "}}},
            {"version": 1, "records": {"valheim:nexus:1": {**item, "repository_url": "https://github.com/owner/repo/"}}},
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                self.state(bad)
                with self.assertRaises(ValueError):
                    M.apply_decisions(self.root, {"decisions": []})

    def test_duplicate_normalized_records_are_rejected(self):
        self.game(); path = self.records([self.record(), self.record(key="nexus:1")]); self.state()
        with self.assertRaises(ValueError):
            M.apply_decisions(self.root, {"decisions": []})
        self.assertEqual(json.loads(path.read_text())[0]["key"], "nexus:1")

    def test_state_record_key_must_bind_to_real_game_record(self):
        self.game(); self.records([self.record(key="nexus:1")])
        self.state({"version": 1, "records": {"other:nexus:1": {
            "status": "approved", "repository_url": "https://github.com/owner/repo",
            "reviewed_fingerprint": "sha256:" + "0" * 64,
            "evidence_urls": ["https://github.com/owner/repo"],
            "review_method": "manual", "rationale": "prior"
        }}})
        with self.assertRaises(ValueError):
            M.apply_decisions(self.root, {"decisions": []})

    def test_current_fingerprint_requires_exact_current_evidence_urls(self):
        self.game()
        rec = self.record(summary="https://github.com/owner/repo/releases/v1 https://github.com/owner/repo/issues/2")
        self.records([rec]); self.state()
        evidence = M.record_evidence(rec)
        decision = self.decision(record=rec, evidence_urls=[evidence["candidates"][0]["occurrences"][0]["exact_url"]])
        with self.assertRaises(ValueError):
            M.apply_decisions(self.root, {"decisions": [decision]})

    def test_ambiguous_decision_creates_one_stable_pending_entry_without_mutation(self):
        self.game(); rec = self.record(description="Current context https://github.com/owner/repo/releases/v1")
        self.records([rec]); path = self.state(); before = path.read_bytes()
        decision = self.decision(record=rec, confidence="medium")
        first = M.apply_decisions(self.root, {"decisions": [decision]})
        queue = (self.root / "PENDING_GITHUB_REVIEW.md").read_text()
        second = M.apply_decisions(self.root, {"decisions": [decision]})
        queue_again = (self.root / "PENDING_GITHUB_REVIEW.md").read_text()
        self.assertEqual(first.get("queued_total"), 1)
        self.assertEqual(second.get("queued_total"), 1)
        self.assertEqual(queue, queue_again)
        self.assertEqual(queue.count("## "), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("owner/repo", queue)
        self.assertIn("Current context", queue)

    def test_backfill_unknown_game_is_controlled_value_error(self):
        self.game("valheim", ".")
        try:
            M.main(["backfill", "--game", "missing", "--project-root", str(self.root)])
        except Exception as exc:
            self.assertIsInstance(exc, ValueError, f"unknown game raised {type(exc).__name__}")
        else:
            self.fail("unknown game was accepted")

    def test_backfill_summary_reports_source_and_unchanged_counts(self):
        self.game()
        self.records([self.record(source="nexus", key="nexus:1"), self.record(source="thunderstore", key="thunderstore:ns/pkg", source_id="ns/pkg")])
        result = M.backfill_game(self.root)
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result.get("records_by_source"), {"nexus": 1, "thunderstore": 1})
        self.assertEqual({k: result.get(k) for k in ("raw_considered", "missing", "repaired", "unchanged", "parse_failed")},
                         {"raw_considered": 0, "missing": 1, "repaired": 0, "unchanged": 0, "parse_failed": 0})

    def test_export_summary_reports_game_source_review_and_batches(self):
        self.game()
        candidate = self.record(key="nexus:1")
        reviewed = self.record(key="nexus:2")
        no_candidate = self.record(key="nexus:3", url="https://example.com/no-github")
        self.records([candidate, reviewed, no_candidate])
        reviewed_state = self.decision(record=reviewed)
        self.state({"version": 1, "records": {"valheim:nexus:2": {k: reviewed_state[k] for k in ("status", "repository_url", "reviewed_fingerprint", "evidence_urls", "review_method", "rationale")}}})
        result = M.export_project(self.root, "valheim", self.root / "batch.json", batch_size=1)
        self.assertEqual(result, {"scanned": 3, "scanned_by_game": {"valheim": 3}, "scanned_by_source": {"nexus": 3}, "no_candidates": 1, "already_reviewed": 1, "candidates": 1, "batches": 1, "dry_run": False})

    def test_apply_summary_reports_resolution_and_queue_categories(self):
        self.game()
        records = [self.record(key=f"nexus:{i}", url=f"https://github.com/owner/repo{i}", canonical_group_id="g") for i in range(4)]
        records[2] = self.record(key="nexus:2", url="https://github.com/owner/repo2")
        records[3] = self.record(key="nexus:3", description="ambiguous https://github.com/owner/repo3")
        self.records(records); self.state()
        decisions = [self.decision(key="nexus:0", record=records[0]), self.decision(key="nexus:1", record=records[1]), self.decision(key="nexus:2", record=records[2], status="no_repository", repository_url=None), self.decision(key="nexus:3", record=records[3], confidence="low")]
        result = M.apply_decisions(self.root, {"decisions": decisions})
        self.assertEqual(result["approved"], 2)
        self.assertEqual(result["no_repository"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual({k: result[k] for k in ("queued_ambiguous", "queued_stale", "queued_conflict", "queued_total")}, {"queued_ambiguous": 1, "queued_stale": 0, "queued_conflict": 1, "queued_total": 2})


if __name__ == "__main__":
    unittest.main()
