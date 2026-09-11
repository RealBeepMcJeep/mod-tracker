#!/usr/bin/env python3
"""Run a deterministic collect, verify, and publish pass for every game."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_ROOT = PROJECT_ROOT.parent / "public-artifacts"
DEFAULT_API_KEY_FILE = Path.home() / ".config/nexus-mods/api-key"

sys.path.insert(0, str(PROJECT_ROOT))
import tracker  # noqa: E402


def tracker_command(action: str, game: str, root: Path, api_key_file: Path) -> list[str]:
    """Build one shell-free tracker command."""
    command = [
        sys.executable,
        str(PROJECT_ROOT / "tracker.py"),
        action,
        "--game",
        game,
        "--output-root",
        str(root),
    ]
    if action == "collect":
        command.extend(["--nexus-api-key-file", str(api_key_file)])
    return command


def batch_publication_command(manifest: Path, public_root: Path, *, dry_run: bool) -> list[str]:
    """Build the single atomic batch-publisher command."""
    command = [
        sys.executable,
        str(public_root / "scripts" / "publish-site.py"),
        "--batch-manifest",
        str(manifest),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def stage_report(game_root: Path, staging: Path) -> Path:
    """Stage only the verified hotlinked report as index.html."""
    source = game_root / "report-hotlinked.html"
    if not source.is_file():
        raise FileNotFoundError(source)
    staging.mkdir(parents=True, exist_ok=False)
    destination = staging / "index.html"
    shutil.copyfile(source, destination)
    return destination


def stage_publication_tree(
    registry: dict, output_root: Path, staging: Path
) -> dict[str, object]:
    """Stage one top-level publication tree with a landing page and game reports."""
    roots = {config["publication"]["root"] for config in registry.values()}
    if roots != {"mod-tracking"}:
        raise ValueError("all games must use the canonical mod-tracking publication root")
    publication_root = roots.pop()
    paths = []
    for key, config in registry.items():
        publication_path = config["publication"]["path"]
        if (
            not isinstance(publication_path, str)
            or not tracker.SLUG_RE.fullmatch(publication_path)
            or publication_path != key
        ):
            raise ValueError(f"{key} has a noncanonical publication path")
        paths.append(publication_path)
    if len(paths) != len(set(paths)):
        raise ValueError("publication paths must be unique")
    if staging.name != publication_root:
        raise ValueError("staging directory must match the publication root")
    staging.mkdir(parents=True, exist_ok=False)
    links = []
    verify_paths = []
    for key, config in registry.items():
        game_root = output_root / config["output_subdir"]
        publication_path = config["publication"]["path"]
        stage_report(game_root, staging / publication_path)
        verify_paths.append(publication_path)
        links.append(
            f'<li><a href="./{html.escape(publication_path, quote=True)}/">'
            f'{html.escape(config["display_name"])}</a></li>'
        )
    landing = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mod Tracking Reports</title>
<style>
:root{color-scheme:dark}body{max-width:54rem;margin:0 auto;padding:3rem 1.25rem;font:16px/1.5 system-ui,sans-serif;background:#0b1020;color:#eef2ff}h1{margin-bottom:.4rem}p{color:#aab5d1}ul{display:grid;gap:.75rem;padding:0;list-style:none}a{display:block;padding:1rem 1.1rem;border:1px solid #33446d;border-radius:.7rem;background:#131c34;color:#8fc7ff;text-decoration:none}a:hover,a:focus{border-color:#8fc7ff;background:#192746}
</style>
</head>
<body>
<main><h1>Mod Tracking Reports</h1><p>Current mod listings and activity reports by game.</p><ul>
""" + "\n".join(links) + """
</ul></main>
</body>
</html>
"""
    (staging / "index.html").write_text(landing, encoding="utf-8")
    return {
        "source": str(staging),
        "root": publication_root,
        "verify_paths": verify_paths,
    }


def run_command(command: list[str], *, cwd: Path) -> dict:
    """Run a command without a shell and return its machine-readable result."""
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    result = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
    }
    output = completed.stdout.strip()
    if output:
        try:
            result["output"] = json.loads(output)
        except json.JSONDecodeError:
            result["output"] = output
    if completed.stderr.strip():
        result["stderr"] = completed.stderr.strip()
    return result


def git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def ensure_clean_repository(root: Path) -> None:
    if git_output(root, "status", "--porcelain"):
        raise RuntimeError(f"repository is not clean: {root}")
    if git_output(root, "branch", "--show-current") != "main":
        raise RuntimeError(f"repository is not on main: {root}")


