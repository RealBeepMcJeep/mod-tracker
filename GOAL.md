# Verified GitHub Repository Links Implementation Plan

> **For Hermes:** Use subagent-driven development to implement this plan task-by-task with RED → GREEN TDD and focused independent review at each milestone.

**Goal:** Discover, review, persist, and display one trustworthy GitHub repository root for every mod with sufficient provider-page evidence, without mislabeling dependencies, frameworks, upstream projects, forks, author profiles, or related mods as the mod's own repository.

**Architecture:** Extend the existing Nexus and Thunderstore detail-data path rather than add a second scraper. Repair and backfill Thunderstore README extraction; refresh provider detail evidence only when the provider's mod update/version changes; deterministically extract GitHub candidates and evidence fingerprints; keep authoritative reviewed decisions in per-game tracked flat JSON; use a manual, bounded LLM review pass for high-confidence decisions and a tracked Markdown queue for ambiguity. The scheduled tracker remains deterministic, stdlib-only, and LLM-free.

**Tech stack:** Python 3 standard library, JSON/Markdown flat files, `unittest`, existing tracker collector/report/verifier, existing atomic static-site publisher.

**Plan date:** 2026-09-13 MST

---

## Difficulty and current facts

**Complexity:** Medium. Expected implementation and verification effort is roughly one to two focused engineering days, plus the one-time batched evidence review. Rendering a link is easy; provenance, stale-evidence handling, safe backfill, and fail-closed verification are the material work.

Current saved corpus at planning time:

- 2,345 normalized records: 995 Nexus Mods and 1,350 Thunderstore.
- Nexus descriptions are populated for 994/995 records.
- Thunderstore descriptions are populated for 0/1,350 records because current package markup no longer uses the `markdown-body` class expected by `ReadmeParser`.
- Saved raw captures include 996 Nexus detail JSON files and 1,496 Thunderstore package HTML/metrics pairs.
- Existing normalized text already exposes 241 mods with GitHub links and 214 distinct repository roots, but 52 mods mention multiple roots.
- Existing evidence includes issue/PR, release, tree/blob, profile, dependency, framework, upstream, port, fork, and related-project links. A raw `github.com` match is not sufficient provenance.
- Nexus detail JSON is currently fetched only for a newly discovered ID; it must also refresh when the provider update timestamp changes.
- Thunderstore package detail HTML already refreshes when `latest_version` changes.

---

## Approved product behavior

### Repository link

1. Display at most one simple `GitHub` text link beside the existing Nexus Mods/Thunderstore source links on a mod card.
2. Link only to a normalized `https://github.com/<owner>/<repository>` repository root.
3. Limit this feature to `github.com`; do not generalize to GitLab, Codeberg, gists, or arbitrary source hosts.
4. A single-source card may show an approved repository from that source's evidence.
5. A mapped cross-provider card may show one approved root when:
   - both providers approve the same root; or
   - only one provider has approved repository evidence and the other has no conflicting approved candidate.
6. If mapped provider records approve different roots, hide the canonical GitHub link and queue the conflict.
7. Normalize deep links under `/issues`, `/pull`, `/releases`, `/tree`, `/blob`, and similar paths to the repository root, while retaining the exact original evidence URL internally.

### Review policy

1. Publish only high-confidence repository associations.
2. A manual batched LLM pass may directly approve high-confidence cases; ambiguous cases require later user review.
3. The LLM may select only from deterministically extracted candidates. It may not invent or repair an owner/repository token.
4. Deterministic application must reject decisions whose source key, candidate root, evidence URL, or evidence fingerprint does not match current extracted evidence.
5. Persist explicit reviewed `no_repository` outcomes so unchanged records are not repeatedly reviewed.
6. Review once per evidence fingerprint. Requeue only when relevant GitHub URLs or their context changes.
7. Keep a previously approved repository visible while changed evidence is pending. Remove or replace it only after explicit reviewed evidence disproves or supersedes it.
8. Perform a sampled independent audit of auto-approved decisions before final publication.
9. Keep ambiguous items in project-root `PENDING_GITHUB_REVIEW.md` with stable IDs, exact source keys, candidates, evidence summaries, conflict state, and resolution instructions.

### Collection and freshness

