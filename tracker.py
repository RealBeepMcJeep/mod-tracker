#!/usr/bin/env python3
"""Track ranked Thunderstore package cards as flat files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def compact_number(text: str) -> int:
    """Convert card counts such as 1.5K and 6.4M to integers."""
    value = text.strip().replace(",", "")
    if not value:
        return 0
    suffixes = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    multiplier = suffixes.get(value[-1].upper(), 1)
    number = value[:-1] if multiplier != 1 else value
    return int(float(number) * multiplier)


class ListingParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.stack: list[dict] = []
        self.card: dict | None = None
        self.cards: list[dict] = []

    @staticmethod
    def _classes(attrs: dict[str, str | None]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs):
        attrs = dict(attrs)
        classes = self._classes(attrs)
        role = None

        if self.card is None and tag == "div" and "card-package" in classes:
            self.card = {
                "title": "", "author": "", "description": "",
                "thumbnail_url": "", "package_url": "", "author_url": "",
                "downloads_display": "", "downloads": 0,
                "likes_display": "", "likes": 0,
                "last_updated_display": "", "categories": [], "pinned": False,
            }
            role = "card"
        elif self.card is not None:
            if tag == "a" and "card-package__media" in classes:
                role = "media"
            elif tag == "a" and "card-package__title" in classes:
                role = "title"
            elif tag == "a" and "card-package__link" in classes:
                role = "author"
            elif tag == "a" and "tag--hoverable" in classes:
                role = "category"
            elif tag == "p" and "card-package__description" in classes:
                role = "description"
            elif "meta-item" in classes:
                role = "meta"
            elif tag == "span" and "card-package__updated" in classes:
                role = "updated"
            elif "tag" in classes:
                role = "badge"

            if tag == "img" and any(f.get("role") == "media" for f in self.stack):
                self.card["thumbnail_url"] = urljoin(self.base_url, attrs.get("src") or "")
            if tag == "svg" and attrs.get("data-icon"):
                for frame in reversed(self.stack):
                    if frame.get("role") in {"meta", "badge"}:
                        frame["icon"] = attrs["data-icon"]
                        break

        frame = {"tag": tag, "attrs": attrs, "role": role, "text": []}
        if tag not in VOID_TAGS:
            self.stack.append(frame)

    def handle_data(self, data: str):
        if self.card is None:
            return
        for frame in self.stack:
            if frame.get("role"):
                frame["text"].append(data)

    def handle_endtag(self, tag: str):
        if not self.stack:
            return
        index = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                index = i
                break
        if index is None:
            return
        frames = self.stack[index:]
        del self.stack[index:]
        for frame in reversed(frames):
            if frame.get("role"):
                self._finish_frame(frame)

    def _finish_frame(self, frame: dict):
        if self.card is None:
            return
        role = frame["role"]
        text = " ".join("".join(frame["text"]).split())
        attrs = frame["attrs"]
        href = urljoin(self.base_url, attrs.get("href") or "")

        if role == "media":
            self.card["package_url"] = href
        elif role == "title":
            self.card["title"] = text
            self.card["package_url"] = href
        elif role == "author":
            self.card["author"] = text
            self.card["author_url"] = href
        elif role == "description":
            self.card["description"] = text
        elif role == "category":
            query = parse_qs(urlparse(href).query)
            raw_id = (query.get("includedCategories") or [None])[0]
            self.card["categories"].append({
                "name": text,
                "id": int(raw_id) if raw_id and raw_id.isdigit() else None,
                "url": href,
            })
        elif role == "meta":
            icon = frame.get("icon")
            if icon == "download":
                self.card["downloads_display"] = text
                self.card["downloads"] = compact_number(text)
            elif icon == "thumbs-up":
                self.card["likes_display"] = text
                self.card["likes"] = compact_number(text)
        elif role == "updated":
            self.card["last_updated_display"] = text
        elif role == "badge" and (frame.get("icon") == "thumbtack" or text == "Pinned"):
            self.card["pinned"] = True
        elif role == "card":
            self.cards.append(self.card)
            self.card = None


def parse_listing(html: str, base_url: str = "https://thunderstore.io") -> list[dict]:
    parser = ListingParser(base_url)
    parser.feed(html)
    parser.close()
    return parser.cards


def parse_datetime(value: str) -> datetime:
    """Parse an API ISO-8601 timestamp as an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_nexus(
    node: dict, detail: dict | None, rank: int, collected_at: str
) -> dict:
    """Map Nexus GraphQL and v1 detail payloads to the common record."""
    detail = detail or {}
    source_id = str(node["modId"])
    category = detail.get("category_name") or node.get("category")
    return {
        "key": f"nexus:{source_id}",
        "source": "nexus",
        "source_id": source_id,
        "title": node.get("name") or detail.get("name") or "",
        "author": node.get("author") or detail.get("author") or "",
        "summary": node.get("summary") or detail.get("summary") or "",
        "description": detail.get("description") or "",
        "categories": [category] if category else [],
        "thumbnail": node.get("pictureUrl") or node.get("thumbnailUrl") or detail.get("picture_url") or "",
        "canonical_url": f"https://www.nexusmods.com/valheim/mods/{source_id}",
        "created_at": node.get("createdAt") or detail.get("created_timestamp"),
        "updated_at": node.get("updatedAt") or detail.get("updated_timestamp"),
        "total_downloads": int(node.get("downloads") or detail.get("mod_downloads") or 0),
        "unique_downloads": detail.get("unique_downloads"),
        "endorsements": int(node.get("endorsements") or detail.get("endorsement_count") or 0),
        "likes": None,
        "views": detail.get("views"),
        "version": node.get("version") or detail.get("version") or "",
        "file_size_kb": node.get("fileSize"),
        "adult_content": bool(node.get("adultContent", detail.get("contains_adult_content", False))),
        "rank": rank,
        "ranks": {"last-updated": rank},
        "pinned": False,
        "collected_at": collected_at,
        "raw_page_capture": detail.get("_raw_page_capture", {
            "status": "unavailable",
            "reason": "no authenticated cookie source supplied",
        }),
    }