def verify_remote_main(root: Path) -> str:
    """Require local HEAD to equal the exact origin/main remote ref."""
    local = git_output(root, "rev-parse", "HEAD")
    remote_output = git_output(root, "ls-remote", "origin", "refs/heads/main")
    fields = remote_output.split()
    if len(fields) != 2 or fields[1] != "refs/heads/main":
        raise RuntimeError(f"origin/main was not returned for {root}")
    if fields[0] != local:
        raise RuntimeError(f"local HEAD does not match origin/main for {root}")
    return local


def resolve_output_root(path: Path, project_root: Path = PROJECT_ROOT) -> Path:
    """Resolve relative output roots consistently against the tracker project."""
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--nexus-api-key-file", type=Path, default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--public-artifacts-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="collect and verify, then dry-run every publication without publishing",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    args.output_root = resolve_output_root(args.output_root)
    args.nexus_api_key_file = args.nexus_api_key_file.expanduser().resolve()
    args.public_artifacts_root = args.public_artifacts_root.resolve()
    registry = tracker.load_game_registry()
    summary = {
        "ok": False,
        "dry_run": args.dry_run,
        "games": {key: {} for key in registry},
    }
    try:
        ensure_clean_repository(PROJECT_ROOT)
        summary["tracker_commit"] = verify_remote_main(PROJECT_ROOT)
    except Exception as exc:
        summary["failures"] = ["tracker-repository"]
        summary["error"] = str(exc)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1

    # Collection is isolated by game. Attempt every game and aggregate failures.
    for key in registry:
        summary["games"][key]["collect"] = run_command(
            tracker_command("collect", key, args.output_root, args.nexus_api_key_file),
            cwd=PROJECT_ROOT,
        )

    for key in registry:
        if summary["games"][key]["collect"]["ok"]:
            summary["games"][key]["verify"] = run_command(
                tracker_command("verify", key, args.output_root, args.nexus_api_key_file),
                cwd=PROJECT_ROOT,
            )

    failures = [
        key
        for key, result in summary["games"].items()
        if not result.get("collect", {}).get("ok") or not result.get("verify", {}).get("ok")
    ]
    if failures:
        summary["failures"] = failures
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 1

    with tempfile.TemporaryDirectory(prefix="mod-tracker-publish-") as temporary:
        temporary_root = Path(temporary)
        publication_root = next(iter(registry.values()))["publication"]["root"]
        manifest_entry = stage_publication_tree(
            registry, args.output_root, temporary_root / publication_root
        )
        manifest = temporary_root / "publication-manifest.json"
        manifest.write_text(
            json.dumps([manifest_entry], indent=2), encoding="utf-8"
        )

        # Preflight the complete batch before the first external write.
        preflight = run_command(
            batch_publication_command(manifest, args.public_artifacts_root, dry_run=True),
            cwd=args.public_artifacts_root,
        )
        summary["publication_preflight"] = preflight
        if not preflight["ok"]:
            summary["failures"] = ["publication-preflight"]
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 1

        if not args.dry_run:
            try:
                ensure_clean_repository(args.public_artifacts_root)
            except Exception as exc:
                summary["failures"] = ["public-artifacts-repository"]
                summary["error"] = str(exc)
                print(json.dumps(summary, indent=2, sort_keys=True))
                return 1
            result = run_command(
                batch_publication_command(manifest, args.public_artifacts_root, dry_run=False),
                cwd=args.public_artifacts_root,
            )
            summary["publication"] = result
            if not result["ok"]:
                summary["failures"] = ["publication"]
                print(json.dumps(summary, indent=2, sort_keys=True))
                return 1
            push = run_command(["git", "push", "origin", "main"], cwd=args.public_artifacts_root)
            summary["public_artifacts_push"] = push
            if not push["ok"]:
                summary["failures"] = ["public-artifacts-push"]
                print(json.dumps(summary, indent=2, sort_keys=True))
                return 1
            try:
                summary["public_artifacts_commit"] = verify_remote_main(
                    args.public_artifacts_root
                )
            except Exception as exc:
                summary["failures"] = ["public-artifacts-remote-verification"]
                summary["error"] = str(exc)
                print(json.dumps(summary, indent=2, sort_keys=True))
                return 1

    summary["ok"] = True
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