1. Repair Thunderstore README extraction for current markup while retaining support for the older fixture shape.
2. Offline-reparse all saved Thunderstore package captures and backfill the complete stored corpus. Do not require 1,350 forced network requests.
3. After backfill, run one normal fresh all-game data pass so currently changed provider pages are fetched under the corrected behavior.
4. Refresh an existing Nexus detail response whenever its provider `updated_at` value advances, not merely when the mod ID is new.
5. Continue refreshing Thunderstore package details when `latest_version` changes.
6. Collection may update normalized evidence/candidate state, but scheduled runs must never invoke an LLM or mutate authoritative review JSON/Markdown.

---

## Explicit exclusions

- No GitHub API dependency in scheduled collection or report generation.
- No runtime LLM calls, vector database, embeddings, or semantic classifier.
- No automatic repository choice from title/author string similarity alone.
- No indexing every GitHub link as a card link.
- No dependency, framework, upstream, fork, port source, issue tracker, author profile, organization profile, or companion-mod link unless reviewed as the primary repository for this exact mod.
- No multiple repository links or expandable related-links UI.
- No automatic replacement/removal of a previously approved link solely because the evidence fingerprint changed.
- No cross-game repository inference and no modification of existing Nexus↔Thunderstore mod/author mappings.
- No forced full refetch of every unchanged Thunderstore package page.

---

## Data model

### Normalized record evidence

Add deterministic fields to each normalized mod record:

```json
{
  "github_evidence": {
    "fingerprint": "sha256:<hex>",
    "candidates": [
      {
        "repository_url": "https://github.com/owner/repository",
        "evidence_url": "https://github.com/owner/repository/releases/tag/v1.2.3",
        "path_type": "release",
        "source_field": "description",
        "context": "bounded normalized text surrounding the link"
      }
    ]
  }
}
```

Rules:

- Candidate order is deterministic by first evidence occurrence, then canonical URL.
- Extract links from HTML `href`, Nexus BBCode URL forms, and plaintext URLs.
- Strip trailing punctuation, query, fragment, `.git`, and subpaths after owner/repository.
- Require HTTPS `github.com`, exactly valid nonempty owner/repository path components, and reject profile-only URLs.
- Retain every evidence occurrence needed for judgment, but deduplicate canonical repository roots.
- Build the fingerprint from canonical JSON containing repository root, original evidence URL, path type, source field, and normalized bounded context. Unrelated description edits outside those windows must not trigger review.
- Empty evidence has a stable fingerprint and an empty candidate list.

### Authoritative review state

Create one tracked `github-repositories.json` per game root, parallel to existing mapping files. Root Valheim remains at project root; other games use `games/<game>/github-repositories.json`.

```json
{
  "version": 1,
  "records": {
    "nexus:79": {
      "status": "approved",
      "repository_url": "https://github.com/owner/repository",
      "reviewed_fingerprint": "sha256:<hex>",
      "selected_evidence_urls": ["https://github.com/owner/repository/..."],
      "review_method": "llm-high-confidence",
      "confidence": "high",
      "rationale": "Concise evidence-backed reason"
    },
    "thunderstore:Author/Package": {
      "status": "no_repository",
      "repository_url": null,
      "reviewed_fingerprint": "sha256:<hex>",
      "selected_evidence_urls": [],
      "review_method": "llm-high-confidence",
      "confidence": "high",
      "rationale": "Only dependency/framework repositories are referenced"
    }
  }
}
```

Allow statuses `approved`, `no_repository`, and `retired`. Current evidence fingerprint equality means reviewed/current; inequality means stale/pending. A stale `approved` entry remains eligible for display unless retired or a mapped-card conflict exists. A stale `no_repository` entry returns to review.

### Review queue

`PENDING_GITHUB_REVIEW.md` entries use stable IDs derived from game, source key, and evidence fingerprint prefix. Each entry contains:

- stable ID and status;
- game and exact source key(s);
- current evidence fingerprint;
- normalized candidate roots;
- original evidence URL(s), path types, and bounded context;
- mapped-provider relationship, if any;
- reason automatic review declined or detected a conflict;
- prior approved root, if retained while stale;
- explicit resolution syntax/process.

Do not let scheduled collection edit this tracked file. The manual review command regenerates/reconciles it from current evidence and authoritative state.

---

## Milestone 1: Repair detail extraction and refresh behavior

**Objective:** Recover complete provider description evidence and prevent future stale Nexus descriptions.

**Files:**

- Modify: `tracker.py` (`ReadmeParser`, `parse_thunderstore_detail`, `collect_thunderstore`, `collect_nexus`, normalization/merge paths)
- Modify: `tests/test_collectors.py`
- Modify: `tests/test_core.py`
- Add sanitized current Thunderstore HTML fixtures inline or under the existing test-fixture convention only if needed.

