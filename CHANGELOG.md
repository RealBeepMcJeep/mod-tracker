# Changelog

## 2026-09-10

- Renamed the local project and private Gitea repository from `thunderstore-mod-tracker` to `mod-tracker`; preserved the dirty working tree and updated `origin` to `AI-Goes-Fast/mod-tracker` on `main`.
- Added the version-controlled five-game registry for Valheim, R.E.P.O., PEAK, Retro Rewind - Video Store Simulator, and TCG Card Shop Simulator, with independently validated Nexus/Thunderstore identifiers, output roots, pagination policy, labels, and publication paths.
- Kept Valheim's root storage, mappings, pinned mods, v1 filter, and `/reports/valheim-mod-tracker/` route unchanged; configured Retro Rewind as Nexus-only.
- Removed the Valheim hard-code from Thunderstore collection, made report source wording configuration-driven, and made configured page counts the defaults with optional CLI overrides.
- Added strict dual-report verification and the stdlib-only `scripts/manual-pass.py` orchestration workflow, including all-game collection, isolation, staging, one atomic five-site preflight/publication, and verified public-repository push.
- Added rollback-safe five-site replacement, requested-path-only Git commits, tracker/public branch guards, and exact local-versus-remote `main` hash verification.
- Expanded the deterministic unit suites to 51 tracker tests and 26 central-publisher tests, including path-traversal, injected rollback-failure, unrelated-staging, and remote-hash regressions; added `games.json` plus the manual-pass source to the fail-closed Git allowlist.
- Completed an explicit cross-source review of the latest 579-record dataset and added 21 manually verified Nexus Mods ↔ Thunderstore pairs, increasing canonical `Both` cards from 20 to 41.
- Added mappings for 14 Jere Kuusela packages plus Heightmap Unlimited JvL, Drop That, Spawn That, Visbending, Recipe Pinner, VNEI, and Grantapher's Valheim Plus fork.
- Regenerated the report as 538 canonical cards: 41 `Both`, 346 Thunderstore-only, and 151 Nexus-only; one NSFW card remains hidden by default.
- Kept mapping discovery outside routine manual scrape/report runs; perform another candidate review only when explicitly requested.

## 2026-09-09

- Completed a fresh dual-source scrape: 313 current records, 376 retained historical source records, and 356 canonical report cards.
- Rendered the report generation timestamp in human-readable Arizona MST instead of UTC ISO format.
- Added four manually verified cross-source mappings for Custom Chest Name, Marsarah Tweaks, Races of Valheim, and Jotunn, bringing the report to 20 `Both` cards.
- Added thousands separators to human-facing downloads, endorsements/likes, and rate metrics while preserving raw numeric HTML sort attributes.
- Changed mapped-card total downloads, lifetime downloads/day, and observed current-version downloads/day to sum confirmed Nexus Mods and Thunderstore values instead of taking the larger source value.
- Changed lifetime downloads/day to divide by age rounded up to the nearest full day, preventing sub-day hourly extrapolation; observed current-version rates still use their exact observation interval.
- Shortened the report status line to the generation timestamp and renamed the date-cutoff checkbox to `v1 filter`, with its cutoff explanation moved to a tooltip.
- Prevented mobile card overflow by allowing card/body/metric grid tracks to shrink, wrapping long unbroken descriptions, and wrapping tag and badge rows within the card.
- Fixed mobile NSFW/v1 toggle alignment and made card-title links inherit the report's white text color in both normal and visited states.

## Initial build
- Added explicit curated cross-source mappings in `mappings.json` for 16 confirmed pairs; mapped pairs render as one `Both` card while unmapped records remain separate.
- Added prominent source badges, labeled per-source metrics, composable source/search/sort/NSFW controls, static NSFW hiding, and the hotlinked `report-hotlinked.html` artifact.
- Current report presentation dataset contains 314 source records and 298 canonical cards; one adult source record/group is hidden initially.
- Completed and verified the live approved-scope dataset: 160 Thunderstore ranking appearances (154 distinct packages), 160 distinct Nexus listing IDs, and 314 normalized records.
- Corrected the deterministic collection scope to 4 Thunderstore pages per ranking and exactly two 80-item Nexus GraphQL pages; added cross-page distinct-ID reporting and stale listing cleanup.
- Added the manual `collect`, `report`, and `verify` CLI pipeline with atomic flat-file persistence and resumable detail caches.
- Added Nexus GraphQL collection, v1 detail caching, runtime-only API-key authentication, and optional authenticated HTML capture from a caller-supplied cookie file.
- Added Thunderstore collection for both required rankings, package metric/detail capture, ranking appearances, and canonical source deduplication.
- Added normalized cross-source records, idempotent observations, lifetime download rates, and observed current-version download rates.
- Added a single searchable, source-filterable, sortable HTML report with fixed pinned cards and optional embedded thumbnails.
- Added stdlib `unittest` coverage for parsing, normalization, rates, collectors, persistence, reporting, verification, and CLI defaults.
- Confirmed the Valheim package listing, `last-updated` and `most-downloaded` ranking scope, 20-card page size, and requested card metadata.
- Initialized the stdlib-only flat-file project structure and documentation.
