# AGENTS.md — Mod Tracker

Deterministic stdlib-only collection and reporting for five games across Thunderstore and Nexus Mods.

## Scope

- Registry: `games.json` is the authoritative five-game source/page/output/publication configuration.
- Games: Valheim, R.E.P.O., PEAK, Retro Rewind - Video Store Simulator, and TCG Card Shop Simulator.
- Retro Rewind is Nexus-only; the other four use Nexus Mods and Thunderstore.
- Thunderstore rankings: `last-updated` and `most-downloaded`, requesting up to each game's configured page count; a later HTTP 404 after a nonempty page terminates that ranking and the actual count is persisted and verified.
- Nexus listings: `updatedAt` descending, using each game's configured maximum and short-page policy; PEAK, R.E.P.O., and Retro Rewind permit terminal short pages.
- Cross-source matching is explicit/manual only; never infer that similarly named mods are identical.

## Layout

- `tracker.py` — shared collector, parser, merger, rate calculator, verifier, and HTML renderer
- `games.json` — version-controlled game/source/output/publication registry
- `scripts/manual-pass.py` — sequential all-game orchestration with per-game provider concurrency, verification, staging, atomic publish, push, and remote verification
- `tests/` — stdlib `unittest` suite and sanitized inline fixtures
- Valheim generated state remains at the project root for compatibility.
- Other games store generated state under `games/<game-key>/`.
- Every game root has independent `data/`, `raw/`, `snapshots/`, reports, and verification artifacts.
- Every game root has an independent version-controlled `author-mappings.json` and generated `data/author-reputation.json`.
- `TODO.md` — outstanding work only
- `CHANGELOG.md` — completed milestones grouped by date

## Rules

- Python standard library only.
- Follow RED → GREEN → REFACTOR for behavior changes.
- Save raw responses before parsing where practical and write canonical JSON atomically.
- Run Nexus and Thunderstore concurrently only within the same dual-source game, preserve each provider's own pacing, aggregate both failures deterministically, and do not merge or render unless both succeed.
- Remove stale listing pages beyond the actual fetched scope and keep Thunderstore listing-manifest counts synchronized with `snapshots/latest.json`.
- Read the Nexus API key only at runtime from an external file; default: `~/.config/nexus-mods/api-key`.
- Never commit credentials, cookie headers/jars, generated datasets, raw captures, or temporary files.
- Optional Nexus page capture must report `captured`, `failed`, or `unavailable` honestly.
- Do not create cron or require an LLM at runtime.
- Keep every game's generated state isolated; preserve Valheim's legacy root layout and publication route.
- Implement optional update-date controls only through the shared `update_filter` registry object, renderer, card metadata, JavaScript predicate, and verifier; labels and inclusive UTC cutoffs are configuration, never game-specific branches.
- Implement author rarity only through shared `author_tiers` registry data: sum raw lifetime downloads per source-scoped/canonical author, merge only reciprocal cross-provider aliases, calculate nearest-rank 60/70/80/90 cutoffs per game, render white/green/blue/purple/orange author metadata with known-mod count and first-publication provenance, and independently recompute it during verification.
- Keep category filtering shared and source-derived: normalized card metadata and dropdown options must match grouped report categories, category chips must be native buttons, all filters must compose in one predicate, and the verifier must reject altered metadata or interaction code. Keep the toolbar outside the title header so desktop viewport-sticky positioning is not parent-bounded; disable sticky positioning at 520px and below so mobile uses normal document flow.
- Routine manual passes do not discover or alter cross-site mappings.
- Publish all configured sites as one preflighted batch: replace with rollback protection, commit once, deploy once, verify every URL.
- Commit only verified milestones. Push when explicitly requested by the active task.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/manual-pass.py
python3 -m json.tool games.json >/dev/null
git diff --check
python3 tracker.py verify --game all --output-root .
```
