#!/usr/bin/env python3
"""Deterministic infrastructure for unattended mod-tracker runs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SECRET_KEY_WORDS = ("authorization", "cookie", "password", "secret", "token", "api_key", "apikey")


class OverlapError(RuntimeError):
    """Another invocation currently owns the whole-run lock."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _reject_symlink_components(path: Path) -> None:
    """Reject existing symlinks in a path or any of its parents."""
    path = Path(path)
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ValueError(f"symlinked path is not allowed: {current}")


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    _reject_symlink_components(path)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists() or temporary.is_symlink():
        if temporary.is_symlink() or not temporary.is_file():
            raise ValueError(f"unsafe temporary path: {temporary}")
        temporary.unlink()
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    except BaseException:
        try:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
        finally:
            raise


class RunRecorder:
    """Persist sanitized stage output and one final run summary."""

    def __init__(self, root: Path, run_id: str, *, secrets=()):
        self.root = Path(root)
        _reject_symlink_components(self.root)
        self.run_id = _validate_name(run_id, "run ID")
        self.path = self.root / self.run_id
        self.stages: dict[str, dict] = {}
        self._completed = False
        self._fields: dict = {}
        self._secrets = tuple(secrets)
        self._started_at = _utc_now()
        self._started_clock = time.monotonic()

    def __enter__(self):
        self.path.mkdir(parents=True, exist_ok=False)
        return self

    def record_stage(
        self, name, stdout, stderr, *, ok, command=None, secrets=(), duration_seconds=None
    ):
        name = _validate_name(name, "stage name")
        started = time.monotonic()
        stdout = sanitize(stdout, secrets)
        stderr = sanitize(stderr, secrets)
        metadata = {
            "ok": bool(ok),
            "command": sanitize(command or [], secrets),
            "duration_seconds": round(
                duration_seconds if duration_seconds is not None else time.monotonic() - started,
                6,
            ),
        }
        stdout_path = self.path / f"{name}.stdout"
        stderr_path = self.path / f"{name}.stderr"
        metadata_path = self.path / f"{name}.json"
        for target in (stdout_path, stderr_path, metadata_path):
            _reject_symlink_components(target)
        stdout_path.write_text(str(stdout), encoding="utf-8")
        stderr_path.write_text(str(stderr), encoding="utf-8")
        _atomic_write_text(metadata_path, json.dumps(metadata, sort_keys=True))
        self.stages[name] = metadata

    def complete(self, **fields):
        self._completed = True
        self._fields.update(fields)

    def __exit__(self, exc_type, exc_value, traceback):
        stages_ok = all(stage.get("ok") is True for stage in self.stages.values())
        ok = self._completed and exc_type is None and stages_ok
        summary = {
            "run_id": self.run_id,
            "ok": ok,
            "started_at": self._started_at,
            "ended_at": _utc_now(),
            "duration_seconds": round(time.monotonic() - self._started_clock, 6),
            "stages": self.stages,
            "counts": {},
            "anomaly": {},
            "override": False,
            "git_shas": {},
            "publication": {},
            "deployment": {},
            "live_verification": {},
        }
        summary.update(sanitize(self._fields, self._secrets))
        summary["ok"] = bool(ok and summary.get("ok", True))
        _atomic_write_text(self.path / "summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
        if summary["ok"]:
            try:
                _atomic_write_text(self.root / "latest", self.run_id + "\n")
            except BaseException:
                summary["ok"] = False
                summary["error"] = "failed to update latest-success pointer"
                _atomic_write_text(
                    self.path / "summary.json",
                    json.dumps(summary, indent=2, sort_keys=True) + "\n",
                )
                raise
        return False


class RunLock:
    """One nonblocking whole-run flock."""

    def __init__(self, path: Path):
        self.path = Path(path)
        _reject_symlink_components(self.path.parent)
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(self.path)
        self._handle = self.path.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise OverlapError(str(self.path)) from exc
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def is_anomalous(baseline: int, current: int) -> bool:
    """Apply the exact count gate, failing closed for zero baselines."""
    for label, value in (("baseline", baseline), ("current", current)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")
    if baseline == 0:
        return current != 0
    change = abs(current - baseline)
    return change >= 25 and change / baseline > 0.10


def tree_digest(root: Path) -> str:
    """Hash a deterministic relative-path/content manifest."""
    root = Path(root)
    _reject_symlink_components(root)
    if not root.is_dir():
        raise ValueError(f"tree root is not a directory: {root}")
    manifest = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in tree: {path}")
        if path.is_file():
            data = path.read_bytes()
            manifest.append({
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            })
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def trees_unchanged(left: Path, right: Path) -> bool:
    return tree_digest(left) == tree_digest(right)


def sanitize(value, secrets):
    """Redact explicit secret values and secret-bearing metadata keys."""
    ordered = sorted((str(secret) for secret in secrets if str(secret)), key=len, reverse=True)

    def clean_text(text):
        for secret in ordered:
            text = text.replace(secret, "[REDACTED]")
        return text

    def clean(item):
        if isinstance(item, str):
            return clean_text(item)
        if isinstance(item, dict):
            cleaned = {}
            for key, val in item.items():
                clean_key = clean_text(str(key))
                if any(word in str(key).casefold() for word in _SECRET_KEY_WORDS):
                    clean_key = "[REDACTED]"
                    val = "[REDACTED]"
                cleaned[clean_key] = clean(val)
            return cleaned
        if isinstance(item, list):
            return [clean(val) for val in item]
        if isinstance(item, tuple):
            return tuple(clean(val) for val in item)
        return item

    return clean(value)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_ROOT = PROJECT_ROOT.parent / "public-artifacts"
DEFAULT_API_KEY_FILE = Path.home() / ".config/nexus-mods/api-key"
DEFAULT_STATE_ROOT = PROJECT_ROOT / ".unattended-runs"
DEFAULT_LOCK_FILE = DEFAULT_STATE_ROOT / "run.lock"
DEFAULT_LIVE_BASE_URL = "https://public-artifacts.xioustic-5f1.workers.dev"


def validate_nexus_key(path: Path) -> str:
    """Read a Nexus key only from a regular file with exactly mode 0600."""
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError("Nexus key file must not be a symlink")
    try:
        info = path.stat()
    except OSError as exc:
        raise ValueError(f"unable to read Nexus key file: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError("Nexus key file must be a regular file with mode 0600")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"unable to read Nexus key file: {path}") from exc
    if not value:
        raise ValueError("Nexus key file is empty")
    return value


def _safe_pointer(value: str) -> str:
    return _validate_name(value.strip(), "run ID")


def load_baseline_counts(state_root: Path) -> dict[str, int]:
    """Read counts from the latest successful run, or return no baseline."""
    state_root = Path(state_root)
    pointer = state_root / "latest"
    if pointer.is_symlink():
        raise ValueError("latest baseline pointer must not be a symlink")
    if not pointer.is_file():
        return {}
    run_id = _safe_pointer(pointer.read_text(encoding="utf-8"))
    run_dir = state_root / run_id
    summary_path = run_dir / "summary.json"
    if run_dir.is_symlink() or summary_path.is_symlink():
        raise ValueError("latest baseline summary must not use symlinks")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("ok") is not True or not isinstance(summary.get("counts"), dict):
        raise ValueError("latest run is not a successful summary with counts")
    counts = summary["counts"]
    if not counts:
        raise ValueError("latest successful summary has no baseline counts")
    result = {}
    for game, count in counts.items():
        if not isinstance(game, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("baseline counts must be nonnegative integers")
        result[game] = count
    return result


def anomaly_report(baseline: dict[str, int], current: dict[str, int], *, override=False) -> dict:
    """Return per-game anomaly evidence and the publication decision."""
    if baseline and set(baseline) != set(current):
        raise ValueError("baseline counts must cover the complete game cohort")
    games = {}
    for game in sorted(current):
        value = current[game]
        old = baseline.get(game)
        anomalous = old is not None and is_anomalous(old, value)
        games[game] = {
            "baseline": old,
            "current": value,
            "anomalous": anomalous,
            "change": abs(value - old) if old is not None else None,
        }
    blocked = any(item["anomalous"] for item in games.values())
    return {
        "games": games,
        "blocked": blocked and not override,
        "overridden": blocked and bool(override),
    }


def compact_summary(summary: dict, *, secrets=()) -> str:
    """Render the stable, single-line no-agent/Telegram result."""
    clean = sanitize(summary, secrets)
    status = "OK" if clean.get("ok") else "FAIL"
    duration = clean.get("duration_seconds", 0)
    counts = " ".join(
        f"{game}={clean.get('counts', {}).get(game, '?')}"
        for game in sorted(clean.get("counts", {}))
    ) or "counts=?"
    anomaly = clean.get("anomaly", {})
    anomaly_state = "overridden" if anomaly.get("overridden") else "blocked" if anomaly.get("blocked") else "clear"
    publication = clean.get("publication", {}).get("state", "none")
    sha_text = " ".join(
        f"{name}={value}" for name, value in sorted(clean.get("git_shas", {}).items())
    ) or "sha=none"
    return f"{status} {duration}s | {counts} | anomaly={anomaly_state} | publication={publication} | {sha_text}"


def tracker_command(
    action: str,
    game: str,
    output_root: Path,
    api_key_file: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    no_report: bool = False,
) -> list[str]:
    """Build one argument-vector tracker invocation."""
    command = [
        sys.executable,
        str(Path(project_root) / "tracker.py"),
        action,
        "--game",
        game,
        "--output-root",
        str(output_root),
    ]
    if action == "collect":
        command.extend(["--nexus-api-key-file", str(api_key_file)])
        if no_report:
            command.append("--no-report")
    return command


def run_command(command: list[str], *, cwd: Path) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    result = {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 6),
    }
    if completed.stdout.strip():
        try:
            result["output"] = json.loads(completed.stdout)
        except json.JSONDecodeError:
            result["output"] = completed.stdout.strip()
    if completed.stderr.strip():
        result["stderr"] = completed.stderr.strip()
    return result


def git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
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
    local = git_output(root, "rev-parse", "HEAD")
    fields = git_output(root, "ls-remote", "origin", "refs/heads/main").split()
    if len(fields) != 2 or fields[1] != "refs/heads/main" or fields[0] != local:
        raise RuntimeError(f"local HEAD does not match origin/main for {root}")
    return local


def batch_publication_command(manifest: Path, public_root: Path, *, dry_run: bool) -> list[str]:
    command = [sys.executable, str(Path(public_root) / "scripts/publish-site.py"), "--batch-manifest", str(manifest)]
    if dry_run:
        command.append("--dry-run")
    return command


def stage_publication_tree(
    registry: dict, output_root: Path, staging: Path, *, project_root: Path = PROJECT_ROOT
) -> dict:
    """Use the manual pass's canonical complete-tree staging interface."""
    path = Path(project_root) / "scripts/manual-pass.py"
    spec = importlib.util.spec_from_file_location("mod_tracker_manual_pass", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load manual-pass staging interface")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stage_publication_tree(registry, output_root, staging)


def _provider_complete(result: dict, required_sources=()) -> bool:
    if result.get("ok") is not True:
        return False
    output = result.get("output")
    if not isinstance(output, dict):
        return False
    sources = output.get("sources")
    if (
        not isinstance(sources, list)
        or any(not isinstance(source, str) for source in sources)
        or len(sources) != len(set(sources))
        or set(sources) != set(required_sources)
    ):
        return False
    providers = output.get("providers")
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict) and (provider.get("ok") is False or provider.get("status") in {"failed", "unavailable"}):
                return False
    return True


def _counts_from_verification(output: dict, games: list[str]) -> dict[str, int]:
    if not isinstance(output, dict) or not isinstance(output.get("games"), dict):
        raise ValueError("all-game verification did not return per-game results")
    counts = {}
    for game in games:
        result = output["games"].get(game)
        if not isinstance(result, dict):
            raise ValueError(f"verification omitted {game}")
        report = result.get("report")
        count = report.get("cards") if isinstance(report, dict) else None
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"verification omitted report card count for {game}")
        counts[game] = count
    return counts


def verify_live(
    base_url: str,
    staging_root: Path,
    registry: dict,
    *,
    attempts: int = 6,
    retry_delay: float = 10,
    sleeper=time.sleep,
) -> dict:
    """Compare exact staged bytes with every live route and require child 404."""
    if attempts < 1:
        raise ValueError("live verification attempts must be positive")
    if retry_delay < 0:
        raise ValueError("live verification retry delay must not be negative")
    base_url = base_url.rstrip("/")
    root_name = next(iter(registry.values()))["publication"]["root"]
    staged = Path(staging_root) / root_name
    checks = {}
    expected = {"/mod-tracking/": staged / "index.html"}
    for key, config in registry.items():
        expected[f"/mod-tracking/{config['publication']['path']}/"] = staged / config["publication"]["path"] / "index.html"
    for route, path in expected.items():
        expected_bytes = path.read_bytes()
        for attempt in range(attempts):
            request = Request(base_url + route, headers={"User-Agent": "mod-tracker-unattended/1"})
            try:
                with urlopen(request, timeout=30) as response:
                    status = response.status
                    actual = response.read()
            except HTTPError as exc:
                status = exc.code
                actual = b""
            if status == 200 and actual == expected_bytes:
                checks[route] = {"status": status, "bytes_match": True}
                break
            if attempt + 1 == attempts:
                if status != 200:
                    raise RuntimeError(f"live route returned HTTP {status}: {route}")
                raise RuntimeError(f"live route does not match staged bytes: {route}")
            sleeper(retry_delay)
    unknown = "/mod-tracking/__unattended-unknown__/"
    try:
        urlopen(Request(base_url + unknown, headers={"User-Agent": "mod-tracker-unattended/1"}), timeout=30)
    except HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(f"unknown route returned HTTP {exc.code}") from exc
    else:
        raise RuntimeError("unknown route did not return HTTP 404")
    return {"ok": True, "routes": checks, "unknown_route": {"path": unknown, "status": 404}}


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"


def _encode_result(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, sort_keys=True)


def _record_command(run: RunRecorder, name: str, result: dict, command: list[str], key: str):
    run.record_stage(
        name,
        _encode_result(result.get("output", "")),
        result.get("stderr", ""),
        ok=result.get("ok") is True,
        command=command,
        secrets=[key],
        duration_seconds=result.get("duration_seconds"),
    )


def run_unattended(args, *, command_runner=None, stage_builder=None, live_verifier=None):
    """Run one complete, mapping-free five-game scheduled pass.

    All subprocesses are existing tracker/publisher interfaces.  The optional
    callables make the complete workflow testable without touching either
    production repository or the live site.
    """
    command_runner = command_runner or run_command
    stage_builder = stage_builder or stage_publication_tree
    live_verifier = live_verifier or verify_live
    run_id = _new_run_id()
    started_clock = time.monotonic()
    fields = {
        "ok": False,
        "dry_run": bool(args.dry_run),
        "override": bool(args.override_anomaly),
        "counts": {},
        "anomaly": {},
        "publication": {"state": "not-attempted"},
        "deployment": {"state": "not-attempted"},
        "git_shas": {},
    }
    def resolve_runtime_path(value, *, base=None):
        path = Path(value).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        _reject_symlink_components(path)
        return path.resolve()

    try:
        project_root = resolve_runtime_path(args.project_root)
        state_root = resolve_runtime_path(args.state_root)
    except Exception as exc:
        fields["error"] = str(exc)
        fields["duration_seconds"] = round(time.monotonic() - started_clock, 6)
        return 1, fields

    key = ""
    with RunRecorder(state_root, run_id) as run:
        try:
            output_root = resolve_runtime_path(args.output_root, base=project_root)
            public_root = resolve_runtime_path(args.public_artifacts_root)
            api_key_file = resolve_runtime_path(args.nexus_api_key_file)
            key = validate_nexus_key(api_key_file)
            run._secrets = (key,)

            # Import only the existing tracker module; no collector is copied here.
            sys.path.insert(0, str(project_root))
            import tracker

            registry = tracker.load_game_registry(project_root / "games.json")
            game_keys = list(registry)
            ensure_clean_repository(project_root)
            tracker_sha = verify_remote_main(project_root)
            fields["git_shas"]["tracker"] = tracker_sha
            run.record_stage("tracker-repository", "", "", ok=True)

            baseline = load_baseline_counts(state_root)
            fields["baseline_counts"] = baseline
            collection_failures = []
            for game in game_keys:
                command = tracker_command(
                    "collect", game, output_root, api_key_file,
                    project_root=project_root, no_report=True,
                )
                try:
                    result = command_runner(command, cwd=project_root)
                except Exception as exc:
                    result = {"ok": False, "returncode": 1, "stderr": str(exc)}
                _record_command(run, f"collect-{game}", result, command, key)
                if not _provider_complete(result, registry[game]["sources"]):
                    collection_failures.append(game)
            if collection_failures:
                raise RuntimeError("collection failed for: " + ", ".join(collection_failures))

            report_command = tracker_command(
                "report", "all", output_root, api_key_file, project_root=project_root
            )
            report_result = command_runner(report_command, cwd=project_root)
            _record_command(run, "report-all", report_result, report_command, key)
            if not report_result.get("ok"):
                raise RuntimeError("all-game report generation failed")

            verify_command = tracker_command(
                "verify", "all", output_root, api_key_file, project_root=project_root
            )
            verify_result = command_runner(verify_command, cwd=project_root)
            _record_command(run, "verify-all", verify_result, verify_command, key)
            if not verify_result.get("ok"):
                raise RuntimeError("all-game verification failed")
            current = _counts_from_verification(verify_result.get("output"), game_keys)
            fields["counts"] = current

            anomaly = anomaly_report(
                baseline,
                current,
                override=bool(args.override_anomaly),
            )
            if args.override_anomaly and not args.override_reason:
                raise RuntimeError("--override-anomaly requires --override-reason")
            if args.override_anomaly:
                anomaly["override_reason"] = args.override_reason
                fields["override_reason"] = args.override_reason
            fields["anomaly"] = anomaly
            run.record_stage("anomaly-gate", _encode_result(anomaly), "", ok=not anomaly["blocked"])
            if anomaly["blocked"]:
                raise RuntimeError("anomaly gate blocked publication")

            with tempfile.TemporaryDirectory(prefix="mod-tracker-publish-") as temporary:
                temporary_root = Path(temporary)
                publication_root = next(iter(registry.values()))["publication"]["root"]
                entry = stage_builder(
                    registry, output_root, temporary_root / publication_root, project_root=project_root
                )
                manifest = temporary_root / "publication-manifest.json"
                _atomic_write_text(manifest, json.dumps([entry], indent=2, sort_keys=True) + "\n")
                staged_tree = temporary_root / publication_root
                preflight_command = batch_publication_command(manifest, public_root, dry_run=True)
                preflight = command_runner(preflight_command, cwd=public_root)
                _record_command(run, "publication-preflight", preflight, preflight_command, key)
                if not preflight.get("ok"):
                    raise RuntimeError("publication preflight failed")

                current_tree = public_root / "public" / publication_root
                changed = not current_tree.is_dir() or not trees_unchanged(staged_tree, current_tree)
                fields["publication"] = {
                    "state": "changed" if changed else "unchanged",
                    "staged_digest": tree_digest(staged_tree),
                }
                if not args.dry_run and changed:
                    ensure_clean_repository(public_root)
                    public_sha = verify_remote_main(public_root)
                    fields["git_shas"]["public-before"] = public_sha
                    publish_command = batch_publication_command(manifest, public_root, dry_run=False)
                    fields["deployment"] = {"state": "attempted"}
                    publication = command_runner(publish_command, cwd=public_root)
                    _record_command(run, "publication", publication, publish_command, key)
                    if not publication.get("ok"):
                        fields["deployment"] = {"state": "unknown-after-publisher-failure"}
                        raise RuntimeError("publication failed")
                    fields["deployment"] = {"state": "published"}
                    push_command = ["git", "push", "origin", "main"]
                    pushed = command_runner(push_command, cwd=public_root)
                    _record_command(run, "push", pushed, push_command, key)
                    if not pushed.get("ok"):
                        raise RuntimeError("public-artifacts push failed")
                    fields["git_shas"]["public"] = verify_remote_main(public_root)
                elif args.dry_run:
                    fields["deployment"] = {"state": "suppressed"}
                    run.record_stage("publication", "dry-run", "", ok=True)
                else:
                    fields["deployment"] = {"state": "not-needed"}
                    run.record_stage("publication", "unchanged", "", ok=True)

                if not args.dry_run:
                    live = live_verifier(args.live_base_url, temporary_root, registry)
                    if not isinstance(live, dict) or live.get("ok") is not True:
                        raise RuntimeError("live verification failed")
                    fields["live_verification"] = live
                    run.record_stage("live-verification", _encode_result(live), "", ok=True)

            fields["ok"] = True
            fields["duration_seconds"] = round(time.monotonic() - started_clock, 6)
            run.complete(**fields)
            return 0, fields
        except Exception as exc:
            fields["error"] = str(exc)
            fields["duration_seconds"] = round(time.monotonic() - started_clock, 6)
            run.record_stage("failure", "", str(exc), ok=False, secrets=[key])
            run.complete(**fields)
            return 1, fields


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--public-artifacts-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--nexus-api-key-file", type=Path, default=DEFAULT_API_KEY_FILE)
    parser.add_argument("--live-base-url", default=DEFAULT_LIVE_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--override-anomaly", "--allow-anomaly", dest="override_anomaly", action="store_true")
    parser.add_argument("--override-reason")
    args = parser.parse_args(argv)
    if args.override_anomaly and (not args.override_reason or not args.override_reason.strip()):
        parser.error("--override-anomaly requires --override-reason")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        with RunLock(args.lock_file):
            code, summary = run_unattended(args)
            print(compact_summary(summary, secrets=()))
            if code:
                error = summary.get("error")
                if error:
                    print(f"ERROR: {error}", file=sys.stderr)
            return code
    except OverlapError:
        print("SKIP overlap")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
