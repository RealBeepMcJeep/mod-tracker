# Changelog

## 2026-09-11

- Added a stdlib-only bounded mapping-candidate CLI using normalized names, token overlap, Levenshtein title/author similarity, and description similarity; it skips mapped records, reports single-source games explicitly, and never auto-applies fuzzy matches.
- Hardened mapping-candidate filesystem access with descriptor-relative `O_NOFOLLOW` traversal, exclusive bounded temporary creation, same-directory atomic replacement, and adversarial symlink and directory-swap tests; the complete suite finished with 134 passing tests and an independent fail-closed review.
- Reviewed 99 bounded candidates across all games, manually accepted 91 reciprocal mod pairs and 27 reciprocal author-alias pairs, rejected 8 ambiguous pairs, and recorded the complete pass in `MAPPING_REVIEW.md`; post-mapping strict report counts are PEAK 220, R.E.P.O. 299, Retro Rewind 160, TCG Card Shop Simulator 178, and Valheim 715.
- Added the omitted exact-handle `nexus:azumatt` ↔ `thunderstore:azumatt` author mapping after report inspection exposed split 5,487-download Nexus and 6,773,808-download Thunderstore profiles; the combined 6,779,295-download profile now receives the intended Legendary tier.
- Kept the complete filter toolbar sticky on desktop while disabling sticky positioning, height capping, and internal toolbar scrolling at 520px and below so mobile report cards regain the full viewport while scrolling.
- Expanded author rarity to Common/Uncommon/Rare/Epic/Legendary using per-game nearest-rank 60th/70th/80th/90th-percentile cutoffs and white/green/blue/purple/orange styling.
- Added distinct known-mod counts and first-known-mod publication timestamps to author reputation artifacts, tooltips, ARIA labels, and strict report verification; explicitly mapped cross-provider records for one canonical mod count once.
- Added a separate `Data last updated at` report timestamp derived from the maximum parsed mod `updated_at`, with canonical metadata and fail-closed verification independent of the generation time.
- Added shared, registry-driven author rarity for all five games using each game’s own canonical-author pool and dynamic nearest-rank percentile cutoffs.
- Summed only raw lifetime downloads across an author’s stored mods; source identities remain separate unless joined by an explicit reciprocal Nexus/Thunderstore mapping.
- Added independent version-controlled `author-mappings.json` files and isolated `data/author-reputation.json` artifacts containing generation time, percentiles, raw cutoffs, canonical totals, known-mod counts, first-publication timestamps, and tiers.
- Rendered author names using the configured five-tier colors with concise legend, tooltip, ARIA, source identity, canonical identity, raw-total, known-mod-count, and first-publication metadata.
- Extended strict verification to recompute reputation and reject missing or altered artifacts, card identities, canonical IDs, totals, provenance, tiers, classes, tooltips, ARIA labels, and report freshness metadata.
- Added fail-closed mapping validation and regression coverage for malformed, missing, duplicate, conflicting, same-provider, nonreciprocal, and unsupported mappings plus pool boundaries, ties, invalid totals, escaping, grouped cards, and all-game isolation.
- Regenerated and strictly verified all five reports from saved data, published them in one preflighted batch, and confirmed every live route is byte-identical to its generated and committed artifact.
- Completed the required ordered rollout: published and verified Valheim first, published and verified the other four games, ran the morning all-game manual collection pass, then regenerated and republished the complete five-game cohort.
- Published the final mapped five-report batch in `public-artifacts` commit `91650cb57ad7167bc35692ea59c191f5705b1304` and Cloudflare Workers version `42cd439e-03fc-4e12-97ef-25447aed2c28`; all five exact routes returned HTTP 200 with byte identity and the unknown-route guard returned HTTP 404.
- Added a report-wide category dropdown derived from current card categories; category chips are native buttons that select the dropdown and compose with search, source, NSFW, and update-date filters.
- Made the complete filter toolbar sticky while scrolling on desktop, with an accessible region label; at 520px and below it returns to unrestricted normal page flow without a height cap or internal scrolling.
- Extended strict verification to reject altered category options, per-card category metadata, tag bindings, category JavaScript, or sticky-toolbar semantics and styling.
- Verified and pushed the completed tracker to the existing `AI-Goes-Fast/mod-tracker` repository, synchronized both project repositories, completed all 55 substantive goal checklist items, and deleted the finished `GOAL.md` in final tracker commit `db04bf223e194e5e8170694f05310679be59d5d0`.

## 2026-09-10

