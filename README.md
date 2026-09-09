# Thunderstore Mod Tracker

A zero-dependency Python tracker for the package cards on Thunderstore's Valheim listing.

The initial dataset indexes the first 10 pages sorted by **Last updated** and the first 10 pages sorted by **Most downloaded**. Duplicate packages are stored once while retaining their position in both ranked views.

## Card fields

- title, author, description, thumbnail URL
- package URL and author URL
- downloads (display text and parsed integer)
- likes (display text and parsed integer)
- last-updated display text
- categories/tags with filter URL and category ID
- pinned status
- sort mode, page, page position, and overall rank
- first/last observation timestamps and deleted status

Relative timestamps such as `7 minutes ago` are preserved exactly as observed; the snapshot timestamp provides their reference time.

## Source listing

https://thunderstore.io/c/valheim/

## Status

Implementation is tracked in [`todo.md`](todo.md).
