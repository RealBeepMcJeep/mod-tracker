# Verified GitHub Repository Links

**Goal:** Add one trustworthy GitHub repository link to each eligible mod card without mistaking dependencies, frameworks, upstream projects, forks, profiles, or related mods for the mod's own repository.

**Complexity:** Medium. The HTML link is simple; reliable attribution and repairing Thunderstore description extraction are the substantive work.

## Progress rule

This file contains only unfinished scope. After each milestone is working, independently reviewed, committed, and pushed:

1. add its concise result and exact verification evidence to the current dated section of `CHANGELOG.md`;
2. remove the completed milestone from this file;
3. commit and push the documentation update with that milestone.

Delete this file only after the final live definition of done passes.

## Fixed decisions

- GitHub only: `https://github.com/<owner>/<repository>`.
- Show at most one simple `GitHub` text link beside existing provider links.
- Normalize issue, pull-request, release, tree, blob, and other deep links to the repository root.
- Publish only high-confidence associations.
- A manual batched LLM review may directly approve high-confidence cases; ambiguous cases go to `PENDING_GITHUB_REVIEW.md`.
- The LLM may select only a repository extracted from the provider evidence. Deterministic validation rejects invented or malformed decisions.
- Persist reviewed `no_repository` outcomes when GitHub links exist but none belongs to the mod.
- Review once per relevant evidence fingerprint; re-review when GitHub links or their nearby context change.
- Keep a prior approved link visible while changed evidence is pending unless a reviewed decision disproves or replaces it.
- For a mapped Nexus/Thunderstore card:
  - use the one approved repository when only one side has evidence and the other side has no conflicting approval;
  - use one deduplicated link when both sides agree;
  - show no GitHub link and queue review when approved roots conflict.
- Repair and offline-backfill all saved Thunderstore descriptions, then run one normal fresh all-game pass.
- Refresh future Nexus details when the provider update timestamp advances; retain Thunderstore's existing version-change refresh.
- Scheduled collection, report generation, and verification remain deterministic, stdlib-only, and LLM-free.

## Deliberate simplifications

- Do **not** persist derived GitHub candidates in every normalized mod record. Extract candidates from retained descriptions when the manual review tool runs.
- Use one tracked project-root `github-repositories.json`, keyed by exact `game:source-key`, instead of five near-identical per-game files.
- Use only two decision states: `approved` and `no_repository`. Replacing an approval with `no_repository` records a disproven repository; no separate retired state is needed.
- Use one manual tool, `scripts/github-review.py`, for offline Thunderstore backfill, candidate export, validated decision application, and Markdown queue reconciliation. Do not create separate one-use scripts for each phase.
- Do not add a GitHub API dependency, repository-health polling, embeddings, a database, or an LLM runtime adapter.
- Do not make scheduled runs modify tracked review JSON or Markdown. New evidence waits for the next explicit manual review pass.
- Strict report verification checks the reviewed decision and rendered link contract. Candidate provenance is validated when a decision is applied; it is not redundantly reimplemented inside the HTML verifier.

## Minimal data contract

`github-repositories.json`:

```json
{
  "version": 1,
  "records": {
    "valheim:nexus:79": {
      "status": "approved",
      "repository_url": "https://github.com/owner/repository",
      "reviewed_fingerprint": "sha256:<hex>",
      "evidence_urls": ["https://github.com/owner/repository/releases/tag/v1"],
      "review_method": "llm-high-confidence",
      "rationale": "The provider page identifies this as the mod source."
    },
    "valheim:thunderstore:Author/Package": {
      "status": "no_repository",
      "repository_url": null,
      "reviewed_fingerprint": "sha256:<hex>",
      "evidence_urls": ["https://github.com/BepInEx/BepInEx"],
      "review_method": "llm-high-confidence",
      "rationale": "The only repository belongs to a dependency."
    }
  }
}
```

Rules:

- Exact key is `<game>:<record key>` where record keys remain verbatim (`nexus:<id>` or `thunderstore:<namespace>/<package>`).
- `repository_url` must be a normalized GitHub repository root and must be one of the candidates extracted from current evidence when the decision is applied.
- `evidence_urls` retain the exact page links supporting the decision.
- Fingerprint is deterministic over normalized candidate roots, original evidence URLs, link type, and short nearby context. Unrelated prose changes do not trigger review.
- A stale `approved` decision remains displayable and is queued by the next manual scan. A stale `no_repository` decision is queued and does not suppress reconsideration.
- `PENDING_GITHUB_REVIEW.md` contains one stable-ID entry per ambiguous/stale/conflicting review item with exact keys, candidates, context, prior approval if any, and the reason it remains open.

