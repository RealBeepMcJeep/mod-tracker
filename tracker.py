#!/usr/bin/env python3
"""Track ranked Thunderstore package cards as flat files."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
import base64
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urljoin, urlparse

from github_evidence import extract_github_evidence
from zoneinfo import ZoneInfo


GAME_CONFIG_PATH = Path(__file__).with_name("games.json")
REQUIRED_GAME_KEYS = {
    "valheim", "repo", "peak", "retro-rewind", "tcg-card-shop-simulator"
}
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def load_game_registry(path: Path = GAME_CONFIG_PATH) -> dict[str, dict]:
    """Load the version-controlled game registry."""
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict):
        raise ValueError("game registry must be a JSON object")
    missing_games = REQUIRED_GAME_KEYS - set(registry)
    if missing_games:
        raise ValueError("game registry is missing: " + ", ".join(sorted(missing_games)))
    output_paths = set()
    publication_paths = set()
    for key, config in registry.items():
        if not SLUG_RE.fullmatch(key) or not isinstance(config, dict):
            raise ValueError(f"invalid game entry: {key!r}")
        required = {
            "author_tiers", "display_name", "nexus_domain", "nexus_pages", "output_subdir",
            "publication", "require_full_nexus_pages", "sources", "update_filter",
        }
        absent = required - set(config)
        if absent:
            raise ValueError(f"{key} is missing fields: {', '.join(sorted(absent))}")
        sources = config["sources"]
        if (
            not isinstance(sources, list)
            or not sources
            or len(sources) != len(set(sources))
            or not set(sources) <= {"thunderstore", "nexus"}
        ):
            raise ValueError(f"{key} has invalid sources")
        if not isinstance(config["display_name"], str) or not config["display_name"].strip():
            raise ValueError(f"{key} has invalid display_name")
        if "nexus" in sources and not SLUG_RE.fullmatch(config["nexus_domain"]):
            raise ValueError(f"{key} has invalid nexus_domain")
        for field in ("nexus_pages",):
            if not isinstance(config[field], int) or config[field] < 1:
                raise ValueError(f"{key} has invalid {field}")
        if "thunderstore" in sources:
            if not SLUG_RE.fullmatch(config.get("thunderstore_community", "")):
                raise ValueError(f"{key} has invalid thunderstore_community")
            if not isinstance(config.get("thunderstore_pages"), int) or config["thunderstore_pages"] < 1:
                raise ValueError(f"{key} has invalid thunderstore_pages")
        output = Path(config["output_subdir"])
        if output.is_absolute() or ".." in output.parts:
            raise ValueError(f"{key} has invalid output_subdir")
        if key == "valheim" and output != Path("."):
            raise ValueError("valheim output_subdir must remain '.'")
        if key != "valheim" and output == Path("."):
            raise ValueError(f"{key} output_subdir must be isolated")
        normalized_output = output.as_posix()
        if normalized_output in output_paths:
            raise ValueError(f"duplicate output_subdir: {normalized_output}")
        output_paths.add(normalized_output)
        publication = config["publication"]
        if not isinstance(publication, dict) or set(publication) != {"root", "path"}:
            raise ValueError(f"{key} has invalid publication")
        if not all(SLUG_RE.fullmatch(publication.get(field, "")) for field in ("root", "path")):
            raise ValueError(f"{key} has invalid publication component")
        if publication["root"] != "mod-tracking" or publication["path"] != key:
            raise ValueError(f"{key} has noncanonical publication destination")
        destination = (publication["root"], publication["path"])
        if destination in publication_paths:
            raise ValueError(f"duplicate publication destination: {'/'.join(destination)}")
        publication_paths.add(destination)
        author_tiers = config["author_tiers"]
        if author_tiers is not None:
            if (
                not isinstance(author_tiers, dict)
                or set(author_tiers) != {"percentiles", "mappings_file"}
                or not isinstance(author_tiers["percentiles"], dict)
                or set(author_tiers["percentiles"]) != {
                    "uncommon", "rare", "epic", "legendary"
                }
            ):
                raise ValueError(f"{key} has invalid author_tiers")
            percentiles = author_tiers["percentiles"]
            values = [
                percentiles[tier]
                for tier in ("uncommon", "rare", "epic", "legendary")
            ]
            if (
                any(not isinstance(value, int) or isinstance(value, bool) for value in values)
                or not 0 < values[0] < values[1] < values[2] < values[3] < 100
            ):
                raise ValueError(f"{key} has invalid author_tiers percentiles")
            mappings_file = author_tiers["mappings_file"]
            mappings_path = Path(mappings_file) if isinstance(mappings_file, str) else Path("..")
            if (
                not isinstance(mappings_file, str)
                or not mappings_file.strip()
                or mappings_path.is_absolute()
                or ".." in mappings_path.parts
                or mappings_path.suffix != ".json"
            ):
                raise ValueError(f"{key} has invalid author_tiers mappings_file")
        update_filter = config["update_filter"]
        if update_filter is not None:
            if (
                not isinstance(update_filter, dict)
                or set(update_filter) != {"label", "cutoff"}
                or not isinstance(update_filter["label"], str)
                or not update_filter["label"].strip()
            ):
                raise ValueError(f"{key} has invalid update_filter")
            cutoff = update_filter["cutoff"]
            if not isinstance(cutoff, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", cutoff
            ):
                raise ValueError(f"{key} has invalid update_filter cutoff")
            try:
                datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValueError(f"{key} has invalid update_filter cutoff") from exc
    return registry


GAME_CONFIGS = load_game_registry()
DEFAULT_UPDATE_FILTER = {
    "label": "v1 filter",
    "cutoff": "2026-09-08T00:00:00Z",
}


def game_output_root(root: Path, game_key: str) -> Path:
    """Resolve isolated generated state while preserving legacy Valheim paths."""
    return root / GAME_CONFIGS[game_key]["output_subdir"]


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
    node: dict,
    detail: dict | None,
    rank: int,
    collected_at: str,
    *,
    game_domain: str = "valheim",
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
        "canonical_url": f"https://www.nexusmods.com/{game_domain}/mods/{source_id}",
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
        "canonical_group_id": None,
        "match": None,
    }


def compute_rates(mod: dict, now: datetime) -> dict:
    """Compute comparable rates, using observed deltas for current versions.

    The current-version value is intentionally not an estimate of all downloads
    since release. It is the download delta per day between the first and latest
    persisted observations carrying the current version string.
    """
    created = parse_datetime(mod["created_at"])
    age_days = max(math.ceil((now - created).total_seconds() / 86400), 1)
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
        for key, value in incoming.items():
            if (
                key in {"canonical_group_id", "credited_author", "match"}
                and value is None
                and previous.get(key) is not None
            ):
                continue
            merged[key] = value
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


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def http_fetch(url: str, *, headers: dict | None = None, data: bytes | None = None) -> bytes:
    request_headers = {"User-Agent": "ModTracker/1.0 (manual collector)"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers, data=data)
    delays = (1, 3)
    for attempt in range(len(delays) + 1):
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except HTTPError as exc:
            transient = exc.code in {408, 425, 429} or 500 <= exc.code < 600
            if not transient or attempt == len(delays):
                raise
        except (TimeoutError, ConnectionError, URLError):
            if attempt == len(delays):
                raise
        time.sleep(delays[attempt])
    raise AssertionError("unreachable")


class ReadmeParser(HTMLParser):
    """Capture the first structurally complete README container."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open_tags: list[dict] = []
        self.candidate: dict | None = None
        self.result: str | None = None
        self.invalid = False

    @staticmethod
    def _render(tag, attrs):
        rendered = "".join(
            f' {name}="{value}"' for name, value in attrs if value is not None
        )
        return f"<{tag}{rendered}>"

    def handle_starttag(self, tag, attrs):
        attrs = list(attrs)
        classes = set((dict(attrs).get("class") or "").split())
        ancestor_classes = [frame["classes"] for frame in self.open_tags]
        is_legacy = "markdown-body" in classes
        is_current = (
            "markdown" in classes
            and any("markdown-wrapper" in c for c in ancestor_classes)
            and any("package-listing__content" in c for c in ancestor_classes)
        )
        if self.candidate is None and self.result is None and (is_legacy or is_current):
            self.invalid = False
            self.candidate = {
                "tag": tag, "opening": self._render(tag, attrs),
                "parts": [], "stack": [],
            }
        if self.candidate is not None:
            self.candidate["parts"].append(self._render(tag, attrs))
            if tag not in VOID_TAGS:
                self.candidate["stack"].append(tag)
        if tag not in VOID_TAGS:
            self.open_tags.append({"tag": tag, "classes": classes})

    def handle_startendtag(self, tag, attrs):
        if self.candidate is not None:
            self.candidate["parts"].append(self._render(tag, attrs)[:-1] + "/>" )

    def handle_endtag(self, tag):
        if self.candidate is not None:
            stack = self.candidate["stack"]
            if not stack or stack[-1] != tag:
                self.invalid = True
                self.candidate = None
            else:
                self.candidate["parts"].append(f"</{tag}>")
                stack.pop()
                if not stack:
                    if not self.invalid and self.result is None:
                        # The container itself is not part of the README payload.
                        rendered = "".join(self.candidate["parts"])
                        opening = self.candidate["opening"]
                        self.result = rendered[len(opening): -len(f"</{tag}>")]
                    self.candidate = None
                    self.invalid = False
        if self.open_tags:
            for index in range(len(self.open_tags) - 1, -1, -1):
                if self.open_tags[index]["tag"] == tag:
                    del self.open_tags[index:]
                    break

    def handle_data(self, data):
        if self.candidate is not None:
            self.candidate["parts"].append(data)

    def close(self):
        super().close()
        if self.candidate is not None:
            self.candidate = None
            self.result = ""


def parse_thunderstore_detail(source: str) -> dict:
    """Extract exact timestamps and README HTML from a package detail page."""
    result = {}
    for source_name, target_name in (
        ("package_created", "package_created"),
        ("version_created", "version_created"),
    ):
        match = re.search(
            source_name + r".{0,80}?(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)",
            source,
            re.DOTALL,
        )
        result[target_name] = match.group(1) if match else None
    parser = ReadmeParser()
    parser.feed(source)
    parser.close()
    result["readme_html"] = parser.result or ""
    return result


def _nexus_freshness(detail: dict) -> datetime | None:
    """Read Nexus detail freshness, preferring ISO and safely handling epochs."""
    updated_time = detail.get("updated_time")
    if isinstance(updated_time, str):
        try:
            return parse_datetime(updated_time)
        except (TypeError, ValueError, OverflowError):
            pass
    timestamp = detail.get("updated_timestamp")
    if isinstance(timestamp, int) and not isinstance(timestamp, bool):
        try:
            return datetime.fromtimestamp(timestamp, timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    return None


def _nexus_listing_freshness(node: dict) -> datetime | None:
    value = node.get("updatedAt")
    if not isinstance(value, str):
        return None
    try:
        return parse_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_thunderstore(
    card: dict, detail: dict, metrics: dict, ranks: dict, collected_at: str
) -> dict:
    path = [part for part in urlparse(card["package_url"]).path.split("/") if part]
    namespace, name = path[-2:]
    return {
        "key": f"thunderstore:{namespace}/{name}",
        "source": "thunderstore",
        "source_id": f"{namespace}/{name}",
        "title": card.get("title", ""),
        "author": card.get("author", namespace),
        "summary": card.get("description", ""),
        "description": detail.get("readme_html", ""),
        "categories": [item["name"] for item in card.get("categories", [])],
        "thumbnail": card.get("thumbnail_url", ""),
        "canonical_url": card["package_url"],
        "created_at": detail.get("package_created"),
        "updated_at": detail.get("version_created"),
        "updated_display": card.get("last_updated_display", ""),
        "total_downloads": int(metrics.get("downloads") or 0),
        "unique_downloads": None,
        "endorsements": None,
        "likes": int(metrics.get("rating_score") or 0),
        "views": None,
        "version": metrics.get("latest_version") or "",
        "rank": min(ranks.values()),
        "ranks": dict(sorted(ranks.items())),
        "pinned": bool(card.get("pinned")),
        "adult_content": False,
        "collected_at": collected_at,
        "raw_page_capture": {"status": "captured", "kind": "public-package-html"},
        "canonical_group_id": None,
        "match": None,
    }


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


SOURCE_COMPONENT_RE = re.compile(r"[A-Za-z0-9_-]+")


def _safe_child(root: Path, *parts: str) -> Path:
    """Resolve a generated path and prove it remains under ``root``."""
    base = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"generated path escapes output root: {candidate}")
    return candidate


def _thunderstore_source_id(package_url: str, community: str) -> str:
    parsed = urlparse(package_url)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.netloc != "thunderstore.io"
        or len(parts) != 5
        or parts[:3] != ["c", community, "p"]
        or not all(SOURCE_COMPONENT_RE.fullmatch(part) for part in parts[3:])
    ):
        raise ValueError(f"invalid Thunderstore package URL: {package_url!r}")
    return "/".join(parts[3:])


