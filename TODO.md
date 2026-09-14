# TODO

> Audited against implementation history through `9e9f10b`; all items below remain open.

## Deferred ideas

- [ ] Explore basing author reputation on more than lifetime downloads by adding an observed activity-span cap calculated as `(max(last update, last upload) - first upload)` in days. Decide whether this should cap the displayed rarity tier or be represented as a separate confidence/establishedness signal so strong new authors are not mislabeled as low quality.
