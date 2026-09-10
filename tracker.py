#!/usr/bin/env python3
"""Track ranked Thunderstore package cards as flat files."""

from __future__ import annotations

import json
import math
import os
import re
import time
import base64
import argparse
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urljoin, urlparse
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
            "display_name", "nexus_domain", "nexus_pages", "output_subdir",
            "publication", "require_full_nexus_pages", "sources", "v1_cutoff",
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
        if not isinstance(publication, dict) or set(publication) != {"section", "name"}:
            raise ValueError(f"{key} has invalid publication")
        if not all(SLUG_RE.fullmatch(publication.get(field, "")) for field in ("section", "name")):
            raise ValueError(f"{key} has invalid publication component")
        destination = (publication["section"], publication["name"])
        if destination in publication_paths:
            raise ValueError(f"duplicate publication destination: {'/'.join(destination)}")
        publication_paths.add(destination)
        cutoff = config["v1_cutoff"]
        if cutoff is not None:
            try:
                datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
            except (AttributeError, ValueError) as exc:
                raise ValueError(f"{key} has invalid v1_cutoff") from exc
    return registry


GAME_CONFIGS = load_game_registry()


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
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get("class") or "").split())
        if self.depth or "markdown-body" in classes:
            self.depth += 1
            rendered = "".join(f' {name}="{value}"' for name, value in attrs if value is not None)
            self.parts.append(f"<{tag}{rendered}>")

    def handle_endtag(self, tag):
        if self.depth:
            self.parts.append(f"</{tag}>")
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


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
    result["readme_html"] = "".join(parser.parts)
    return result


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
    for ordering in ("last-updated", "most-downloaded"):
        rank = 0
        for page in range(1, pages + 1):
            url = f"https://thunderstore.io/c/{community}/?ordering={ordering}&page={page}"
            body = fetch(url)
            atomic_write_bytes(root / f"raw/thunderstore/listings/{ordering}/page-{page}.html", body)
            pause()
            cards = parse_listing(body.decode("utf-8"))
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
            if match and int(match.group(1)) > pages:
                stale.unlink()

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
        if is_new:
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
    result = []
    for mod in mods:
        copied = dict(mod)
        mapping = mappings.get(mod["key"])
        if mapping:
            copied["canonical_group_id"] = mapping.get("canonical_group_id")
            copied["match"] = {
                "method": mapping.get("method", "manual"),
                "matched_to": list(mapping.get("matched_to", [])),
            }
        else:
            copied.setdefault("canonical_group_id", None)
            copied.setdefault("match", None)
        result.append(copied)
    return result


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