**TDD slices:**

1. Add a failing current-markup Thunderstore detail fixture proving README HTML/text and links are extracted; retain the legacy `markdown-body` fixture.
2. Implement a semantic current-markup parser boundary without scraping unrelated navigation/footer content.
3. Add malformed/truncated/no-README cases and prove the parser fails safely to an empty description while timestamps still parse.
4. Add a failing Nexus collector test: unchanged `updated_at` reuses saved detail; advanced `updated_at` fetches and replaces detail exactly once.
5. Implement update-aware Nexus detail refresh while preserving pacing, raw-before-normalize persistence, aggregate failure semantics, and credentials outside logs.
6. Add Thunderstore version-change and unchanged-version regression assertions around the repaired parser.
7. Verify normalized descriptions are replaced from repaired raw evidence without damaging observations, mappings, attribution, or source metrics.

**Focused verification:**

```bash
python3 -m unittest tests.test_collectors tests.test_core
python3 -m py_compile tracker.py
```

**Milestone commit:** Parser/refresh code and tests only. Push after focused/full verification and independent review.

---

## Milestone 2: Deterministic GitHub evidence extraction

**Objective:** Produce complete, reproducible GitHub repository candidates and evidence fingerprints without selecting a canonical repository.

**Files:**

- Modify: `tracker.py` or add a small project-local stdlib module such as `github_evidence.py` if extraction would otherwise make `tracker.py` shallower rather than deeper.
- Add: `tests/test_github_evidence.py`
- Modify: `tests/test_core.py`

**TDD slices:**

1. Parse HTML anchors, Nexus BBCode URLs, and plaintext URLs.
2. Normalize repository roots from root/release/issue/PR/tree/blob/raw-looking paths while preserving original evidence URL and path type.
3. Reject profiles, malformed paths, non-GitHub hosts, credentials, non-HTTPS lookalikes, gists, and URLs without both owner and repository.
4. Deduplicate roots while preserving every evidence occurrence needed for review.
5. Extract bounded normalized context around each occurrence.
6. Prove deterministic candidate order and fingerprints across dictionary ordering and inconsequential non-evidence text changes.
7. Prove relevant URL/context changes alter the fingerprint.
8. Integrate evidence into both Nexus and Thunderstore normalized records through one shared source-agnostic path.
9. Extend strict saved-data verification to recompute evidence from retained descriptions and reject missing/tampered candidate data.

**Focused verification:**

```bash
python3 -m unittest tests.test_github_evidence tests.test_core tests.test_tracker
python3 -m py_compile tracker.py github_evidence.py
```

Omit `github_evidence.py` from commands if extraction remains in `tracker.py`.

---

## Milestone 3: Authoritative review state and manual queue tooling

**Objective:** Make LLM review bounded, durable, auditable, and impossible to apply outside extracted evidence.

**Files:**

- Add: project-root and four per-game `github-repositories.json`
- Add: `PENDING_GITHUB_REVIEW.md`
- Add: `scripts/github-review.py` (candidate export, validated decision application, queue reconciliation; no LLM SDK/runtime dependency)
- Add: `tests/test_github_review.py`
- Modify: `.gitignore` to explicitly allowlist required tracked files if needed
- Modify: `AGENTS.md` with the manual GitHub-review pass vocabulary

**TDD slices:**

1. Validate schemas, exact source keys, canonical repository roots, allowed statuses, required fingerprints, evidence membership, and rationale/confidence fields.
2. Reject invented candidate URLs, repaired source IDs, missing records, cross-game keys, unsupported hosts, profile URLs, and stale decision fingerprints.
3. Export deterministic bounded review batches containing all candidate roots and evidence context for each unreviewed/changed source record.
4. Apply only `high`-confidence LLM approvals/no-repository decisions; route every lower-confidence, malformed, conflicting, or uncertain result to Markdown.
5. Preserve a previous `approved` root when its fingerprint changes; mark it stale and queue the new evidence.
6. Requeue stale `no_repository` outcomes.
7. Detect mapped-provider conflicts without mutating existing cross-provider mappings.
8. Reconcile `PENDING_GITHUB_REVIEW.md` idempotently: stable IDs, no duplicate open entries, resolved entries removed only after valid authoritative application.
9. Prove no review command is called by `collect`, `report`, `verify`, `manual-pass.py`, or `unattended_run.py`.
10. Verify ignored/tracked file boundaries with `git check-ignore -v` and exact staged-file allowlists.

