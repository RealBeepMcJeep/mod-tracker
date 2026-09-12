# TODO

## Optional validation and operations

- [ ] Repeat desktop and narrow-screen screenshot inspection when a working local browser runner is available.
- [ ] When a user-exported Nexus cookie file is available outside the repository, run a fresh Nexus collection and verify authenticated detail-page capture statuses.
- [ ] Add a simple unattended-run log retention policy if accumulated run directories become large enough to require pruning.
- [ ] Add automated pre/post-run digests for `mappings.json` and `author-mappings.json` if explicit mapping-immutability auditing is needed later.

## Deferred ideas

- [ ] Revisit cross-provider mod reconciliation as an explicitly requested manual project. Keep current reciprocal `mappings.json` records unchanged; use the existing bounded candidate generator only as advisory evidence and require manual confirmation before applying new pairs.
- [ ] Revisit the independent Nexus Mods ↔ Thunderstore author-identity audit separately from mod matching. Preserve source-scoped identities unless concrete evidence supports a reciprocal alias.
- [ ] If persistent mapping review is wanted later, design a smaller descriptor-bound review store from scratch with strict RED → GREEN tests. Do not restore the abandoned queue implementation directly; its temporary diagnostic patch is not production code.
- [ ] Explore basing author reputation on more than lifetime downloads by adding an observed activity-span cap calculated as `(max(last update, last upload) - first upload)` in days. Decide whether this should cap the displayed rarity tier or be represented as a separate confidence/establishedness signal so strong new authors are not mislabeled as low quality.
