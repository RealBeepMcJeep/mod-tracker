# Cross-Provider Mapping Review

## Scope

This explicit manual pass reviewed saved Nexus Mods and Thunderstore records for every configured game. `scripts/mapping_candidates.py` generated deterministic shortlists capped at 20 pairs per game and pass, using a minimum aggregate score of `0.45`.

The scorer compared only Nexus↔Thunderstore pairs and used:

- normalized-title Levenshtein similarity;
- title-token overlap;
- description-token overlap;
- normalized-author Levenshtein similarity.

Only bounded summaries of at most 500 characters were included in the review artifact. Similarity output never wrote an authoritative mapping. Every accepted mod mapping and author alias was applied manually and reciprocally.

## Results

- PEAK: 72 Nexus and 158 Thunderstore records; 10 unique candidates reviewed; 8 mod pairs accepted; 2 rejected; 7 author-alias pairs added.
- R.E.P.O.: 143 Nexus and 160 Thunderstore records; 4 unique candidates reviewed; 4 mod pairs accepted; none rejected; 3 author-alias pairs added.
- Retro Rewind: 160 Nexus and 0 Thunderstore records; explicitly recorded as `single-source`; no candidates or mappings.
- TCG Card Shop Simulator: 160 Nexus and 22 Thunderstore records; 6 unique candidates reviewed; 4 mod pairs accepted; 2 rejected; 1 author-alias pair added.
- Valheim: 284 Nexus and 585 Thunderstore records; 85 unique candidates reviewed across five bounded tranches; 82 new mod pairs accepted; 3 rejected; 17 author-alias pairs added. Together with 41 existing pairs, Valheim now has 123 reciprocal mod pairs.

Total: 105 unique candidate pairs reviewed, 98 accepted, 7 rejected, and 28 reciprocal author-alias pairs added.

Follow-up report inspection added the exact-handle reciprocal alias `nexus:azumatt` ↔ `thunderstore:azumatt`. The earlier bounded candidate pass excluded the already-mapped BepInExPack mod pair, so it did not surface this author-only mapping; combining the two source-scoped profiles correctly makes Azumatt Legendary.

The 2026-09-11 full pass reviewed a bounded 14-pair refreshed shortlist. It accepted R.E.P.O.'s explicitly attributed `MoneyValueTracker` port plus six Valheim pairs (`StartSpawnOnDeath`, `Spyglass`, `StumpsRegrow`, `CartographySkill`, `XPortal_Patched`, and `PreciseRotation`). The three Advize author decisions reused an existing alias; concrete linked GitHub and Ko-fi evidence added only the new reciprocal `nexus:jd` ↔ `thunderstore:disregardthatisuck` alias. Unsupported uploader identities remained separate.

## Rejected pairs

These remain deliberately unmapped after fail-closed review:

- PEAK `nexus:13` ↔ `thunderstore:Roose/Piggyback`: title and summary match, but authors conflict without provenance linking the uploaders.
- PEAK `nexus:95` ↔ `thunderstore:quackandcheese/ItemSpawner`: generic item-spawner similarity and conflicting authors are insufficient.
- TCG Card Shop Simulator `nexus:1193` ↔ `thunderstore:TCGPatch/TCGShopExpansionMod_0703_Patch`: similar patch purpose but conflicting authors and insufficient provenance.
- TCG Card Shop Simulator `nexus:1116` ↔ `thunderstore:GhostNarwhal/Enhanced_Binder_Sort`: different authors and different binder-feature scope.
- Valheim `nexus:1356` ↔ `thunderstore:Azumatt/AzuExtendedPlayerInventory`: generic inventory-expansion similarity does not establish the same implementation.
- Valheim `nexus:2625` ↔ `thunderstore:fedorovdgap/PlantEverything`: a translation and an unofficial rebuild/fork are not the same canonical artifact.
- Valheim `nexus:174` ↔ `thunderstore:Azumatt/AzuAutoStore`: related functionality but different titles, authors, and feature scope.

## Exhaustion and verification

After accepted pairs were applied, the scorer was rerun. The final all-game shortlist contained exactly the seven rejected pairs above and no unseen pair at or above `0.45`. R.E.P.O. had no remaining candidates, and Retro Rewind remained explicitly `single-source`.

Regeneration and strict verification succeeded for all five local reports after applying the refreshed mappings. These generated release artifacts and `data/author-reputation.json` files are intentionally gitignored; the authoritative mapping inputs are the staged reciprocal JSON files.

- PEAK: 222 canonical cards;
- R.E.P.O.: 299 canonical cards;
- Retro Rewind: 160 canonical cards;
- TCG Card Shop Simulator: 178 canonical cards;
- Valheim: 746 canonical cards.
