# Goal: Fully Automated Six-Hour Mod-Tracker Passes

Build and enable a deterministic, standard-library-only, fail-closed automation pipeline for the five-game mod tracker. It must refresh and publish verified reports every six hours using the existing approved mod and author mappings as read-only inputs. Further cross-provider mapping discovery and reconciliation are deferred to `TODO.md` and are not part of the scheduled path.

## Approved behavior

### Scheduled full pass

1. Run at 12:00 AM, 6:00 AM, 12:00 PM, and 6:00 PM in `America/Phoenix` using cron expression `0 */6 * * *`.
2. Process games sequentially. For a dual-source game, collect Nexus Mods and Thunderstore concurrently with at most one standard-library worker per provider while preserving each provider's independent pacing; join results deterministically.
3. Any required provider or game collection failure aborts generation and publication for the entire cohort and preserves the prior live site. Aggregate provider failures accurately rather than publishing partial data.
4. Generate every report using only the existing version-controlled `mappings.json` and `author-mappings.json` files. The scheduled path must not discover, queue, infer, reconcile, or mutate mappings.
5. Strictly verify every local report and publication artifact before the first external write.
6. Abort publication when a game's canonical card-count change is both greater than 10% and at least 25 cards unless an explicit one-run override is recorded in the run log.
7. Run from isolated clean worktrees under one shared nonblocking lock. Abort on remote divergence or a non-fast-forward push; never auto-rebase scheduled changes.
8. Publish through the existing `/opt/data/projects/public-artifacts/scripts/publish-site.py` batch publisher, push `public-artifacts/main`, and verify the exact landing page and all five live game routes plus a nonexistent-route HTTP 404 check.
9. If generated publication bytes are unchanged, skip empty commits, pushes, and deployment while still completing strict local and live verification and reporting success.
10. If a verified local pass succeeds but publication, deployment, push, or live verification fails, retain complete diagnostics and a recoverable publication state. Preserve the prior live site where possible and never report the run as fully successful.
11. Send a compact Telegram summary after every scheduled invocation, including success/failure, stage durations, per-game record/card counts, anomaly results, publication/deployment status, and relevant Git SHAs.

### Client-side report pagination

1. Keep exactly one self-contained HTML file per game report; do not create page files or server endpoints.
2. Paginate the current filtered result set in fixed increments of 100 cards.
3. Pinned cards count toward the 100-card page size.
4. Provide accessible Previous and Next controls plus a live page indicator.
5. Search, sort, category, source, NSFW, update-date, and other filters operate over the complete card set before pagination.
6. Any filter or sort change resets to page 1.
7. Strict verification binds and validates the pagination markup, behavior, and canonical client script.

### Logging and retention

1. Create a durable project-local run directory for every invocation, including interrupted and failed runs.
2. Record run ID, start/end timestamps, stage status and duration, sanitized command arguments, separate stdout/stderr, provider counts and pagination evidence, report counts, anomaly results and overrides, Git SHAs, publication manifest, deployment/version output, live HTTP and byte-identity checks, and final `summary.json`.
3. Never log credentials, authorization headers, API-key values, cookies, or secret-bearing environments or commands.
4. Retain detailed logs for 90 days and always keep at least the latest 100 runs; maintain a `latest` pointer to the newest completed invocation.
5. Make log, state, and lock paths injectable for isolated tests and ignore runtime state in Git.

### Implementation and operating constraints

1. Keep the complete runtime Python-standard-library-only: no package installation, database, service, frontend framework, or scheduled-path LLM call.
2. Read the Nexus key only from `~/.config/nexus-mods/api-key`; require a nonempty regular file with mode `0600`. Never expose the value in repositories, process arguments, logs, summaries, reports, manifests, or child-process environments that do not require it, and never loosen the file mode.
3. Preserve source-scoped `nexus:` and `thunderstore:` identities and all existing explicit reciprocal mappings. The scheduled path treats mapping files as immutable configuration and performs no fuzzy identity matching.
4. `--dry-run` suppresses publication, deployment, and public-repository pushes only. It still persists successfully collected data and generates and verifies local artifacts.
5. Use the existing public-artifacts batch publisher without modifying it unless the reduced workflow cannot be represented. Preserve legacy static assets and publish one atomic `mod-tracking` tree with `publication.root == "mod-tracking"` and each `publication.path == <game key>`.
6. Keep reports self-contained server-rendered static HTML with client-side pagination and no Preact or other frontend framework.
7. Fail closed on symlinks, traversal, filesystem races, incomplete writes, malformed state, repository divergence, unverifiable publication state, or missing required outputs.
8. Hold one nonblocking whole-run `flock` across automated passes. The flat Hermes no-agent wrapper lives under `/opt/data/scripts`; project implementation and runtime state remain under the project directory.
9. Send scheduled summaries to the configured originating Telegram thread. If persisted gateway destination fields are missing or insufficient, stop delivery rather than guessing another destination.
10. Keep the existing mapping-candidate utility available only for future explicit manual work recorded in `TODO.md`; it is never invoked by the automated full pass.

## Implementation milestones

- [x] Document the reduced mapping-free automated/full-pass contract in project guidance.
- [x] Add client-side 100-card report pagination using strict RED → GREEN → REFACTOR tests.
- [ ] Add the shared lock, isolated-worktree orchestrator, source-completeness gate, count-anomaly gate, durable stage logs, retention, no-change handling, Git operations, publication, and recovery using strict TDD.
- [ ] Add a flat no-agent wrapper beneath `/opt/data/scripts` and verify its exact stdout/stderr/exit-code contract.
- [ ] Exercise success, no-change, provider-failure, anomaly-block, publication-failure, remote-divergence, interrupted-run, and overlapping-run paths.
- [ ] Run the complete unit, syntax, JSON, stdlib-import, deterministic-output, strict all-game, publication dry-run, Git-diff, and security gates.
- [ ] Obtain independent fail-closed review; fix and re-review every security, logic, or requirement finding.
- [ ] Commit and push each verified milestone; synchronize both repositories.
- [ ] Run a successful real scheduled-path rehearsal and verify its local, repository, publication, live-route, log, and summary outputs.
- [ ] Create the Hermes cron job paused, read back its exact definition, exercise it once, verify run history, delivery, and ticker prerequisites, and enable it only after every acceptance gate passes.
- [ ] Move completed checklist material to `CHANGELOG.md`, delete `GOAL.md`, and leave only genuinely deferred work in `TODO.md`.

## Definition of done

- Every new behavior has a test that was observed failing before implementation and passing afterward.
- `python3 -m unittest discover -s tests -v`, Python compilation, JSON validation, a standard-library import audit, deterministic-output checks, `git diff --check`, and `python3 tracker.py verify --game all --output-root .` all pass.
- Generated reports remain single-file HTML, show no more than 100 matching cards per client-side page, expose working accessible pagination controls, and pass strict tamper tests.
- Scheduled runs never discover or modify mod or author mappings; existing mappings remain valid read-only inputs.
- Scheduled runs cannot overlap manual automation and cannot publish partial collections or suspicious count changes.
- Every run has reviewable, sanitized, retained diagnostics and emits an accurate compact Telegram summary.
- Automatic collection, generation, strict verification, publication, public-repository push, and live verification are proven on the real scheduled path; failures are accurately recorded and recoverable.
- Both repositories finish clean and synchronized with their respective `origin/main` branches.
- The exact `/mod-tracking/` landing page and all five game routes return the verified current artifacts; an unknown route returns HTTP 404.
- The Hermes job is a verified no-agent script job scheduled at `0 */6 * * *` for Phoenix time and is enabled only after the paused rehearsal passes.