def render_report(
    mods,
    generated_at,
    *,
    embed_thumbnails=False,
    thumbnail_fetch=http_fetch,
    game_name="Valheim",
    sources=("thunderstore", "nexus"),
    v1_cutoff: str | None = "2026-09-08T00:00:00Z",
):
    now = parse_datetime(generated_at)
    arizona_now = now.astimezone(ZoneInfo("America/Phoenix"))
    generated_label = (
        f"{arizona_now.strftime('%b')} {arizona_now.day}, {arizona_now.year} at "
        f"{arizona_now.strftime('%I:%M %p').lstrip('0')} {arizona_now.tzname()}"
    )
    def card(members):
        members = sorted(members, key=lambda m: m['source'])
        primary = max(members, key=lambda m: (m.get('updated_at') or '', m.get('key','')))
        sources = {m['source'] for m in members}; both = len(sources) > 1
        source = 'both' if both else next(iter(sources)); label = 'Both' if both else ('Thunderstore' if source == 'thunderstore' else 'Nexus Mods')
        rates = [compute_rates(m, now) for m in members]
        updated = max((m.get('updated_at') or '' for m in members), default='')
        created = min((m.get('created_at') or '' for m in members if m.get('created_at')), default='')
        lifetime = sum(r['lifetime_downloads_per_day'] for r in rates)
        vr = [r['current_version_observed_downloads_per_day'] for r in rates if r['current_version_observed_downloads_per_day'] is not None]
        version_rate = sum(vr) if vr else None
        total_downloads = sum(int(m.get('total_downloads') or 0) for m in members)
        lifetime_label = 'Combined lifetime / day' if both else 'Lifetime / day'
        adult = any(m.get('adult_content') for m in members)
        pinned = any(m.get('pinned') for m in members)
        cats = sorted({x for m in members for x in m.get('categories',[])})
        search = ' '.join([x for m in members for x in [m.get('title',''),m.get('author','')]+m.get('categories',[])]).lower()
        links = ''.join('<a class="source-link" href="%s">%s</a>' % (escape(m['canonical_url'],quote=True), 'Thunderstore' if m['source']=='thunderstore' else 'Nexus Mods') for m in members)
        metrics = ''.join('<div><dt>%s downloads</dt><dd>%s</dd></div><div><dt>Endorsements / likes</dt><dd>%s / %s</dd></div>' % ('Thunderstore' if m['source']=='thunderstore' else 'Nexus Mods', f"{int(m.get('total_downloads') or 0):,}", f"{int(m.get('endorsements') or 0):,}", f"{int(m.get('likes') or 0):,}") for m in members)
        images = ''.join('<img class="thumb" src="%s" alt="" loading="lazy">' % escape(_thumbnail_src(m, embed_thumbnails, thumbnail_fetch), quote=True) for m in members)
        return '''<article class="mod-card source-%s%s" data-source="%s" data-nsfw="%s" data-v1="%s" data-search="%s" data-url="%s" tabindex="0" role="link" data-sort-lifetime-rate="%s" data-sort-version-rate="%s" data-sort-updated="%s" data-sort-downloads="%s">
<div class="media">%s</div><div class="body"><div class="badges"><span class="source %s">%s</span>%s%s</div><h2><a href="%s">%s</a></h2><p class="by">by %s · v%s</p><p class="summary">%s</p><div class="tags">%s</div><p class="source-links">%s</p><p class="dates">Updated <time>%s</time> · Uploaded <time>%s</time></p></div><dl class="metrics">%s<div><dt>%s</dt><dd>%s</dd></div></dl></article>''' % (
            source, ' pinned' if pinned else '', source, str(adult).lower(), str(bool(v1_cutoff and updated >= v1_cutoff)).lower(), escape(search,quote=True), escape(primary['canonical_url'],quote=True), _sort_number(lifetime), _sort_number(version_rate), escape(updated,quote=True), _sort_number(total_downloads), images, source, label, '<span class="pin">Pinned</span>' if pinned else '', '<span class="nsfw">NSFW</span>' if adult else '', escape(primary['canonical_url'],quote=True), escape(primary.get('title','')), escape(primary.get('author','')), escape(str(primary.get('version') or '—')), escape(primary.get('summary') or ''), ''.join('<span class="tag">%s</span>'%escape(x) for x in cats), links, escape(updated[:10] or 'unknown'), escape(created[:10] or 'unknown'), metrics, lifetime_label, f"{lifetime:,.1f}")
    groups = _report_groups(mods)
    pinned = ''.join(card(g) for g in groups if any(m.get('pinned') for m in g)); regular = ''.join(card(g) for g in groups if not any(m.get('pinned') for m in g))
    initial_visible = sum(not any(m.get('adult_content') for m in group) for group in groups)
    page = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Valheim Mod Tracker</title><style>