---

## Milestone 1 — Provider descriptions and deterministic candidates

**Outcome:** Current provider pages yield complete retained descriptions and a small pure interface extracts review evidence from those descriptions.

### Work

1. Repair `parse_thunderstore_detail()` for current `.package-listing__content .markdown-wrapper .markdown` markup while retaining legacy `.markdown-body` support.
2. Bound extraction to the first complete README, handle HTML void elements correctly, exclude navigation/footer content, and fail closed on malformed nesting without losing timestamps.
3. Change Nexus detail reuse so an existing detail is refreshed only when the listing's provider update timestamp advances. Missing or invalid freshness evidence refreshes once rather than silently reusing stale content.
4. Preserve existing observations, manual mapping fields, creator attribution, and metrics when refreshed normalized records merge.
5. Add a pure candidate-extraction interface that:
   - reads HTML anchors, Nexus BBCode URLs, and plaintext URLs;
   - accepts only HTTPS `github.com` links with owner and repository components;
   - rejects profiles, gists, lookalike hosts, credentials, and malformed paths;
   - normalizes deep links and `.git` suffixes to the repository root;
   - retains original evidence URL, link type, source field, and bounded context;
   - deduplicates deterministically and computes the relevant evidence fingerprint.
6. Keep candidates derived on demand; do not add them to `data/mods.json`.

### Likely files

- `tracker.py`
- `github_evidence.py` only if a separate deep module produces a meaningfully smaller interface
- `tests/test_collectors.py`
- `tests/test_core.py`
- `tests/test_github_evidence.py`

### Required RED→GREEN coverage

- Legacy README and a sanitized current README containing ordinary non-self-closing `<img>` tags.
- First-README-only, no README, truncated README, mismatched closing tag, and navigation/footer exclusion.
- Real Nexus detail shape: integer `updated_timestamp` plus ISO `updated_time`; unchanged reuse, advanced refresh, and missing/invalid timestamp refresh.
- Incoming normalized `None` mapping fields do not erase persisted mapping/attribution state.
- Root, release, issue/PR, tree/blob, BBCode, plaintext, profile, malformed, non-GitHub, duplicate, multiple-root, and context/fingerprint cases.

### Verification and completion

```bash
python3 -m unittest tests.test_collectors tests.test_core tests.test_github_evidence
python3 -m unittest discover -s tests
python3 -m py_compile tracker.py github_evidence.py
python3 -m json.tool games.json >/dev/null
git diff --check
```

If no separate module is created, omit `github_evidence.py` from the compile command. Independently review real saved Thunderstore markup and Nexus timestamp shapes before commit.

---

## Milestone 2 — Offline backfill and reviewed repository decisions

**Outcome:** Saved descriptions are repaired, all current candidates receive a durable reviewed outcome or stable pending entry, and the process is repeatable without runtime LLM dependencies.

### Work

1. Implement `scripts/github-review.py` as a manual stdlib tool with three operations:
   - `backfill`: reparse saved Thunderstore package HTML into existing normalized records without network access;
   - `export`: write bounded review batches to an explicitly supplied temporary path;
   - `apply`: validate decision JSON, update `github-repositories.json`, and reconcile `PENDING_GITHUB_REVIEW.md`.
2. Backfill must preserve records lacking raw captures and never replace a nonempty description with empty output after a parse failure.
3. Preserve observations, mappings, creator attribution, metrics, and unrelated normalized fields byte-for-byte in meaning.
4. Decision application accepts only exact existing game/source keys and current extracted candidates/fingerprints. Reject stale, invented, malformed, non-high-confidence, cross-game, or unsupported-host output.
5. Persist `no_repository` only for reviewed records that actually contained GitHub candidates; records with no GitHub evidence need no JSON entry and are naturally absent from later review exports.
6. Keep stale approved links in JSON while adding them to the pending queue. Requeue stale `no_repository` decisions. Queue mapped-card repository conflicts.
7. Prove the tool is not invoked by collection, reports, verification, `manual-pass.py`, or `unattended_run.py`.
8. Run the real offline backfill over all saved Thunderstore captures.
9. Export bounded batches and run one batched LLM review. The LLM may choose only from supplied candidates and must return confidence plus concise rationale.
10. Apply only validated high-confidence decisions. Route the rest to Markdown.
11. Independently audit a reproducible sample of accepted decisions, including multiple-root and dependency/framework-language cases. Any material false positive blocks publication and expands the audit.
12. Run backfill/export/apply again and prove idempotence.