def _nexus_mod_id(value) -> str:
    mod_id = str(value)
    if not re.fullmatch(r"[1-9]\d*", mod_id):
        raise ValueError(f"invalid Nexus mod ID: {value!r}")
    return mod_id


def collect_thunderstore(
    root: Path,
    pages: int,
    collected_at: str,
    *,
    community: str = "valheim",
    fetch=http_fetch,
    pause=lambda: time.sleep(1),
) -> list[dict]:
    """Collect both deterministic Thunderstore rankings and exact details."""
    if not SLUG_RE.fullmatch(community):
        raise ValueError(f"invalid Thunderstore community: {community!r}")
    found: dict[str, dict] = {}
    listing_scope = {
        "requested_pages_per_sort": pages,
        "rankings": {},
    }
    for ordering in ("last-updated", "most-downloaded"):
        rank = 0
        fetched_pages = set()
        terminal_http_status = None
        nonempty_page_seen = False
        for page in range(1, pages + 1):
            url = f"https://thunderstore.io/c/{community}/?ordering={ordering}&page={page}"
            try:
                body = fetch(url)
            except HTTPError as exc:
                if exc.code == 404 and nonempty_page_seen:
                    terminal_http_status = 404
                    break
                raise
            atomic_write_bytes(root / f"raw/thunderstore/listings/{ordering}/page-{page}.html", body)
            fetched_pages.add(page)
            pause()
            cards = parse_listing(body.decode("utf-8"))
            nonempty_page_seen = nonempty_page_seen or bool(cards)
            for position, card in enumerate(cards, 1):
                rank += 1
                source_id = _thunderstore_source_id(card["package_url"], community)
                item = found.setdefault(source_id, {"card": card, "ranks": {}})
                item["ranks"][ordering] = rank
                item.setdefault("appearances", []).append({
                    "ordering": ordering, "page": page, "position": position, "rank": rank,
                })

        listing_dir = root / f"raw/thunderstore/listings/{ordering}"
        for stale in listing_dir.glob("page-*.html"):
            match = re.fullmatch(r"page-(\d+)\.html", stale.name)
            if match and int(match.group(1)) not in fetched_pages:
                stale.unlink()
        listing_scope["rankings"][ordering] = {
            "fetched_pages": len(fetched_pages),
            "terminal_http_status": terminal_http_status,
        }

    atomic_write_json(root / "raw/thunderstore/listings/manifest.json", listing_scope)
    normalized = []
    for source_id in sorted(found):
        namespace, name = source_id.split("/", 1)
        metrics_path = _safe_child(
            root, "raw", "thunderstore", "metrics", namespace, f"{name}.json"
        )
        detail_path = _safe_child(
            root, "raw", "thunderstore", "packages", namespace, f"{name}.html"
        )
        old_metrics = _load_json(metrics_path, {})
        metrics_url = f"https://thunderstore.io/api/v1/package-metrics/{namespace}/{name}/"
        metrics_body = fetch(metrics_url)
        pause()
        metrics = json.loads(metrics_body)
        atomic_write_json(metrics_path, metrics)
        if (not detail_path.exists()) or old_metrics.get("latest_version") != metrics.get("latest_version"):
            detail_body = fetch(found[source_id]["card"]["package_url"])
            pause()
            atomic_write_bytes(detail_path, detail_body)
        detail = parse_thunderstore_detail(detail_path.read_text(encoding="utf-8"))
        mod = normalize_thunderstore(
            found[source_id]["card"], detail, metrics, found[source_id]["ranks"], collected_at
        )
        mod["appearances"] = found[source_id]["appearances"]
        normalized.append(mod)
    return normalized


NEXUS_QUERY = """query TrackedGameMods {
  mods(filter: {gameDomainName: [{value: \"GAME_DOMAIN\", op: EQUALS}]},
       sort: [{updatedAt: {direction: DESC}}], count: 80, offset: OFFSET) {
    nodes { modId name summary author downloads endorsements adultContent createdAt
            updatedAt version fileSize category pictureUrl thumbnailUrl }
  }
}"""


def capture_nexus_page(
    root: Path,
    mod_id: str,
    *,
    cookie_header: str,
    game_domain: str = "valheim",
    fetch=http_fetch,
) -> dict:
    """Capture an actual Nexus detail page using caller-supplied auth cookies."""
    mod_id = _nexus_mod_id(mod_id)
    url = f"https://www.nexusmods.com/{game_domain}/mods/{mod_id}"
    try:
        body = fetch(url, headers={"Cookie": cookie_header})
        lower = body[:20000].lower()
        if b"just a moment" in lower or b"cf-chl" in lower or len(body) < 100:
            raise ValueError("received Cloudflare interstitial or undersized page")
        atomic_write_bytes(
            _safe_child(root, "raw", "nexus", "pages", f"{mod_id}.html"), body
        )
        return {"status": "captured", "kind": "authenticated-detail-html"}
    except Exception as exc:  # persisted status is evidence; the run remains resumable
        return {"status": "failed", "reason": str(exc)}


def collect_nexus(
    root: Path,
    api_key: str,
    collected_at: str,
    *,
    cookie_header: str | None = None,
    game_domain: str = "valheim",
    pages: int = 2,
    require_full_pages: bool = True,
    fetch=http_fetch,
    pause=lambda: time.sleep(1),
) -> list[dict]:
    """Collect up to ``pages`` Nexus listing pages and cache v1 details."""
    if not re.fullmatch(r"[a-z0-9-]+", game_domain):
        raise ValueError(f"invalid Nexus game domain: {game_domain!r}")
    headers = {"Content-Type": "application/json", "apikey": api_key}
    nodes = []
    fetched_pages = set()
    for page in range(1, pages + 1):
        offset = (page - 1) * 80
        query = (
            NEXUS_QUERY
            .replace("GAME_DOMAIN", game_domain)
            .replace("OFFSET", str(offset))
        )
        listing_body = fetch(
            "https://api.nexusmods.com/v2/graphql",
            headers=headers,
            data=json.dumps({"query": query}, separators=(",", ":")).encode(),
        )
        pause()
        listing = json.loads(listing_body)
        if listing.get("errors"):
            raise RuntimeError("Nexus GraphQL errors: " + json.dumps(listing["errors"]))
        atomic_write_json(root / f"raw/nexus/listing-page-{page}.json", listing)
        fetched_pages.add(page)
        page_nodes = listing.get("data", {}).get("mods", {}).get("nodes", [])
        nodes.extend(page_nodes)
        if not require_full_pages and len(page_nodes) < 80:
            break
    for stale in (root / "raw/nexus").glob("listing-page-*.json"):
        match = re.fullmatch(r"listing-page-(\d+)\.json", stale.name)
        if match and int(match.group(1)) not in fetched_pages:
            stale.unlink()
    normalized = []
    seen = set()
    for rank, node in enumerate(nodes, 1):
        mod_id = _nexus_mod_id(node["modId"])
        if mod_id in seen:
            continue
        seen.add(mod_id)
        detail_path = _safe_child(root, "raw", "nexus", "mods", f"{mod_id}.json")
        is_new = not detail_path.exists()
        detail = _load_json(detail_path, {})
        listing_freshness = _nexus_listing_freshness(node)
        saved_freshness = _nexus_freshness(detail) if isinstance(detail, dict) else None
        refresh = is_new or listing_freshness is None or saved_freshness is None
        if not refresh and listing_freshness is not None and saved_freshness is not None:
            if listing_freshness > saved_freshness:
                refresh = True
        if refresh:
            body = fetch(
                f"https://api.nexusmods.com/v1/games/{game_domain}/mods/{mod_id}.json",
                headers={"apikey": api_key},
            )
            pause()
            atomic_write_bytes(detail_path, body)
        detail = _load_json(detail_path, {})
        if is_new and cookie_header:
            detail["_raw_page_capture"] = capture_nexus_page(
                root,
                mod_id,
                cookie_header=cookie_header,
                game_domain=game_domain,
                fetch=fetch,
            )
            pause()
        elif (root / f"raw/nexus/pages/{mod_id}.html").exists():
            detail["_raw_page_capture"] = {
                "status": "captured", "kind": "authenticated-detail-html"
            }
        normalized.append(
            normalize_nexus(
                node,
                detail,
                rank,
                collected_at,
                game_domain=game_domain,
            )
        )
    return normalized


def apply_manual_mappings(mods: list[dict], mappings: dict) -> list[dict]:
    """Apply only explicit cross-source grouping metadata; never infer matches."""
    mod_keys = {mod.get("key") for mod in mods}
    group_authors = {}
    for mod in mods:
        mapping = mappings.get(mod.get("key"))
        if not isinstance(mapping, dict) or not mapping.get("canonical_group_id"):
            continue
        source = str(mod.get("source") or "").strip().casefold()
        author = " ".join(str(mod.get("author") or "").split()).casefold()
        if source and author:
            group_authors.setdefault(mapping["canonical_group_id"], set()).add(
                f"{source}:{author}"
            )
    for key, mapping in mappings.items():
        if not isinstance(mapping, dict) or "credited_author" not in mapping:
            continue
        credited = mapping["credited_author"]
        if not isinstance(credited, str) or ":" not in credited:
            raise ValueError(f"invalid creator attribution for {key!r}")
        source, author = credited.split(":", 1)
        normalized = f"{source}:{' '.join(author.split()).casefold()}"
        if source not in {"nexus", "thunderstore"} or credited != normalized:
            raise ValueError(f"invalid creator attribution for {key!r}")
        group = mapping.get("canonical_group_id")
        targets = mapping.get("matched_to")
        if (
            not isinstance(key, str)
            or ":" not in key
            or key not in mod_keys
            or not isinstance(group, str)
            or not group
            or not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or target not in mod_keys for target in targets)
            or credited not in group_authors.get(group, set())
        ):
            raise ValueError(f"invalid creator attribution for {key!r}")
        for target in targets:
            if not isinstance(target, str):
                raise ValueError(f"invalid creator attribution for {key!r}")
            reciprocal = mappings.get(target)
            if (
                key.split(":", 1)[0] == target.split(":", 1)[0]
                or not isinstance(reciprocal, dict)
                or key not in reciprocal.get("matched_to", [])
                or reciprocal.get("canonical_group_id") != group
                or reciprocal.get("credited_author") != credited
            ):
                raise ValueError(f"creator attribution for {key!r} is not reciprocal")
    result = []
    for mod in mods:
        copied = dict(mod)
        mapping = mappings.get(mod["key"])
        if mapping:
            copied["canonical_group_id"] = mapping.get("canonical_group_id")
            copied["credited_author"] = mapping.get("credited_author")
            copied["match"] = {
                "method": mapping.get("method", "manual"),
                "matched_to": list(mapping.get("matched_to", [])),
            }
        else:
            copied["canonical_group_id"] = None
            copied["credited_author"] = None
            copied["match"] = None
        result.append(copied)
    return result


def load_author_mappings(path: Path) -> dict:
    """Load and validate explicit reciprocal source-scoped author mappings."""
    try:
        mappings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load author mappings from {path}") from exc
    if not isinstance(mappings, dict):
        raise ValueError("author mappings must be a JSON object")

    def valid_identity(value) -> bool:
        if not isinstance(value, str) or ":" not in value:
            return False
        source, author = value.split(":", 1)
        normalized_author = " ".join(author.split()).casefold()
        return (
            source in {"nexus", "thunderstore"}
            and bool(normalized_author)
            and value == f"{source}:{normalized_author}"
        )

    for identity, mapping in mappings.items():
        if not valid_identity(identity):
            raise ValueError(f"invalid source-scoped identity: {identity!r}")
        if not isinstance(mapping, dict) or set(mapping) != {
            "canonical_author_id", "matched_to", "method"
        }:
            raise ValueError(f"invalid author mapping for {identity!r}")
        canonical = mapping["canonical_author_id"]
        matched_to = mapping["matched_to"]
        method = mapping["method"]
        if (
            not isinstance(canonical, str)
            or not SLUG_RE.fullmatch(canonical)
            or not isinstance(matched_to, list)
            or not matched_to
            or len(matched_to) != len(set(matched_to))
            or not all(valid_identity(target) for target in matched_to)
            or not isinstance(method, str)
            or not method.strip()
        ):
            raise ValueError(f"invalid author mapping for {identity!r}")
        source = identity.split(":", 1)[0]
        if any(target.split(":", 1)[0] == source for target in matched_to):
            raise ValueError(f"author mapping for {identity!r} must be cross-provider")
        for target in matched_to:
            reciprocal = mappings.get(target)
            if (
                not isinstance(reciprocal, dict)
                or identity not in reciprocal.get("matched_to", [])
                or reciprocal.get("canonical_author_id") != canonical
            ):
                raise ValueError(f"author mapping for {identity!r} is not reciprocal")
    return mappings


def author_identity_key(mod: dict) -> str:
    """Return the normalized source-scoped identity for one mod author."""
    source = str(mod.get("source") or "").strip().casefold()
    author = " ".join(str(mod.get("author") or "").split()).casefold()
    return f"{source}:{author}" if source and author else ""


