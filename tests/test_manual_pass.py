import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/manual-pass.py"


def load_manual_pass():
    spec = importlib.util.spec_from_file_location("manual_pass", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManualPassTests(unittest.TestCase):
    def test_build_tracker_command_is_shell_free_and_game_specific(self):
        module = load_manual_pass()
        command = module.tracker_command("collect", "peak", Path("/tracker"), Path("/key"))
        self.assertEqual(
            command[:4],
            [module.sys.executable, str(module.PROJECT_ROOT / "tracker.py"), "collect", "--game"],
        )
        self.assertIn("peak", command)
        self.assertIn("--output-root", command)
        self.assertNotIn("shell=True", command)

    def test_stage_report_copies_hotlinked_report_byte_for_byte(self):
        module = load_manual_pass()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "game"
            stage = root / "stage"
            output.mkdir()
            (output / "report-hotlinked.html").write_bytes(b"<html>exact</html>")
            module.stage_report(output, stage)
            self.assertEqual((stage / "index.html").read_bytes(), b"<html>exact</html>")

    def test_publish_command_uses_explicit_registry_destination(self):
        module = load_manual_pass()
        command = module.publication_command(
            Path("/stage"),
            {"publication": {"section": "reports", "name": "peak-mod-tracker"}},
            Path("/public-artifacts"),
            dry_run=True,
        )
        self.assertEqual(command[1], "/public-artifacts/scripts/publish-site.py")
        self.assertIn("reports", command)
        self.assertIn("peak-mod-tracker", command)
        self.assertIn("--dry-run", command)

    def test_resolve_output_root_is_consistent_outside_project(self):
        module = load_manual_pass()
        self.assertEqual(
            module.resolve_output_root(Path("generated"), Path("/project")),
            Path("/project/generated"),
        )

    def test_batch_publish_command_uses_one_manifest(self):
        module = load_manual_pass()
        command = module.batch_publication_command(
            Path("/tmp/sites.json"), Path("/public-artifacts"), dry_run=False,
        )
        self.assertIn("--batch-manifest", command)
        self.assertEqual(command.count("/public-artifacts/scripts/publish-site.py"), 1)

    def test_verify_remote_main_requires_exact_matching_hash(self):
        module = load_manual_pass()
        with mock.patch.object(
            module,
            "git_output",
            side_effect=["abc123", "abc123\trefs/heads/main"],
        ):
            self.assertEqual(module.verify_remote_main(Path("/repo")), "abc123")

        with mock.patch.object(
            module,
            "git_output",
            side_effect=["abc123", "def456\trefs/heads/main"],
        ):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                module.verify_remote_main(Path("/repo"))


if __name__ == "__main__":
    unittest.main()