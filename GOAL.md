# Dynamic Author Rarity Across All Mod Reports

Complete dynamic author-rarity support for Valheim first and then all other configured games using raw lifetime downloads and per-game 60/85/97 percentile thresholds, followed by regeneration, verification, and republication of every report.

## Current State

### Modified files and environment

- Repository: `/opt/data/projects/mod-tracker`
- Active branch: `main`
- Publication repository: `/opt/data/projects/public-artifacts`, branch `main`
- Author-rarity work is currently uncommitted.
- Files already modified or added include:
  - `tracker.py`
  - `games.json`
  - `tests/test_report.py`
  - `tests/test_cli.py`
  - `author-mappings.json`
  - `games/peak/author-mappings.json`
  - `games/repo/author-mappings.json`
  - `games/retro-rewind/author-mappings.json`
  - `games/tcg-card-shop-simulator/author-mappings.json`
- No background processes or active containers are involved.
- No author-rarity changes have been committed, pushed, regenerated, or published.

### What has already succeeded

- Implemented source-scoped author identities.
- Implemented raw lifetime-download aggregation.
- Implemented explicit canonical cross-provider mappings without fuzzy matching.
- Implemented dynamic per-game Normal, Magic, Epic, and Legendary tiers at the 60th, 85th, and 97th percentiles.
- Enabled the shared author-tier policy for all five games in `games.json`.
- Added independent empty author-mapping files for all five game roots.
- Added percentile ordering and safe mapping-path validation.
- Added reciprocal mapping loading and rejection of nonreciprocal or unsupported-source mappings.
- Added accessible author-name rendering with white, blue, purple, and orange rarity classes, tooltips, ARIA labels, and subtle higher-tier glow.
- Added a concise visible Author rarity legend.
- Added generation and persistence of per-game `data/author-reputation.json` artifacts.
- Wired author tiers through collection, standalone report generation, and verification paths.
- Added verification for missing or inconsistent reputation artifacts, invalid generation timestamps, tampered author metadata, and missing author metadata on individual cards.
- Added fail-closed validation for Boolean and non-integer download totals.
- Targeted RED→GREEN tests are passing; the most recent complete suite passed before the latest unfinished mapping-validation slice.

## Constraints

- Python standard library only.
- Do not add runtime dependencies, a database, service, scheduler, cron job, or runtime LLM call.
- Reports remain static and self-contained; do not add a frontend framework.
- Follow strict RED→GREEN TDD for behavior changes.
- Require an independent fail-closed pre-commit review.
- Author score uses only combined raw lifetime downloads, never mod count, endorsements, likes, age, or download velocity.
- Identities remain source-scoped unless explicitly linked through validated reciprocal mappings.
- Never fuzzy-match author identities.
- Recalculate tiers and raw-download thresholds independently from each game’s current author pool.
- Implement and verify Valheim first, then apply the shared implementation to PEAK, R.E.P.O., Retro Rewind, and TCG Card Shop Simulator.
- Read the Nexus key only from `~/.config/nexus-mods/api-key`; verify the file is nonempty and mode `0600`; never expose its value in commands, logs, reports, repositories, or summaries.
- Do not perform a fresh scrape for final regeneration unless separately requested.
- Do not add a disclaimer to the report or legend.

## Remaining Tasks

