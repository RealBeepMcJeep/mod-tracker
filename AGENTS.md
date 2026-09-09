# AGENTS.md — Thunderstore Mod Tracker

Tracks ranked Thunderstore package cards as a flat-file dataset.

## Scope

- Community: Valheim (`https://thunderstore.io/c/valheim/`)
- Rankings: `last-updated` and `most-downloaded`
- Depth: first 10 pages per ranking, 20 cards per page
- Canonical package records are deduplicated by package URL.
- Each ranking appearance retains sort mode, page, and rank.

## Layout

- `tracker.py` — stdlib-only collector, parser, merger, and renderer
- `tests/` — stdlib `unittest` suite and sanitized HTML fixtures
- `data/packages/` — one canonical JSON record per package
- `raw/<snapshot>/` — source listing HTML for each ranking/page
- `snapshots/` — collection manifests and change summaries
- `INDEX.md` — generated human-readable ranked views
- `todo.md` — build checklist and dated changelog

## Rules

- Python standard library only.
- Save raw HTML before parsing; raw responses are source evidence.
- Write JSON and manifests atomically.
- Preserve packages missing from later snapshots with `deleted: true`; never silently erase them.
- Treat card-relative update text as observed text, not an exact timestamp.
- Commit only verified milestones. Never commit secrets or temporary files.

## Verification

```bash
python3 -m unittest discover -s tests -t . -v
python3 tracker.py collect --pages 1 --output-root /tmp/thunderstore-probe
python3 tracker.py verify --output-root /tmp/thunderstore-probe --expected-pages 1
python3 -m py_compile tracker.py
```
