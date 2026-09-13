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

## 2026-09-12 fresh-corpus pass

The full saved corpus contained PEAK 72 Nexus/174 Thunderstore records, R.E.P.O. 143/166, Retro Rewind 161/0, TCG Card Shop Simulator 167/22, and Valheim 374/815. Two deterministic shortlist runs were byte-identical. Previously mapped records were excluded, and the pass iterated through bounded tranches of at most 20 candidates per game.

This initiative reviewed 37 newly surfaced mod candidates: 30 Valheim pairs were accepted and seven pairs were rejected. The 30 accepted Valheim pairs reduced the canonical card count exactly from 1,066 to 1,036. PEAK remained at 238 cards, R.E.P.O. at 305, Retro Rewind at 161, and TCG Card Shop Simulator at 185.

The independent full-corpus author track added 29 canonical cross-provider identities: 26 Valheim (`blacks7ar`, `cooleyy`, `deathwizsh`, `gemhunter1`, `goathedge`, `goldenrevolver`, `hyleanlegend`, `igentuman`, `kadrio`, `marsarah`, `midnightsfx`, `moddedwolf`, `nandor`, `nightkosh`, `nussbacker`, `ontrigger`, `patocino`, `pattpc`, `randyknapp`, `sakey391`, `spikehimself`, `stonaar`, `treextr`, `trentinidev`, `valheimmodding`, and `zellds`), two R.E.P.O. (`dirtygames`, `wellingtondiascf`), and one TCG (`definitezer0`). The `moddedwolf` identity contains two evidenced Nexus handles and one Thunderstore handle. Shared publisher, port-maintainer, and fork-maintainer accounts remain source-scoped rather than globally aliased.

Fifteen canonical groups gained pair-scoped creator attribution: Valheim `equipmentsheet`, `feastmaster`, `here-comes-the-vein`, `instant-monster-loot-drop`, `inventorylink`, `no-rain-damage`, `not-so-needy-crafting-station`, `planbuild`, `radialrebind`, `ship-config`, `station-range-plus`, `terrain-shaper-plus`, `terramizer`, and `terramizerserver`; plus R.E.P.O. `map-value-tracker`. Attribution is reciprocal within each mod pair and credits the evidenced creator without globally merging unrelated publisher profiles.

## Rejected pairs

These remain deliberately unmapped after fail-closed review:

- PEAK `nexus:13` ↔ `thunderstore:Roose/Piggyback`: title and summary match, but authors conflict without provenance linking the uploaders.
- PEAK `nexus:95` ↔ `thunderstore:quackandcheese/ItemSpawner`: generic item-spawner similarity and conflicting authors are insufficient.
- TCG Card Shop Simulator `nexus:1193` ↔ `thunderstore:TCGPatch/TCGShopExpansionMod_0703_Patch`: similar patch purpose but conflicting authors and insufficient provenance.
- TCG Card Shop Simulator `nexus:1116` ↔ `thunderstore:GhostNarwhal/Enhanced_Binder_Sort`: different authors and different binder-feature scope.
- Valheim `nexus:1356` ↔ `thunderstore:Azumatt/AzuExtendedPlayerInventory`: generic inventory-expansion similarity does not establish the same implementation.
- Valheim `nexus:2625` ↔ `thunderstore:fedorovdgap/PlantEverything`: a translation and an unofficial rebuild/fork are not the same canonical artifact.
- Valheim `nexus:174` ↔ `thunderstore:Azumatt/AzuAutoStore`: related functionality but different titles, authors, and feature scope.
- PEAK `nexus:25` (`PeakLobbies`) ↔ `thunderstore:tony4twenty/PEAK_Zombies`: scorer collision on the generic game-name token; unrelated lobby and zombie systems.
- Valheim `nexus:1068` ↔ `thunderstore:Muindor/DeathTweaks`: Thunderstore explicitly identifies a from-scratch reimplementation of aedenthorn's original, not the same artifact.
- Valheim `nexus:2394` ↔ `thunderstore:Iandmygears/Agility`: identical generic title but different authors, language, mechanics, and implementation scope.
- Valheim `nexus:3670` ↔ `thunderstore:MilkyTeam/EliteCreatures`: matching title/description/date but the rejected Thunderstore listing exposes no concrete source or creator provenance sufficient for fail-closed mapping.
- Valheim `nexus:3535` ↔ `thunderstore:Wynston/Hearthfolk`: independently authored packages with differing implementation scope; the corresponding Thunderstore package for the Nexus creator is under `Hadorn96`.
- Valheim `nexus:1125` ↔ `thunderstore:ShelledGhost/PlanBuild`: explicit Valheim 1.0 compatibility fork; the official `MathiasDecrock/PlanBuild` package is mapped instead.
- Valheim `nexus:332` ↔ `thunderstore:PONEIS/SmartContainers`: explicit unofficial community rebuild/maintenance fork; its corresponding Nexus fork is mod 3656, not original mod 332.

## Exhaustion and verification

After accepted pairs were applied, the scorer was rerun. The final all-game shortlist contained exactly 13 documented rejected pairs—three PEAK, two TCG Card Shop Simulator, and eight Valheim—and no unseen pair at or above `0.45`. The reviewed `ShelledGhost/PlanBuild` fork is additionally suppressed from the scorer because the official cross-provider PlanBuild pair is now mapped. R.E.P.O. had no remaining candidates, and Retro Rewind remained explicitly `single-source`.

Regeneration and strict verification succeeded for both report variants across all five games after applying the refreshed mod mappings, author aliases, and pair-scoped attribution. Generated release artifacts and `data/author-reputation.json` files are intentionally gitignored; the reciprocal JSON inputs are authoritative.

- PEAK: 238 canonical cards;
- R.E.P.O.: 305 canonical cards;
- Retro Rewind: 161 canonical cards;
- TCG Card Shop Simulator: 185 canonical cards;
- Valheim: 1,036 canonical cards.
