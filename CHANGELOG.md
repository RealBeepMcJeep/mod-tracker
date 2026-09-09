# Changelog

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
