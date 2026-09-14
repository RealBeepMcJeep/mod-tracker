# One-Time Valheim Mod Feature Matrix

**Status:** Specification only — not started.

**Goal:** Compile a one-time, standalone Valheim mod report that identifies map, tamed-pet, and nearby-storage behavior; records client/server requirements with evidence and confidence; and provides a fast sortable/filterable comparison table with known provider and source-repository links.

## Mandatory kickoff gate

Before implementation or classification begins:

1. invoke the **Grill Me** workflow;
2. resolve every open decision in this file with the user;
3. revise and simplify this specification from those answers;
4. obtain explicit approval of the revised scope.

Do not collect evidence, classify mods, add dependencies, write the compiler, or build the report before that gate passes.

## Deliverable boundary

- Produce one standalone HTML report intended to remain usable without a server or build process.
- This is a one-time research/compilation project, not a scheduled tracker feature.
- Do not add it to collection, report generation, publication automation, cron, or the normal mod-tracker runtime.
- Do not mutate existing mod mappings, author mappings, GitHub review decisions, or pending-review queues.
- Preserve the evidence behind every positive or uncertain classification so the report is auditable.
- Keep the report English-only and suitable for desktop and mobile use.

## Proposed artifacts

Final paths are subject to the kickoff grill, but the default shape is:

- `valheim-feature-review.json` — compact, evidence-backed classification records keyed by canonical mod identity.
- `scripts/compile-valheim-feature-report.py` — deterministic stdlib compiler with no network access.
- `reports/valheim-mod-feature-matrix.html` — self-contained report with embedded styles, behavior, and compiled data.
- `tests/test_valheim_feature_report.py` — stdlib `unittest` contract for the compiler and report.

The review dataset and compiler are preferred over hand-authoring a large HTML file because they make counts, evidence, and classifications reproducible. The report remains the only user-facing artifact.

## Corpus and row identity

At kickoff, decide whether “Valheim mods” means:

- only mods present in the current provider listing cohort;
- every retained historical Valheim record;
- or current mods by default with an optional historical filter.

Default proposal: one row per canonical mod, deduplicating only existing explicit Nexus/Thunderstore mappings. Unmapped source records remain separate. Do not infer new cross-provider matches for this report.

Every reviewed record must retain the exact underlying source keys so coverage can be reconciled against the selected corpus.

## Classification dimensions

Each row must classify the following independently. Do not infer one feature from another.

### Map

Whether the mod changes or extends map-related behavior. The kickoff grill must define boundaries such as:

- map display, pins, markers, exploration reveal, sharing, cartography, or navigation;
- world-map/terrain generation changes;
- minimap-only behavior;
- dependencies that expose map APIs but do not themselves provide a user-facing map feature.

### Tamed pets

Whether the mod changes tamed-creature or pet behavior. The kickoff grill must define whether this includes:

- taming mechanics or eligible creatures;
- commands, AI, following, combat, feeding, breeding, inventory, transport, or protection;
- broad creature mods whose tamed behavior is incidental;
- dependencies/frameworks without direct pet behavior.

### Nearby storage

Classify these as three separate feature columns:

1. **Craft from nearby chests** — recipes/building consume materials from nearby storage.
2. **Store to nearby chests** — collected or deposited items are routed into nearby storage.
3. **Restock from nearby chests** — player, station, or container inventories are replenished from nearby storage.

Do not collapse these into a generic “craft from containers” label. A mod can support any combination of the three.

## Cell states and evidence

Feature cells need at least three semantic states:

- **Yes** — evidence supports the feature.
- **No** — reviewed evidence indicates the feature is not provided.
- **Unknown** — evidence is absent, unclear, version-dependent, configurable, or conflicting.

Render the matrix with checkbox-like cells as requested, but preserve the tri-state distinction accessibly. A checked box means Yes, an empty box means No, and Unknown must have a visible `?`/label rather than looking like a confident No.

For every Yes or Unknown classification, retain:

- a concise evidence note;
- one or more evidence URLs when available;
- a confidence level: **High**, **Medium**, or **Low**;
- the evidence source type, such as provider description, README, repository documentation, configuration documentation, release notes, or cautious inference.

Negative classifications must not be fabricated from a title-only scan. The kickoff grill must decide how much evidence is required before assigning No instead of Unknown.

## Client/server requirement

Record one compatibility assessment per canonical mod:

- **Client only** — expected to work correctly without the server running the mod.
- **Server required** — server must run it for correct operation.
- **Server recommended / mixed** — some behavior works client-side but full or consistent behavior needs the server mod.
- **Unknown** — evidence does not establish deployment requirements.

Each assessment must include High/Medium/Low confidence and a short rationale. Do not equate Thunderstore’s `Client-side` or `Server-side` category labels with proof unless documentation supports the conclusion.

The report must clearly distinguish the compatibility assessment from the confidence in that assessment.

## Links and repository status

Include known links when available:

- Nexus Mods page;
- Thunderstore package page;
- approved canonical GitHub repository root.

Reuse only existing explicit provider identities/mappings and approved `github-repositories.json` decisions unless the kickoff grill authorizes a separate evidence review. Do not publish pending, conflicting, profile, dependency, framework, upstream, or otherwise unapproved GitHub candidates.

Add an **Open source repository** field/filter with at least:

- Yes — an approved repository link is known;
- No — reviewed `no_repository` decision;
- Unknown — unreviewed, stale-no-repository, ambiguous, or conflicting evidence.

