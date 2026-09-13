# Pending Mapping Review

This is the durable follow-up queue for cross-provider mod and author decisions that are genuinely uncertain, disputed, or removed from authoritative mappings pending stronger evidence. It is reviewed manually; it is not consumed by collection, report generation, scheduled jobs, or any automatic mapping process.

## Required process

At the start of every explicitly requested manual mapping pass:

1. Read this file before generating new similarity candidates.
2. Revalidate each open entry against current provider pages, linked repositories, package manifests/source metadata, author profiles, and explicit mirror/port statements.
3. Update `last_reviewed`, evidence, confidence, status, and disposition history even when the decision does not change.
4. Resolve an entry into authoritative `mappings.json` or `author-mappings.json` only when evidence establishes the same artifact or same person/team.
5. If evidence establishes a fork, successor, reimplementation, translation, publisher, uploader, or unrelated collision, retain separate identities and close the entry as `confirmed-separate` in `MAPPING_REVIEW.md`.
6. If evidence proves creator credit without proving profile identity, use reciprocal pair-scoped `credited_author`; do not create a global author alias.
7. Review pending entries before scoring unseen candidates so old uncertainty is not indefinitely hidden by the shortlist cap.
8. Never remove an entry without recording its final disposition in the history and durable review record.

## Entry schema

Each entry must contain:

- `id`: stable lowercase identifier such as `valheim-mod-nexus-123-ts-team-package`.
- `track`: `mod-pair` or `author-identity`.
- `game`: configured game key.
- `sources`: exact source-scoped keys and canonical URLs/profile URLs.
- `classification`: current best description, such as `same-artifact-uncertain`, `possible-fork`, `publisher-vs-creator`, or `identity-uncertain`.
- `status`: `open`, `blocked`, or `needs-recheck` while pending.
- `confidence`: `high`, `medium`, or `low`, describing confidence in the current provisional classification—not pressure to accept a mapping.
- `evidence_for`: concrete facts supporting a shared artifact/identity.
- `evidence_against`: concrete facts supporting separation or uncertainty.
- `next_evidence_needed`: the smallest specific evidence that could resolve the entry.
- `first_reviewed` and `last_reviewed`: `YYYY-MM-DD` in Phoenix local date.
- `history`: dated append-only disposition notes.

Confidence meanings:

- `high`: multiple direct primary-source links or explicit provenance statements support the provisional classification.
- `medium`: distinctive metadata aligns, but direct ownership/artifact provenance is missing or conflicting.
- `low`: mostly title/function/handle similarity; insufficient for authoritative mapping.

## Open mod-pair reviews

Entries are added here by the complete legacy audit. An empty section means there are no unresolved mod-pair decisions, not that future passes may skip checking this file.

## Open author-identity reviews

Entries are added here by the complete legacy audit. An empty section means there are no unresolved author-identity decisions, not that future passes may skip checking this file.

## Resolved-entry rule

When an entry is resolved, append its final history line, move the substantive disposition and evidence to `MAPPING_REVIEW.md`, then remove it from the open sections in the same commit. Git preserves prior queue history; `MAPPING_REVIEW.md` preserves the current durable rationale.