### Likely files

- `scripts/github-review.py`
- `tests/test_github_review.py`
- `github-repositories.json`
- `PENDING_GITHUB_REVIEW.md`
- `.gitignore` only if explicit allowlisting is required
- `AGENTS.md` for the concise manual review workflow

### Required reporting

Record exact totals for:

- normalized records scanned by game/source;
- raw Thunderstore pages considered, repaired, missing, and parse-failed;
- records with no GitHub candidates;
- approved repositories;
- reviewed `no_repository` outcomes;
- ambiguous/stale/conflicting queue entries;
- rejected LLM decisions;
- independent audit sample size and findings.

### Verification and completion

```bash
python3 -m unittest tests.test_github_review
python3 -m unittest discover -s tests
python3 -m py_compile tracker.py scripts/*.py github_evidence.py
python3 -m json.tool github-repositories.json >/dev/null
git diff --check
```

Also verify exact before/after record counts, preserved mapping/observation fields, no network calls during backfill, idempotent second execution, and the exact tracked-file allowlist before commit.

---

## Milestone 3 — Report links, fresh pass, and publication

**Outcome:** Verified GitHub repository roots appear on eligible cards, conflicts remain hidden, and the complete live report cohort is refreshed and deployed.

### Work

1. Load and validate `github-repositories.json` during report generation through one shared interface.
2. Resolve at most one repository per card using the fixed single-source/mapped-card rules above.
3. Render a simple `GitHub` anchor beside existing provider links; do not add badges, icons, related links, card-level click behavior, or JavaScript.
4. Extend strict report verification to derive expected per-card links from validated decisions and mappings. Reject missing, added, duplicate, wrong-card, profile, deep-path, conflicting, or altered repository links.
5. Cover current and stale approvals, `no_repository`, unreviewed records, one-sided mapped evidence, matching mapped approvals, and mapped conflicts.
6. Verify the Nexus API-key file is nonempty and mode `0600` without logging its value.
7. Run one normal fresh all-game pass. It must use the repaired parser/refresh behavior but must not invoke an LLM or modify tracked review files.
8. Run the manual review scan once more for evidence changed by the fresh pass; apply validated high-confidence results and leave ambiguity queued.
9. Regenerate and strictly verify all five reports.
10. Commit/push the tracker milestone, stage the complete six-route publication tree, dry-run once, publish atomically once, and push public-artifacts.
11. Verify all six canonical HTTPS routes return 200 and exact committed bytes; verify an unknown route returns 404.
12. Browser-check representative Nexus, Thunderstore, mapped-agreement, and mapped-conflict cards while confirming search, filters, pagination, and author controls still work.
13. Add final exact counts and verification results to `CHANGELOG.md`, reconcile only genuinely outstanding `TODO.md` work, and delete this file.

### Required RED→GREEN coverage

- One approved single-source repository link.
- Deep evidence URL displayed as repository root.
- No link for unreviewed or `no_repository` records.
- Stale approved link retained.
- One-sided mapped approval accepted when no conflicting approval exists.
- Matching mapped approvals deduplicated.
- Conflicting mapped approvals hidden.
- Tampering: changed href, deep path, profile URL, duplicate, wrong card, missing link, and label-only spoof.

### Final gates

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/*.py github_evidence.py
python3 -m json.tool games.json >/dev/null
python3 -m json.tool github-repositories.json >/dev/null
git diff --check
python3 tracker.py report --game all --output-root .
python3 tracker.py verify --game all --output-root .
```

If no separate evidence module exists, omit it from compile commands.

## Final definition of done

- All saved Thunderstore package captures were considered by offline backfill, with exact exceptions reported.
- Future changed Nexus and Thunderstore details refresh under deterministic provider signals.
- Candidate extraction and review application are evidence-bound and deterministic.
- Every candidate-bearing current record is approved, explicitly `no_repository`, or represented once in the pending queue.
- Independent sample audit finds no material false-positive repository associations.
- Every eligible card shows at most one normalized repository-root GitHub link; conflicts and ineligible records show none.
- Scheduled/full automation remains stdlib-only, LLM-free, and does not mutate tracked review state.
- Full tests and saved-data verifiers pass.
- Tracker/public commits are pushed and synchronized.
- Six live routes match committed bytes, unknown route returns 404, and browser interaction passes.
- Completed work is recorded under the correct dated `CHANGELOG.md` heading and `GOAL.md` is deleted.