- [x] Inspect the current diff and rerun the latest targeted author-mapping, rendering, verifier, and generation tests to establish the exact resumed baseline.
- [x] Finish the active RED→GREEN mapping-validation slice so same-provider aliases are rejected; explicit author aliases must be genuinely cross-provider.
- [x] Add tests for malformed mapping entries, duplicate targets, conflicting canonical groups, invalid canonical IDs, one-way mappings, missing mapping files, and unsupported providers; fail closed with actionable errors.
- [x] Confirm `ReportVerifier` and `verify_report()` reject missing, incorrect, or tampered tier classes, source identity keys, canonical identities, raw-download totals, thresholds, and generation metadata.
- [x] Confirm grouped cross-provider mods use the correct source-scoped primary author identity and merge author downloads only through explicit reciprocal mappings.
- [x] Confirm HTML escaping protects author names, source identity attributes, canonical IDs, tooltip text, ARIA labels, and all mapping-derived values.
- [x] Finish and verify Valheim’s dynamic thresholds, exact tier assignments, persisted reputation metadata, rendered colors, legend, accessibility metadata, and report verification.
- [x] Confirm the completed implementation is shared and registry-driven without game-key branches or duplicated per-game logic.
- [x] Add registry and integration tests proving each game computes thresholds only from its own author pool and cannot inherit another game’s thresholds, mappings, reputation artifact, or author totals.
- [x] Add tests covering single-provider games, dual-provider games, empty author pools, one-author pools, equal download totals at percentile boundaries, missing authors, zero downloads, negative downloads, invalid or Boolean download values, and authors with multiple mods.
- [x] Ensure each game stores its own reproducibility artifact without overwriting another game’s `data/author-reputation.json`.
- [x] Verify Normal, Magic, Epic, and Legendary rendering independently for Valheim, PEAK, R.E.P.O., Retro Rewind, and TCG Card Shop Simulator.
- [x] Update `README.md`, `CHANGELOG.md`, `TODO.md`, `DATA_FLOW.html`, and relevant project documentation with the algorithm, exact percentile semantics, mapping format, per-game isolation, all-game rollout, legend, and accessibility behavior.
- [x] Run the complete unit suite, Python compilation, JSON validation, repository consistency checks, standard-library import audit, and generated-report verification; fix every failure using RED→GREEN TDD.
- [x] Dispatch the mandatory independent pre-commit review over the complete all-game diff and fail closed on any security concern, logic error, or requirement mismatch.
- [x] Fix any review findings and rerun all gates.
- [x] After review passes, commit with a `[verified]` message and push `mod-tracker/main`.
- [x] Verify local tracker HEAD equals `origin/main` and the worktree is clean.
- [x] Regenerate all five reports from saved collected data using `python3 tracker.py report --game all`; do not perform a fresh scrape unless separately requested.
- [x] Run aggregate and per-game verification and record each game’s dynamically calculated raw-download cutoffs plus exact Normal, Magic, Epic, and Legendary author counts.
- [x] Stage all five freshly generated `report-hotlinked.html` artifacts in `/opt/data/projects/public-artifacts` as their respective `index.html` files.
- [x] Build a five-entry publication batch manifest for Valheim, PEAK, R.E.P.O., Retro Rewind, and TCG Card Shop Simulator.
- [x] Run the complete five-report publication batch with `--dry-run` and confirm exactly the five intended report files would change.
- [x] Run the live five-report publication batch only after the dry run passes.
- [x] Verify the public-artifacts change set contains exactly the five intended `public/reports/*/index.html` files.
- [x] Commit and push `public-artifacts/main`, then verify local HEAD equals `origin/main` and the worktree is clean.
- [x] Fetch all five public report URLs and verify each returns HTTP 200 and is byte-identical to both its freshly generated local report and committed static artifact.
- [x] Fetch a nonexistent report route and confirm it still returns HTTP 404.
- [x] Update the `multi-game-mod-tracker` skill with any reusable dynamic author-tier, mapping, verification, or all-game publication lessons not already documented.

## Additional Criteria: Category Filter and Sticky Controls

- [x] Add RED→GREEN renderer tests for a category dropdown populated from the current report’s categories, including an all-categories option and HTML escaping.
- [x] Add RED→GREEN interaction-contract tests proving category filtering composes with search, source, NSFW, and update-date filters.
- [x] Make every category tag a keyboard-accessible button that selects its category in the dropdown and reapplies filtering without navigating the card.
- [x] Make the search, dropdowns, and checkboxes remain visible at the top while scrolling, with responsive styling that does not obscure report content.
- [x] Extend strict report verification to require the shared category control, card category metadata, category predicate, tag-to-filter behavior, and sticky toolbar contract.
- [x] Update project documentation, run all static and generated-report gates, and pass an independent fail-closed pre-commit review.
- [x] Commit and push the verified tracker milestone; confirm local `HEAD` equals `origin/main` and the worktree is clean.
- [x] Regenerate and strictly verify all five reports from saved data, publish them in one preflighted batch, push `public-artifacts/main`, and verify all five live routes are HTTP 200 and byte-identical.
- [x] Use the existing `AI-Goes-Fast/mod-tracker` Gitea repository and verify its `main` branch is reachable before pushing this milestone.

## Additional Criteria: Ordered Morning Publication Pass

- [x] Regenerate Valheim from saved data, strictly verify it, publish it alone, and verify its live route before starting any other game.
- [ ] Regenerate and strictly verify the other four games, publish them as one batch, and verify their four live routes before starting the manual pass.
- [ ] Run this morning's full manual collection pass for all five games and strictly verify every refreshed game without publishing partial results.
- [ ] Regenerate all five reports from the refreshed saved data, publish them as one batch, push both repositories, and verify all five live routes are HTTP 200 and byte-identical.

