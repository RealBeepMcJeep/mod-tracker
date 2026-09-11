# TODO

## Optional validation and operations

- [ ] Repeat desktop and narrow-screen screenshot inspection when a working local browser runner is available.
- [ ] When a user-exported Nexus cookie file is available outside the repository, run a fresh Nexus collection and verify authenticated detail-page capture statuses.
- [ ] Review new mod or author cross-site mapping candidates only when explicitly requested; mapping discovery is not part of a routine manual pass.

## Deferred ideas

- [ ] Explore basing author reputation on more than lifetime downloads by adding an observed activity-span cap calculated as `(max(last update, last upload) - first upload)` in days. Decide whether this should cap the displayed rarity tier or be represented as a separate confidence/establishedness signal so strong new authors are not mislabeled as low quality.
