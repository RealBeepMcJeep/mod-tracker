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
- `scripts/manual-pass.py` — sequential all-game collection/generation orchestration with per-game provider concurrency, verification, staging, atomic publish, push, and remote verification; it is the reusable base for the scheduled mapping-free full pass
- `tests/` — stdlib `unittest` suite and sanitized inline fixtures
- Valheim generated state remains at the project root for compatibility.
- Other games store generated state under `games/<game-key>/`.
- Every game root has independent `data/`, `raw/`, `snapshots/`, reports, and verification artifacts.
- Every game root has an independent version-controlled `author-mappings.json` and generated `data/author-reputation.json`.
- `TODO.md` — outstanding work only
- `CHANGELOG.md` — completed milestones grouped by date

## Run vocabulary

- **Data pass** — scrape the latest configured mod listings, fetch details for new or changed mods not already covered by valid saved evidence, and persist raw captures, normalized records, observations, snapshots, and data-verification results. It does not discover mappings, generate a publication release, or publish reports.
- **Mapping pass** — deferred optional manual work. Run the bounded deterministic Nexus↔Thunderstore candidate generator only when explicitly requested, review mod and author identity separately, and apply only evidenced reciprocal mappings. It is never part of scheduled automation.
- **Generation pass** — generate every requested report from the current saved data and mappings, strictly verify the local artifacts, stage and dry-run the complete static-site publication cohort, publish it, push `public-artifacts`, and verify the deployment at its intended routes. It does not scrape provider data or discover mappings.
- **Verification pass** — perform a read-only audit of saved data, mappings, generated reports, repository synchronization, and requested live routes. It may regenerate nothing, scrape nothing, alter no mapping, publish nothing, and commit nothing.
- **Full pass** — run a data pass, generation pass, and verification pass, in that order, using existing mappings as read-only configuration. Stop on any failed stage and never publish partial or unverified results. Scheduled full passes never discover or alter mappings.
- **Dry run** — a modifier, not a run type. It must not publish, deploy, or push changes to `public-artifacts`, but it is not a no-write simulation: a data or full pass still persists newly collected evidence and normalized state, and a generation or full pass still generates and verifies local reports. Mapping changes remain manual and require explicit acceptance; dry-run mode never auto-applies them.

## Rules

- Python standard library only.
- Follow RED → GREEN → REFACTOR for behavior changes.
- Save raw responses before parsing where practical and write canonical JSON atomically.
- Run Nexus and Thunderstore concurrently only within the same dual-source game, preserve each provider's own pacing, aggregate both failures deterministically, and do not merge or render unless both succeed.
- Remove stale listing pages beyond the actual fetched scope and keep Thunderstore listing-manifest counts synchronized with `snapshots/latest.json`.
- Read the Nexus API key only at runtime from an external file; default: `~/.config/nexus-mods/api-key`.
- Never commit credentials, cookie headers/jars, generated datasets, raw captures, or temporary files.
- Optional Nexus page capture must report `captured`, `failed`, or `unavailable` honestly.
- Do not require an LLM at runtime. Create and enable the six-hour cron job only after the mapping-free automated path passes its failure, anomaly, no-change, overlap, publication, and real-run acceptance gates.
- Keep every game's generated state isolated; preserve Valheim's legacy local output root. Publish the complete cohort under `/mod-tracking/`, with its landing page at `/mod-tracking/` and each game at `/mod-tracking/<game-key>/`; legacy public assets remain untouched.
- Implement optional update-date controls only through the shared `update_filter` registry object, renderer, card metadata, JavaScript predicate, and verifier; labels and inclusive UTC cutoffs are configuration, never game-specific branches.
- Implement author rarity only through shared `author_tiers` registry data: sum raw lifetime downloads per source-scoped/canonical author, merge only reciprocal cross-provider aliases or explicit reciprocal per-mod `credited_author` attribution, calculate nearest-rank 60/70/80/90 cutoffs per game, render the canonical creator in white/green/blue/purple/orange with combined metrics, known-mod count, and first-publication provenance, and independently recompute the visible name and metadata during verification. Use per-mod attribution for shared port-publisher namespaces; never globally alias one publisher to unrelated original creators.
- Keep category filtering shared and source-derived: normalized card metadata and dropdown options must match grouped report categories, category chips must be native buttons, all filters must compose in one predicate, and the verifier must reject altered metadata or interaction code. Search every grouped title, displayed/credited creator, provider author, retained short description, and category; rank title matches before author matches and description/category matches, using the selected sort only as the within-tier tiebreaker and preserving it unchanged for an empty query. Paginate that complete filtered set client-side at exactly 100 cards per page in the same HTML file, count pinned cards toward the limit, reset page state after filter/sort/search changes, and bind the controls, search indexes, relevance program, and pagination script in strict verification. Keep the toolbar outside the title header so desktop viewport-sticky positioning is not parent-bounded; disable sticky positioning at 520px and below so mobile uses normal document flow.
- Data, generation, verification, and full passes do not discover or alter cross-site mappings. Mapping work is deferred and manual-only.
- Use `scripts/mapping_candidates.py` only for explicit mapping passes. Keep output bounded and deterministic, compare only Nexus↔Thunderstore pairs, expose component scores and reasons, and never let similarity output write authoritative mod or author mappings automatically.
- Publish the configured `/mod-tracking/` tree as one preflighted root batch: replace with rollback protection, commit once, deploy once, and verify the landing page plus all five game URLs.
- Commit only verified milestones. Push when explicitly requested by the active task.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/manual-pass.py
python3 -m json.tool games.json >/dev/null
git diff --check
python3 tracker.py verify --game all --output-root .
```
