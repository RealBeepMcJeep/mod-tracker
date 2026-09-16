# TODO

> Audited against implementation history through `9e9f10b`; all items below remain open.

## Deferred ideas

- [ ] Add `https://valheim.hexium.gg/?sort=updated` as a Valheim provider, scraping its listing and mod-detail data alongside Nexus Mods and Thunderstore. Define stable identities, pagination, freshness timestamps, normalized fields, raw evidence retention, explicit cross-provider mappings, report links/filters, strict verification, and scheduled full-pass behavior without weakening the existing all-provider cohort gate.
- [ ] Explore basing author reputation on more than lifetime downloads by adding an observed activity-span cap calculated as `(max(last update, last upload) - first upload)` in days. Decide whether this should cap the displayed rarity tier or be represented as a separate confidence/establishedness signal so strong new authors are not mislabeled as low quality.
