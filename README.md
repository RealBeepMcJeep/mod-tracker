# Mod Tracker

A deterministic, standard-library-only Python pipeline that collects mods from Thunderstore and Nexus Mods, keeps each game’s evidence and history isolated, verifies the artifacts, and publishes one sortable dark-mode HTML report per game.

[Data-flow and field-lineage diagram](DATA_FLOW.html)

## Games and sources

| Game | Nexus domain | Thunderstore community | Local output | Published report |
| --- | --- | --- | --- | --- |
| Valheim | `valheim` | `valheim` | project root (preserved legacy layout) | `/reports/valheim-mod-tracker/` |
| R.E.P.O. | `repo` | `repo` | `games/repo/` | `/reports/repo-mod-tracker/` |
| PEAK | `peak` | `peak` | `games/peak/` | `/reports/peak-mod-tracker/` |
| Retro Rewind - Video Store Simulator | `retrorewindvideostoresimulator` | unavailable; Nexus-only | `games/retro-rewind/` | `/reports/retro-rewind-mod-tracker/` |
| TCG Card Shop Simulator | `tcgcardshopsimulator` | `tcg-card-shop-simulator` | `games/tcg-card-shop-simulator/` | `/reports/tcg-card-shop-simulator-mod-tracker/` |

The exact registry is version-controlled in [`games.json`](games.json). It defines source support, source identifiers, pagination policy, output directory, display name, shared author-tier percentiles and mapping path, an optional update-filter label/cutoff, and publication destination. Registry validation rejects missing required games, unsupported sources, unsafe paths, invalid slugs, malformed author-tier or update-filter configuration, and duplicate output/publication destinations.

Validated source references:

- R.E.P.O.: <https://www.nexusmods.com/games/repo> and <https://thunderstore.io/c/repo/>
- PEAK: <https://www.nexusmods.com/games/peak/mods> and <https://thunderstore.io/c/peak/>
- Retro Rewind: <https://www.nexusmods.com/games/retrorewindvideostoresimulator/mods>
- TCG Card Shop Simulator: <https://www.nexusmods.com/games/tcgcardshopsimulator> and <https://thunderstore.io/c/tcg-card-shop-simulator/>
- Thunderstore ecosystem metadata: <https://github.com/thunderstore-io/ecosystem-schema/tree/master> (the authoritative repository uses `master`; `main` does not exist)
- PEAK’s ancillary community library: <https://github.com/PEAKModding/PEAKLib/tree/main> (`main`; not used as a listing source)

## Scope and runtime

- Thunderstore games: request up to four pages each for `last-updated` and `most-downloaded`, normally 20 cards per page. After at least one nonempty page, HTTP 404 on a later listing page is a clean terminal condition; actual per-ranking page counts and the terminal status are persisted and verified.
- Nexus games: request up to two `updatedAt DESC` GraphQL pages of 80 mods each.
- PEAK, R.E.P.O., and Retro Rewind permit a terminal short Nexus page; Valheim and TCG Card Shop Simulator require complete configured Nexus pages.
- Python standard library only: no runtime package installation, database, service, scheduler, cron job, or LLM call.
- Network requests are paced and raw captures are retained for deterministic verification.
- For a dual-source game, the Nexus and Thunderstore collectors run concurrently in two standard-library worker threads. Each provider retains its own pacing; games remain sequential, and normalized state/report writes begin only after both provider jobs succeed.

## Manual all-games pass

The Nexus API key is read at runtime from `~/.config/nexus-mods/api-key` by default and is never copied into project output. The reusable manual workflow is:

```bash
cd /opt/data/projects/mod-tracker
python3 scripts/manual-pass.py
```

The wrapper:

1. collects every configured game independently, overlapping its Nexus and Thunderstore provider jobs when both are configured;
2. generates `report.html` and `report-hotlinked.html` for each game;
3. strictly verifies every game before publication;
4. stages each hotlinked report in a temporary directory as `index.html`;
5. dry-runs the complete five-destination batch before the first external write;
6. replaces all five destination trees with rollback protection, commits once, deploys once, and verifies every URL through `/opt/data/projects/public-artifacts/scripts/publish-site.py --batch-manifest`;
7. pushes `public-artifacts/main` and verifies its remote hash equals local `HEAD`.

