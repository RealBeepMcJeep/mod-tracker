import importlib.util
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/unattended_run.py"
WRAPPER = Path("/opt/data/scripts/mod-tracker-unattended.py")


def load_module():
    spec = importlib.util.spec_from_file_location("unattended_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UnattendedRunTests(unittest.TestCase):
    def _args(self, root, *, dry_run=True, override_anomaly=False, override_reason=None):
        root.mkdir(parents=True, exist_ok=True)
        key = root / "key"
        key.write_text("test-secret\n", encoding="utf-8")
        key.chmod(0o600)
        return SimpleNamespace(
            project_root=Path("/opt/data/projects/mod-tracker"),
            output_root=root / "output",
            public_artifacts_root=root / "public",
            state_root=root / "state",
            lock_file=root / "lock",
            nexus_api_key_file=key,
            github_repo="https://example.invalid/mod-tracker.git",
            live_base_url="https://example.invalid",
            dry_run=dry_run,
            override_anomaly=override_anomaly,
            override_reason=override_reason,
        )

    def _stage(self, registry, output_root, staging, **kwargs):
        staging.mkdir(parents=True)
        (staging / "index.html").write_bytes(b"landing")
        for key, config in registry.items():
            path = staging / config["publication"]["path"]
            path.mkdir()
            (path / "index.html").write_bytes(key.encode())
        return {
            "source": str(staging), "root": "mod-tracking",
            "verify_paths": [config["publication"]["path"] for config in registry.values()],
        }

    def _runner(self, calls, *, count=3, failed_game=None):
        def run(command, *, cwd):
            calls.append(command)
            if command[0] == "git":
                return {"ok": True, "returncode": 0, "output": {"ok": True}}
            if command[1].endswith("publish-site.py"):
                return {"ok": True, "returncode": 0, "output": {"ok": True}}
            if command[1].endswith("publish-github.py"):
                return {"ok": True, "returncode": 0, "output": {"ok": True, "changed": True}}
            action, game = command[2], command[4]
            if action == "collect":
                required = ["nexus"] if game == "retro-rewind" else ["nexus", "thunderstore"]
                return {"ok": game != failed_game, "returncode": 0 if game != failed_game else 1,
                        "output": {"sources": required,
                                   "providers": {source: {"ok": game != failed_game} for source in required}}}
            if action == "report":
                return {"ok": True, "returncode": 0, "output": {"ok": True}}
            if action == "verify":
                return {"ok": True, "returncode": 0, "output": {
                    "games": {key: {"report": {"cards": count}}
                               for key in ("peak", "repo", "retro-rewind", "tcg-card-shop-simulator", "valheim")}
                }}
            return {"ok": True, "returncode": 0, "output": {"ok": True}}
        return run

    def test_unattended_collects_all_games_then_reports_and_verifies_once(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="tracker-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls), stage_builder=self._stage
                )
            self.assertEqual(code, 0)
            self.assertEqual([call[2] for call in calls[:5]], ["collect"] * 5)
            self.assertEqual([call[2] for call in calls[5:7]], ["report", "verify"])
            self.assertIn("publish-site.py", calls[7][1])
            self.assertEqual(set(summary["counts"].values()), {3})
            self.assertIn("duration_seconds", summary)

    def test_provider_failure_blocks_report_and_publication(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self._args(root); calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="tracker-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls, failed_game="peak"), stage_builder=self._stage
                )
            self.assertNotEqual(code, 0)
            self.assertNotIn("report", [call[2] for call in calls])
            self.assertNotIn("publish-site.py", [call[2] for call in calls])
            self.assertIn("peak", summary["error"])

    def test_provider_completeness_rejects_missing_required_source(self):
        module = load_module()
        self.assertTrue(module._provider_complete({"ok": True, "output": {"sources": ["nexus"]}}, ["nexus"]))
        self.assertFalse(module._provider_complete({"ok": True, "output": {"sources": ["nexus"]}}, ["nexus", "thunderstore"]))
        self.assertFalse(module._provider_complete({"ok": True, "output": "not-json"}, ["nexus"]))
        self.assertFalse(module._provider_complete({"ok": 1, "output": {"sources": ["nexus"]}}, ["nexus"]))
        self.assertFalse(module._provider_complete({"ok": True, "output": {"sources": ["nexus", "nexus"]}}, ["nexus"]))

    def test_flat_wrapper_propagates_help_output_without_agent_dependency(self):
        direct = subprocess.run(
            ["python3", str(SCRIPT), "--help"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        wrapped = subprocess.run(
            ["python3", str(WRAPPER), "--help"], text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(wrapped.returncode, direct.returncode)
        self.assertEqual(wrapped.stdout, direct.stdout)
        self.assertEqual(wrapped.stderr, direct.stderr)
        self.assertNotIn("agent", WRAPPER.read_text(encoding="utf-8").casefold())

    def test_anomaly_gate_blocks_before_publisher_and_override_is_one_run(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self._args(root, dry_run=True)
            previous = root / "state" / "run-old"
            previous.mkdir(parents=True)
            (root / "state" / "latest").write_text("run-old\n", encoding="utf-8")
            (previous / "summary.json").write_text(
                json.dumps({"ok": True, "counts": {game: 100 for game in
                    ("peak", "repo", "retro-rewind", "tcg-card-shop-simulator", "valheim")}}),
                encoding="utf-8",
            )
            calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="tracker-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls, count=125), stage_builder=self._stage
                )
            self.assertNotEqual(code, 0)
            self.assertTrue(summary["anomaly"]["blocked"])
            self.assertNotIn("publish-site.py", " ".join(" ".join(call) for call in calls))

            args = self._args(root / "override", dry_run=True, override_anomaly=True, override_reason="reviewed")
            previous = args.state_root / "run-old"
            previous.mkdir(parents=True)
            (args.state_root / "latest").write_text("run-old\n", encoding="utf-8")
            (previous / "summary.json").write_text(
                json.dumps({"ok": True, "counts": {game: 100 for game in
                    ("peak", "repo", "retro-rewind", "tcg-card-shop-simulator", "valheim")}}),
                encoding="utf-8",
            )
            calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="tracker-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls, count=125), stage_builder=self._stage
                )
            self.assertEqual(code, 0)
            self.assertTrue(summary["anomaly"]["overridden"])
            self.assertEqual(summary["anomaly"]["override_reason"], "reviewed")

    def test_unchanged_public_tree_skips_publish_and_still_verifies_live_routes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self._args(root, dry_run=False); calls = []
            public_tree = root / "public" / "public" / "mod-tracking"
            public_tree.mkdir(parents=True)
            (public_tree / "index.html").write_bytes(b"landing")
            for game in ("peak", "repo", "retro-rewind", "tcg-card-shop-simulator", "valheim"):
                path = public_tree / game; path.mkdir(); (path / "index.html").write_bytes(game.encode())
            live_calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="tracker-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls), stage_builder=self._stage,
                    live_verifier=lambda *values: live_calls.append(values) or {"ok": True},
                )
            self.assertEqual(code, 0)
            self.assertEqual(summary["publication"]["state"], "unchanged")
            self.assertEqual(len(live_calls), 1)
            self.assertEqual(sum("publish-site.py" in " ".join(call) for call in calls), 1)
            self.assertFalse(any(call[:2] == ["git", "push"] for call in calls))

    def test_changed_public_tree_publishes_once_then_pushes_and_checks_remote(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self._args(root, dry_run=False); calls = []
            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="public-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=self._runner(calls), stage_builder=self._stage,
                    live_verifier=lambda *values: {"ok": True},
                )
            self.assertEqual(code, 0)
            publisher_calls = [call for call in calls if "publish-site.py" in " ".join(call)]
            self.assertEqual(len(publisher_calls), 2)
            self.assertEqual(sum(call[:3] == ["git", "push", "origin"] for call in calls), 1)
            self.assertEqual(summary["git_shas"]["public"], "public-sha")
            # The same staged tree is pushed to the GitHub Pages branch as well.
            github_calls = [call for call in calls if "publish-github.py" in " ".join(call)]
            self.assertEqual(len(github_calls), 1)
            self.assertIn("--source", github_calls[0])
            self.assertIn("https://example.invalid/mod-tracker.git", github_calls[0])
            self.assertEqual(summary["deployment_github"]["state"], "published")

    def test_publisher_failure_records_an_attempted_deployment(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self._args(root, dry_run=False); calls = []
            base_runner = self._runner(calls)

            def fail_real_publish(command, *, cwd):
                result = base_runner(command, cwd=cwd)
                if "publish-site.py" in " ".join(command) and "--dry-run" not in command:
                    return {"ok": False, "returncode": 1, "stderr": "publisher failed"}
                return result

            with patch.object(module, "ensure_clean_repository"), patch.object(
                module, "verify_remote_main", return_value="public-sha"
            ):
                code, summary = module.run_unattended(
                    args, command_runner=fail_real_publish, stage_builder=self._stage,
                    live_verifier=lambda *values: {"ok": True},
                )
            self.assertNotEqual(code, 0)
            self.assertEqual(summary["deployment"]["state"], "unknown-after-publisher-failure")
            self.assertFalse(any(call[:2] == ["git", "push"] for call in calls))

    def test_validate_nexus_key_requires_regular_0600_nonempty_file(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "key"
            key.write_text("secret\n", encoding="utf-8")
            key.chmod(0o600)
            self.assertEqual(module.validate_nexus_key(key), "secret")
            for mode in (0o644, 0o400):
                key.chmod(mode)
                with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                    module.validate_nexus_key(key)
            key.chmod(0o600)
            key.write_text("  \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                module.validate_nexus_key(key)
            key.unlink()
            real = root / "real-key"
            real.write_text("secret", encoding="utf-8")
            real.chmod(0o600)
            key.symlink_to(real)
            with self.assertRaises(ValueError):
                module.validate_nexus_key(key)

    def test_run_unattended_rejects_symlinked_runtime_arguments(self):
        module = load_module()
        for field in ("nexus_api_key_file", "output_root", "public_artifacts_root", "state_root"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args = self._args(root)
                original = Path(getattr(args, field))
                if original.exists():
                    if original.is_dir():
                        shutil.rmtree(original)
                    else:
                        original.unlink()
                target = root / f"real-{field}"
                if field == "nexus_api_key_file":
                    target.write_text("test-secret\n", encoding="utf-8")
                    target.chmod(0o600)
                else:
                    target.mkdir()
                original.symlink_to(target, target_is_directory=target.is_dir())
                with patch.object(module, "ensure_clean_repository"), patch.object(
                    module, "verify_remote_main", return_value="tracker-sha"
                ):
                    code, summary = module.run_unattended(
                        args, command_runner=self._runner([]), stage_builder=self._stage
                    )
                self.assertNotEqual(code, 0)
                self.assertIn("symlink", summary["error"].casefold())

    def test_load_baseline_counts_reads_only_latest_successful_summary(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "latest").write_text("run-1\n", encoding="utf-8")
            run = root / "run-1"
            run.mkdir()
            (run / "summary.json").write_text(
                json.dumps({"ok": True, "counts": {"peak": 12}}), encoding="utf-8"
            )
            self.assertEqual(module.load_baseline_counts(root), {"peak": 12})

    def test_load_baseline_counts_rejects_symlinked_latest_pointer(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.write_text("run-1\n", encoding="utf-8")
            (root / "latest").symlink_to(target)
            with self.assertRaises(ValueError):
                module.load_baseline_counts(root)

    def test_load_baseline_counts_rejects_empty_successful_counts(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "latest").write_text("run-1\n", encoding="utf-8")
            run = root / "run-1"
            run.mkdir()
            (run / "summary.json").write_text(
                json.dumps({"ok": True, "counts": {}}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                module.load_baseline_counts(root)

    def test_anomaly_report_requires_explicit_one_run_override(self):
        module = load_module()
        result = module.anomaly_report({"peak": 100}, {"peak": 125})
        self.assertTrue(result["blocked"])
        self.assertTrue(result["games"]["peak"]["anomalous"])
        self.assertTrue(module.anomaly_report({"peak": 100}, {"peak": 125}, override=True)["overridden"])

    def test_anomaly_report_rejects_partial_baseline(self):
        module = load_module()
        with self.assertRaises(ValueError):
            module.anomaly_report({"peak": 100}, {"peak": 100, "repo": 100})

    def test_override_flag_requires_a_reason_before_running(self):
        module = load_module()
        with self.assertRaises(SystemExit):
            module.parse_args(["--override-anomaly"])

    def test_tracker_commands_collect_without_reports_then_report_all(self):
        module = load_module()
        collect = module.tracker_command("collect", "peak", Path("/project"), Path("/key"), no_report=True)
        report = module.tracker_command("report", "all", Path("/project"), Path("/key"))
        self.assertIn("--no-report", collect)
        self.assertNotIn("--no-report", report)
        self.assertIn("all", report)

    def test_compact_telegram_summary_is_deterministic_and_secret_free(self):
        module = load_module()
        summary = {
            "ok": True,
            "duration_seconds": 3.2,
            "counts": {"peak": 12, "valheim": 34},
            "anomaly": {"blocked": False},
            "publication": {"state": "unchanged"},
            "git_shas": {"tracker": "abc"},
        }
        self.assertEqual(
            module.compact_summary(summary, secrets=["secret"]),
            "OK 3.2s | peak=12 valheim=34 | anomaly=clear | publication=unchanged | tracker=abc",
        )

    def test_run_command_measures_command_duration(self):
        module = load_module()
        result = module.run_command(
            ["python3", "-c", "import time; time.sleep(0.03)"], cwd=Path.cwd()
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["duration_seconds"], 0.02)

    def test_registry_failure_still_writes_failed_run_summary(self):
        module = load_module()
        import tracker
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self._args(root)
            with patch.object(tracker, "load_game_registry", side_effect=RuntimeError("registry boom")):
                try:
                    code, summary = module.run_unattended(args)
                except RuntimeError as exc:
                    self.fail(f"registry failure escaped without summary: {exc}")
            self.assertNotEqual(code, 0)
            self.assertIn("registry boom", summary["error"])
            summaries = list(args.state_root.glob("run-*/summary.json"))
            self.assertEqual(len(summaries), 1)
            self.assertFalse(json.loads(summaries[0].read_text())["ok"])

    def test_live_verification_requires_http_200(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "mod-tracking"
            (staged / "peak").mkdir(parents=True)
            (staged / "index.html").write_bytes(b"landing")
            (staged / "peak/index.html").write_bytes(b"peak")
            registry = {"peak": {"publication": {"root": "mod-tracking", "path": "peak"}}}

            class Response:
                status = 206
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return b"landing"

            with patch.object(module, "urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "HTTP 206"):
                    module.verify_live(
                        "https://example.invalid",
                        root,
                        registry,
                        attempts=1,
                        retry_delay=0,
                        sleeper=lambda _seconds: None,
                    )

    def test_live_verification_retries_the_same_exact_url_for_http_error_and_stale_bytes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "mod-tracking"
            (staged / "peak").mkdir(parents=True)
            (staged / "index.html").write_bytes(b"landing-new")
            (staged / "peak/index.html").write_bytes(b"peak-new")
            registry = {"peak": {"publication": {"root": "mod-tracking", "path": "peak"}}}
            calls = []
            sleeps = []
            landing_reads = iter((b"landing-old", b"landing-new"))
            landing_attempt = 0

            class Response:
                status = 200
                def __init__(self, body): self.body = body
                def __enter__(self): return self
                def __exit__(self, *args): return False
                def read(self): return self.body

            def fake_urlopen(request, timeout):
                nonlocal landing_attempt
                calls.append(request.full_url)
                if request.full_url.endswith("/__unattended-unknown__/"):
                    raise module.HTTPError(request.full_url, 404, "missing", {}, None)
                if request.full_url.endswith("/mod-tracking/"):
                    landing_attempt += 1
                    if landing_attempt == 1:
                        raise module.HTTPError(request.full_url, 503, "unavailable", {}, None)
                    return Response(next(landing_reads))
                return Response(b"peak-new")

            with patch.object(module, "urlopen", side_effect=fake_urlopen):
                result = module.verify_live(
                    "https://example.invalid",
                    root,
                    registry,
                    attempts=3,
                    retry_delay=10,
                    sleeper=sleeps.append,
                )
            self.assertTrue(result["ok"])
            self.assertEqual(sleeps, [10, 10])
            self.assertEqual(calls[:3], [
                "https://example.invalid/mod-tracking/",
                "https://example.invalid/mod-tracking/",
                "https://example.invalid/mod-tracking/",
            ])
            self.assertTrue(all("?" not in url for url in calls))

    def test_run_id_and_stage_names_reject_path_escape_forms(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for run_id in ("../escape", "/absolute", "nested/run"):
                with self.subTest(run_id=run_id):
                    with self.assertRaises(ValueError):
                        module.RunRecorder(root, run_id)
            with module.RunRecorder(root, "safe") as run:
                for stage in ("../escape", "/absolute", "nested/stage"):
                    with self.subTest(stage=stage):
                        try:
                            run.record_stage(stage, "", "", ok=True)
                        except Exception as exc:
                            self.assertIsInstance(exc, ValueError)
                        else:
                            self.fail("unsafe stage name was accepted")

    def test_run_recorder_and_lock_reject_symlinked_roots_and_lock_parents(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real"
            root.mkdir()
            root_link = Path(tmp) / "root-link"
            root_link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.RunRecorder(root_link, "run-001")

            lock_parent = Path(tmp) / "lock-parent"
            lock_parent.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.RunLock(lock_parent / "run.lock").__enter__()

    def test_record_stage_does_not_follow_preexisting_symlinked_outputs(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"
            outside.write_text("untouched", encoding="utf-8")
            with module.RunRecorder(root, "run-001") as run:
                (run.path / "collect.stdout").symlink_to(outside)
                with self.assertRaises(ValueError):
                    run.record_stage("collect", "new", "", ok=True)
            self.assertEqual(outside.read_text(encoding="utf-8"), "untouched")

    def test_tree_digest_rejects_symlinked_root_or_file(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            target = root / "target.txt"
            target.write_text("secret", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                module.tree_digest(root)

            root_link = Path(tmp) / "root-link"
            root_link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                module.tree_digest(root_link)


    def test_sanitize_redacts_secret_dictionary_keys_and_nested_jsonish_values(self):
        module = load_module()
        value = {"NEXUS-SECRET": {"nested": ("NEXUS-SECRET", None, True, 3)}}
        clean = module.sanitize(value, ["NEXUS-SECRET"])
        encoded = json.dumps(clean)
        self.assertNotIn("NEXUS-SECRET", encoded)
        self.assertIn("[REDACTED]", clean)

    def test_anomaly_gate_fails_closed_for_zero_baseline_and_bad_counts(self):
        module = load_module()
        self.assertFalse(module.is_anomalous(0, 0))
        self.assertTrue(module.is_anomalous(0, 1))
        for baseline, current in ((-1, 0), (0, -1), (True, 1), (1, True), (1.0, 2)):
            with self.subTest(baseline=baseline, current=current):
                with self.assertRaises(ValueError):
                    module.is_anomalous(baseline, current)

    def test_complete_cannot_publish_when_any_recorded_stage_failed(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, "run-failed-stage") as run:
                run.record_stage("collect", "", "failed", ok=False)
                run.complete()
            summary = json.loads((root / "run-failed-stage" / "summary.json").read_text())
            self.assertFalse(summary["ok"])
            self.assertFalse((root / "latest").exists())


    def test_summary_replace_failure_does_not_advance_latest_or_leave_canonical_summary(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, "run-old") as run:
                run.complete()
            original = Path.replace

            def fail_replace(path, target):
                if path.name == "summary.json.tmp":
                    raise OSError("injected replace failure")
                return original(path, target)

            with patch.object(Path, "replace", fail_replace):
                with self.assertRaises(OSError):
                    with module.RunRecorder(root, "run-new") as run:
                        run.complete()
            self.assertEqual((root / "latest").read_text(), "run-old\n")
            self.assertFalse((root / "run-new" / "summary.json").exists())
            self.assertFalse((root / "run-new" / "summary.json.tmp").exists())

    def test_latest_replace_failure_does_not_leave_pointer_temp_or_advance_latest(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, "run-old") as run:
                run.complete()
            original = Path.replace

            def fail_latest_replace(path, target):
                if path.name == "latest.tmp":
                    raise OSError("injected latest failure")
                return original(path, target)

            with patch.object(Path, "replace", fail_latest_replace):
                with self.assertRaises(OSError):
                    with module.RunRecorder(root, "run-new") as run:
                        run.complete()
            self.assertEqual((root / "latest").read_text(), "run-old\n")
            self.assertFalse((root / "latest.tmp").exists())
            summary = json.loads((root / "run-new" / "summary.json").read_text())
            self.assertFalse(summary["ok"])


    def test_final_summary_has_runner_fields_and_cannot_claim_ok_over_failed_stage(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, "run-fields") as run:
                run.record_stage("deploy", "", "", ok=False)
                run.complete()
            summary = json.loads((root / "run-fields" / "summary.json").read_text())
            for field in (
                "started_at", "ended_at", "duration_seconds", "counts", "anomaly",
                "override", "git_shas", "publication", "deployment", "live_verification",
            ):
                with self.subTest(field=field):
                    self.assertIn(field, summary)
            self.assertFalse(summary["ok"])
            self.assertIn("duration_seconds", summary["stages"]["deploy"])

    def test_whole_run_lock_is_nonblocking_and_held_for_context(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "run.lock"
            with module.RunLock(lock_path):
                result = {}
                def contend():
                    try:
                        with module.RunLock(lock_path):
                            result["acquired"] = True
                    except module.OverlapError:
                        result["acquired"] = False
                thread = threading.Thread(target=contend)
                thread.start(); thread.join()
                self.assertFalse(result["acquired"])

    def test_run_recorder_persists_stages_summary_and_completed_latest(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, run_id="run-001") as run:
                self.assertTrue(run.path.is_dir())
                run.record_stage(
                    "collect", "secret output NEXUS-SECRET", "warning NEXUS-SECRET", ok=True,
                    command=["tracker", "--key", "NEXUS-SECRET"], secrets=["NEXUS-SECRET"],
                )
                run.complete()
            self.assertEqual((run.path / "collect.stdout").read_text(), "secret output [REDACTED]")
            self.assertEqual((run.path / "collect.stderr").read_text(), "warning [REDACTED]")
            metadata = json.loads((run.path / "collect.json").read_text())
            self.assertNotIn("NEXUS-SECRET", json.dumps(metadata))
            summary = json.loads((run.path / "summary.json").read_text())
            self.assertTrue(summary["ok"])
            self.assertEqual((root / "latest").read_text(), "run-001\n")
            self.assertEqual(summary["run_id"], "run-001")


    def test_anomaly_gate_requires_both_absolute_and_percentage_thresholds(self):
        module = load_module()
        self.assertFalse(module.is_anomalous(100, 124))
        self.assertTrue(module.is_anomalous(100, 125))
        self.assertFalse(module.is_anomalous(100, 110))
        self.assertTrue(module.is_anomalous(0, 1))

    def test_tree_manifest_is_deterministic_and_detects_content_changes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "left"; (root / "b").mkdir(parents=True)
            (root / "a.txt").write_text("a"); (root / "b/x.txt").write_text("x")
            first = module.tree_digest(root)
            clone = Path(tmp) / "right"
            shutil.copytree(root, clone)
            self.assertEqual(first, module.tree_digest(clone))
            (root / "b/x.txt").write_text("changed")
            self.assertNotEqual(first, module.tree_digest(root))

    def test_sanitize_redacts_secrets_in_nested_metadata_and_text(self):
        module = load_module()
        value = {"command": ["--key", "NEXUS-SECRET"], "text": "token NEXUS-SECRET"}
        clean = module.sanitize(value, ["NEXUS-SECRET"])
        self.assertNotIn("NEXUS-SECRET", json.dumps(clean))
        self.assertEqual(clean["command"][1], "[REDACTED]")


    def test_failed_invocation_writes_summary_without_replacing_latest(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with module.RunRecorder(root, run_id="run-ok") as run:
                run.complete()
            with module.RunRecorder(root, run_id="run-failed"):
                pass
            self.assertEqual((root / "latest").read_text(), "run-ok\n")
            self.assertFalse(json.loads((root / "run-failed/summary.json").read_text())["ok"])

    def test_compare_trees_uses_the_same_deterministic_manifest(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "left"; right = Path(tmp) / "right"
            left.mkdir(); right.mkdir(); (left / "x").write_text("same"); (right / "x").write_text("same")
            self.assertTrue(module.trees_unchanged(left, right))
            (right / "x").write_text("different")
            self.assertFalse(module.trees_unchanged(left, right))


if __name__ == "__main__":
    unittest.main()