def compute_rates(mod: dict, now: datetime) -> dict:
    """Compute comparable rates, using observed deltas for current versions.

    The current-version value is intentionally not an estimate of all downloads
    since release. It is the download delta per day between the first and latest
    persisted observations carrying the current version string.
    """
    created = parse_datetime(mod["created_at"])
    age_days = max((now - created).total_seconds() / 86400, 1 / 86400)
    observations = sorted(
        (item for item in mod.get("observations", []) if item.get("version") == mod.get("version")),
        key=lambda item: item["observed_at"],
    )
    observed_rate = None
    observed_delta = None
    baseline_at = observations[0]["observed_at"] if observations else None
    if len(observations) >= 2:
        elapsed = (
            parse_datetime(observations[-1]["observed_at"])
            - parse_datetime(observations[0]["observed_at"])
        ).total_seconds() / 86400
        if elapsed > 0:
            observed_delta = max(0, observations[-1]["downloads"] - observations[0]["downloads"])
            observed_rate = observed_delta / elapsed
    return {
        "lifetime_downloads_per_day": round(int(mod.get("total_downloads") or 0) / age_days, 6),
        "current_version_observed_downloads_per_day": (
            round(observed_rate, 6) if observed_rate is not None else None
        ),
        "current_version_observed_delta": observed_delta,
        "current_version_baseline_at": baseline_at,
        "rate_definition": "download delta/day between first and latest stored observations for the current version",
    }


def merge_mods(old: list[dict], fresh: list[dict], observed_at: str) -> list[dict]:
    """Merge fresh records and append idempotent download observations."""
    by_key = {item["key"]: dict(item) for item in old}
    for incoming in fresh:
        previous = by_key.get(incoming["key"], {})
        observations = list(previous.get("observations", []))
        observation = {
            "observed_at": observed_at,
            "downloads": int(incoming.get("total_downloads") or 0),
            "version": incoming.get("version") or "",
        }
        if not any(item.get("observed_at") == observed_at for item in observations):
            observations.append(observation)
        merged = dict(previous)
        merged.update(incoming)
        merged["observations"] = sorted(observations, key=lambda item: item["observed_at"])
        by_key[incoming["key"]] = merged
    return [by_key[key] for key in sorted(by_key)]


def atomic_write_json(path: Path, payload) -> None:
    """Write deterministic UTF-8 JSON using an atomic same-directory rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