Use `--dry-run` to perform collection, verification, staging, and all publisher preflights without publishing or pushing:

```bash
python3 scripts/manual-pass.py --dry-run
```

The wrapper attempts collection for every game and reports per-game failures as JSON. Within a dual-source game, both provider results or errors are joined in deterministic source order; one provider failure cannot partially merge normalized data, rewrite snapshots/reports, or allow publication. It never performs a real publication if any collection, verification, staging, or publisher preflight fails.

## Individual commands

```bash
# One game, all supported sources
python3 tracker.py collect --game peak --nexus-api-key-file /path/to/key
python3 tracker.py verify --game peak

# All generated outputs
python3 tracker.py verify --game all --output-root .
python3 tracker.py report --game all --output-root .

# One source only; persisted records from the other source remain untouched
python3 tracker.py collect --game valheim --sources thunderstore
python3 tracker.py collect --game valheim --sources nexus --nexus-api-key-file /path/to/key

# Explicit page-count overrides; normally use games.json defaults
python3 tracker.py collect --game repo --thunderstore-pages 3 --nexus-pages 1
```

`collect` is resumable: listing evidence is atomically replaced, stale pages after a terminal Thunderstore 404 or short Nexus page are removed, per-mod details are cached, and Thunderstore detail pages are fetched again only when a latest version changes. Network reads retry transient timeouts, connection failures, HTTP 408/425/429, and HTTP 5xx responses at most twice with bounded backoff. A later Thunderstore listing 404 is terminal only after a nonempty page; page-one 404s and other permanent HTTP errors fail immediately. JSON uses sorted keys and stable indentation. Collection timestamps are necessarily run-specific.

## Per-game storage

Each game root contains only that game’s generated state:

- `data/mods.json` — normalized source records, observations, and computed rates
- `author-mappings.json` — explicit reciprocal Nexus/Thunderstore author aliases; `{}` is valid when no alias is confirmed
- `data/author-reputation.json` — generation timestamp, configured percentiles, dynamic raw-download cutoffs, canonical raw-download totals, known-mod counts, first-known-mod publication timestamps, and assigned tiers
- `raw/thunderstore/listings/` — listing HTML by ranking/page plus `manifest.json` with requested pages, actual fetched counts, and terminal status, where supported
- `raw/thunderstore/packages/` — public package details, where supported
- `raw/thunderstore/metrics/` — exact package metrics, where supported
- `raw/nexus/listing-page-*.json` — exact GraphQL responses
- `raw/nexus/mods/` — cached v1 details
- `raw/nexus/pages/` — optional authenticated page HTML
- `snapshots/latest.json` — latest collection manifest and counts
- `report.html` — local sortable report
- `report-hotlinked.html` — verified publication artifact

Valheim deliberately retains these paths at the repository root. All other games live below their configured `games/<slug>/` directory. Generated data, raw captures, snapshots, reports, transient files, cookies, environment files, and credentials are ignored by Git.

Writes use a same-directory temporary file followed by `os.replace`, so interrupted writes do not leave partially serialized canonical files.

## Authentication

Nexus GraphQL and v1 detail requests use the API key file supplied at runtime. The key is sent only as an HTTP header and is not logged or persisted.

A live comparison on September 10, 2026 verified that the separate public website endpoint `https://api-router.nexusmods.com/graphql` returns the same ordered PEAK listing payload as authenticated v2 GraphQL: 72 records with every field selected by this tracker and no API-key header. This proves a deterministic anonymous listing source exists, but the current manual pipeline intentionally continues using the authenticated API because v1 detail enrichment still requires the key; no automatic fallback is claimed or wired.

Optional Nexus detail-page HTML is Cloudflare-protected. To attempt a one-time authenticated capture for newly observed mods, provide a Netscape cookie jar or a file containing an exported `Cookie:` header:

```bash
python3 tracker.py collect --game valheim --sources nexus \
  --nexus-api-key-file /path/to/key \
  --nexus-cookie-file /path/outside/repo/nexus-cookies.txt
```

