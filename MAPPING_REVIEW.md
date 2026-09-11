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

- PEAK: 72 Nexus and 156 Thunderstore records; 10 candidates reviewed; 8 mod pairs accepted; 2 rejected; 7 author-alias pairs added.
- R.E.P.O.: 143 Nexus and 159 Thunderstore records; 4 candidates reviewed; 3 mod pairs accepted; 1 rejected; 3 author-alias pairs added.
- Retro Rewind: 160 Nexus and 0 Thunderstore records; explicitly recorded as `single-source`; no candidates or mappings.
- TCG Card Shop Simulator: 160 Nexus and 22 Thunderstore records; 6 candidates reviewed; 4 mod pairs accepted; 2 rejected; 1 author-alias pair added.
- Valheim: 275 Nexus and 557 Thunderstore records; 79 candidates reviewed across four bounded tranches; 76 new mod pairs accepted; 3 rejected; 15 author-alias pairs added. Together with 41 existing pairs, Valheim now has 117 reciprocal mod pairs.

Total: 99 candidate pairs reviewed, 91 accepted, 8 rejected, and 26 reciprocal author-alias pairs added.

## Rejected pairs

These remain deliberately unmapped after fail-closed review:

- PEAK `nexus:13` ↔ `thunderstore:Roose/Piggyback`: title and summary match, but authors conflict without provenance linking the uploaders.
- PEAK `nexus:95` ↔ `thunderstore:quackandcheese/ItemSpawner`: generic item-spawner similarity and conflicting authors are insufficient.
- R.E.P.O. `nexus:39` ↔ `thunderstore:Tansinator/Map_Value_Tracker`: similar functionality, but materially different titles and conflicting authors lack identity evidence.
- TCG Card Shop Simulator `nexus:1193` ↔ `thunderstore:TCGPatch/TCGShopExpansionMod_0703_Patch`: similar patch purpose but conflicting authors and insufficient provenance.
- TCG Card Shop Simulator `nexus:1116` ↔ `thunderstore:GhostNarwhal/Enhanced_Binder_Sort`: different authors and different binder-feature scope.
- Valheim `nexus:1356` ↔ `thunderstore:Azumatt/AzuExtendedPlayerInventory`: generic inventory-expansion similarity does not establish the same implementation.
- Valheim `nexus:2625` ↔ `thunderstore:fedorovdgap/PlantEverything`: a translation and an unofficial rebuild/fork are not the same canonical artifact.
- Valheim `nexus:174` ↔ `thunderstore:Azumatt/AzuAutoStore`: related functionality but different titles, authors, and feature scope.

## Exhaustion and verification

After accepted pairs were applied, the scorer was rerun. The final all-game shortlist contained exactly the eight rejected pairs above and no unseen pair at or above `0.45`. Retro Rewind remained explicitly `single-source`.

Regeneration and strict verification succeeded for all five reports after applying mappings:

- PEAK: 220 canonical cards;
- R.E.P.O.: 299 canonical cards;
- Retro Rewind: 160 canonical cards;
- TCG Card Shop Simulator: 178 canonical cards;
- Valheim: 715 canonical cards.
