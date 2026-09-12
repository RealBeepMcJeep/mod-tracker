# TODO

> Audited against implementation history through `5328c1a`; all items below remain open.

## Deferred ideas

- [ ] If cross-provider mapping work is explicitly requested, conduct one manual initiative with separate mod-pair and author-alias review tracks. Preserve current source-scoped identities and reciprocal mappings unless concrete evidence supports a change; use the bounded candidate generator only as advisory evidence and require manual confirmation.
- [ ] Explore basing author reputation on more than lifetime downloads by adding an observed activity-span cap calculated as `(max(last update, last upload) - first upload)` in days. Decide whether this should cap the displayed rarity tier or be represented as a separate confidence/establishedness signal so strong new authors are not mislabeled as low quality.
