#!/usr/bin/env python3
"""Deterministic offline GitHub evidence review tool; never called by tracker runs."""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import tracker  # noqa: E402
from github_evidence import extract_github_evidence  # noqa: E402

_MAX_BATCH = 25
_RECORD_FIELDS = {"status", "repository_url", "reviewed_fingerprint", "evidence_urls", "review_method", "rationale"}
_COMPONENT = re.compile(r"^[^/\\]+$")


def atomic_write(path: Path, value) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def record_evidence(record: dict) -> dict:
    return extract_github_evidence({"summary": record.get("summary", ""), "description": record.get("description", "")})


def _records(root: Path):
    root = Path(root)
    path = root / "data/mods.json"
    current = root
    if current.is_symlink(): raise ValueError("symlink in accepted game path")
    for part in ("data", "mods.json"):
        current /= part
        if current.is_symlink(): raise ValueError("symlink in accepted project data path")
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"invalid {path}") from exc
    if not isinstance(data, list): raise ValueError(f"invalid {path}")
    for index, record in enumerate(data):
        if not isinstance(record, dict): raise ValueError(f"invalid record index {index}")
    return path, data


def _safe_capture(root: Path, namespace: str, package: str) -> Path:
    if not (_COMPONENT.fullmatch(namespace) and _COMPONENT.fullmatch(package)):
        raise ValueError("invalid Thunderstore source_id components")
    if namespace in {".", ".."} or package in {".", ".."} or package.endswith(".html"):
        raise ValueError("invalid Thunderstore source_id components")
    root = Path(root)
    capture = root / "raw/thunderstore/packages" / namespace / (package + ".html")
    try: relative = capture.relative_to(root)
    except ValueError as exc: raise ValueError("capture escapes game root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink(): raise ValueError("symlink in accepted capture path")
    return capture


def backfill_game(root: Path, *, dry_run=False) -> dict:
    path, records = _records(root)
    sources = {}
    for record in records:
        source = record.get("source")
        sources[source] = sources.get(source, 0) + 1
    result = {"scanned": len(records), "records_by_source": sources, "raw_considered": 0,
              "repaired": 0, "missing": 0, "unchanged": 0, "parse_failed": 0}
    updated = [dict(r) for r in records]
    for index, record in enumerate(records):
        if record.get("source") != "thunderstore": continue
        key = record.get("key")
        source_id = record.get("source_id")
        if source_id is None:
            source_id = key.removeprefix("thunderstore:") if isinstance(key, str) else ""
        if not isinstance(source_id, str) or key != f"thunderstore:{source_id}":
            raise ValueError(f"source_id does not match key at index {index}")
        parts = source_id.split("/")
        if len(parts) != 2: raise ValueError(f"invalid source_id at index {index}")
        capture = _safe_capture(Path(root), parts[0], parts[1])
        if not capture.is_file(): result["missing"] += 1; continue
        result["raw_considered"] += 1
        try: parsed = tracker.parse_thunderstore_detail(capture.read_text(encoding="utf-8"))
        except Exception: result["parse_failed"] += 1; continue
        description = parsed.get("readme_html") if isinstance(parsed, dict) else None
        if not isinstance(description, str) or not description:
            result["parse_failed"] += 1; continue
        if record.get("description", "") != description:
            updated[index]["description"] = description; result["repaired"] += 1
        else: result["unchanged"] += 1
    if not dry_run and updated != records: atomic_write(path, updated)
    result["dry_run"] = bool(dry_run)
    return result


def _config(project: Path) -> dict:
    try: value = json.loads((Path(project) / "games.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("invalid games.json") from exc
    if not isinstance(value, dict): raise ValueError("invalid games.json")
    return value


def _game_root(project: Path, games: dict, game: str) -> Path:
    if game not in games or not isinstance(games[game], dict): raise ValueError("unknown game")
    subdir = games[game].get("output_subdir", ".")
    if not isinstance(subdir, str) or not subdir or Path(subdir).is_absolute(): raise ValueError("invalid output_subdir")
    if any(part == ".." for part in Path(subdir).parts): raise ValueError("invalid output_subdir")
    root = Path(project) / subdir
    try: root.relative_to(Path(project))
    except ValueError as exc: raise ValueError("output_subdir escapes project") from exc
    cur = Path(project)
    for part in Path(subdir).parts:
        cur = cur / part
        if cur.is_symlink(): raise ValueError("symlink in game root")
    return root


def _export_items(game, records, reviewed):
    items = []
    for record in sorted(records, key=lambda r: str(r.get("key", ""))):
        key = record.get("key")
        if not isinstance(key, str): raise ValueError("record key must be a string")
        evidence = record_evidence(record)
        prior = reviewed.get(f"{game}:{key}", {})
        if evidence["candidates"] and (not isinstance(prior, dict) or prior.get("reviewed_fingerprint") != evidence["fingerprint"]):
            items.append({"game": game, "key": key, "fingerprint": evidence["fingerprint"], "candidates": evidence["candidates"]})
    return items


def export_game(game: str, root: Path, state: dict, output: Path, *, batch_size=25, dry_run=False) -> dict:
    if not isinstance(batch_size, int) or not 1 <= batch_size <= _MAX_BATCH: raise ValueError("batch size must be between 1 and 25")
    _, records = _records(root)
    items = _export_items(game, records, state.get("records", {}))
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    if not dry_run: atomic_write(Path(output), {"version": 1, "game": game, "batch_size": batch_size, "batches": batches})
    return {"candidates": len(items), "batches": len(batches), "dry_run": bool(dry_run)}


def export_project(project: Path, game: str, output: Path, *, batch_size=25, dry_run=False) -> dict:
    if not isinstance(batch_size, int) or not 1 <= batch_size <= _MAX_BATCH: raise ValueError("batch size must be between 1 and 25")
    project = Path(project); games = _config(project)
    state_path = project / "github-repositories.json"
    try: state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"version": 1, "records": {}}
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("invalid state") from exc
    found = _load_all_records(project)
    _validate_state(state, found)
    selected = sorted(games) if game == "all" else [game]
    all_items = []; scanned = 0; by_game = {}; by_source = {}; no_candidates = 0; already_reviewed = 0
    for name in selected:
        root = _game_root(project, games, name)
        _, records = _records(root)
        scanned += len(records); by_game[name] = len(records)
        for record in records:
            source = record.get("source")
            by_source[source] = by_source.get(source, 0) + 1
            evidence = record_evidence(record)
            prior = state["records"].get(f"{name}:{record.get('key')}", {})
            if not evidence["candidates"]: no_candidates += 1
            elif isinstance(prior, dict) and prior.get("reviewed_fingerprint") == evidence["fingerprint"]:
                already_reviewed += 1
        all_items.extend(_export_items(name, records, state["records"]))
    batches = [all_items[i:i + batch_size] for i in range(0, len(all_items), batch_size)]
    payload = {"version": 1, "batch_size": batch_size, "batches": batches}
    if game != "all": payload["game"] = game
    if not dry_run: atomic_write(output, payload)
    return {"scanned": scanned, "scanned_by_game": by_game, "scanned_by_source": by_source,
            "no_candidates": no_candidates, "already_reviewed": already_reviewed,
            "candidates": len(all_items), "batches": len(batches), "dry_run": bool(dry_run)}


def _canonical_root(url: str):
    ev = extract_github_evidence({"x": url})
    return ev["candidates"][0]["repository_url"] if len(ev["candidates"]) == 1 else None


def _load_all_records(project: Path):
    games = _config(project); found = {}
    for game in sorted(games):
        root = _game_root(project, games, game); _, records = _records(root)
        for r in records:
            key = r.get("key")
            if not isinstance(key, str): raise ValueError("record key must be a string")
            full = f"{game}:{key}"
            if full in found: raise ValueError("duplicate normalized record key")
            found[full] = (game, root, r)
    return found


def _validate_state(state, found=None):
    if (not isinstance(state, dict) or set(state) != {"version", "records"}
            or state.get("version") != 1 or not isinstance(state.get("records"), dict)):
        raise ValueError("invalid state schema")
    for key, item in state["records"].items():
        if not isinstance(key, str) or not isinstance(item, dict) or set(item) != _RECORD_FIELDS: raise ValueError("invalid state record")
        if found is not None and key not in found: raise ValueError("state record does not bind to a real record")
        if not isinstance(item["status"], str) or item["status"] not in {"approved", "no_repository"}: raise ValueError("invalid state status")
        if item["status"] == "approved" and (not isinstance(item["repository_url"], str) or _canonical_root(item["repository_url"]) != item["repository_url"]): raise ValueError("invalid approved state")
        if item["status"] == "no_repository" and item["repository_url"] is not None: raise ValueError("invalid no_repository state")
        if (not isinstance(item["reviewed_fingerprint"], str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["reviewed_fingerprint"])
                or not isinstance(item["evidence_urls"], list)
                or not item["evidence_urls"]
                or any(not isinstance(url, str) or not url.strip() for url in item["evidence_urls"])
                or len(set(item["evidence_urls"])) != len(item["evidence_urls"])
                or not isinstance(item["review_method"], str)
                or item["review_method"] not in {"manual", "llm-high-confidence"}
                or not isinstance(item["rationale"], str) or not item["rationale"].strip()):
            raise ValueError("invalid state record")
        if found is not None:
            current = record_evidence(found[key][2])
            if item["reviewed_fingerprint"] == current["fingerprint"]:
                exact_urls = {
                    occurrence["exact_url"]
                    for candidate in current["candidates"]
                    for occurrence in candidate["occurrences"]
                }
                candidate_roots = {
                    candidate["repository_url"] for candidate in current["candidates"]
                }
                if set(item["evidence_urls"]) != exact_urls:
                    raise ValueError("current state evidence does not match current record")
                if (item["status"] == "approved"
                        and item["repository_url"] not in candidate_roots):
                    raise ValueError("current approved state is not a current candidate")


def _decision_validation(decision, found):
    if not isinstance(decision, dict) or set(decision) != {"game", "key", "status", "repository_url", "reviewed_fingerprint", "confidence", "evidence_urls", "review_method", "rationale"} and set(decision) != {"game", "key", "status", "repository_url", "reviewed_fingerprint", "confidence", "evidence_urls", "review_method", "rationale", "ambiguous"}:
        raise ValueError("invalid decision schema")
    game, key = decision["game"], decision["key"]; full = f"{game}:{key}"
    if not isinstance(game, str) or not isinstance(key, str) or full not in found: raise ValueError("unknown or cross-game record key")
    current = record_evidence(found[full][2])
    if decision["reviewed_fingerprint"] != current["fingerprint"]: raise ValueError("stale fingerprint")
    if not isinstance(decision["status"], str) or decision["status"] not in {"approved", "no_repository"} or not isinstance(decision["rationale"], str) or not decision["rationale"].strip(): raise ValueError("invalid decision")
    if not isinstance(decision["confidence"], str) or decision["confidence"] not in {"low", "medium", "high"}: raise ValueError("invalid confidence")
    if not isinstance(decision["review_method"], str) or decision["review_method"] not in {"manual", "llm-high-confidence"}: raise ValueError("invalid review method")
    if "ambiguous" in decision and not isinstance(decision["ambiguous"], bool): raise ValueError("invalid ambiguous flag")
    if (not isinstance(decision["evidence_urls"], list)
            or not decision["evidence_urls"]
            or any(not isinstance(url, str) or not url.strip()
                   for url in decision["evidence_urls"])):
        raise ValueError("evidence URLs required")
    exact = {o["exact_url"] for c in current["candidates"] for o in c["occurrences"]}
    if (len(set(decision["evidence_urls"])) != len(decision["evidence_urls"])
            or any(u not in exact for u in decision["evidence_urls"])
            or (decision["confidence"] == "high" and not decision.get("ambiguous", False)
                and set(decision["evidence_urls"]) != exact)):
        raise ValueError("evidence URLs are not current evidence")
    if decision["status"] == "approved":
        root = decision["repository_url"]
        candidates = {c["repository_url"] for c in current["candidates"]}
        if not isinstance(root, str) or _canonical_root(root) != root or root not in candidates: raise ValueError("repository is not a current canonical candidate")
    elif decision["repository_url"] is not None: raise ValueError("no_repository must have null repository_url")
    return current


def _queue_text(entries):
    lines = ["# Pending GitHub Review", "", "Deterministic queue generated by `scripts/github-review.py`.", ""]
    if not entries: lines.append("No open GitHub review items.")
    for entry in sorted(entries, key=lambda e: e[0]):
        sid, key, reason, ev, prior = entry
        lines += [f"## {sid}", f"- key: `{key}`", f"- reason: {reason}", f"- candidates: `{json.dumps(ev['candidates'], sort_keys=True)}`"]
        if prior: lines += [f"- prior: `{json.dumps(prior, sort_keys=True)}`"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def reconcile_pending(project: Path, state: dict, found: dict, extra=None, *, dry_run=False) -> dict:
    entries = []
    extras = {f"{d['game']}:{d['key']}": d for d in (extra or [])}
    queued_stale = 0
    for full, (_, _, record) in sorted(found.items()):
        ev = record_evidence(record); prior = state["records"].get(full, {})
        stale = isinstance(prior, dict) and prior.get("status") in {"approved", "no_repository"} and prior.get("reviewed_fingerprint") != ev["fingerprint"]
        if full in extras:
            d = extras[full]
            reason = "ambiguous or lower-confidence decision"
            sid = hashlib.sha256(full.encode()).hexdigest()[:16]
            entries.append((sid, full, reason, ev, None))
            continue
        if ev["candidates"] and (stale or not isinstance(prior, dict) or not prior.get("status")):
            reason = "stale reviewed decision" if stale else "review required"
            sid = hashlib.sha256(full.encode()).hexdigest()[:16]
            entries.append((sid, full, reason, ev, prior if stale else None))
            queued_stale += int(stale)
    groups = {}
    for full, (game, _, r) in found.items():
        group = r.get("canonical_group_id"); prior = state["records"].get(full, {})
        if group and isinstance(prior, dict) and prior.get("status") == "approved": groups.setdefault((game, group), set()).add(prior.get("repository_url"))
    for (game, group), roots in groups.items():
        if len(roots) > 1:
            sid = hashlib.sha256((f"conflict:{game}:{group}").encode()).hexdigest()[:16]
            entries.append((sid, f"{game}:group:{group}", "mapped approved repository conflict", {"candidates": sorted(roots)}, None))
    if not dry_run:
        atomic_write(Path(project) / "PENDING_GITHUB_REVIEW.md", _queue_text(entries))
    return {"queued_stale": queued_stale,
            "queued_ambiguous": len(extras),
            "queued_conflict": sum(1 for entry in entries if entry[2] == "mapped approved repository conflict")}


def apply_decisions(project: Path, payload: dict, *, state_path=None, dry_run=False) -> dict:
    project = Path(project); found = _load_all_records(project)
    decisions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(decisions, list): raise ValueError("decisions must be a list")
    target = Path(state_path or project / "github-repositories.json")
    try: old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"version": 1, "records": {}}
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("invalid state") from exc
    _validate_state(old, found); new = json.loads(json.dumps(old)); seen = set(); accepted = []; queued = []
    for d in decisions:
        full = f"{d.get('game')}:{d.get('key')}"
        if full in seen: raise ValueError("duplicate decision")
        seen.add(full); ev = _decision_validation(d, found)
        if d.get("confidence") != "high" or d.get("ambiguous", False):
            queued.append(d); continue
        accepted.append(d)
        new["records"][full] = {"status": d["status"], "repository_url": d["repository_url"], "reviewed_fingerprint": d["reviewed_fingerprint"], "evidence_urls": sorted(d["evidence_urls"]), "review_method": d["review_method"], "rationale": d["rationale"]}
    counts = {"approved": sum(d["status"] == "approved" for d in accepted), "no_repository": sum(d["status"] == "no_repository" for d in accepted), "rejected": 0, "dry_run": bool(dry_run)}
    if not dry_run:
        queue_counts = reconcile_pending(project, new, found, queued)
        counts.update(queue_counts)
        if accepted:
            atomic_write(target, new)
    else:
        counts.update(reconcile_pending(project, new, found, queued, dry_run=True))
    counts["queued_total"] = counts["queued_ambiguous"] + counts["queued_stale"] + counts["queued_conflict"]
    return counts


def main(argv=None):
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest="op", required=True)
    for op in ("backfill", "export", "apply"):
        q = sub.add_parser(op); q.add_argument("--game", default="all"); q.add_argument("--project-root", type=Path, default=PROJECT_ROOT); q.add_argument("--dry-run", action="store_true")
    sub.choices["export"].add_argument("--output", type=Path, required=True); sub.choices["export"].add_argument("--batch-size", type=int, default=25)
    sub.choices["apply"].add_argument("decision_file", type=Path)
    args = p.parse_args(argv); project = args.project_root
    if args.op == "backfill":
        configs = _config(project)
        if args.game != "all" and args.game not in configs:
            raise ValueError("unknown game")
        games = configs if args.game == "all" else {args.game: configs[args.game]}; out = {"games": {}}
        for name, c in sorted(games.items()): out["games"][name] = backfill_game(_game_root(project, configs, name), dry_run=args.dry_run)
    elif args.op == "export": out = export_project(project, args.game, args.output, batch_size=args.batch_size, dry_run=args.dry_run)
    else: out = apply_decisions(project, json.loads(args.decision_file.read_text()), dry_run=args.dry_run)
    print(json.dumps(out, sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