**Manual review workflow:**

1. Generate bounded JSON review batches into `/tmp`, not the repository.
2. Dispatch LLM reviewers over batches with complete evidence and the explicit relationship taxonomy.
3. Accept direct decisions only when confidence is high and the candidate is evidence-bound.
4. Run deterministic decision validation before any authoritative write.
5. Independently audit a reproducible sample of auto-approved and no-repository decisions, including all multiple-root and dependency-language cases in the sample boundary.
6. Apply validated decisions and regenerate the tracked ambiguous queue.
7. Report exact totals: records scanned, no-link, approved, explicit no-repository, ambiguous, conflicts, stale retained approvals, rejected LLM outputs, and sampled-audit findings.

---

## Milestone 4: Offline Thunderstore backfill and corpus review

**Objective:** Recover all stored Thunderstore descriptions/evidence and complete the initial repository review without unnecessary provider traffic.

**Files:**

- Add: `scripts/backfill-thunderstore-descriptions.py` or equivalent narrow command
- Add: `tests/test_description_backfill.py`
- Generated/ignored: normalized `data/mods.json`, snapshots/verification artifacts as existing project conventions require
- Tracked: per-game `github-repositories.json`, `PENDING_GITHUB_REVIEW.md`

**TDD slices and rehearsal:**

1. Dry-run fixture proves the backfill reads only saved raw package captures and performs no network calls.
2. Backfill matches raw packages to exact game/source keys and rejects cross-game/path traversal/malformed captures.
3. Preserve records without raw captures and report them explicitly; never erase existing nonempty descriptions on parse failure.
4. Preserve observations, manual mappings, credited authors, metrics, and collection timestamps unless the canonical existing merge rules intentionally recompute a derived field.
5. Run the offline backfill over all five game roots.
6. Recompute and strictly verify GitHub evidence for every normalized record.
7. Generate LLM review batches; apply high-confidence decisions; run sampled independent audit; write ambiguous queue.
8. Re-run the same backfill/review scan and prove idempotence: no unexplained data or queue changes.
9. Record exact corpus totals and missing-raw exceptions before proceeding.

**Stop conditions:** Any source-key mismatch, lost observation/mapping, parser collapse, unexplained candidate-count decrease, invalid LLM decision, or failed sample audit blocks report work and publication.

---

## Milestone 5: Card rendering and strict verification

**Objective:** Display only valid canonical repository links and make report verification fail closed.

**Files:**

- Modify: `tracker.py` (`apply_manual_mappings`/group preparation as appropriate, `render_report`, report parser/verifier, `generate_report`, `verify_output`)
- Modify: `tests/test_report.py`
- Modify: `tests/test_tracker.py`

**TDD slices:**

1. Single-source approved/current repository renders one `GitHub` anchor beside source links.
2. Deep evidence URL renders the normalized repository root.
3. No-repository, unreviewed, ambiguous, retired, and invalid decisions render no link.
4. Stale previously approved decision remains visible while pending.
5. Mapped cards with matching approvals render one deduplicated link.
6. Mapped cards with one approved root and no conflicting root render one link.
7. Mapped cards with conflicting approved roots render no GitHub link and are reported as conflict state.
8. Card/report output escapes URLs and attributes; use explicit anchors, no nested pseudo-link behavior.
9. Strict verifier independently derives expected repository links from records, authoritative state, evidence fingerprints, and mappings; it rejects added, removed, duplicated, cross-card, non-root, or altered links.
10. Tamper tests cover href replacement, label-only spoofing, duplicate links, profile/deep URL substitution, stale-state behavior, and mapped conflicts.
11. Both embedded and hotlinked reports remain byte-contract-valid under existing report verification.

**Focused verification:**

```bash
python3 -m unittest tests.test_report tests.test_tracker tests.test_github_review
python3 tracker.py report --game all --output-root .
python3 tracker.py verify --game all --output-root .
```

---

## Milestone 6: Fresh pass, publication, and completion

**Objective:** Exercise the corrected live collection path, publish the complete verified cohort atomically, and close the goal.

1. Verify the Nexus key file is nonempty and mode `0600` without printing its value.
2. Confirm tracker and public-artifacts repositories are clean, on `main`, and synchronized.
3. Run one normal fresh all-game pass after the offline backfill. This must:
   - refresh current listings;
   - fetch changed Nexus details by provider update timestamp;
   - fetch changed Thunderstore details by version;
   - retain existing reviewed repository state without running an LLM;
   - generate and strictly verify all reports.