def reputation_author_key(mod: dict) -> str:
    """Return an explicit per-mod credited creator or the publishing account."""
    credited = mod.get("credited_author")
    return str(credited) if credited else author_identity_key(mod)


def build_author_reputation(
    mods: list[dict],
    config: dict | None,
    mappings: dict,
) -> dict | None:
    """Tier source-scoped authors by raw lifetime-download percentiles."""
    if config is None:
        return None
    canonical_by_identity = {}
    display_names = {}
    native_display_names = set()
    totals = {}
    mod_keys = {}
    first_published = {}
    for mod in mods:
        native_identity = author_identity_key(mod)
        identity = reputation_author_key(mod)
        if not identity:
            continue
        if native_identity == identity:
            display_names[identity] = " ".join(str(mod.get("author") or "").split())
            native_display_names.add(identity)
        elif identity not in native_display_names:
            display_names[identity] = identity.split(":", 1)[-1]
        mapping = mappings.get(identity)
        canonical = (
            mapping.get("canonical_author_id")
            if isinstance(mapping, dict) and mapping.get("canonical_author_id")
            else identity
        )
        canonical_by_identity[identity] = canonical
        raw_downloads = mod.get("total_downloads")
        if raw_downloads is None:
            downloads = 0
        elif isinstance(raw_downloads, bool) or not isinstance(raw_downloads, int):
            raise ValueError(
                f"invalid total_downloads for {mod.get('key', '<unknown>')!r}"
            )
        else:
            downloads = max(0, raw_downloads)
        totals[canonical] = totals.get(canonical, 0) + downloads
        mod_key = (
            f"group:{mod['canonical_group_id']}"
            if mod.get("canonical_group_id")
            else f"record:{mod.get('key', '')}"
        )
        mod_keys.setdefault(canonical, set()).add(mod_key)
        created_at = mod.get("created_at")
        if created_at:
            created = parse_datetime(str(created_at))
            if canonical not in first_published or created < first_published[canonical]:
                first_published[canonical] = created
    canonical_display_names = {}
    for identity, canonical in sorted(canonical_by_identity.items()):
        candidate = display_names[identity]
        priority = (0 if identity.startswith("nexus:") else 1, identity)
        current = canonical_display_names.get(canonical)
        if current is None or priority < current[0]:
            canonical_display_names[canonical] = (priority, candidate)
    values = sorted(totals.values())
    percentiles = config["percentiles"]
    cutoffs = {
        tier: values[max(0, math.ceil(percentile / 100 * len(values)) - 1)] if values else 0
        for tier, percentile in percentiles.items()
    }

    def tier_for(downloads: int) -> str:
        if downloads >= cutoffs["legendary"]:
            return "legendary"
        if downloads >= cutoffs["epic"]:
            return "epic"
        if downloads >= cutoffs["rare"]:
            return "rare"
        if downloads >= cutoffs["uncommon"]:
            return "uncommon"
        return "common"

    return {
        "percentiles": dict(percentiles),
        "cutoffs": cutoffs,
        "authors": {
            identity: {
                "canonical_author_id": canonical,
                "display_name": canonical_display_names[canonical][1],
                "downloads": totals[canonical],
                "mod_count": len(mod_keys[canonical]),
                "first_mod_published_at": (
                    first_published[canonical].isoformat().replace("+00:00", "Z")
                    if canonical in first_published
                    else None
                ),
                "tier": tier_for(totals[canonical]),
            }
            for identity, canonical in canonical_by_identity.items()
        },
    }


def _thumbnail_src(mod: dict, embed: bool, fetch) -> str:
    url = mod.get("thumbnail") or ""
    if not embed or not url:
        return url
    try:
        body = fetch(url)
        kind = "image/png" if body.startswith(b"\x89PNG") else "image/jpeg"
        return f"data:{kind};base64," + base64.b64encode(body).decode("ascii")
    except Exception:
        return url


def _sort_number(value) -> str:
    return str(value if value is not None else -1)


def _report_groups(mods):
    groups = {}
    singles = []
    for mod in mods:
        gid = mod.get('canonical_group_id')
        if gid: groups.setdefault(gid, []).append(mod)
        else: singles.append([mod])
    return singles + [groups[k] for k in sorted(groups)]