The kickoff grill must decide whether “open source” means merely an approved public repository or requires an identifiable open-source license. Default recommendation: require a public repository plus a detectable license; otherwise label it “Repository known” rather than “Open source.”

## Update dates

Show the provider-reported last-updated date in the table. For mapped rows, the kickoff grill must decide between:

- one latest date across provider members;
- both provider dates;
- or one primary date with per-provider detail.

Default recommendation: sortable latest-known update date plus both provider-specific dates in row details.

Do not substitute collection time for provider update time. If useful after the current timestamp milestone, row details may separately expose `listing_seen_at` and `detail_fetched_at`.

## Report UI

The standalone report must include:

- a sortable table view;
- one row per selected canonical mod identity;
- checkbox-like cells for each feature dimension;
- visible and keyboard-accessible sort controls;
- filters for Map, Tamed pets, each of the three storage capabilities, server requirement, confidence, repository/open-source status, source provider, and update date;
- composable filters with a clear/reset action;
- a text search over mod title, author, and evidence notes;
- exact visible/total result counts;
- provider and repository links that do not make the whole row clickable;
- responsive behavior that remains usable on narrow screens;
- a legend explaining Yes/No/Unknown and confidence levels.

Sorting and filtering must operate over the complete compiled dataset without changing any classifications.

## Preact decision gate

Preact is **not approved yet**. Decide during the kickoff grill.

Default recommendation: start with plain HTML/CSS/JavaScript because this is a one-time standalone table and the project otherwise remains stdlib-only. Use Preact only if a small spike demonstrates materially simpler state management or better performance on the real row count.

If Preact is selected:

- pin the exact version;
- bundle it into the standalone artifact rather than loading a CDN at runtime;
- document the build/reproducibility path;
- keep the compiler deterministic;
- compare output size, first render, filter latency, and maintainability against the plain-JavaScript spike;
- do not add Preact to the normal tracker runtime.

## Research procedure

After the Grill Me gate:

1. Freeze and count the selected Valheim corpus.
2. Resolve rows using only existing explicit mappings.
3. Extract current stored descriptions, summaries, provider metadata, approved repositories, and update timestamps.
4. Create a deterministic candidate shortlist using feature terms only as discovery aids, never as final classifications.
5. Review every selected row or explicitly define a reconciled exclusion rule; do not report only keyword hits as complete coverage.
6. Inspect provider descriptions and approved repository documentation as needed.
7. Record classifications, evidence, compatibility, and confidence in the review dataset.
8. Independently audit all positive classifications plus a reproducible sample of No/Unknown rows.
9. Resolve or downgrade material disagreements before compilation.
10. Compile the standalone report offline from the frozen review dataset.

## Milestones

### Milestone 1 — Grill, definitions, and frozen corpus

- Run Grill Me and revise this specification.
- Fix the exact corpus, row identity, feature boundaries, No-versus-Unknown evidence threshold, server compatibility vocabulary, open-source definition, update-date presentation, and Preact decision.
- Record exact starting counts and evidence sources.
- Independently review the simplified specification before implementation.

### Milestone 2 — Evidence-backed classification dataset

- Define and validate the minimal review schema.
- Compile the full selected corpus with source keys and canonical grouping.
- Classify map, pet, and three storage capabilities separately.
- Add compatibility assessment, confidence, rationale, links, repository status, and update dates.
- Reconcile exact corpus counts.
- Audit all positive classifications and a reproducible negative/unknown sample.
- Commit the verified dataset milestone and move completed scope to `CHANGELOG.md`.

### Milestone 3 — Standalone report

- Build the deterministic offline compiler test-first.
- Render the sortable/filterable accessible matrix and supporting notes.
- Verify every row/cell/link against the review dataset.
- Exercise representative filter combinations, sorting, reset, search, mobile layout, and large-corpus performance in a real browser.
- Record exact row and classification counts in `CHANGELOG.md`.
- Commit/push the completed report and delete this file after the definition of done passes.

## Required RED→GREEN coverage

- Corpus identity and exact count reconciliation.
- Existing mapped records produce one row; unmapped records remain separate.
- Independent Yes/No/Unknown values for all five feature columns.
- Unknown is visually and accessibly distinct from No.
- Compatibility status and confidence are independent fields.
- Approved GitHub links render; pending/conflicting/unreviewed links do not.
- Nexus and Thunderstore links remain associated with the correct row.
- Repository/open-source filter follows the approved definition.
- Update-date sorting handles missing dates and timezone-equivalent instants deterministically.
- Every filter composes with text search and sorting.
- Reset restores the full default result set.
- Table cells and controls are keyboard accessible.
- Compiler output is deterministic and self-contained.
- Tampering with compiled feature values, links, row identities, or counts fails verification.

## Final definition of done

- Grill Me decisions are reflected in a simplified approved specification.
- The selected Valheim corpus is reconciled exactly with no silent omissions.
- Every included row has five independent feature classifications.
- Every positive or uncertain classification has an evidence note and confidence.
- Every row has a client/server assessment with confidence and rationale.
- Known approved Nexus, Thunderstore, and GitHub links are correctly associated.
- Repository/open-source status is defined honestly and filterable.
- Provider update dates are visible and sortable.
- The standalone report is deterministic, self-contained, responsive, keyboard usable, sortable, searchable, and filterable.
- Independent audit finds no unresolved material false-positive classifications.
- Tests, static checks, dataset validation, exact-count reconciliation, and browser interaction pass.
- Completed work is summarized under the correct dated `CHANGELOG.md` heading and this file is deleted.
