# AGENTS.md — Valheim Mod Tracker

Deterministic stdlib-only collection and reporting for Valheim mods from Thunderstore and Nexus Mods.

## Scope

- Thunderstore community: `https://thunderstore.io/c/valheim/`
- Thunderstore rankings: `last-updated` and `most-downloaded`
- Thunderstore depth: first 4 pages per ranking, 20 cards per page
- Nexus listing: exactly two pages/80 items each sorted by `updatedAt` descending
- Cross-source matching is explicit/manual only; never infer that similarly named mods are identical.

## Layout

- `tracker.py` — collector, parser, merger, rate calculator, verifier, and HTML renderer
- `tests/` — stdlib `unittest` suite and sanitized inline fixtures
- `data/mods.json` — generated normalized flat store with observations
- `raw/` — generated source HTML and JSON evidence
- `snapshots/latest.json` — generated run manifest
- `report.html` — generated sortable combined report
- `TODO.md` — outstanding work only
- `CHANGELOG.md` — completed milestones grouped by date

## Rules

- Python standard library only.
- Follow RED → GREEN → REFACTOR for behavior changes.
- Save raw responses before parsing where practical and write canonical JSON atomically.
- Read the Nexus API key only at runtime from the configured external file.
- Never commit credentials, cookie headers/jars, generated datasets, raw captures, or temporary files.
- Optional Nexus page capture must report `captured`, `failed`, or `unavailable` honestly.
- Do not create cron or require an LLM at runtime.
- Commit only verified milestones. Do not push unless explicitly requested by the active task.

## Verification

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m py_compile tracker.py
python3 tracker.py collect --output-root /tmp/valheim-mod-tracker
python3 tracker.py verify --output-root /tmp/valheim-mod-tracker
```