:root{--bg:#090b0e;--panel:#171a1f;--line:#30353d;--text:#f2f4f7;--muted:#9ca3ad;--ts-bg:#202c3d;--ts-line:#4d6b91;--nx-bg:#3b2922;--nx-line:#9a5e3b}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui}header,main{max-width:1320px;margin:auto;padding:28px}header{border-bottom:1px solid var(--line)}h1{font-size:clamp(30px,5vw,52px);margin:0}.subtitle{color:var(--muted)}.toolbar{display:flex;align-items:end;gap:12px;flex-wrap:wrap}.results{font-weight:700;margin-right:auto;min-height:44px;display:flex;align-items:center}.control{display:grid;gap:4px;color:var(--muted);font-size:12px}.toggle-row{display:flex;gap:16px;align-items:center;min-height:44px;flex-wrap:wrap}.toggle-control{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap}.toggle-control input{width:18px;height:18px;min-height:0;margin:0;padding:0;flex:0 0 auto;accent-color:#2587e8}.body h2 a,.body h2 a:visited{color:var(--text);text-decoration:none}.body h2 a:hover{text-decoration:underline}input,select{min-height:44px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:10px;font:inherit}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px}.mod-card{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:auto 1fr auto;overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:8px;cursor:pointer}.mod-card[data-nsfw="true"]{display:none}.show-nsfw .mod-card[data-nsfw="true"]{display:grid}.mod-card.source-thunderstore{background:var(--ts-bg);border-color:var(--ts-line)}.mod-card.source-nexus{background:var(--nx-bg);border-color:var(--nx-line)}.mod-card.source-both{background:linear-gradient(110deg,var(--ts-bg),var(--nx-bg));border-color:#75614d}.mod-card:hover{border-color:#d5dbe3}.mod-card:focus{outline:2px solid #7cb7ff}.media{aspect-ratio:16/8;background:#222}.thumb{width:100%%;height:100%%;object-fit:cover}.body{padding:15px;min-width:0;overflow-wrap:anywhere}.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.source,.pin,.nsfw,.tag{display:inline-block;padding:5px 9px;border-radius:99px;font-size:11px;font-weight:750}.source{background:#1b6c9e;border:1px solid #8ed0ff}.source.nexus{background:#9a4d27;border-color:#ffc09b}.source.both{background:linear-gradient(90deg,#236e9e,#9a4d27);border-color:#f0d0a2}.nsfw{background:#671d35;border:1px solid #ff9abb}.pin{background:#705b18;border:1px solid #f3d76b}.tags{display:flex;flex-wrap:wrap;gap:4px}.tag{background:#252a31;color:var(--muted);margin:2px;max-width:100%%;overflow-wrap:anywhere}.source-link{color:#b9dbff;margin-right:12px;font-weight:700}.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0;border-top:1px solid var(--line)}.metrics div{padding:10px 12px;border-right:1px solid var(--line)}dt{color:var(--muted);font-size:11px}dd{margin:3px 0;font-weight:700}[hidden]{display:none!important}@media(max-width:520px){header,main{padding:18px 14px}.toolbar{align-items:stretch}.control{width:100%%}.toggle-row{width:100%%;justify-content:flex-start}.grid{display:block}.mod-card{display:grid;grid-template-columns:88px minmax(0,1fr);margin-bottom:12px}.media{grid-column:1;grid-row:1;aspect-ratio:1;margin:12px}.body{grid-column:2;grid-row:1;padding:12px 12px 12px 0}.summary,.tags,.dates,.source-links{grid-column:1/-1}.metrics{grid-column:1/-1;grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body><header><h1>Valheim Mod Tracker</h1><p class="subtitle">Discover and compare recently updated Valheim mods across Thunderstore and Nexus Mods.</p><div class="toolbar"><span class="results" id="results-count">%d results</span><label class="control">Search<input id="search" type="search" placeholder="Title, author, category"></label><label class="control">Filter<select id="source-filter"><option value="">All sources</option><option value="thunderstore">Thunderstore</option><option value="nexus">Nexus Mods</option><option value="both">Both</option></select></label><div class="toggle-row"><label class="toggle-control"><input id="nsfw-toggle" type="checkbox"><span>Show NSFW mods</span></label><label class="toggle-control"><input id="v1-toggle" type="checkbox"><span title="Shows mods updated on or after Sep 8, 2026; not a semantic version filter.">v1 filter</span></label></div><label class="control">Sort<select id="sort"><option value="lifetime-rate">Lifetime downloads/day</option><option value="version-rate">Current version observed downloads/day</option><option value="updated">Last updated</option><option value="downloads">Total downloads</option></select></label></div></header><main><p>Generated %s.</p><section id="pinned-section"%s><h2>Pinned Thunderstore mods</h2><div class="grid" id="pinned-group">%s</div></section><section><h2>All other mods</h2><div class="grid" id="regular-group">%s</div></section><noscript><p>Filtering requires JavaScript; NSFW content remains hidden when JavaScript is disabled.</p></noscript></main><script>const cards=[...document.querySelectorAll('.mod-card')],search=document.querySelector('#search'),source=document.querySelector('#source-filter'),sort=document.querySelector('#sort'),nsfw=document.querySelector('#nsfw-toggle'),v1=document.querySelector('#v1-toggle'),count=document.querySelector('#results-count');function update(){document.body.classList.toggle('show-nsfw',nsfw.checked);const q=search.value.toLowerCase();let n=0;cards.forEach(c=>{const show=c.dataset.search.includes(q)&&(!source.value||c.dataset.source===source.value)&&(nsfw.checked||c.dataset.nsfw!=='true')&&(!v1||!v1.checked||c.dataset.v1==='true');c.hidden=!show;if(show)n++});count.textContent=n+' result'+(n===1?'':'s');for(const id of ['pinned-group','regular-group']){const g=document.getElementById(id),key='sort'+sort.value.split('-').map(x=>x[0].toUpperCase()+x.slice(1)).join('');[...g.children].sort((a,b)=>sort.value==='updated'?b.dataset[key].localeCompare(a.dataset[key]):Number(b.dataset[key])-Number(a.dataset[key])).forEach(c=>g.appendChild(c))}}[search,source,sort,nsfw,...(v1?[v1]:[])].forEach(x=>x.addEventListener('input',update));cards.forEach(c=>c.addEventListener('click',e=>{if(!e.target.closest('a,button,input,select'))location.href=c.dataset.url}));update();</script></body></html>''' % (initial_visible, escape(generated_label), '' if pinned else ' hidden', pinned, regular)
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
    if v1_cutoff is None:
        page = page.replace(
            '<label class="toggle-control"><input id="v1-toggle" type="checkbox"><span title="Shows mods updated on or after Sep 8, 2026; not a semantic version filter.">v1 filter</span></label>',
            "",
        )
    return page


class ReportVerifier(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = 0
        self.ids = set()
        self.missing_sort = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "article" and "mod-card" in (attrs.get("class") or "").split():
            self.cards += 1
            required = {"data-sort-lifetime-rate", "data-sort-version-rate", "data-sort-updated", "data-sort-downloads", "data-url", "data-source", "data-nsfw", "data-v1"}
            if not required.issubset(attrs):
                self.missing_sort += 1


def verify_report(
    path: Path,
    expected_cards: int | None = None,
    *,
    expect_v1_filter: bool = True,
) -> dict:
    parser = ReportVerifier()
    parser.feed(path.read_text(encoding="utf-8"))
    errors = []
    if expected_cards is not None and parser.cards != expected_cards:
        errors.append(f"expected {expected_cards} cards, found {parser.cards}")
    required_ids = {"pinned-group", "regular-group", "search", "source-filter", "sort", "nsfw-toggle"}
    if expect_v1_filter:
        required_ids.add("v1-toggle")
    if not required_ids.issubset(parser.ids):
        errors.append("missing report controls or fixed groups")
    if parser.missing_sort:
        errors.append(f"{parser.missing_sort} cards lack sort/navigation attributes")
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
    v1_cutoff: str | None = "2026-09-08T00:00:00Z",
    thumbnail_fetch=http_fetch,
) -> dict:
    mods_path = root / "data/mods.json"
    mods = _load_json(mods_path, [])
    mods = apply_manual_mappings(mods, _load_json(root / "mappings.json", {}))
    now = parse_datetime(generated_at)
    for mod in mods:
        mod["rates"] = compute_rates(mod, now)
    atomic_write_json(mods_path, mods)
    page = render_report(
        mods,
        generated_at,
        embed_thumbnails=embed_thumbnails,
        thumbnail_fetch=thumbnail_fetch,
        game_name=game_name,
        sources=sources,
        v1_cutoff=v1_cutoff,
    )
    atomic_write_bytes(root / "report.html", page.encode("utf-8"))
    hotlinked_page = page if not embed_thumbnails else render_report(
        mods,
        generated_at,
        embed_thumbnails=False,
        game_name=game_name,
        sources=sources,
        v1_cutoff=v1_cutoff,
    )
    atomic_write_bytes(root / "report-hotlinked.html", hotlinked_page.encode("utf-8"))
    result = verify_report(
        root / "report.html",
        expected_cards=len(_report_groups(mods)),
        expect_v1_filter=v1_cutoff is not None,
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
    expect_v1_filter: bool = True,
    require_reports: bool = False,
) -> dict:
    errors = []
    ts_appearances = 0
    for ordering in ("last-updated", "most-downloaded"):
        listing_dir = root / f"raw/thunderstore/listings/{ordering}"
        for stale in listing_dir.glob("page-*.html"):
            match = re.fullmatch(r"page-(\d+)\.html", stale.name)
            if match and int(match.group(1)) > expected_thunderstore_pages:
                errors.append(f"unexpected {stale.relative_to(root)} beyond configured scope")
        for page in range(1, expected_thunderstore_pages + 1):
            path = root / f"raw/thunderstore/listings/{ordering}/page-{page}.html"
            if not path.exists():
                errors.append(f"missing {path.relative_to(root)}")
                continue
            count = len(parse_listing(path.read_text(encoding="utf-8")))
            ts_appearances += count
            if count != 20:
                errors.append(f"{path.relative_to(root)} has {count} cards, expected 20")
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
    report_result = None
    report_path = root / "report.html"
    hotlinked_path = root / "report-hotlinked.html"
    if report_path.exists():
        report_result = verify_report(
            report_path,
            expected_cards=len(_report_groups(mods)),
            expect_v1_filter=expect_v1_filter,
        )
        errors.extend(report_result["errors"])
    elif require_reports:
        errors.append("missing report.html")
    hotlinked_result = None
    if hotlinked_path.exists():
        hotlinked_result = verify_report(
            hotlinked_path,
            expected_cards=len(_report_groups(mods)),
            expect_v1_filter=expect_v1_filter,
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
    fresh = []
    if "thunderstore" in selected_sources:
        fresh.extend(collect_thunderstore(
            root,
            thunderstore_pages,
            collected_at,
            community=config["thunderstore_community"],
        ))
    if "nexus" in selected_sources:
        api_key = args.nexus_api_key_file.read_text(encoding="utf-8").strip()
        cookie_header = load_cookie_header(args.nexus_cookie_file) if args.nexus_cookie_file else None
        fresh.extend(
            collect_nexus(
                root,
                api_key,
                collected_at,
                cookie_header=cookie_header,
                game_domain=config["nexus_domain"],
                pages=nexus_pages,
                require_full_pages=config["require_full_nexus_pages"],
            )
        )
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
        "thunderstore_pages_per_sort": thunderstore_pages if "thunderstore" in selected_sources else 0,
        "nexus_pages": nexus_pages if "nexus" in selected_sources else 0,
    }
    atomic_write_json(root / "snapshots/latest.json", manifest)
    report = generate_report(
        root,
        collected_at,
        embed_thumbnails=args.embed_thumbnails,
        game_name=config["display_name"],
        sources=config["sources"],
        v1_cutoff=config["v1_cutoff"],
    )
    return {**manifest, "report_cards": report["cards"]}


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
            v1_cutoff=config["v1_cutoff"],
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
            expect_v1_filter=config["v1_cutoff"] is not None,
            require_reports=True,
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
