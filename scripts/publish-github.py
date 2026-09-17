#!/usr/bin/env python3
"""Publish a staged publication tree to a GitHub Pages branch.

Replaces the Cloudflare deployment step for the mod-tracking namespace. The tree
is committed as a single orphan commit and force-pushed, so the branch always
holds exactly one commit: the current site. Nothing from the previous release is
carried forward, and the repository stays small.

Credentials are read at runtime, never from arguments or the repository, and the
token is passed to git through the environment only.

Usage:
    publish-github.py --source DIR --repo URL [--branch gh-pages] [--dry-run]

Machine output on stdout is a single JSON object; diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRANCH = "gh-pages"
DEFAULT_TOKEN_FILE = Path("/opt/data/.env")
DEFAULT_HELPER = "!/opt/data/bin/gh auth git-credential"


def fail(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print(json.dumps({"ok": False, "error": message}), file=sys.stdout)
    raise SystemExit(1)


def read_token(token_file: Path, env: dict) -> str | None:
    """Token from the environment first, then the credential file."""
    token = (env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or "").strip()
    if token:
        return token
    try:
        text = token_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("GITHUB_TOKEN=") and not line.startswith("#"):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            return value or None
    return None


def validate_tree(source: Path) -> list[Path]:
    """Reject anything that could redirect or surprise the publication."""
    if not source.is_dir():
        fail(f"source is not a directory: {source}")
    if any(part.is_symlink() for part in [*source.parents, source]):
        fail(f"source path must not contain a symlink: {source}")
    files: list[Path] = []
    for current, dirs, names in os.walk(source, followlinks=False):
        here = Path(current)
        for name in list(dirs):
            if (here / name).is_symlink():
                fail(f"refusing to publish a symlinked directory: {here / name}")
            if name == ".git":
                fail(f"refusing to publish a nested repository: {here / name}")
        for name in names:
            path = here / name
            if path.is_symlink():
                fail(f"refusing to publish a symlink: {path}")
            if not path.is_file():
                fail(f"refusing to publish a non-file entry: {path}")
            files.append(path.relative_to(source))
    if "index.html" not in {str(p) for p in files}:
        fail(f"source has no index.html at its root: {source}")
    for child in sorted(p for p in source.iterdir() if p.is_dir()):
        if not (child / "index.html").is_file():
            fail(f"published directory has no index.html: {child}")
    if not files:
        fail(f"source is empty: {source}")
    return sorted(files)


def tree_digest(source: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update((source / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git(args: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )


def run_git(args: list[str], cwd: Path, env: dict) -> str:
    result = git(args, cwd, env)
    if result.returncode != 0:
        fail(f"git {' '.join(args)} failed: {result.stderr.strip()[:400]}")
    return result.stdout.strip()


def publish(
    source: Path,
    repo: str,
    branch: str,
    *,
    dry_run: bool,
    token_file: Path,
    helper: str,
    workdir: Path,
) -> dict:
    files = validate_tree(source)
    digest = tree_digest(source, files)

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = read_token(token_file, env)
    credentials = ["-c", "credential.helper="]
    if token:
        env["GH_TOKEN"] = token
        credentials += ["-c", f"credential.helper={helper}"]
    elif helper and Path(helper.lstrip("!")).exists():
        credentials += ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]

    work = workdir
    run_git(["git", "init", "-q", "-b", branch], work, env)
    run_git(["git", "config", "user.name", "mod-tracker"], work, env)
    run_git(["git", "config", "user.email", "mod-tracker@localhost"], work, env)
    for relative in files:
        destination = work / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, destination)
    (work / ".nojekyll").write_text("", encoding="utf-8")
    run_git(["git", "add", "-A"], work, env)
    run_git(
        ["git", "commit", "-q", "-m", f"Publish mod-tracking site ({len(files)} files)"],
        work,
        env,
    )
    commit = run_git(["git", "rev-parse", "HEAD"], work, env)
    tree = run_git(["git", "rev-parse", "HEAD^{tree}"], work, env)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "repo": repo,
            "branch": branch,
            "files": len(files),
            "digest": digest,
            "commit": commit,
        }

    # Skip the push when the remote branch already holds this exact tree, so an
    # unchanged pass does not force a pointless Pages rebuild.
    remote = git(["git", "ls-remote", repo, f"refs/heads/{branch}"], work, env)
    if remote.returncode == 0 and remote.stdout.strip():
        remote_sha = remote.stdout.split()[0]
        fetched = git(["git", "fetch", "-q", repo, f"refs/heads/{branch}"], work, env)
        if fetched.returncode == 0:
            remote_tree = git(["git", "rev-parse", "FETCH_HEAD^{tree}"], work, env)
            if remote_tree.returncode == 0 and remote_tree.stdout.strip() == tree:
                return {
                    "ok": True,
                    "changed": False,
                    "repo": repo,
                    "branch": branch,
                    "files": len(files),
                    "digest": digest,
                    "commit": remote_sha,
                }

    push = git(["git", *credentials, "push", "--force", repo, f"{branch}:{branch}"], work, env)
    if push.returncode != 0:
        fail(f"git push failed: {(push.stderr or push.stdout).strip()[:400]}")
    return {
        "ok": True,
        "changed": True,
        "repo": repo,
        "branch": branch,
        "files": len(files),
        "digest": digest,
        "commit": commit,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--credential-helper", default=DEFAULT_HELPER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="publish-github-") as temporary:
        result = publish(
            args.source,
            args.repo,
            args.branch,
            dry_run=args.dry_run,
            token_file=args.token_file,
            helper=args.credential_helper,
            workdir=Path(temporary),
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