def load_github_repositories(path: Path) -> dict:
    """Load the tracked review state, rejecting every malformed entry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid GitHub review state: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {"version", "records"} or payload["version"] != 1 or not isinstance(payload["records"], dict):
        raise ValueError("invalid GitHub review state schema")
    required = {"status", "repository_url", "reviewed_fingerprint", "evidence_urls", "review_method", "rationale"}
    for key, record in payload["records"].items():
        key_match = (
            re.fullmatch(
                r"([A-Za-z0-9-]+):(?:nexus:\d+|thunderstore:[^/:]+/[^/:]+)",
                key,
            )
            if isinstance(key, str)
            else None
        )
        if key_match is None or key_match.group(1) not in GAME_CONFIGS:
            raise ValueError(f"invalid GitHub review key: {key!r}")
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError(f"invalid GitHub review record: {key}")
        if record["status"] not in {"approved", "no_repository"}:
            raise ValueError(f"invalid GitHub review status: {key}")
        if record["status"] == "no_repository":
            if record["repository_url"] is not None:
                raise ValueError(f"no_repository has a URL: {key}")
        else:
            url = record["repository_url"]
            if not isinstance(url, str) or not re.fullmatch(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url
            ):
                raise ValueError(f"invalid approved GitHub root: {key}")
            evidence = extract_github_evidence({"url": url})
            if len(evidence["candidates"]) != 1 or evidence["candidates"][0]["repository_url"] != url:
                raise ValueError(f"invalid approved GitHub root: {key}")
        if not isinstance(record["reviewed_fingerprint"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", record["reviewed_fingerprint"]):
            raise ValueError(f"invalid GitHub fingerprint: {key}")
        if (
            not isinstance(record["evidence_urls"], list)
            or not record["evidence_urls"]
            or any(not isinstance(value, str) or not value.strip() for value in record["evidence_urls"])
            or len(set(record["evidence_urls"])) != len(record["evidence_urls"])
        ):
            raise ValueError(f"invalid GitHub evidence URLs: {key}")
        if any(
            not isinstance(record[field], str) or not record[field].strip()
            for field in ("review_method", "rationale")
        ):
            raise ValueError(f"invalid GitHub review text: {key}")
    return payload


def _github_decision(decisions, mod, game_key=None):
    keys = []
    if game_key:
        keys.append(f"{game_key}:{mod.get('key', '')}")
    if not game_key:
        keys.append(mod.get("key"))
    else:
        return decisions.get(keys[0])
    for key in keys:
        if key in decisions:
            return decisions[key]
    suffix = ":" + str(mod.get("key", ""))
    matches = [decision for key, decision in decisions.items() if isinstance(key, str) and key.endswith(suffix)]
    return matches[0] if len(matches) == 1 else None


def resolve_github_repository(members, decisions, *, game_key=None):
    """Resolve one reviewed repository for a rendered card, or suppress it."""
    approvals = set()
    for mod in members:
        decision = _github_decision(decisions, mod, game_key)
        if isinstance(decision, dict) and decision.get("status") == "approved":
            url = decision.get("repository_url")
            if isinstance(url, str):
                approvals.add(url)
    return next(iter(approvals)) if len(approvals) == 1 else None


def report_github_links(mods, decisions, *, game_key=None):
    """Return the expected repository root in exact card-rendering order."""
    groups = _report_groups(mods)
    ordered = [
        *[group for group in groups if any(mod.get("pinned") for mod in group)],
        *[group for group in groups if not any(mod.get("pinned") for mod in group)],
    ]
    return [
        resolve_github_repository(group, decisions, game_key=game_key)
        for group in ordered
    ]


def validate_github_game_scope(mods, decisions, game_key):
    """Require every reviewed key for the selected game to bind to a record."""
    if game_key is None:
        return
    prefix = f"{game_key}:"
    expected = {prefix + str(mod.get("key", "")) for mod in mods}
    actual = {key for key in decisions if key.startswith(prefix)}
    unknown = sorted(actual - expected)
    if unknown:
        raise ValueError(
            f"GitHub review state has unknown {game_key} records: "
            + ", ".join(unknown)
        )


def _github_state_path(root: Path, explicit: Path | None = None) -> Path | None:
    """Find review state at the output root or its bounded project parent."""
    if explicit is not None:
        explicit = Path(explicit)
        if not explicit.is_file():
            raise ValueError(f"missing GitHub review state: {explicit}")
        return explicit
    candidates = [root / "github-repositories.json", root.parent / "github-repositories.json"]
    if root.parent.name == "games":
        candidates.append(root.parent.parent / "github-repositories.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def report_author_keys(mods: list[dict], author_reputation: dict | None):
    """Return the rendered primary author identity for each authored report card."""
    if author_reputation is None:
        return None
    keys = []
    for members in _report_groups(mods):
        primary = max(
            members,
            key=lambda mod: (
                timestamp_sort_key(mod.get("updated_at") or ""),
                mod.get("key", ""),
            ),
        )
        identity = reputation_author_key(primary)
        if identity and identity in author_reputation["authors"]:
            keys.append(identity)
    return keys


def report_category_sets(mods: list[dict]) -> list[list[str]]:
    """Return normalized categories in the exact card-rendering order."""
    groups = _report_groups(mods)
    ordered = [
        *[group for group in groups if any(mod.get("pinned") for mod in group)],
        *[group for group in groups if not any(mod.get("pinned") for mod in group)],
    ]
    return [
        sorted({
            " ".join(str(category).split()).casefold()
            for mod in group
            for category in mod.get("categories", [])
            if " ".join(str(category).split())
        })
        for group in ordered
    ]


def matches_update_filter(updated_at: str, update_filter: dict | None) -> bool:
    """Classify one update timestamp against an optional inclusive UTC cutoff."""
    return bool(
        update_filter
        and updated_at
        and parse_datetime(updated_at) >= parse_datetime(update_filter["cutoff"])
    )


def timestamp_sort_key(value: str):
    """Return a comparable UTC-aware key, sorting a missing timestamp first."""
    return parse_datetime(value) if value else datetime.min.replace(tzinfo=timezone.utc)


def render_update_filter_control(update_filter: dict | None) -> str:
    """Render the one shared optional update-filter control."""
    if update_filter is None:
        return ""
    cutoff = parse_datetime(update_filter["cutoff"])
    cutoff_label = f"{cutoff.strftime('%b')} {cutoff.day}, {cutoff.year}"
    return (
        '<label class="toggle-control"><input id="update-filter-toggle" '
        'type="checkbox"><span title="Shows mods updated on or after %s; '
        'not a semantic version filter.">%s</span></label>'
        % (escape(cutoff_label, quote=True), escape(update_filter["label"]))
    )


def render_author_name(mod: dict, author_reputation: dict | None) -> str:
    """Render one author name with optional computed rarity evidence."""
    author = str(mod.get("author") or "")
    if author_reputation is None:
        return escape(author)
    identity = reputation_author_key(mod)
    profile = author_reputation["authors"].get(identity)
    if profile is None:
        return escape(author)
    author = str(profile.get("display_name") or author)
    tier = profile["tier"]
    downloads = int(profile["downloads"])
    mod_count = int(profile["mod_count"])
    first_published = profile.get("first_mod_published_at")
    if first_published:
        first_date = parse_datetime(str(first_published))
        first_label = f"{first_date.strftime('%b')} {first_date.day}, {first_date.year}"
        first_evidence = f"first known mod published {first_label}"
    else:
        first_evidence = "first known mod publication unknown"
    mod_label = f"{mod_count} known mod{'s' if mod_count != 1 else ''}"
    canonical = str(profile["canonical_author_id"])
    evidence = (
        f"{tier.title()} author · {downloads:,} lifetime downloads · "
        f"{mod_label} · {first_evidence}"
    )
    aria = (
        f"{author}, {tier.title()} author, {downloads:,} lifetime downloads, "
        f"{mod_label}, {first_evidence}"
    )
    metadata = (
        '<span class="author author-tier-%s" data-author-tier="%s" '
        'data-author-downloads="%d" data-author-mod-count="%d" '
        'data-author-first-published="%s" data-author-key="%s" '
        'data-author-canonical="%s" title="%s" '
        'aria-label="%s">%s</span>'
        % (
            tier, tier, downloads, mod_count,
            escape(str(first_published or ""), quote=True),
            escape(identity, quote=True), escape(canonical, quote=True),
            escape(evidence, quote=True), escape(aria, quote=True),
            escape(author),
        )
    )
    return (
        '<button type="button" class="author-button" data-author-key="%s" '
        'data-author-canonical="%s" aria-pressed="false">%s</button>'
        % (escape(identity, quote=True), escape(canonical, quote=True), metadata)
    )


def render_pagination(position: str) -> str:
    """Render one accessible pagination control set."""
    return (
        f'<nav class="pagination" id="pagination-{position}" aria-label="Report pages">'
        f'<button type="button" id="previous-page-{position}">Previous</button>'
        f'<span class="page-indicator" id="page-indicator-{position}" aria-live="polite">Page 1 of 1</span>'
        f'<button type="button" id="next-page-{position}">Next</button></nav>'
    )


def render_author_legend(author_reputation: dict | None) -> str:
    """Render the concise rarity key only when author tiers are enabled."""
    if author_reputation is None:
        return ""
    items = "".join(
        f'<span class="author-tier-{tier}">{tier.title()}</span>'
        for tier in ("common", "uncommon", "rare", "epic", "legendary")
    )
    return (
        '<div class="author-legend" aria-label="Author rarity legend">'
        f'<strong>Author rarity</strong>{items}</div>'
    )


REPORT_JAVASCRIPT = "const cards=[...document.querySelectorAll('.mod-card')],search=document.querySelector('#search'),source=document.querySelector('#source-filter'),category=document.querySelector('#category-filter'),author=document.querySelector('#author-filter'),sort=document.querySelector('#sort'),nsfw=document.querySelector('#nsfw-toggle'),updateFilter=document.querySelector('#update-filter-toggle'),count=document.querySelector('#results-count'),paginations=[...document.querySelectorAll('.pagination')],previousPages=paginations.map(p=>p.querySelector('[id^=previous-page]')),nextPages=paginations.map(p=>p.querySelector('[id^=next-page]')),pageIndicators=paginations.map(p=>p.querySelector('[id^=page-indicator]')),pinnedGroup=document.querySelector('#pinned-group'),regularGroup=document.querySelector('#regular-group'),pinnedSection=document.querySelector('#pinned-section'),regularSection=document.querySelector('#regular-section'),clearAuthor=document.querySelector('#clear-author-filter');const pageSize=100;let currentPage=1;function normalizeSearch(value){return value.replace(/^[ \\t\\n\\r\\f\\v]+|[ \\t\\n\\r\\f\\v]+$/g,'').toLowerCase().replace(/[ \\t\\n\\r\\f\\v]+/g,' ')}function matchingCards(group,q){const key='sort'+sort.value.split('-').map(x=>x[0].toUpperCase()+x.slice(1)).join('');return [...group.children].filter(c=>c.dataset.search.includes(q)&&(!source.value||c.dataset.source===source.value)&&(!category.value||JSON.parse(c.dataset.categories).includes(category.value))&&(!author||!author.value||c.dataset.authorCanonical===author.value)&&(nsfw.checked||c.dataset.nsfw!=='true')&&(!updateFilter||!updateFilter.checked||c.dataset.updateFilter==='true')).sort((a,b)=>sort.value==='updated'?b.dataset[key].localeCompare(a.dataset[key]):Number(b.dataset[key])-Number(a.dataset[key]))}function update(){document.body.classList.toggle('show-nsfw',nsfw.checked);const q=normalizeSearch(search.value),pinned=matchingCards(pinnedGroup,q),regular=matchingCards(regularGroup,q);pinned.forEach(c=>pinnedGroup.appendChild(c));regular.forEach(c=>regularGroup.appendChild(c));const matching=[...pinned,...regular];const totalPages=Math.ceil(matching.length/pageSize);if(totalPages)currentPage=Math.min(currentPage,totalPages);else currentPage=1;const start=(currentPage-1)*pageSize;const pageCards=matching.slice(start,start+pageSize);const pageSet=new Set(pageCards);cards.forEach(c=>c.hidden=!pageSet.has(c));pinnedSection.hidden=!pageCards.some(c=>c.parentElement===pinnedGroup);regularSection.hidden=!pageCards.some(c=>c.parentElement===regularGroup);count.textContent=matching.length+' result'+(matching.length===1?'':'s');pageIndicators.forEach(i=>i.textContent='Page '+(totalPages?currentPage:0)+' of '+totalPages);previousPages.forEach(b=>b.disabled=currentPage<=1||!totalPages);nextPages.forEach(b=>b.disabled=!totalPages||currentPage>=totalPages);paginations.forEach(p=>p.hidden=totalPages<=1);document.querySelectorAll('.author-button').forEach(b=>{const active=!!author&&b.dataset.authorCanonical===author.value;b.classList.toggle('author-filter-active',active);b.setAttribute('aria-pressed',String(active))});if(clearAuthor){clearAuthor.hidden=!author||!author.value}}[search,source,category,sort,nsfw,...(updateFilter?[updateFilter]:[])].forEach(x=>x.addEventListener('input',()=>{currentPage=1;update()}));if(author)author.addEventListener('input',()=>{currentPage=1;update()});previousPages.forEach(b=>b.addEventListener('click',()=>{if(currentPage>1){currentPage--;update()}}));nextPages.forEach(b=>b.addEventListener('click',()=>{currentPage++;update()}));const tags=[...document.querySelectorAll('.tag[data-category]')];tags.forEach(tag=>tag.addEventListener('click',e=>{e.stopPropagation();category.value=tag.dataset.category;currentPage=1;update();category.focus()}));const authorButtons=[...document.querySelectorAll('.author-button[data-author-canonical]')];authorButtons.forEach(b=>b.addEventListener('click',e=>{e.stopPropagation();if(author){author.value=author.value===b.dataset.authorCanonical?'':b.dataset.authorCanonical;currentPage=1;update();author.focus()}}));if(clearAuthor)clearAuthor.addEventListener('click',e=>{e.stopPropagation();author.value='';currentPage=1;update();author.focus()});update();"
REPORT_STYLESHEET_SHA256 = "99cf97bf15f5ba9b2f47a5e80428e1815fd6c32ce64b0b2f1a29493dd1f43e73"


def render_report(
    mods,
    generated_at,
    *,
    embed_thumbnails=False,
    thumbnail_fetch=http_fetch,
    game_name="Valheim",
    sources=("thunderstore", "nexus"),
    update_filter: dict | None = DEFAULT_UPDATE_FILTER,
    author_reputation: dict | None = None,
    github_decisions: dict | None = None,
    github_game: str | None = None,
):
    now = parse_datetime(generated_at)
    arizona_now = now.astimezone(ZoneInfo("America/Phoenix"))
    generated_label = (
        f"{arizona_now.strftime('%b')} {arizona_now.day}, {arizona_now.year} at "
        f"{arizona_now.strftime('%I:%M %p').lstrip('0')} {arizona_now.tzname()}"
    )
    latest_update = max(
        (parse_datetime(str(mod["updated_at"])) for mod in mods if mod.get("updated_at")),
        default=None,
    )
    if latest_update is not None:
        latest_arizona = latest_update.astimezone(ZoneInfo("America/Phoenix"))
        latest_label = (
            f"{latest_arizona.strftime('%b')} {latest_arizona.day}, "
            f"{latest_arizona.year} at "
            f"{latest_arizona.strftime('%I:%M %p').lstrip('0')} "
            f"{latest_arizona.tzname()}"
        )
        latest_iso = latest_update.isoformat().replace("+00:00", "Z")
    else:
        latest_label = "unknown"
        latest_iso = ""
    categories = {}
    for mod in mods:
        for category in mod.get("categories", []):
            label = " ".join(str(category).split())
            if label:
                categories.setdefault(label.casefold(), label)
    category_options = '<option value="">All categories</option>' + "".join(
        '<option value="%s">%s</option>'
        % (escape(value, quote=True), escape(categories[value]))
        for value in sorted(categories)
    )
    author_options = {}
    if author_reputation is not None:
        for group in _report_groups(mods):
            primary = max(group, key=lambda m: (timestamp_sort_key(m.get("updated_at") or ""), m.get("key", "")))
            profile = author_reputation["authors"].get(reputation_author_key(primary))
            if profile is not None:
                canonical = str(profile["canonical_author_id"])
                author_options.setdefault(canonical, str(profile.get("display_name") or primary.get("author") or canonical))
    author_filter = ""
    if author_options:
        author_filter = (
            '<label class="control">Author<select id="author-filter">'
            '<option value="">All authors</option>'
            + "".join('<option value="%s">%s</option>' % (escape(key, quote=True), escape(author_options[key])) for key in sorted(author_options))
            + '</select></label><button type="button" id="clear-author-filter" hidden>Clear author filter</button>'
        )
    def card(members):
        members = sorted(members, key=lambda m: m['source'])
        primary = max(
            members,
            key=lambda m: (timestamp_sort_key(m.get('updated_at') or ''), m.get('key', '')),
        )
        sources = {m['source'] for m in members}; both = len(sources) > 1
        source = 'both' if both else next(iter(sources)); label = 'Both' if both else ('Thunderstore' if source == 'thunderstore' else 'Nexus Mods')
        rates = [compute_rates(m, now) for m in members]
        updated = max(
            (m.get('updated_at') or '' for m in members),
            key=timestamp_sort_key,
            default='',
        )
        created = min((m.get('created_at') or '' for m in members if m.get('created_at')), default='')
        lifetime = sum(r['lifetime_downloads_per_day'] for r in rates)
        vr = [r['current_version_observed_downloads_per_day'] for r in rates if r['current_version_observed_downloads_per_day'] is not None]
        version_rate = sum(vr) if vr else None
        total_downloads = sum(int(m.get('total_downloads') or 0) for m in members)
        lifetime_label = 'Combined lifetime / day' if both else 'Lifetime / day'
        adult = any(m.get('adult_content') for m in members)
        pinned = any(m.get('pinned') for m in members)
        category_labels = {}
        for member in members:
            for category in member.get('categories', []):
                category_label = " ".join(str(category).split())
                if category_label:
                    category_labels.setdefault(category_label.casefold(), category_label)
        category_values = sorted(category_labels)
        cats = [category_labels[value] for value in category_values]
        category_data = escape(
            json.dumps(category_values, separators=(",", ":")), quote=True
        )
        def search_index(values):
            seen = set()
            normalized = []
            for value in values:
                text = re.sub(
                    r"[ \t\n\r\f\v]+",
                    " ",
                    str(value or "").strip(" \t\n\r\f\v"),
                ).lower()
                if text and text not in seen:
                    seen.add(text)
                    normalized.append(text)
            return " ".join(normalized)
        title_search = search_index(m.get("title", "") for m in members)
        author_values = [m.get("author", "") for m in members]
        if author_reputation is not None:
            for member in members:
                profile = author_reputation["authors"].get(reputation_author_key(member))
                if profile is not None:
                    author_values.append(profile.get("display_name", ""))
        author_search = search_index(author_values)
        description_search = search_index(
            member.get("summary", "") for member in members
        )
        search = " ".join((title_search, author_search, description_search))
        links = ''.join('<a class="source-link" href="%s">%s</a>' % (escape(m['canonical_url'],quote=True), 'Thunderstore' if m['source']=='thunderstore' else 'Nexus Mods') for m in members)
        github_root = resolve_github_repository(members, github_decisions or {}, game_key=github_game)
        if github_root:
            links += '<a class="github-link" href="%s">GitHub</a>' % escape(github_root, quote=True)
        def source_metrics(member):
            source_name = (
                "Thunderstore" if member["source"] == "thunderstore" else "Nexus Mods"
            )
            engagement_name = (
                "likes" if member["source"] == "thunderstore" else "endorsements"
            )
            engagement_value = member.get(
                "likes" if member["source"] == "thunderstore" else "endorsements"
            )
            blocks = [
                '<div><dt>%s downloads</dt><dd>%s</dd></div>'
                % (
                    source_name,
                    f"{int(member.get('total_downloads') or 0):,}",
                )
            ]
            if engagement_value is not None:
                blocks.append(
                    '<div><dt>%s %s</dt><dd>%s</dd></div>'
                    % (
                        source_name,
                        engagement_name,
                        f"{int(engagement_value):,}",
                    )
                )
            return "".join(blocks)
        metrics = ''.join(source_metrics(member) for member in members)
        images = ''.join('<img class="thumb" src="%s" alt="" loading="lazy">' % escape(_thumbnail_src(m, embed_thumbnails, thumbnail_fetch), quote=True) for m in members)
        author_html = render_author_name(primary, author_reputation)
        author_profile = author_reputation["authors"].get(reputation_author_key(primary)) if author_reputation is not None else None
        author_canonical = str(author_profile["canonical_author_id"]) if author_profile is not None else ""
        return '''<article class="mod-card source-%s%s" data-source="%s" data-nsfw="%s" data-update-filter="%s" data-categories="%s" data-author-canonical="%s" data-search-title="%s" data-search-author="%s" data-search-description="%s" data-search="%s" data-sort-lifetime-rate="%s" data-sort-version-rate="%s" data-sort-updated="%s" data-sort-downloads="%s">
<div class="media">%s</div><div class="body"><div class="badges"><span class="source %s">%s</span>%s%s</div><h2><a href="%s">%s</a></h2><p class="by">by %s · v%s</p><p class="summary">%s</p><div class="tags">%s</div><p class="source-links">%s</p><div class="dates"><div class="date-row"><span class="date-label">Updated</span><time datetime="%s">%s</time></div><div class="date-row"><span class="date-label">Uploaded</span><time datetime="%s">%s</time></div></div></div><dl class="metrics">%s<div><dt>%s</dt><dd>%s</dd></div></dl></article>''' % (
            source, ' pinned' if pinned else '', source, str(adult).lower(), str(matches_update_filter(updated, update_filter)).lower(), category_data, escape(author_canonical,quote=True), escape(title_search,quote=True), escape(author_search,quote=True), escape(description_search,quote=True), escape(search,quote=True), _sort_number(lifetime), _sort_number(version_rate), escape(updated,quote=True), _sort_number(total_downloads), images, source, label, '<span class="pin">Pinned</span>' if pinned else '', '<span class="nsfw">NSFW</span>' if adult else '', escape(primary['canonical_url'],quote=True), escape(primary.get('title','')), author_html, escape(str(primary.get('version') or '—')), escape(primary.get('summary') or ''), ''.join('<button type="button" class="tag" data-category="%s">%s</button>' % (escape(" ".join(str(x).split()).casefold(), quote=True), escape(str(x))) for x in cats), links, escape(updated,quote=True), escape(updated[:10] or 'unknown'), escape(created,quote=True), escape(created[:10] or 'unknown'), metrics, lifetime_label, f"{lifetime:,.1f}")
    groups = _report_groups(mods)
    pinned = ''.join(card(g) for g in groups if any(m.get('pinned') for m in g)); regular = ''.join(card(g) for g in groups if not any(m.get('pinned') for m in g))
    initial_visible = sum(not any(m.get('adult_content') for m in group) for group in groups)
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Valheim Mod Tracker</title><style>
:root{--bg:#090b0e;--panel:#171a1f;--line:#30353d;--text:#f2f4f7;--muted:#9ca3ad;--ts-bg:#202c3d;--ts-line:#4d6b91;--nx-bg:#3b2922;--nx-line:#9a5e3b;--author-common:#f2f4f7;--author-uncommon:#4ade80;--author-rare:#4da3ff;--author-epic:#c084fc;--author-legendary:#fb923c}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui}header,main{max-width:1320px;margin:auto;padding:28px}header{border-bottom:1px solid var(--line)}h1{font-size:clamp(30px,5vw,52px);margin:0}.subtitle{color:var(--muted)}.toolbar{position:sticky;top:0;z-index:20;display:flex;align-items:end;gap:12px;flex-wrap:wrap;padding:12px max(28px,calc((100vw - 1320px)/2 + 28px));background:var(--bg);border-bottom:1px solid var(--line);box-shadow:0 8px 18px rgba(0,0,0,.3)}.results{font-weight:700;margin-right:auto;min-height:44px;display:flex;align-items:center}.control{display:grid;gap:4px;color:var(--muted);font-size:12px}.toggle-row{display:flex;gap:16px;align-items:center;min-height:44px;flex-wrap:wrap}.toggle-control{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap}.toggle-control input{width:18px;height:18px;min-height:0;margin:0;padding:0;flex:0 0 auto;accent-color:#2587e8}.author{font-weight:750}.author-button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer;text-decoration:underline;text-underline-offset:2px}.author-button.author-filter-active{outline:2px solid #f3d76b;outline-offset:3px;border-radius:3px}.author-legend{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 20px;padding:10px 12px;background:var(--panel);border:1px solid var(--line);border-radius:7px}.author-legend strong{margin-right:2px}.author-legend span{font-weight:750}.author-tier-common{color:var(--author-common)}.author-tier-uncommon{color:var(--author-uncommon);text-shadow:0 0 7px rgba(74,222,128,.28)}.author-tier-rare{color:var(--author-rare);text-shadow:0 0 7px rgba(77,163,255,.28)}.author-tier-epic{color:var(--author-epic);text-shadow:0 0 8px rgba(192,132,252,.32)}.author-tier-legendary{color:var(--author-legendary);text-shadow:0 0 9px rgba(251,146,60,.38)}.body h2 a,.body h2 a:visited{color:var(--text);text-decoration:none}.body h2 a:hover{text-decoration:underline}input,select{min-height:44px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:10px;font:inherit}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}.mod-card{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto 1fr auto;overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:8px}.mod-card[data-nsfw="true"]{display:none}.show-nsfw .mod-card[data-nsfw="true"]{display:grid}.mod-card.source-thunderstore{background:var(--ts-bg);border-color:var(--ts-line)}.mod-card.source-nexus{background:var(--nx-bg);border-color:var(--nx-line)}.mod-card.source-both{background:linear-gradient(110deg,var(--ts-bg),var(--nx-bg));border-color:#75614d}.mod-card:hover{border-color:#d5dbe3}.media{aspect-ratio:16/8;background:#222}.thumb{width:100%%;height:100%%;object-fit:cover}.body{padding:15px;min-width:0;overflow-wrap:anywhere}.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.source,.pin,.nsfw,.tag{display:inline-block;padding:5px 9px;border-radius:99px;font-size:11px;font-weight:750}.source{background:#1b6c9e;border:1px solid #8ed0ff}.source.nexus{background:#9a4d27;border-color:#ffc09b}.source.both{background:linear-gradient(90deg,#236e9e,#9a4d27);border-color:#f0d0a2}.nsfw{background:#671d35;border:1px solid #ff9abb}.pin{background:#705b18;border:1px solid #f3d76b}.tags{display:flex;flex-wrap:wrap;gap:4px}.tag{background:#252a31;color:var(--muted);border:0;font:inherit;font-size:11px;font-weight:750;margin:2px;max-width:100%%;overflow-wrap:anywhere;cursor:pointer}.tag:focus-visible{outline:2px solid #7cb7ff;outline-offset:2px}.source-link{color:#b9dbff;margin-right:12px;font-weight:700}.dates{display:grid;gap:4px;margin:1em 0}.date-row{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:baseline}.date-label{color:var(--muted);font-weight:600}.date-row time{white-space:nowrap}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0;border-top:1px solid var(--line)}.metrics div{padding:10px 12px;border-right:1px solid var(--line)}dt{color:var(--muted);font-size:11px}dd{margin:3px 0;font-weight:700}.pagination{display:flex;align-items:center;justify-content:center;gap:12px;margin:24px 0}.pagination button{min-height:44px;padding:10px 16px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;font:inherit;font-weight:700;cursor:pointer}.pagination button:disabled{opacity:.5;cursor:not-allowed}.page-indicator{min-width:92px;text-align:center;font-weight:700}[hidden]{display:none!important}@media(max-width:520px){header,main{padding:18px 14px}.toolbar{position:static;padding:10px 14px;max-height:none;overflow:visible;align-items:stretch}.control{width:100%%}.toggle-row{width:100%%;justify-content:flex-start}.grid{display:block}.mod-card{display:grid;grid-template-columns:88px minmax(0,1fr);margin-bottom:12px}.media{grid-column:1;grid-row:1;aspect-ratio:1;margin:12px}.body{grid-column:2;grid-row:1;padding:12px 12px 12px 0}.summary,.tags,.dates,.source-links{grid-column:1/-1}.metrics{grid-column:1/-1;grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:360px){.date-row{grid-template-columns:1fr;gap:0}}
</style></head><body><header><h1>Valheim Mod Tracker</h1><p class="subtitle">Discover and compare recently updated Valheim mods across Thunderstore and Nexus Mods.</p></header><div class="toolbar" role="region" aria-label="Mod filters"><span class="results" id="results-count">%d results</span><label class="control">Search<input id="search" type="search" placeholder="Title, author, description"></label><label class="control">Filter<select id="source-filter"><option value="">All sources</option><option value="thunderstore">Thunderstore</option><option value="nexus">Nexus Mods</option><option value="both">Both</option></select></label><label class="control">Category<select id="category-filter">{CATEGORY_OPTIONS}</select></label>{AUTHOR_FILTER}<div class="toggle-row"><label class="toggle-control"><input id="nsfw-toggle" type="checkbox"><span>Show NSFW mods</span></label>{UPDATE_FILTER_CONTROL}</div><label class="control">Sort<select id="sort"><option value="lifetime-rate">Lifetime downloads/day</option><option value="version-rate">Current version observed downloads/day</option><option value="updated">Last updated</option><option value="downloads">Total downloads</option></select></label></div><main><p>Generated %s.</p>{AUTHOR_LEGEND}<div class="report-pagination-top">{PAGINATION_TOP}</div><section id="pinned-section"%s><h2>Pinned Thunderstore mods</h2><div class="grid" id="pinned-group">%s</div></section><section id="regular-section"><h2>All other mods</h2><div class="grid" id="regular-group">%s</div></section><div class="report-pagination-bottom">{PAGINATION_BOTTOM}</div><noscript><p>Filtering requires JavaScript; NSFW content remains hidden when JavaScript is disabled.</p></noscript></main><script>{REPORT_JAVASCRIPT}</script></body></html>''' % (initial_visible, generated_label, ' hidden' if not pinned else '', pinned, regular)
    report_title = escape(f"{game_name} Mod Tracker")
    source_names = [
        label for source, label in (("thunderstore", "Thunderstore"), ("nexus", "Nexus Mods"))
        if source in sources
    ]
    source_phrase = (
        f"across {source_names[0]} and {source_names[1]}."
        if len(source_names) == 2
        else f"on {source_names[0]}."
    )
    subtitle = escape(f"Discover and compare recently updated {game_name} mods {source_phrase}")
    page = page.replace("<title>Valheim Mod Tracker</title>", f"<title>{report_title}</title>")
    page = page.replace("<h1>Valheim Mod Tracker</h1>", f"<h1>{report_title}</h1>")
    page = page.replace(
        "Discover and compare recently updated Valheim mods across Thunderstore and Nexus Mods.",
        subtitle,
    )
    page = page.replace(
        "{UPDATE_FILTER_CONTROL}", render_update_filter_control(update_filter)
    )
    page = page.replace("{AUTHOR_FILTER}", author_filter)
    page = page.replace("{PAGINATION_TOP}", render_pagination("top"))
    page = page.replace("{PAGINATION_BOTTOM}", render_pagination("bottom"))
    page = page.replace("{CATEGORY_OPTIONS}", category_options)
    page = page.replace("{REPORT_JAVASCRIPT}", REPORT_JAVASCRIPT)
    page = page.replace("{AUTHOR_LEGEND}", render_author_legend(author_reputation))
    page = page.replace(
        f"<p>Generated {generated_label}.</p>",
        f"<p>Generated {generated_label}.</p>"
        f"<p>Data last updated at {latest_label}.</p>",
        1,
    )
    page = page.replace(
        "<head>",
        '<head><meta name="report-generated-at" content="%s">'
        '<meta name="report-data-last-updated-at" content="%s">'
        % (escape(generated_at, quote=True), escape(latest_iso, quote=True)),
        1,
    )
    return page


class ReportVerifier(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = 0
        self.ids = set()
        self.missing_sort = 0
        self.missing_search = 0
        self.card_update_metadata = []
        self.update_filter_controls = 0
        self.author_filter_controls = 0
        self.author_options = []
        self._in_author_filter = False
        self.clear_author_filter_controls = 0
        self.author_buttons = []
        self.author_metadata = []
        self.card_author_metadata = []
        self.card_author_canonical = []
        self._current_card_authors = None
        self._current_author_metadata = None
        self._current_card_categories = None
        self.github_links = []
        self._current_card_github_links = None
        self._in_anchor = False
        self._anchor_text = ""
        self.report_generated_at = None
        self.report_data_last_updated_at = None
        self.report_data_last_updated_count = 0
        self.category_controls = 0
        self.category_options = []
        self.card_category_metadata = []
        self.card_category_buttons = []
        self._current_card_category_buttons = None
        self._in_category_filter = False
        self.sticky_toolbars = 0
        self.pagination_semantics = {
            key: 0 for key in (
                "pagination-top", "previous-page-top", "next-page-top", "page-indicator-top",
                "pagination-bottom", "previous-page-bottom", "next-page-bottom", "page-indicator-bottom",
            )
        }
        self._in_script = False
        self._in_style = False
        self.script_parts = []
        self.style_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._in_script = True
        if tag == "style":
            self._in_style = True
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        element_id = attrs.get("id")
        if (
            element_id in {"pagination-top", "pagination-bottom"}
            and tag == "nav" and attrs.get("aria-label") == "Report pages"
            and "pagination" in (attrs.get("class") or "").split()
        ):
            self.pagination_semantics[element_id] += 1
        if (
            element_id in {"previous-page-top", "previous-page-bottom", "next-page-top", "next-page-bottom"}
            and tag == "button" and attrs.get("type") == "button"
        ):
            self.pagination_semantics[element_id] += 1
        if (
            element_id in {"page-indicator-top", "page-indicator-bottom"}
            and tag == "span" and attrs.get("aria-live") == "polite"
            and "page-indicator" in (attrs.get("class") or "").split()
        ):
            self.pagination_semantics[element_id] += 1
        if tag == "input" and attrs.get("id") == "update-filter-toggle":
            self.update_filter_controls += 1
        if tag == "select" and attrs.get("id") == "author-filter":
            self.author_filter_controls += 1
            self._in_author_filter = True
        if tag == "option" and self._in_author_filter:
            self.author_options.append(attrs.get("value"))
        if tag == "button" and attrs.get("id") == "clear-author-filter":
            self.clear_author_filter_controls += 1
        if tag == "button" and "author-button" in (attrs.get("class") or "").split():
            self.author_buttons.append(attrs)
        if tag == "select" and attrs.get("id") == "category-filter":
            self.category_controls += 1
            self._in_category_filter = True
        if tag == "option" and self._in_category_filter:
            self.category_options.append(attrs.get("value"))
        if (
            tag == "div"
            and "toolbar" in (attrs.get("class") or "").split()
            and attrs.get("role") == "region"
            and attrs.get("aria-label") == "Mod filters"
        ):
            self.sticky_toolbars += 1
        if tag == "article" and "mod-card" in (attrs.get("class") or "").split():
            self.cards += 1
            self._current_card_github_links = []
            self.github_links.append(self._current_card_github_links)
            self._current_card_authors = []
            self.card_author_metadata.append(self._current_card_authors)
            self.card_author_canonical.append(attrs.get("data-author-canonical"))
            self._current_card_category_buttons = []
            self.card_category_buttons.append(self._current_card_category_buttons)
            raw_categories = attrs.get("data-categories")
            try:
                if not isinstance(raw_categories, str):
                    raise ValueError
                parsed_categories = json.loads(raw_categories)
                if (
                    not isinstance(parsed_categories, list)
                    or any(not isinstance(value, str) for value in parsed_categories)
                    or parsed_categories != sorted(set(parsed_categories))
                ):
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_categories = None
            self.card_category_metadata.append(parsed_categories)
            required = {"data-sort-lifetime-rate", "data-sort-version-rate", "data-sort-updated", "data-sort-downloads", "data-source", "data-nsfw", "data-update-filter", "data-categories"}
            if not required.issubset(attrs):
                self.missing_sort += 1
            search_required = {
                "data-search", "data-search-title", "data-search-author",
                "data-search-description",
            }
            if not search_required.issubset(attrs):
                self.missing_search += 1
            self.card_update_metadata.append(
                (attrs.get("data-sort-updated", ""), attrs.get("data-update-filter"))
            )
        if tag == "a" and self._current_card_github_links is not None:
            href = attrs.get("href") or ""
            if "github.com" in href.lower() or "github-link" in (attrs.get("class") or "").split():
                self._in_anchor = True
                self._anchor_href = href
                self._anchor_class = attrs.get("class")
                self._anchor_text = ""
        if tag == "span" and (
            attrs.get("data-author-tier") or attrs.get("data-author-key")
        ):
            attrs["_visible_text"] = ""
            self.author_metadata.append(attrs)
            self._current_author_metadata = attrs
            if self._current_card_authors is not None:
                self._current_card_authors.append(attrs)
        if tag == "button" and "tag" in (attrs.get("class") or "").split():
            if self._current_card_category_buttons is not None:
                self._current_card_category_buttons.append(attrs.get("data-category"))
        if tag == "meta" and attrs.get("name") == "report-generated-at":
            self.report_generated_at = attrs.get("content")
        if tag == "meta" and attrs.get("name") == "report-data-last-updated-at":
            self.report_data_last_updated_at = attrs.get("content")
            self.report_data_last_updated_count += 1

    def handle_endtag(self, tag):
        if tag == "span" and self._current_author_metadata is not None:
            self._current_author_metadata = None
        if tag == "article":
            self._current_card_authors = None
            self._current_card_category_buttons = None
            self._current_card_github_links = None
        if tag == "a" and self._in_anchor:
            if self._current_card_github_links is not None:
                self._current_card_github_links.append(
                    (self._anchor_href, self._anchor_text.strip(), self._anchor_class)
                )
            self._in_anchor = False
        if tag == "select" and self._in_category_filter:
            self._in_category_filter = False
        if tag == "select" and self._in_author_filter:
            self._in_author_filter = False
        if tag == "script":
            self._in_script = False
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_anchor:
            self._anchor_text += data
        if self._current_author_metadata is not None:
            self._current_author_metadata["_visible_text"] = (
                str(self._current_author_metadata.get("_visible_text") or "") + data
            )
        if self._in_script:
            self.script_parts.append(data)
        if self._in_style:
            self.style_parts.append(data)


def verify_report(
    path: Path,
    expected_cards: int | None = None,
    *,
    update_filter: dict | None = DEFAULT_UPDATE_FILTER,
    expected_author_reputation: dict | None = None,
    expected_author_keys: list[str] | None = None,
    expected_card_categories: list[list[str]] | None = None,
    expected_github_links: list[str | None] | None = None,
    github_decisions: dict | None = None,
) -> dict:
    text = path.read_text(encoding="utf-8")
    parser = ReportVerifier()
    parser.feed(text)
    script_text = "".join(parser.script_parts)
    stylesheet_text = "".join(parser.style_parts)
    style_text = re.sub(r"/\*.*?\*/", "", stylesheet_text, flags=re.DOTALL)
    errors = []
    if expected_cards is not None and parser.cards != expected_cards:
        errors.append(f"expected {expected_cards} cards, found {parser.cards}")
    if expected_github_links is None and github_decisions is not None:
        expected_github_links = []
    if expected_github_links is not None:
        actual = []
        for index, card_links in enumerate(parser.github_links):
            if len(card_links) > 1:
                errors.append(f"card {index + 1} has duplicate GitHub links")
            actual.append(card_links[0][0] if card_links else None)
            for href, label, css_class in card_links:
                if label != "GitHub":
                    errors.append("GitHub link label is invalid")
                if css_class != "github-link":
                    errors.append("GitHub link class is invalid")
                if not re.fullmatch(
                    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", href
                ):
                    errors.append("GitHub link is not a canonical repository root")
        if actual != expected_github_links:
            errors.append("GitHub links do not match expected cards")

    required_ids = {
        "pinned-group", "regular-group", "pinned-section", "regular-section",
        "search", "source-filter", "category-filter", "sort", "nsfw-toggle",
    }
    pagination_ids = {
        "pagination-top", "previous-page-top", "next-page-top", "page-indicator-top",
        "pagination-bottom", "previous-page-bottom", "next-page-bottom", "page-indicator-bottom",
    }
    expected_control = render_update_filter_control(update_filter)
    if update_filter is not None:
        required_ids.add("update-filter-toggle")
        if parser.update_filter_controls != 1 or text.count(expected_control) != 1:
            errors.append("update-filter control does not match configuration")
    elif parser.update_filter_controls or "update-filter-toggle" in parser.ids:
        errors.append("unexpected update-filter control")
    if not required_ids.issubset(parser.ids):
        errors.append("missing report controls or fixed groups")
    if not pagination_ids.issubset(parser.ids):
        errors.append("pagination controls are missing or invalid")
    if any(count != 1 for count in parser.pagination_semantics.values()):
        errors.append("pagination control semantics are missing or invalid")
    if parser.missing_sort:
        errors.append(f"{parser.missing_sort} cards lack sort/navigation attributes")
    if parser.missing_search:
        errors.append(f"{parser.missing_search} cards lack search field attributes")
    try:
        latest_update = max(
            (
                parse_datetime(updated_at)
                for updated_at, _ in parser.card_update_metadata
                if updated_at
            ),
            default=None,
        )
    except ValueError:
        latest_update = None
        errors.append("data last updated timestamp is missing or invalid")
    if latest_update is not None:
        expected_latest_iso = latest_update.isoformat().replace("+00:00", "Z")
        latest_arizona = latest_update.astimezone(ZoneInfo("America/Phoenix"))
        expected_latest_label = (
            f"{latest_arizona.strftime('%b')} {latest_arizona.day}, "
            f"{latest_arizona.year} at "
            f"{latest_arizona.strftime('%I:%M %p').lstrip('0')} "
            f"{latest_arizona.tzname()}"
        )
    else:
        expected_latest_iso = ""
        expected_latest_label = "unknown"
    if (
        parser.report_data_last_updated_count != 1
        or parser.report_data_last_updated_at != expected_latest_iso
        or text.count(f"Data last updated at {expected_latest_label}.") != 1
    ):
        errors.append("data last updated timestamp is missing or invalid")
    if parser.category_controls != 1:
        errors.append("category filter control is missing or duplicated")
    if expected_card_categories is not None:
        if parser.card_category_metadata != expected_card_categories:
            errors.append("card category metadata does not match source records")
        if parser.card_category_buttons != expected_card_categories:
            errors.append("category tag buttons do not match card metadata")
        expected_options = [""] + sorted({
            category
            for categories in expected_card_categories
            for category in categories
        })
        if parser.category_options != expected_options:
            errors.append("category filter options do not match report categories")
    if parser.sticky_toolbars != 1 or (
        hashlib.sha256(stylesheet_text.encode("utf-8")).hexdigest()
        != REPORT_STYLESHEET_SHA256
        or
        ".toolbar{position:sticky;top:0;z-index:20" not in style_text
        or "@media(max-width:520px){header,main{padding:18px 14px}.toolbar{position:static;padding:10px 14px;max-height:none;overflow:visible" not in style_text
    ):
        errors.append("sticky toolbar contract is missing or invalid")
    category_javascript = (
        "category=document.querySelector('#category-filter')",
        "(!category.value||JSON.parse(c.dataset.categories).includes(category.value))",
        "[search,source,category,sort,nsfw,...(updateFilter?[updateFilter]:[])]",
        "e.stopPropagation();category.value=tag.dataset.category;currentPage=1;update();category.focus()",
    )
    if script_text != REPORT_JAVASCRIPT or any(
        fragment not in script_text for fragment in category_javascript
    ):
        errors.append("category filter JavaScript contract is missing or invalid")
    pagination_javascript = (
        "const pageSize=100",
        "const totalPages=Math.ceil(matching.length/pageSize)",
        "const pageCards=matching.slice(start,start+pageSize)",
        "pinnedSection.hidden=!pageCards.some(c=>c.parentElement===pinnedGroup)",
        "regularSection.hidden=!pageCards.some(c=>c.parentElement===regularGroup)",
        "currentPage=1;update()",
        "previousPages.forEach(b=>b.addEventListener('click'",
        "nextPages.forEach(b=>b.addEventListener('click'",
        "pageIndicators.forEach(i=>i.textContent",
        "previousPages.forEach(b=>b.disabled",
        "nextPages.forEach(b=>b.disabled",
    )
    if script_text != REPORT_JAVASCRIPT or any(
        fragment not in script_text for fragment in pagination_javascript
    ):
        errors.append("pagination JavaScript contract is missing or invalid")
    search_javascript = (
        "c.dataset.search.includes(q)",
        ".sort((a,b)=>sort.value==='updated'?b.dataset[key].localeCompare(a.dataset[key]):Number(b.dataset[key])-Number(a.dataset[key]))",
        "function normalizeSearch(value){return value.replace(/^[ \\t\\n\\r\\f\\v]+|[ \\t\\n\\r\\f\\v]+$/g,'').toLowerCase().replace(/[ \\t\\n\\r\\f\\v]+/g,' ')}",
        "const q=normalizeSearch(search.value)",
    )
    if script_text != REPORT_JAVASCRIPT or any(
        fragment not in script_text for fragment in search_javascript
    ):
        errors.append("search JavaScript contract is missing or invalid")
    metadata_errors = 0
    for updated_at, actual in parser.card_update_metadata:
        try:
            expected = str(matches_update_filter(updated_at, update_filter)).lower()
        except ValueError:
            metadata_errors += 1
            continue
        if actual != expected:
            metadata_errors += 1
    if metadata_errors:
        errors.append(f"{metadata_errors} cards have incorrect update-filter metadata")
    if expected_author_reputation is not None:
        expected_authors = expected_author_reputation.get("authors", {})
        expected_generated_at = expected_author_reputation.get("generated_at")
        if parser.report_generated_at != expected_generated_at:
            errors.append("report and author reputation generated_at do not match")
        if expected_authors and not parser.author_metadata:
            errors.append("enabled author reputation has no rendered author metadata")
        author_errors = 0
        for attrs in parser.author_metadata:
            identity = attrs.get("data-author-key")
            profile = expected_authors.get(identity)
            tier = attrs.get("data-author-tier")
            downloads = attrs.get("data-author-downloads")
            mod_count = attrs.get("data-author-mod-count")
            first_published = attrs.get("data-author-first-published")
            classes = set((attrs.get("class") or "").split())
            if profile is None:
                author_errors += 1
                continue
            if (
                tier != profile.get("tier")
                or downloads != str(profile.get("downloads"))
                or mod_count != str(profile.get("mod_count"))
                or first_published != str(profile.get("first_mod_published_at") or "")
                or attrs.get("data-author-canonical")
                != str(profile.get("canonical_author_id"))
                or (
                    profile.get("display_name") is not None
                    and attrs.get("_visible_text") != str(profile.get("display_name"))
                )
                or "author" not in classes
                or f"author-tier-{profile.get('tier')}" not in classes
            ):
                author_errors += 1
            expected_mod_count = int(profile.get("mod_count", -1))
            mod_label = (
                f"{expected_mod_count} known mod"
                f"{'s' if expected_mod_count != 1 else ''}"
            )
            expected_first = profile.get("first_mod_published_at")
            if expected_first:
                first_date = parse_datetime(str(expected_first))
                first_label = (
                    f"{first_date.strftime('%b')} {first_date.day}, {first_date.year}"
                )
                first_evidence = f"first known mod published {first_label}"
            else:
                first_evidence = "first known mod publication unknown"
            evidence = (
                f"{str(profile.get('tier', '')).title()} author · "
                f"{int(profile.get('downloads', -1)):,} lifetime downloads · "
                f"{mod_label} · {first_evidence}"
            )
            if evidence not in attrs.get("title", ""):
                author_errors += 1
            aria_label = attrs.get("aria-label", "")
            if (
                f"{str(profile.get('tier', '')).title()} author" not in aria_label
                or f"{int(profile.get('downloads', -1)):,}" not in aria_label
                or mod_label not in aria_label
                or first_evidence not in aria_label
            ):
                author_errors += 1
        if author_errors:
            errors.append(f"{author_errors} author metadata entries do not match reputation")
        if expected_author_keys is not None:
            actual_author_keys = [
                attrs.get("data-author-key") for attrs in parser.author_metadata
            ]
            if sorted(actual_author_keys) != sorted(expected_author_keys):
                errors.append("rendered author identities do not match report cards")
            if len(parser.card_author_metadata) != len(expected_author_keys) or any(
                len(card_authors) != 1
                or parser.card_author_canonical[index] != card_authors[0].get("data-author-canonical")
                for index, card_authors in enumerate(parser.card_author_metadata)
            ):
                errors.append("each report card must contain exactly one author metadata entry")
    if expected_author_reputation is not None:
        expected_authors = expected_author_reputation.get("authors", {})
        rendered_identity_keys = (
            expected_author_keys
            if expected_author_keys is not None
            else [attrs.get("data-author-key") for attrs in parser.author_metadata]
        )
        rendered_canonicals = {
            str(expected_authors[identity].get("canonical_author_id"))
            for identity in rendered_identity_keys
            if identity in expected_authors
            and expected_authors[identity].get("canonical_author_id") is not None
        }
        if rendered_canonicals:
            if parser.author_filter_controls != 1 or parser.clear_author_filter_controls != 1:
                errors.append("author filter controls are missing or invalid")
            expected_options = [""] + sorted(rendered_canonicals)
            if parser.author_options != expected_options:
                errors.append("author filter options do not match report authors")
            actual_canonicals = {attrs.get("data-author-canonical") for attrs in parser.author_buttons}
            actual_button_keys = {attrs.get("data-author-key") for attrs in parser.author_buttons}
            actual_metadata_keys = {attrs.get("data-author-key") for attrs in parser.author_metadata}
            actual_metadata_canonicals = {attrs.get("data-author-canonical") for attrs in parser.author_metadata}
            if actual_canonicals != rendered_canonicals or actual_button_keys != actual_metadata_keys or actual_metadata_canonicals != actual_canonicals:
                errors.append("author filter buttons do not match report authors")
            if any(attrs.get("type") != "button" or attrs.get("aria-pressed") != "false" for attrs in parser.author_buttons):
                errors.append("author buttons are not native or lack state semantics")
        elif parser.author_filter_controls or parser.clear_author_filter_controls or parser.author_buttons:
            errors.append("unexpected author filter controls")
    elif parser.author_filter_controls or parser.clear_author_filter_controls or parser.author_buttons:
        errors.append("unexpected author filter controls")
    required_javascript = (
        "updateFilter=document.querySelector('#update-filter-toggle')",
        "(!updateFilter||!updateFilter.checked||c.dataset.updateFilter==='true')",
        "[search,source,category,sort,nsfw,...(updateFilter?[updateFilter]:[])]",
    )
    if not all(fragment in script_text for fragment in required_javascript):
        errors.append("missing shared update-filter JavaScript")
    return {"ok": not errors, "cards": parser.cards, "errors": errors}


def load_cookie_header(path: Path) -> str:
    """Load either a Netscape cookie jar or a one-line exported Cookie header."""
    text = path.read_text(encoding="utf-8").strip()
    if "\t" not in text:
        return text.removeprefix("Cookie:").strip()
    cookies = []
    for line in text.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if len(fields) >= 7 and fields[0].lstrip(".").endswith("nexusmods.com"):
            cookies.append(f"{fields[5]}={fields[6]}")
    if not cookies:
        raise ValueError("cookie file contains no nexusmods.com cookies")
    return "; ".join(cookies)


def generate_report(
    root: Path,
    generated_at: str,
    *,
    embed_thumbnails: bool = False,
    game_name: str = "Valheim",
    sources=("thunderstore", "nexus"),
    update_filter: dict | None = DEFAULT_UPDATE_FILTER,
    author_tiers: dict | None = None,
    thumbnail_fetch=http_fetch,
    github_game: str | None = None,
    github_state_path: Path | None = None,
) -> dict:
    mods_path = root / "data/mods.json"
    mods = _load_json(mods_path, [])
    mods = apply_manual_mappings(mods, _load_json(root / "mappings.json", {}))
    state_path = _github_state_path(root, github_state_path)
    github_decisions = load_github_repositories(state_path)["records"] if state_path else {}
    validate_github_game_scope(mods, github_decisions, github_game)
    now = parse_datetime(generated_at)
    for mod in mods:
        mod["rates"] = compute_rates(mod, now)
    atomic_write_json(mods_path, mods)
    author_reputation = None
    if author_tiers is not None:
        mappings = load_author_mappings(root / author_tiers["mappings_file"])
        built_reputation = build_author_reputation(mods, author_tiers, mappings)
        if built_reputation is None:
            raise AssertionError("configured author tiers did not produce reputation data")
        author_reputation = {"generated_at": generated_at, **built_reputation}
        atomic_write_json(root / "data/author-reputation.json", author_reputation)
    page = render_report(
        mods,
        generated_at,
        embed_thumbnails=embed_thumbnails,
        thumbnail_fetch=thumbnail_fetch,
        game_name=game_name,
        sources=sources,
        update_filter=update_filter,
        author_reputation=author_reputation,
        github_decisions=github_decisions,
        github_game=github_game,
    )
    atomic_write_bytes(root / "report.html", page.encode("utf-8"))
    hotlinked_page = page if not embed_thumbnails else render_report(
        mods,
        generated_at,
        embed_thumbnails=False,
        game_name=game_name,
        sources=sources,
        update_filter=update_filter,
        author_reputation=author_reputation,
        github_decisions=github_decisions,
        github_game=github_game,
    )
    atomic_write_bytes(root / "report-hotlinked.html", hotlinked_page.encode("utf-8"))
    result = verify_report(
        root / "report.html",
        expected_cards=len(_report_groups(mods)),
        update_filter=update_filter,
        expected_author_reputation=author_reputation,
        expected_author_keys=report_author_keys(mods, author_reputation),
        expected_card_categories=report_category_sets(mods),
        expected_github_links=report_github_links(mods, github_decisions, game_key=github_game),
    )
    if not result["ok"]:
        raise RuntimeError("generated report failed verification: " + "; ".join(result["errors"]))
    return result


def verify_output(
    root: Path,
    *,
    expected_thunderstore_pages: int = 4,
    expected_nexus_pages: int = 2,
    require_full_nexus_pages: bool = True,
    update_filter: dict | None = DEFAULT_UPDATE_FILTER,
    author_tiers: dict | None = None,
    require_reports: bool = False,
    github_game: str | None = None,
    github_state_path: Path | None = None,
) -> dict:
    errors = []
    ts_appearances = 0
    thunderstore_page_counts = {}
    if expected_thunderstore_pages:
        listing_root = root / "raw/thunderstore/listings"
        listing_scope = _load_json(listing_root / "manifest.json", None)
        snapshot = _load_json(root / "snapshots/latest.json", None)
        if not isinstance(listing_scope, dict):
            errors.append("missing or invalid raw/thunderstore/listings/manifest.json")
            listing_scope = {}
        if listing_scope.get("requested_pages_per_sort") != expected_thunderstore_pages:
            errors.append(
                "Thunderstore listing manifest requested page count does not match configured scope"
            )
        rankings = listing_scope.get("rankings", {})
        snapshot_counts = (
            snapshot.get("thunderstore_pages_per_sort")
            if isinstance(snapshot, dict)
            else None
        )
        if not isinstance(snapshot_counts, dict):
            errors.append("snapshot lacks Thunderstore pages-per-sort counts")
            snapshot_counts = {}

        for ordering in ("last-updated", "most-downloaded"):
            ranking = rankings.get(ordering, {}) if isinstance(rankings, dict) else {}
            fetched_pages = ranking.get("fetched_pages")
            terminal_status = ranking.get("terminal_http_status")
            if (
                not isinstance(fetched_pages, int)
                or isinstance(fetched_pages, bool)
                or not 1 <= fetched_pages <= expected_thunderstore_pages
            ):
                errors.append(f"invalid fetched page count for Thunderstore {ordering}")
                fetched_pages = expected_thunderstore_pages
            thunderstore_page_counts[ordering] = fetched_pages
            if fetched_pages < expected_thunderstore_pages and terminal_status != 404:
                errors.append(f"Thunderstore {ordering} ended early without terminal HTTP 404")
            if fetched_pages == expected_thunderstore_pages and terminal_status is not None:
                errors.append(f"unexpected terminal HTTP status for Thunderstore {ordering}")
            if snapshot_counts.get(ordering) != fetched_pages:
                errors.append(f"snapshot page count does not match Thunderstore {ordering} evidence")

            listing_dir = listing_root / ordering
            for stale in listing_dir.glob("page-*.html"):
                match = re.fullmatch(r"page-(\d+)\.html", stale.name)
                if match and int(match.group(1)) not in range(1, fetched_pages + 1):
                    errors.append(f"unexpected {stale.relative_to(root)} beyond fetched scope")
            for page in range(1, fetched_pages + 1):
                path = listing_dir / f"page-{page}.html"
                if not path.exists():
                    errors.append(f"missing {path.relative_to(root)}")
                    continue
                count = len(parse_listing(path.read_text(encoding="utf-8")))
                ts_appearances += count
                terminal_page = page == fetched_pages and terminal_status == 404
                if count < 1 or count > 20 or (not terminal_page and count != 20):
                    expectation = "1 to 20" if terminal_page else "20"
                    errors.append(
                        f"{path.relative_to(root)} has {count} cards, expected {expectation}"
                    )
    nexus_appearances = 0
    nexus_ids = []
    short_page_seen = False
    for stale in (root / "raw/nexus").glob("listing-page-*.json"):
        match = re.fullmatch(r"listing-page-(\d+)\.json", stale.name)
        if match and int(match.group(1)) > expected_nexus_pages:
            errors.append(f"unexpected {stale.relative_to(root)} beyond configured scope")
    for page in range(1, expected_nexus_pages + 1):
        path = root / f"raw/nexus/listing-page-{page}.json"
        if short_page_seen:
            if path.exists():
                errors.append(f"unexpected {path.relative_to(root)} after a short Nexus page")
            continue
        listing = _load_json(path, None)
        if listing is None:
            errors.append(f"missing or invalid {path.relative_to(root)}")
            continue
        count = len(listing.get("data", {}).get("mods", {}).get("nodes", []))
        nexus_ids.extend(
            str(node.get("modId"))
            for node in listing.get("data", {}).get("mods", {}).get("nodes", [])
        )
        nexus_appearances += count
        if require_full_nexus_pages and count != 80:
            errors.append(f"{path.relative_to(root)} has {count} nodes, expected 80")
        elif not require_full_nexus_pages:
            if count > 80:
                errors.append(f"{path.relative_to(root)} has {count} nodes, expected at most 80")
            short_page_seen = count < 80
    nexus_distinct = len(set(nexus_ids))
    if nexus_distinct != len(nexus_ids):
        errors.append(
            f"Nexus listing contains {nexus_distinct} distinct mod IDs across "
            f"{len(nexus_ids)} appearances"
        )
    mods = _load_json(root / "data/mods.json", None)
    if mods is None:
        errors.append("missing or invalid data/mods.json")
        mods = []
    keys = [item.get("key") for item in mods]
    if len(keys) != len(set(keys)):
        errors.append("data/mods.json contains duplicate keys")
    required = {"source", "source_id", "title", "author", "summary", "categories", "thumbnail", "canonical_url", "created_at", "updated_at", "total_downloads", "version", "rank", "pinned", "observations", "canonical_group_id", "match"}
    incomplete = [item.get("key", "<unknown>") for item in mods if not required.issubset(item)]
    if incomplete:
        errors.append(f"{len(incomplete)} records lack common fields")
    try:
        authoritative_mods = apply_manual_mappings(
            mods,
            _load_json(root / "mappings.json", {}),
        )
        mapping_fields = ("canonical_group_id", "match", "credited_author")
        mapping_mismatches = sum(
            any(persisted.get(field) != authoritative.get(field) for field in mapping_fields)
            for persisted, authoritative in zip(mods, authoritative_mods)
        )
        if mapping_mismatches:
            errors.append(
                f"{mapping_mismatches} records disagree with authoritative mappings"
            )
        mods = authoritative_mods
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"invalid authoritative mappings: {exc}")
    expected_author_reputation = None
    reputation_path = root / "data/author-reputation.json"
    if author_tiers is not None:
        try:
            mappings = load_author_mappings(root / author_tiers["mappings_file"])
            expected_author_reputation = build_author_reputation(
                mods, author_tiers, mappings
            )
            if expected_author_reputation is None:
                raise ValueError("author reputation could not be built")
            actual_reputation = _load_json(reputation_path, None)
            if not isinstance(actual_reputation, dict):
                errors.append("missing or invalid author reputation artifact")
            else:
                actual_core = {
                    key: value
                    for key, value in actual_reputation.items()
                    if key != "generated_at"
                }
                if actual_core != expected_author_reputation:
                    errors.append("author reputation artifact does not match current data")
                generated_at = actual_reputation.get("generated_at")
                if not isinstance(generated_at, str):
                    errors.append("author reputation artifact has invalid generated_at")
                else:
                    try:
                        parse_datetime(generated_at)
                    except ValueError:
                        errors.append("author reputation artifact has invalid generated_at")
                    expected_author_reputation = {
                        "generated_at": generated_at,
                        **expected_author_reputation,
                    }
        except (OSError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"invalid author reputation configuration or data: {exc}")
    elif reputation_path.exists():
        errors.append("unexpected author reputation artifact")
    expected_author_keys = report_author_keys(mods, expected_author_reputation)
    state_path = _github_state_path(root, github_state_path)
    github_decisions = load_github_repositories(state_path)["records"] if state_path else {}
    validate_github_game_scope(mods, github_decisions, github_game)
    expected_github_links = report_github_links(mods, github_decisions, game_key=github_game)
    report_result = None
    report_path = root / "report.html"
    hotlinked_path = root / "report-hotlinked.html"
    if report_path.exists():
        report_result = verify_report(
            report_path,
            expected_cards=len(_report_groups(mods)),
            update_filter=update_filter,
            expected_author_reputation=expected_author_reputation,
            expected_author_keys=expected_author_keys,
            expected_card_categories=report_category_sets(mods),
            expected_github_links=expected_github_links,
        )
        errors.extend(report_result["errors"])
    elif require_reports:
        errors.append("missing report.html")
    hotlinked_result = None
    if hotlinked_path.exists():
        hotlinked_result = verify_report(
            hotlinked_path,
            expected_cards=len(_report_groups(mods)),
            update_filter=update_filter,
            expected_author_reputation=expected_author_reputation,
            expected_author_keys=expected_author_keys,
            expected_card_categories=report_category_sets(mods),
            expected_github_links=expected_github_links,
        )
        errors.extend(hotlinked_result["errors"])
        local_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
        if (
            report_path.exists()
            and "data:image/" not in local_text
            and report_path.read_bytes() != hotlinked_path.read_bytes()
        ):
            errors.append("report.html and report-hotlinked.html differ")
        if "data:image/" in hotlinked_path.read_text(encoding="utf-8"):
            errors.append("report-hotlinked.html contains embedded images")
    elif require_reports:
        errors.append("missing report-hotlinked.html")
    return {
        "ok": not errors,
        "errors": errors,
        "mods": len(mods),
        "thunderstore_appearances": ts_appearances,
        "thunderstore_pages_per_sort": thunderstore_page_counts,
        "nexus_appearances": nexus_appearances,
        "nexus_distinct": nexus_distinct,
        "report": report_result,
        "report_hotlinked": hotlinked_result,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual multi-game mod tracker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="collect sources, persist data, and render report")
    collect.add_argument("--game", choices=(*GAME_CONFIGS, "all"), default="valheim")
    collect.add_argument("--output-root", type=Path, default=Path("."))
    collect.add_argument("--sources", choices=("all", "thunderstore", "nexus"), default="all")
    collect.add_argument("--thunderstore-pages", type=int)
    collect.add_argument("--nexus-pages", type=int)
    collect.add_argument("--nexus-api-key-file", type=Path, default=Path.home() / ".config/nexus-mods/api-key")
    collect.add_argument("--nexus-cookie-file", type=Path)
    collect.add_argument("--mappings", type=Path)
    collect.add_argument("--embed-thumbnails", action="store_true")
    collect.add_argument(
        "--no-report",
        action="store_true",
        help="persist collection data without rendering a report",
    )
    report = subparsers.add_parser("report", help="regenerate report from persisted data")
    report.add_argument("--game", choices=(*GAME_CONFIGS, "all"), default="valheim")
    report.add_argument("--output-root", type=Path, default=Path("."))
    report.add_argument("--embed-thumbnails", action="store_true")
    verify = subparsers.add_parser("verify", help="verify raw inputs, normalized data, and report")
    verify.add_argument("--game", choices=(*GAME_CONFIGS, "all"), default="valheim")
    verify.add_argument("--output-root", type=Path, default=Path("."))
    verify.add_argument("--thunderstore-pages", type=int)
    verify.add_argument("--nexus-pages", type=int)
    return parser


def _game_keys(selection: str) -> list[str]:
    return list(GAME_CONFIGS) if selection == "all" else [selection]


def game_page_counts(config: dict, args) -> tuple[int, int]:
    """Resolve optional CLI overrides against per-game registry defaults."""
    thunderstore_pages = (
        args.thunderstore_pages
        if args.thunderstore_pages is not None
        else config.get("thunderstore_pages", 0)
    )
    nexus_pages = args.nexus_pages if args.nexus_pages is not None else config["nexus_pages"]
    if thunderstore_pages < 1 and "thunderstore" in config["sources"]:
        raise ValueError("thunderstore page count must be positive")
    if nexus_pages < 1 and "nexus" in config["sources"]:
        raise ValueError("nexus page count must be positive")
    return thunderstore_pages, nexus_pages


def _run_game_collection(args, game_key: str, collected_at: str) -> dict:
    config = GAME_CONFIGS[game_key]
    root = game_output_root(args.output_root.resolve(), game_key)
    supported_sources = set(config["sources"])
    if args.sources == "all":
        selected_sources = supported_sources
    elif args.sources in supported_sources:
        selected_sources = {args.sources}
    else:
        raise ValueError(f"{game_key} does not support source {args.sources!r}")
    thunderstore_pages, nexus_pages = game_page_counts(config, args)
    provider_jobs = {}
    if "thunderstore" in selected_sources:
        provider_jobs["thunderstore"] = (
            collect_thunderstore,
            (root, thunderstore_pages, collected_at),
            {"community": config["thunderstore_community"]},
        )
    if "nexus" in selected_sources:
        api_key = args.nexus_api_key_file.read_text(encoding="utf-8").strip()
        cookie_header = load_cookie_header(args.nexus_cookie_file) if args.nexus_cookie_file else None
        provider_jobs["nexus"] = (
            collect_nexus,
            (root, api_key, collected_at),
            {
                "cookie_header": cookie_header,
                "game_domain": config["nexus_domain"],
                "pages": nexus_pages,
                "require_full_pages": config["require_full_nexus_pages"],
            },
        )

    if len(provider_jobs) == 1:
        provider_results = {
            source: function(*positional, **keywords)
            for source, (function, positional, keywords) in provider_jobs.items()
        }
    else:
        with ThreadPoolExecutor(max_workers=len(provider_jobs)) as executor:
            futures = {
                source: executor.submit(function, *positional, **keywords)
                for source, (function, positional, keywords) in provider_jobs.items()
            }
            provider_results = {}
            provider_failures = []
            for source in ("thunderstore", "nexus"):
                if source not in futures:
                    continue
                try:
                    provider_results[source] = futures[source].result()
                except Exception as exc:
                    detail = str(exc) or type(exc).__name__
                    provider_failures.append(f"{source}: {detail}")
            if provider_failures:
                raise RuntimeError(
                    f"provider collection failed for {game_key}: "
                    + "; ".join(provider_failures)
                )

    fresh = []
    for source in ("thunderstore", "nexus"):
        fresh.extend(provider_results.get(source, []))

    thunderstore_page_counts = {}
    if "thunderstore" in selected_sources:
        listing_scope = _load_json(
            root / "raw/thunderstore/listings/manifest.json", None
        )
        rankings = listing_scope.get("rankings") if isinstance(listing_scope, dict) else None
        if not isinstance(rankings, dict):
            raise RuntimeError("Thunderstore collector did not write valid listing scope")
        for ordering in ("last-updated", "most-downloaded"):
            ranking = rankings.get(ordering)
            fetched_pages = ranking.get("fetched_pages") if isinstance(ranking, dict) else None
            if not isinstance(fetched_pages, int) or isinstance(fetched_pages, bool):
                raise RuntimeError(
                    f"Thunderstore collector wrote invalid page count for {ordering}"
                )
            thunderstore_page_counts[ordering] = fetched_pages
    mods_path = root / "data/mods.json"
    mods = merge_mods(_load_json(mods_path, []), fresh, collected_at)
    if args.mappings and game_key == "valheim":
        mods = apply_manual_mappings(mods, _load_json(args.mappings, {}))
    else:
        mods = apply_manual_mappings(mods, _load_json(root / "mappings.json", {}))
    atomic_write_json(mods_path, mods)
    manifest = {
        "collected_at": collected_at,
        "game": game_key,
        "sources": sorted(selected_sources),
        "fresh_records": len(fresh),
        "stored_records": len(mods),
        "thunderstore_pages_per_sort": thunderstore_page_counts,
        "nexus_pages": nexus_pages if "nexus" in selected_sources else 0,
    }
    atomic_write_json(root / "snapshots/latest.json", manifest)
    report = None
    if not args.no_report:
        report = generate_report(
            root,
            collected_at,
            embed_thumbnails=args.embed_thumbnails,
            game_name=config["display_name"],
            sources=config["sources"],
            update_filter=config["update_filter"],
            author_tiers=config["author_tiers"],
            github_game=game_key,
            github_state_path=_default_github_state_path(args.output_root),
        )
    return {**manifest, "report_cards": report["cards"] if report else None}


def run_collection(args) -> dict:
    collected_at = utc_now()
    keys = _game_keys(args.game)
    unsupported = [
        key
        for key in keys
        if args.sources != "all" and args.sources not in GAME_CONFIGS[key]["sources"]
    ]
    if unsupported:
        raise ValueError(
            f"source {args.sources!r} is not configured for: {', '.join(unsupported)}"
        )
    results = {key: _run_game_collection(args, key, collected_at) for key in keys}
    if args.game != "all":
        return results[keys[0]]
    return {"ok": True, "collected_at": collected_at, "games": results}


def _default_github_state_path(output_root: Path) -> Path | None:
    path = output_root.resolve() / "github-repositories.json"
    return path if path.is_file() else None


def _generate_selected_reports(args, generated_at: str) -> dict:
    results = {}
    for key in _game_keys(args.game):
        config = GAME_CONFIGS[key]
        root = game_output_root(args.output_root.resolve(), key)
        results[key] = generate_report(
            root,
            generated_at,
            embed_thumbnails=args.embed_thumbnails,
            game_name=config["display_name"],
            sources=config["sources"],
            update_filter=config["update_filter"],
            author_tiers=config["author_tiers"],
            github_game=key,
            github_state_path=_default_github_state_path(args.output_root),
        )
    if args.game != "all":
        return results[args.game]
    return {"ok": all(result["ok"] for result in results.values()), "games": results}


def _verify_selected_outputs(args) -> dict:
    results = {}
    for key in _game_keys(args.game):
        config = GAME_CONFIGS[key]
        root = game_output_root(args.output_root.resolve(), key)
        thunderstore_pages, nexus_pages = game_page_counts(config, args)
        results[key] = verify_output(
            root,
            expected_thunderstore_pages=thunderstore_pages if "thunderstore" in config["sources"] else 0,
            expected_nexus_pages=nexus_pages if "nexus" in config["sources"] else 0,
            require_full_nexus_pages=config["require_full_nexus_pages"],
            update_filter=config["update_filter"],
            author_tiers=config["author_tiers"],
            require_reports=True,
            github_game=key,
            github_state_path=_default_github_state_path(args.output_root),
        )
    if args.game != "all":
        return results[args.game]
    return {"ok": all(result["ok"] for result in results.values()), "games": results}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        result = run_collection(args)
    elif args.command == "report":
        result = _generate_selected_reports(args, utc_now())
    else:
        result = _verify_selected_outputs(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
