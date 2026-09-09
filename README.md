# Valheim Mod Tracker

A deterministic, dependency-free Python CLI that collects and compares Valheim mods from Thunderstore and Nexus Mods, persists source evidence and normalized observations, and generates one sortable HTML report.

[Data-flow and field-lineage diagram](DATA_FLOW.html)

## Required scope

- Thunderstore: 4 pages sorted by `last-updated` and 4 pages sorted by `most-downloaded` (20 cards per page; 160 ranked appearances total).
- Nexus Mods: exactly two GraphQL pages of 80 mods each, sorted by `updatedAt` descending (160 listing results total).
- Runtime: Python standard library only. No package installation, service, scheduler, or cron job is required.

## Run

The Nexus API key is read at runtime and is never copied into project output:

```bash
python3 tracker.py collect
python3 tracker.py verify
```

Defaults:

- output root: current directory
- Nexus key: `~/.config/nexus-mods/api-key`
- report: `report.html` (and `report-hotlinked.html` when thumbnails are not embedded)
- normalized store: `data/mods.json`

Useful manual commands:

```bash
# Collect just one source (the persisted store retains the other source).
python3 tracker.py collect --sources thunderstore
python3 tracker.py collect --sources nexus

# Rebuild the report without network access.
python3 tracker.py report

# Inline fetched thumbnails as data URLs in the report.
python3 tracker.py report --embed-thumbnails

# Use a different isolated output directory.
python3 tracker.py collect --output-root /tmp/valheim-mod-tracker
python3 tracker.py verify --output-root /tmp/valheim-mod-tracker
```

`collect` is resumable: listing evidence is replaced atomically, per-mod detail payloads are cached, and a detail page is fetched again only when needed. JSON serialization uses sorted keys and stable indentation. Network collection timestamps are necessarily run-specific.

## Nexus authentication and raw page capture

The GraphQL listing and v1 detail requests use the API key from `~/.config/nexus-mods/api-key`. The key is sent only as an HTTP header and is not logged or persisted.

Nexus detail-page HTML is Cloudflare-protected. For a one-time authenticated capture of each newly observed mod page, provide either a Netscape cookie jar or a file containing a browser-exported `Cookie:` header:

```bash
python3 tracker.py collect --sources nexus --nexus-cookie-file /path/outside/repo/nexus-cookies.txt
```

Cookie files and headers must remain outside Git. Without a cookie file, collection still caches the complete v1 API detail payload under `raw/nexus/mods/` and records `raw_page_capture.status` as `unavailable`. Failed HTML captures are recorded honestly as `failed`; they are never represented as successful.

## Stored output

Generated output is deliberately ignored by Git:

- `data/mods.json` — flat normalized records with observation history and computed rates
- `raw/thunderstore/listings/` — source listing HTML by ranking and page
- `raw/thunderstore/packages/` — public package detail HTML
- `raw/thunderstore/metrics/` — exact package metric JSON
- `raw/nexus/listing-page-{1,2}.json` — exact GraphQL responses for the two 80-item listing pages
- `raw/nexus/mods/` — cached v1 detail JSON for newly observed mods
- `raw/nexus/pages/` — optional authenticated page HTML
- `snapshots/latest.json` — latest run manifest
- `report.html` and `report-hotlinked.html` — sortable, searchable combined report (the latter is the explicit externally hotlinked-image artifact)

Writes use a same-directory temporary file followed by `os.replace`, so interrupted writes do not leave partially serialized canonical files.

## Comparable rates

Each source is normalized to the same two rate fields:

- `lifetime_downloads_per_day`: current total downloads divided by age since creation, with a one-day minimum denominator.
- `current_version_observed_downloads_per_day`: download delta divided by elapsed time between the first and latest stored observations of the current version.

The current-version rate remains unknown until two observations for that version exist. Rates are based on observations made by this tracker; they do not claim provider-side historical precision.

## Report behavior

`report.html` combines both sources into canonical cards: explicit mappings are rendered once with a prominent `Both` badge and separate Thunderstore/Nexus links; unmapped records remain source-specific cards. Source badges are in the card body, source metrics stay labeled, and the NSFW toggle defaults off (adult cards are also hidden by static CSS when JavaScript is disabled). Search, source filter (`Thunderstore`, `Nexus Mods`, or `Both`), NSFW visibility, updated-date filter, and sorting compose together. Thunderstore pinned entries remain in a separate fixed group. Optional thumbnail embedding removes report-time image dependencies.

## Verification

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m py_compile tracker.py
python3 tracker.py verify
```

The verifier checks all 8 Thunderstore listing pages for 20 cards each, reports the 160 ranked appearances, checks both Nexus pages for 80 nodes each and reports their distinct-ID count, checks normalized-record uniqueness and required fields, and validates report card count and sort metadata.

Project status is in [`TODO.md`](TODO.md); completed milestones are in [`CHANGELOG.md`](CHANGELOG.md).
