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

### `valheim-mod-nexus-164-ts-cjayride-instantmonsterlootdrop`

- `track`: `mod-pair`
- `game`: `valheim`
- `sources`: `nexus:164` — <https://www.nexusmods.com/valheim/mods/164>; `thunderstore:cjayride/InstantMonsterLootDrop` — <https://thunderstore.io/c/valheim/p/cjayride/InstantMonsterLootDrop/>
- `classification`: `possible-fork`
- `status`: `needs-recheck`
- `confidence`: `high`
- `evidence_for`: Same title and purpose; Thunderstore credits aedenthorn's original work.
- `evidence_against`: Thunderstore explicitly describes cjayride's package as a fork of aedenthorn's Nexus implementation.
- `next_evidence_needed`: First-party repository history or identical release artifacts proving this is an official continuation rather than a separate fork.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — removed from authoritative mappings by the complete legacy audit under the same-artifact-only rule.

### `repo-mod-nexus-39-ts-tansinator-map-value-tracker`

- `track`: `mod-pair`
- `game`: `repo`
- `sources`: `nexus:39` — <https://www.nexusmods.com/repo/mods/39>; `thunderstore:Tansinator/Map_Value_Tracker` — <https://thunderstore.io/c/repo/p/Tansinator/Map_Value_Tracker/>
- `classification`: `possible-port`
- `status`: `needs-recheck`
- `confidence`: `high`
- `evidence_for`: Same feature family and the Nexus page credits Tansinator's implementation.
- `evidence_against`: Nexus explicitly calls Lucario's package a MelonLoader port of Tansinator's original Thunderstore/BepInEx implementation.
- `next_evidence_needed`: First-party evidence that both listings distribute the same implementation and release lineage rather than separate loader-specific ports.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — removed from authoritative mappings by the complete legacy audit under the same-artifact-only rule.

### `valheim-mod-nexus-3009-ts-milkyteam-shipconfig`

- `track`: `mod-pair`
- `game`: `valheim`
- `sources`: `nexus:3009` — <https://www.nexusmods.com/valheim/mods/3009>; `thunderstore:MilkyTeam/ShipConfig` — <https://thunderstore.io/c/valheim/p/MilkyTeam/ShipConfig/>
- `classification`: `same-artifact-uncertain`
- `status`: `open`
- `confidence`: `medium`
- `evidence_for`: Exact title, behavior, initial version, and release timing; the listings were created minutes apart.
- `evidence_against`: Nexus credits gjglasgow while Thunderstore publishes under MilkyTeam, and the current Thunderstore page exposes no direct creator repository or Nexus mirror link.
- `next_evidence_needed`: A MilkyTeam package manifest, source repository, or first-party mirror statement linking the package to gjglasgow/Nexus 3009.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — removed from authoritative mappings after legacy audit because matching metadata did not establish publisher provenance.

### `valheim-mod-nexus-3639-ts-teamsmoochie-xportal-patched`

- `track`: `mod-pair`
- `game`: `valheim`
- `sources`: `nexus:3639` — <https://www.nexusmods.com/valheim/mods/3639>; `thunderstore:TeamSmoochie/XPortal_Patched` — <https://thunderstore.io/c/valheim/p/TeamSmoochie/XPortal_Patched/>
- `classification`: `same-artifact-uncertain`
- `status`: `open`
- `confidence`: `medium`
- `evidence_for`: Exact patched-project title, near-identical initial version and release timing, and compatible TeamSmoochie/ItsSmoochie publisher handles.
- `evidence_against`: Nexus 3639 is currently hidden; the Thunderstore package links Nexus 2239, the original XPortal listing, rather than Nexus 3639.
- `next_evidence_needed`: A first-party TeamSmoochie repository, manifest, or restored Nexus page directly linking both patched listings.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — removed from authoritative mappings after legacy audit because the only exposed Nexus link points to a different record.

### `peak-mod-nexus-13-ts-roose-piggyback`

- `track`: `mod-pair`
- `game`: `peak`
- `sources`: `nexus:13` — <https://www.nexusmods.com/peak/mods/13>; `thunderstore:Roose/Piggyback` — <https://thunderstore.io/c/peak/p/Roose/Piggyback/>
- `classification`: `same-artifact-uncertain`
- `status`: `open`
- `confidence`: `medium`
- `evidence_for`: Exact title and compatible distinctive summary.
- `evidence_against`: Different authors and no first-party mirror, repository, or ownership link.
- `next_evidence_needed`: A direct source/mirror link or matching package manifest identifying a shared release lineage.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — carried from the bounded mapping-pass rejection list into the durable queue.

### `tcg-mod-nexus-1193-ts-tcgpatch-expansion-0703`

- `track`: `mod-pair`
- `game`: `tcg-card-shop-simulator`
- `sources`: `nexus:1193` — <https://www.nexusmods.com/tcgcardshopsimulator/mods/1193>; `thunderstore:TCGPatch/TCGShopExpansionMod_0703_Patch` — <https://thunderstore.io/c/tcg-card-shop-simulator/p/TCGPatch/TCGShopExpansionMod_0703_Patch/>
- `classification`: `same-artifact-uncertain`
- `status`: `open`
- `confidence`: `low`
- `evidence_for`: Both describe a patch for the same expansion-mod feature family.
- `evidence_against`: Conflicting publishers and no source, mirror, manifest, or release-lineage evidence.
- `next_evidence_needed`: A first-party cross-link or matching repository/package identity proving one shared patch artifact.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — carried from the bounded mapping-pass rejection list into the durable queue.

### `valheim-mod-nexus-3670-ts-milkyteam-elitecreatures`

- `track`: `mod-pair`
- `game`: `valheim`
- `sources`: `nexus:3670` — <https://www.nexusmods.com/valheim/mods/3670>; `thunderstore:MilkyTeam/EliteCreatures` — <https://thunderstore.io/c/valheim/p/MilkyTeam/EliteCreatures/>
- `classification`: `same-artifact-uncertain`
- `status`: `open`
- `confidence`: `medium`
- `evidence_for`: Matching title, description, and release timing.
- `evidence_against`: The Thunderstore listing exposes no concrete source, mirror, or creator provenance linking it to the Nexus creator.
- `next_evidence_needed`: A first-party source repository, package manifest, or mirror statement linking both records.
- `first_reviewed`: `2026-09-13`
- `last_reviewed`: `2026-09-13`
- `history`: `2026-09-13` — carried from the bounded mapping-pass rejection list into the durable queue.

## Open author-identity reviews

No unresolved author-identity entries remain after the complete legacy audit. The next manual pass must still check this section before generating new candidates.

## Resolved-entry rule

When an entry is resolved, append its final history line, move the substantive disposition and evidence to `MAPPING_REVIEW.md`, then remove it from the open sections in the same commit. Git preserves prior queue history; `MAPPING_REVIEW.md` preserves the current durable rationale.
