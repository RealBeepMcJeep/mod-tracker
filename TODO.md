# TODO

## Current milestone

- [ ] Run and verify one live all-games collection.
- [ ] Publish and read back all five game reports.
- [ ] Push and verify the `public-artifacts` `main` branch.
- [ ] Verify exact per-game fresh/stored/card/source/error counts, isolation, byte equality, and a deliberate HTTP 404.

## Optional validation and operations

- [ ] Repeat desktop and narrow-screen screenshot inspection when a working local browser runner is available.
- [ ] When a user-exported Nexus cookie file is available outside the repository, run a fresh Nexus collection and verify authenticated detail-page capture statuses.
- [ ] Review new cross-site mapping candidates only when explicitly requested; mapping discovery is not part of a routine manual pass.
- [ ] Investigate a deterministic anonymous Nexus listing fallback; the current Nexus API requires authentication, so do not claim keyless fallback until a real equivalent source is validated.
