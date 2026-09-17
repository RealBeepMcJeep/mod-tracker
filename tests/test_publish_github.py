"""Tests for the GitHub Pages publisher (scripts/publish-github.py).

Every test pushes to a local bare repository, so the full push path is exercised
without network access or credentials.
"""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_github", ROOT / "scripts" / "publish-github.py"
)
assert SPEC and SPEC.loader
publish_github = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish_github)


def git(args, cwd):
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


class PublisherTestCase(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="publish-github-test-")
        self.tmp = Path(self._temporary.name)
        self.remote = self.tmp / "remote.git"
        git(["init", "-q", "--bare", str(self.remote)], self.tmp)
        self.source = self.tmp / "source"
        (self.source / "valheim").mkdir(parents=True)
        (self.source / "index.html").write_text("<h1>landing</h1>\n", encoding="utf-8")
        (self.source / "valheim" / "index.html").write_text(
            "<h1>valheim</h1>\n", encoding="utf-8"
        )

    def tearDown(self):
        self._temporary.cleanup()

    def publish(self, *, dry_run=False):
        work = Path(tempfile.mkdtemp(prefix="work-", dir=self.tmp))
        return publish_github.publish(
            self.source,
            str(self.remote),
            "gh-pages",
            dry_run=dry_run,
            token_file=self.tmp / "absent.env",
            helper="",
            workdir=work,
        )

    def remote_files(self):
        return set(
            git(["--git-dir", str(self.remote), "ls-tree", "-r", "--name-only", "gh-pages"], self.tmp).split()
        )

    def remote_commits(self):
        return git(
            ["--git-dir", str(self.remote), "rev-list", "--count", "gh-pages"], self.tmp
        )

    def test_publishes_the_tree_to_the_branch(self):
        result = self.publish()
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(self.remote_files(), {"index.html", ".nojekyll", "valheim/index.html"})

    def test_unchanged_tree_skips_the_push(self):
        first = self.publish()
        second = self.publish()
        self.assertTrue(second["ok"])
        self.assertFalse(second["changed"])
        # The branch still holds exactly one commit, and it is the first one.
        self.assertEqual(self.remote_commits(), "1")
        self.assertEqual(second["commit"], first["commit"])

    def test_changed_content_pushes_a_replacement_commit(self):
        self.publish()
        (self.source / "valheim" / "index.html").write_text(
            "<h1>valheim v2</h1>\n", encoding="utf-8"
        )
        result = self.publish()
        self.assertTrue(result["changed"])
        # Force-pushed orphan history: still a single commit, new content.
        self.assertEqual(self.remote_commits(), "1")
        blob = git(
            ["--git-dir", str(self.remote), "show", "gh-pages:valheim/index.html"], self.tmp
        )
        self.assertIn("valheim v2", blob)

    def test_dry_run_leaves_the_remote_untouched(self):
        result = self.publish(dry_run=True)
        self.assertTrue(result["dry_run"])
        listing = subprocess.run(
            ["git", "--git-dir", str(self.remote), "ls-remote", "--heads"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        self.assertEqual(listing, "")

    def test_rejects_a_symlink_in_the_source(self):
        (self.source / "valheim" / "link.html").symlink_to(self.source / "index.html")
        with self.assertRaises(SystemExit):
            self.publish()

    def test_rejects_a_missing_root_index(self):
        (self.source / "index.html").unlink()
        with self.assertRaises(SystemExit):
            self.publish()

    def test_rejects_a_published_directory_without_index(self):
        (self.source / "peak").mkdir()
        (self.source / "peak" / "other.html").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.publish()

    def test_rejects_a_symlinked_source_root(self):
        link = self.tmp / "linked-source"
        link.symlink_to(self.source)
        work = Path(tempfile.mkdtemp(prefix="work-", dir=self.tmp))
        with self.assertRaises(SystemExit):
            publish_github.publish(
                link,
                str(self.remote),
                "gh-pages",
                dry_run=True,
                token_file=self.tmp / "absent.env",
                helper="",
                workdir=work,
            )


if __name__ == "__main__":
    unittest.main()