## Definition of Done / Verification

- Run from `/opt/data/projects/mod-tracker`:

  ```bash
  python3 -m unittest discover -s tests -v
  ```

  Confirm exit code 0 with every test passing.

- Run:

  ```bash
  python3 -m py_compile tracker.py scripts/*.py tests/*.py
  ```

  Confirm exit code 0.

- Validate registry and mappings:

  ```bash
  python3 -m json.tool games.json >/dev/null
  python3 -m json.tool author-mappings.json >/dev/null
  python3 -m json.tool games/peak/author-mappings.json >/dev/null
  python3 -m json.tool games/repo/author-mappings.json >/dev/null
  python3 -m json.tool games/retro-rewind/author-mappings.json >/dev/null
  python3 -m json.tool games/tcg-card-shop-simulator/author-mappings.json >/dev/null
  ```

  Confirm every command exits 0.

- Confirm every game in `games.json` enables `author_tiers` with:

  ```json
  {
    "magic": 60,
    "epic": 85,
    "legendary": 97
  }
  ```

  Each game must also have a safe relative `mappings_file` path.

- Run:

  ```bash
  python3 tracker.py report --game all
  ```

  Confirm exit code 0, all five reports are regenerated, and each game receives an isolated `data/author-reputation.json`.

- Run aggregate verification:

  ```bash
  python3 tracker.py verify --game all
  ```

  Confirm aggregate `"ok": true` with zero errors.

- Run each game independently:

  ```bash
  python3 tracker.py verify --game valheim
  python3 tracker.py verify --game peak
  python3 tracker.py verify --game repo
  python3 tracker.py verify --game retro-rewind
  python3 tracker.py verify --game tcg-card-shop-simulator
  ```

  Confirm each exits 0 and reports zero errors.

- Confirm each game’s reputation artifact records:
  - Generation timestamp
  - Percentile policy
  - Dynamically calculated raw-download cutoffs
  - Source-scoped identities
  - Canonical identities where explicitly mapped
  - Combined raw lifetime-download totals
  - Final tier assignments

- Confirm each game’s thresholds are calculated only from that game’s author pool and differ naturally when download distributions differ; no absolute raw-download threshold may be hardcoded.
- Confirm all reports contain applicable `author-tier-normal`, `author-tier-magic`, `author-tier-epic`, and `author-tier-legendary` classes using white, blue, purple, and orange styling, plus accessible tooltip and ARIA metadata and the concise rarity legend.
- Confirm explicit cross-provider mappings combine totals only within the configured game, while unmapped same-looking Nexus and Thunderstore names remain separate.
- Run `git diff --check` and the repository’s standard-library import audit; confirm both pass.
- Confirm the independent pre-commit review returns `passed: true` with no security concerns, logic errors, or requirement mismatches.
- In `/opt/data/projects/mod-tracker`, run `git status --short`, `git rev-parse HEAD`, and `git rev-parse origin/main`; confirm the tree is clean and both SHAs match after push.
- In `/opt/data/projects/public-artifacts`, dry-run and then execute one batch publication using `scripts/publish-site.py --batch-manifest`; both invocations must exit 0.
- Confirm the public-artifacts diff contains exactly:
  - `public/reports/valheim-mod-tracker/index.html`
  - `public/reports/peak-mod-tracker/index.html`
  - `public/reports/repo-mod-tracker/index.html`
  - `public/reports/retro-rewind-mod-tracker/index.html`
  - `public/reports/tcg-card-shop-simulator-mod-tracker/index.html`
- Commit and push the public-artifacts changes, then confirm its worktree is clean and local HEAD equals `origin/main`.
- Fetch and verify HTTP 200 for:
  - `https://public-artifacts.xioustic-5f1.workers.dev/reports/valheim-mod-tracker/`
  - `https://public-artifacts.xioustic-5f1.workers.dev/reports/peak-mod-tracker/`
  - `https://public-artifacts.xioustic-5f1.workers.dev/reports/repo-mod-tracker/`
  - `https://public-artifacts.xioustic-5f1.workers.dev/reports/retro-rewind-mod-tracker/`
  - `https://public-artifacts.xioustic-5f1.workers.dev/reports/tcg-card-shop-simulator-mod-tracker/`
- Programmatically compare every live response against both its freshly generated local report and committed static artifact; all five comparisons must be byte-for-byte identical.
- Fetch a nonexistent report route and confirm HTTP 404.