4. Run the manual GitHub review scan once more for evidence changed by the fresh pass. Apply new high-confidence decisions and queue ambiguity; rerun generation/verification if authoritative state changed.
5. Run full gates:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile tracker.py scripts/*.py
python3 -m json.tool games.json >/dev/null
git diff --check
python3 tracker.py report --game all --output-root .
python3 tracker.py verify --game all --output-root .
```

6. Independently review parser boundaries, refresh decisions, evidence normalization/fingerprints, authoritative writes, queue reconciliation, grouped-card conflict behavior, renderer/verifier parity, and credential/network safety.
7. Commit and push verified implementation/config/review artifacts using exact file allowlists; generated data remains ignored according to project conventions.
8. Stage the complete six-route `/mod-tracking/` tree from verified hotlinked reports.
9. Run one atomic publisher dry run, then one real commit/deploy, then push public-artifacts.
10. Verify all six canonical URLs return HTTP 200 and exact committed bytes; verify a nonexistent route returns HTTP 404.
11. Browser-check a high-card report for:
    - ordinary Nexus and Thunderstore GitHub links;
    - mapped-card deduplication;
    - no link on a known ambiguous/conflicting case;
    - repository-root hrefs;
    - preserved search/filter/pagination/author behavior.
12. Reconcile `TODO.md` and add a dated `CHANGELOG.md` entry with exact review and publication counts.
13. Check off all milestones here, summarize the completed goal in `CHANGELOG.md`, and delete `GOAL.md` in the final docs commit.

---

## Risks and controls

- **False canonical association:** Fail closed; evidence-bound decisions only; dependency/multiple-root cases enter review; sample audit before publication.
- **Thunderstore parser drift:** Support legacy and current markup with sanitized fixtures; verify extraction boundaries, not a brittle class substring alone.
- **Nexus quota/load:** Refresh details only when provider update time advances; do not refetch every old detail in the initial backfill.
- **Description churn:** Fingerprint only relevant URLs/path types/context; keep prior approved link pending explicit supersession.
- **LLM hallucination:** Candidate allowlist plus exact fingerprint/source-key validation makes invented output unapplicable.
- **Mapped-card disagreement:** Never pick a provider winner; suppress the canonical link and queue the conflict.
- **Scheduled repository dirtiness:** Scheduled collection updates ignored normalized evidence only; tracked JSON/Markdown changes occur solely in explicit manual review passes.
- **Backfill damage:** Offline/no-network rehearsal, copy-on-write/atomic JSON updates, preservation tests, exact before/after counts, and idempotence check.
- **Verifier self-consistency trap:** Recompute evidence and expected rendered roots independently from retained description plus authoritative state; do not validate generated artifacts only against themselves.

---

## Definition of done

- [ ] Current and legacy Thunderstore README fixtures parse correctly.
- [ ] Every saved Thunderstore raw package capture has been considered by the offline backfill; exceptions are enumerated exactly.
- [ ] Existing Nexus descriptions are retained and future details refresh when provider update timestamps advance.
- [ ] Every normalized record has deterministic GitHub evidence and a reproducible fingerprint.
- [ ] Every reviewed record has a valid `approved`, `no_repository`, or `retired` authoritative outcome bound to exact evidence.
- [ ] High-confidence LLM decisions pass deterministic validation and sampled independent audit.
- [ ] Every ambiguous, stale-no-repository, or mapped-conflict case is represented once in `PENDING_GITHUB_REVIEW.md` with a stable ID.
- [ ] Reports show at most one repository-root `GitHub` link per eligible card and none for ineligible/conflicting cards.
- [ ] Strict verification detects every tested form of GitHub-link tampering.
- [ ] Scheduled/full collection remains deterministic, stdlib-only, LLM-free, and does not mutate tracked review artifacts.
- [ ] Offline backfill and review regeneration are idempotent.
- [ ] One normal fresh all-game pass succeeds after backfill.
- [ ] Full tests, compile, JSON, whitespace, saved-data report, and independent-review gates pass.
- [ ] Tracker and public-artifacts commits are pushed and synchronized.
- [ ] All six live routes exactly match committed files; unknown route returns 404; browser behavior is verified.
- [ ] `TODO.md`/`CHANGELOG.md` are reconciled and `GOAL.md` is removed only after every item above is complete.
