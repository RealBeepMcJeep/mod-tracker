# Goal: Automated Six-Hour Mod-Tracker Passes

Build and enable a deterministic, standard-library-only scheduled pipeline for all five games. It must collect current data, generate and verify reports, publish the complete site, verify the live result, and report each run to Telegram. Existing mod and author mappings are read-only inputs; mapping discovery and reconciliation remain deferred manual work in `TODO.md`.

## Scheduled workflow

1. Acquire one nonblocking lock. If another automated pass is running, exit immediately without collecting or publishing.
2. Process all five games sequentially. Within a dual-source game, Nexus Mods and Thunderstore may run concurrently while keeping their independent pacing.
3. If any required source or game fails, stop before report generation and publication. Never publish a partial cohort.
4. Generate all reports and run strict all-game verification. The scheduled path uses existing mappings but never runs mapping discovery or reconciliation.
5. Compare each game's card count with the previous successful run. Block publication when the absolute change is at least 25 cards and the percentage change is greater than 10%, unless a one-run override is explicitly recorded. Treat a zero-to-nonzero baseline as requiring review.
6. Stage the landing page and all five reports as one `mod-tracking` tree. Publish it through `/opt/data/projects/public-artifacts/scripts/publish-site.py` only after the complete cohort passes verification.
7. Commit and push `public-artifacts/main` when publication bytes changed. When bytes are unchanged, skip the empty commit, push, and deployment.
8. Verify the live landing page and all five game routes against the generated artifacts, and confirm an unknown child route returns HTTP 404.
9. Write a sanitized per-run log and `summary.json`, then emit a compact Telegram result containing status, duration, per-game counts, anomaly state, publication state, and relevant Git SHAs.

## Basic operating rules

- Use Python's standard library only. Scheduled execution must not install packages, use a database, invoke an LLM, or discover mappings.
- Read the Nexus key only from `~/.config/nexus-mods/api-key`. Require a nonempty regular file with mode `0600`, keep it out of command arguments and generated artifacts, and redact secrets from logs and summaries.
- Use existing registry paths and fixed internal stage names. Reject absolute paths, traversal, and symlinks where runtime paths are accepted.
- Write JSON state and final summaries atomically. A failed run must not be marked successful or replace the latest-success pointer.
- Keep enough per-run output to diagnose collection, verification, publication, push, or live-site failures.
- `--dry-run` still performs collection, generation, and local verification, but does not publish, deploy, or push `public-artifacts`.
- Refuse to publish when either repository is unexpectedly dirty or its local `main` has diverged from `origin/main`. Never auto-rebase a scheduled run.
- Preserve the previous live site when a run fails before deployment. If deployment occurred but a later check failed, report that state accurately.
- Send scheduled output to the configured Telegram thread. Do not guess a destination if the persisted delivery target is incomplete.

## Implementation milestones

- [x] Document the mapping-free full-pass contract and move mapping reconciliation to `TODO.md`.
- [x] Finish and test the unattended runner: lock, collection, verification, anomaly gate, logging, publication, push, and live verification.
- [x] Add and test the flat no-agent wrapper under `/opt/data/scripts`.
- [x] Exercise the essential paths: overlap, provider failure, anomaly block, no change, dry run, publication failure, and success.
- [x] Run the complete project gates and obtain an independent review of the integrated scheduled path.
- [x] Commit and push the verified implementation; confirm both repositories are clean and synchronized.
- [ ] Complete one real scheduled-path publication and verify its logs, repository state, deployed artifacts, six live routes, and unknown-route 404.
- [ ] Create the Hermes cron job paused at `0 */6 * * *` in `America/Phoenix`, read back its persisted definition, run it once, verify run history and Telegram delivery, then enable it.
- [ ] Record completed work in `CHANGELOG.md`, leave only deferred work in `TODO.md`, and delete this file after every acceptance criterion passes.

## Definition of done

- All five games complete collection, report generation, and strict verification as one cohort without scheduled mapping discovery or reconciliation.
- Required source failures and suspicious count changes prevent publication; overlapping runs do no work.
- Unchanged publication bytes skip commit, push, and deployment while local and live verification still pass.
- Every invocation leaves an accurate sanitized run summary, and successful scheduled output reaches the intended Telegram thread.
- The publisher receives one complete atomic `mod-tracking` tree.
- `https://public-artifacts.xioustic-5f1.workers.dev/mod-tracking/` and all five game routes return HTTP 200 with the expected artifacts; an unknown child route returns HTTP 404.
- The following checks pass:

```bash
python3 -m unittest -v tests.test_unattended_run
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/manual-pass.py scripts/mapping_candidates.py scripts/unattended_run.py
python3 -m json.tool games.json >/dev/null
python3 tracker.py verify --game all --output-root .
git diff --check
git diff --cached --check
```

- The scheduled-path import audit finds no third-party Python imports.
- Local and `origin/main` hashes match for both `mod-tracker` and `public-artifacts`, and both working trees are clean.
- The enabled Hermes job is a no-agent script job scheduled every six hours in Phoenix time.
