#!/usr/bin/env python3
"""Generate bounded cross-provider mapping candidates without applying them."""

import argparse
import bisect
import html
import json
import os
from pathlib import Path
import re
import secrets


MAX_LIMIT = 20


def levenshtein_similarity(left: str, right: str) -> float:
    """Return normalized edit similarity in the inclusive range 0..1."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, 1):
        current = [row]
        for column, right_char in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def rank_candidates(
    mods: list[dict], mappings: dict, limit: int = 20, min_score: float = 0.45
) -> list[dict]:
    """Return at most ``MAX_LIMIT`` deterministic candidates without mutation."""
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must not exceed {MAX_LIMIT}")
    if limit <= 0:
        return []

    def words(value: object) -> list[str]:
        text = html.unescape(str(value or ""))
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        text = re.sub(r"<[^>]*>|\[[^]]*]", " ", text)
        return re.findall(r"[a-z0-9]+", text.casefold())

    def compact(value: object) -> str:
        return "".join(words(value))

    def token_similarity(left: set[str], right: set[str]) -> float:
        return len(left & right) / len(left | right) if left and right else 0.0

    def prepared(mod: dict) -> dict:
        description = f"{mod.get('summary') or ''} {mod.get('description') or ''}"
        return {
            "mod": mod,
            "title_compact": compact(mod.get("title")),
            "title_tokens": set(words(mod.get("title"))),
            "description_tokens": set(words(description)),
            "author_compact": compact(mod.get("author")),
        }

    eligible = sorted(
        (
            mod
            for mod in mods
            if isinstance(mod, dict)
            and isinstance(mod.get("key"), str)
            and mod["key"] not in mappings
            and not mod.get("canonical_group_id")
        ),
        key=lambda mod: mod["key"],
    )
    nexus = [
        prepared(mod)
        for mod in eligible
        if mod.get("source") == "nexus" and compact(mod.get("title"))
    ]
    thunderstore = [
        prepared(mod)
        for mod in eligible
        if mod.get("source") == "thunderstore" and compact(mod.get("title"))
    ]
    candidates = []
    for left in nexus:
        for right in thunderstore:
            components = {
                "title_levenshtein": levenshtein_similarity(
                    left["title_compact"], right["title_compact"]
                ),
                "title_tokens": token_similarity(
                    left["title_tokens"], right["title_tokens"]
                ),
                "description_tokens": token_similarity(
                    left["description_tokens"], right["description_tokens"]
                ),
                "author_levenshtein": levenshtein_similarity(
                    left["author_compact"], right["author_compact"]
                ),
            }
            score = (
                components["title_levenshtein"] * 0.40
                + components["title_tokens"] * 0.20
                + components["description_tokens"] * 0.25
                + components["author_levenshtein"] * 0.15
            )
            if score < min_score:
                continue
            reasons = []
            if components["title_levenshtein"] >= 0.95:
                reasons.append("near-exact normalized title")
            elif components["title_levenshtein"] >= 0.75:
                reasons.append("similar normalized title")
            if components["description_tokens"] >= 0.60:
                reasons.append("strong description token overlap")
            elif components["description_tokens"] >= 0.30:
                reasons.append("moderate description token overlap")
            if components["author_levenshtein"] >= 0.90:
                reasons.append("near-exact normalized author")
            left_mod = left["mod"]
            right_mod = right["mod"]
            candidate = {
                    "score": round(score, 6),
                    "components": {
                        key: round(value, 6) for key, value in components.items()
                    },
                    "reasons": reasons or ["combined weak signals"],
                    "nexus_key": left_mod["key"],
                    "thunderstore_key": right_mod["key"],
                    "nexus": {
                        "title": left_mod.get("title") or "",
                        "author": left_mod.get("author") or "",
                        "summary": str(left_mod.get("summary") or "")[:500],
                        "url": left_mod.get("canonical_url") or "",
                    },
                    "thunderstore": {
                        "title": right_mod.get("title") or "",
                        "author": right_mod.get("author") or "",
                        "summary": str(right_mod.get("summary") or "")[:500],
                        "url": right_mod.get("canonical_url") or "",
                    },
            }
            sort_key = (
                -candidate["score"],
                candidate["nexus_key"],
                candidate["thunderstore_key"],
            )
            bisect.insort_right(candidates, (sort_key, candidate))
            if len(candidates) > limit:
                candidates.pop()
    return [candidate for _, candidate in candidates]


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_directory(path: Path, *, create: bool = False) -> int:
    """Open an absolute directory without following any path-component symlink."""
    absolute = Path(os.path.abspath(path))
    descriptor = os.open(absolute.anchor, _DIRECTORY_FLAGS)
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, dir_fd=descriptor)
                child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _relative_parts(path: Path, label: str) -> tuple[str, ...]:
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{label} escapes project root")
    return tuple(part for part in path.parts if part not in ("", "."))


def _open_relative_directory(root_descriptor: int, path: Path, label: str) -> int:
    descriptor = os.dup(root_descriptor)
    try:
        for component in _relative_parts(path, label):
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _load_json_at(root_descriptor: int, path: Path, default, label: str):
    parts = _relative_parts(path, label)
    if not parts:
        raise ValueError(f"{label} must name a file")
    parent = _open_relative_directory(root_descriptor, Path(*parts[:-1]), label)
    try:
        try:
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
            )
        except FileNotFoundError:
            return default
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "r", encoding="utf-8") as source:
        return json.load(source)


def _load_registry(path: Path) -> tuple[dict, int]:
    absolute = Path(os.path.abspath(path))
    parent = _open_directory(absolute.parent)
    try:
        descriptor = os.open(
            absolute.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
        )
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            registry = json.load(source)
        return registry, parent
    except BaseException:
        os.close(parent)
        raise


def _atomic_write_text(path: Path, payload: str) -> None:
    """Atomically replace a file relative to one held, no-follow directory FD."""
    absolute = Path(os.path.abspath(path))
    parent = _open_directory(absolute.parent, create=True)
    temporary_name = None
    try:
        for _ in range(100):
            candidate = f".{absolute.name}.tmp-{secrets.token_hex(12)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        else:
            raise FileExistsError("could not create exclusive output staging file")
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(
            temporary_name,
            absolute.name,
            src_dir_fd=parent,
            dst_dir_fd=parent,
        )
        temporary_name = None
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)


def build_report(
    registry_path: Path, selected_game: str, limit: int, min_score: float
) -> dict:
    if limit > MAX_LIMIT:
        raise ValueError(f"limit must not exceed {MAX_LIMIT}")
    registry, project_descriptor = _load_registry(registry_path)
    try:
        if not isinstance(registry, dict) or not registry:
            raise ValueError("registry must be a nonempty JSON object")
        if selected_game != "all" and selected_game not in registry:
            raise ValueError(f"unknown game: {selected_game}")
        games = sorted(registry) if selected_game == "all" else [selected_game]
        report = {"limit_per_game": limit, "min_score": min_score, "games": {}}
        for game in games:
            config = registry[game]
            if not isinstance(config, dict):
                raise ValueError(f"{game} registry entry must be an object")
            relative = Path(config.get("output_subdir", ""))
            try:
                game_descriptor = _open_relative_directory(
                    project_descriptor, relative, f"{game} output_subdir"
                )
                try:
                    mods = _load_json_at(
                        game_descriptor,
                        Path("data/mods.json"),
                        [],
                        f"{game} mods.json",
                    )
                    mappings = _load_json_at(
                        game_descriptor,
                        Path("mappings.json"),
                        {},
                        f"{game} mappings.json",
                    )
                finally:
                    os.close(game_descriptor)
            except OSError as exc:
                raise ValueError(
                    f"{game} input path escapes project root or contains symlinks"
                ) from exc
            if not isinstance(mods, list) or not isinstance(mappings, dict):
                raise ValueError(f"{game} has invalid mods or mappings JSON")
            source_counts = {
                source: sum(
                    mod.get("source") == source for mod in mods if isinstance(mod, dict)
                )
                for source in ("nexus", "thunderstore")
            }
            configured_sources = set(config.get("sources", []))
            if not {"nexus", "thunderstore"}.issubset(configured_sources):
                status = "single-source"
                candidates = []
            elif not all(source_counts.values()):
                status = "no-cross-provider-data"
                candidates = []
            else:
                candidates = rank_candidates(mods, mappings, limit, min_score)
                status = "candidates" if candidates else "no-candidates"
            report["games"][game] = {
                "status": status,
                "source_counts": source_counts,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        return report
    finally:
        os.close(project_descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate bounded Nexus/Thunderstore mapping candidates"
    )
    parser.add_argument("--registry", type=Path, default=Path("games.json"))
    parser.add_argument("--game", default="all")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-score", type=float, default=0.45)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.limit > MAX_LIMIT:
        parser.error(f"--limit must not exceed {MAX_LIMIT}")
    if not 0 <= args.min_score <= 1:
        parser.error("--min-score must be between 0 and 1")
    try:
        report = build_report(args.registry, args.game, args.limit, args.min_score)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(payload, end="")
    else:
        try:
            _atomic_write_text(args.output, payload)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