- Renamed the local project and private Gitea repository from `thunderstore-mod-tracker` to `mod-tracker`; preserved the dirty working tree and updated `origin` to `AI-Goes-Fast/mod-tracker` on `main`.
- Added the version-controlled five-game registry for Valheim, R.E.P.O., PEAK, Retro Rewind - Video Store Simulator, and TCG Card Shop Simulator, with independently validated Nexus/Thunderstore identifiers, output roots, pagination policy, labels, and publication paths.
- Kept Valheim's root storage, mappings, pinned mods, v1 filter, and `/reports/valheim-mod-tracker/` route unchanged; configured Retro Rewind as Nexus-only.
- Removed the Valheim hard-code from Thunderstore collection, made report source wording configuration-driven, and made configured page counts the defaults with optional CLI overrides.
- Added strict dual-report verification and the stdlib-only `scripts/manual-pass.py` orchestration workflow, including all-game collection, isolation, staging, one atomic five-site preflight/publication, and verified public-repository push.
- Added rollback-safe five-site replacement, requested-path-only Git commits, tracker/public branch guards, and exact local-versus-remote `main` hash verification.
- Expanded the deterministic unit suites to 51 tracker tests and 26 central-publisher tests, including path-traversal, injected rollback-failure, unrelated-staging, and remote-hash regressions; added `games.json` plus the manual-pass source to the fail-closed Git allowlist.
- Committed and pushed the shared five-game tracker and atomic central-publisher milestones to `main`, verifying exact local/remote commit equality and clean worktrees in both repositories.
- Added bounded retries for transient timeouts, connection/URL failures, HTTP 408/425/429, and HTTP 5xx responses after the first live all-game dry run exposed intermittent Thunderstore detail-read timeouts; permanent HTTP errors still fail immediately.
- Added shared Thunderstore terminal-page handling: after a nonempty page, a later listing HTTP 404 ends that ranking cleanly, removes stale pages, and records actual per-ranking counts and terminal status for strict manifest/snapshot verification; page-one 404s and unrelated permanent errors still fail.
- Enabled verified terminal short Nexus pages for PEAK and R.E.P.O. in addition to Retro Rewind, retaining stale-page cleanup and full-page requirements for Valheim and TCG Card Shop Simulator.
- Expanded the tracker suite to 60 passing tests, including terminal Thunderstore 404, short final page, stale cleanup, actual snapshot count, and PEAK/R.E.P.O. Nexus policy regressions.
- Completed successful dry and real five-game manual passes with strict verification and one complete publication preflight. The real pass recorded: PEAK 224 fresh/224 stored/224 cards, Thunderstore 160 appearances/152 distinct and Nexus 72/72; R.E.P.O. 297 fresh/299 stored/299 cards, Thunderstore 160/154 and Nexus 143/143; Retro Rewind 160 fresh/160 stored/160 cards, Thunderstore 0/0 and Nexus 160/160; TCG Card Shop Simulator 182 fresh/182 stored/182 cards, Thunderstore 44/22 and Nexus 160/160; Valheim 316 fresh/669 stored/628 cards, Thunderstore 160/156 and Nexus 160/160. Every collection and verification error count was zero.
- Published all five report destinations atomically in one commit and one Cloudflare deployment, pushed `public-artifacts/main` at `581cfc50e410b8ad5502d9ef652d4a9fdbffed41`, and deployed Workers version `6ea37ac3-b4c9-4aeb-8e4a-33f5a1a98d8f`.
- Independently read back every live report and confirmed HTTP 200, current game title and MST generation timestamp, exact card count, expected Nexus domain and Thunderstore community, no cross-game source leakage, no embedded images, and byte equality between generated, committed, and live artifacts; a deliberately nonexistent report route returned HTTP 404.
- Verified `https://api-router.nexusmods.com/graphql` as a deterministic anonymous Nexus listing source: an unauthenticated PEAK query returned the same ordered 72-record payload and complete tracker-selected field set as authenticated v2 GraphQL. The current pipeline retains authenticated collection for v1 detail enrichment and does not claim an automatic fallback implementation.
- Added deterministic per-game provider concurrency: Nexus and Thunderstore collection overlap in two stdlib worker threads while retaining independent provider pacing; results merge in fixed source order only after both succeed, and dual failures are aggregated without partially updating normalized data, snapshots, or reports.
- Expanded the tracker suite to 63 passing tests with explicit overlap, dual-failure aggregation, and no-partial-merge coverage.
- Completed a live five-game parallel dry pass in 711 seconds (11 minutes 51 seconds): every collection and strict verification succeeded with zero errors, the complete five-destination publication preflight passed, and `public-artifacts` remained unchanged at `581cfc50e410b8ad5502d9ef652d4a9fdbffed41`. Final fresh/stored/card counts were PEAK 224/224/224, R.E.P.O. 297/299/299, Retro Rewind 160/160/160, TCG Card Shop Simulator 182/182/182, and Valheim 316/673/632.
- Completed an explicit cross-source review of the latest 579-record dataset and added 21 manually verified Nexus Mods ↔ Thunderstore pairs, increasing canonical `Both` cards from 20 to 41.
- Added mappings for 14 Jere Kuusela packages plus Heightmap Unlimited JvL, Drop That, Spawn That, Visbending, Recipe Pinner, VNEI, and Grantapher's Valheim Plus fork.
- Regenerated the report as 538 canonical cards: 41 `Both`, 346 Thunderstore-only, and 151 Nexus-only; one NSFW card remains hidden by default.
- Kept mapping discovery outside routine manual scrape/report runs; perform another candidate review only when explicitly requested.
- Split each card's Uploaded and Updated timestamps into a compact two-row grid with muted, fixed-width labels and non-wrapping date values, preventing the mobile orphan/wrap shown in the report screenshot.
- Generalized Valheim's update-date checkbox into one shared registry-driven filter implementation and configured PEAK's `v2.0 filter` for August 10, 2026, R.E.P.O.'s `v0.4 filter` for May 7, 2026, and Valheim's existing `v1 filter` for September 8, 2026; every cutoff is inclusive at midnight UTC.

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