Without a cookie file, v1 API details are still cached and `raw_page_capture.status` is recorded as `unavailable`. Failed captures are recorded honestly as `failed`.

## Rates, mappings, and reports

Every source record uses the same derived fields:

- `lifetime_downloads_per_day`: downloads divided by age rounded up to a full day, with a one-day minimum.
- `current_version_observed_downloads_per_day`: same-version download delta divided by elapsed time between first and latest tracker observations.

The current-version rate remains unknown until there are two observations for that version.

Cross-site grouping is explicit and manual only. The routine manual pass does not discover or add mappings. Mapped pairs render as one `Both` card with separate source links and combined confirmed source metrics; unmapped records remain source-specific.

For an explicit mapping review, generate a bounded advisory shortlist from saved data:

```bash
python3 scripts/mapping_candidates.py --game all --limit 20 --min-score 0.45 \
  --output /tmp/mod-tracker-mapping-candidates.json
```

The stdlib-only tool compares Nexus records only with Thunderstore records, skips already mapped records, and ranks pairs deterministically using normalized-title Levenshtein similarity, title-token overlap, description-token overlap, and normalized-author Levenshtein similarity. Output includes component scores, reasons, URLs, and summaries capped at 500 characters so manual or LLM review consumes only the shortlist rather than complete catalogs. It never edits `mappings.json` or `author-mappings.json`; authoritative reciprocal mappings remain a manual, separately verified decision. Nexus-only games are recorded explicitly as `single-source`.

Author rarity is explicit and deterministic. Each game independently sums raw lifetime downloads across every stored mod for each source-scoped identity, merges identities only through that game’s reciprocal `author-mappings.json`, and computes nearest-rank cutoffs from that game’s canonical-author pool. The configured bands are Common below the 60th percentile, Uncommon at or above the 60th, Rare at or above the 70th, Epic at or above the 80th, and Legendary at or above the 90th. Ties at a cutoff are promoted together. Author names render white, green, blue, purple, or orange with matching tier, lifetime-download total, known-mod count, and first-known-mod publication tooltip/ARIA metadata plus a concise on-page legend. Explicitly mapped source records for one canonical mod count once toward the known-mod total.

Reports retain their generation timestamp and separately show `Data last updated at` using the latest parsed `updated_at` value among that game’s stored mods. They provide search, source and category dropdowns, NSFW visibility (off by default and statically hidden without JavaScript), and numeric/date sorting using raw `data-*` values. Clicking a category chip selects that category in the dropdown and reapplies every filter together. The complete filtered result set is paginated client-side in fixed 100-card pages inside the same self-contained HTML file; pinned cards count toward the page size, Previous/Next controls report the current page accessibly, and every filter or sort change returns to page 1. The complete filter toolbar remains at the top while scrolling on desktop-width viewports; at 520px and below it returns to normal document flow so it does not consume the mobile viewport. One shared registry-driven update-filter path serves Valheim (`v1 filter`, September 8, 2026), PEAK (`v2.0 filter`, August 10, 2026), and R.E.P.O. (`v0.4 filter`, May 7, 2026); each includes mods updated exactly at or after its UTC cutoff. Games with a null filter omit the control.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/manual-pass.py
python3 -m json.tool games.json >/dev/null
python3 tracker.py verify --game all --output-root .
git diff --check
```

Strict CLI verification checks configured and actual raw-page scope, Thunderstore listing-manifest/snapshot agreement, valid terminal short pages, stale-page absence, source-record uniqueness and required fields, both report artifacts, exact canonical card counts, required controls and sort metadata, source-derived category options/card metadata/buttons, category JavaScript, sticky responsive toolbar behavior, independently recomputed author reputation, exact rendered author identity/canonical/total/tier/mod-count/first-publication/accessibility metadata, parsed latest-data timestamp metadata and visible text, matching hotlinked/local bytes, and absence of embedded `data:image/` content from the publication artifact.

Project status is in [`TODO.md`](TODO.md); completed milestones are in [`CHANGELOG.md`](CHANGELOG.md); the latest bounded cross-provider decisions are recorded in [`MAPPING_REVIEW.md`](MAPPING_REVIEW.md).
