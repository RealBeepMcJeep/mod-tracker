#!/usr/bin/env python3
"""Track ranked Thunderstore package cards as flat files."""

from __future__ import annotations

import json
import os
import re
import time
import base64
import argparse
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
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


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def http_fetch(url: str, *, headers: dict | None = None, data: bytes | None = None) -> bytes:
    request_headers = {"User-Agent": "ValheimModTracker/1.0 (manual collector)"}
    request_headers.update(headers or {})
    request = Request(url, headers=request_headers, data=data)
    with urlopen(request, timeout=60) as response:
        return response.read()


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


def collect_thunderstore(
    root: Path,
    pages: int,
    collected_at: str,
    *,
    fetch=http_fetch,
    pause=lambda: time.sleep(1),
) -> list[dict]:
    """Collect both deterministic Thunderstore rankings and exact details."""
    found: dict[str, dict] = {}
    for ordering in ("last-updated", "most-downloaded"):
        rank = 0
        for page in range(1, pages + 1):
            url = f"https://thunderstore.io/c/valheim/?ordering={ordering}&page={page}"
            body = fetch(url)
            atomic_write_bytes(root / f"raw/thunderstore/listings/{ordering}/page-{page}.html", body)
            pause()
            cards = parse_listing(body.decode("utf-8"))
            for position, card in enumerate(cards, 1):
                rank += 1
                source_id = "/".join(
                    [part for part in urlparse(card["package_url"]).path.split("/") if part][-2:]
                )
                item = found.setdefault(source_id, {"card": card, "ranks": {}})
                item["ranks"][ordering] = rank
                item.setdefault("appearances", []).append({
                    "ordering": ordering, "page": page, "position": position, "rank": rank,
                })

    normalized = []
    for source_id in sorted(found):
        namespace, name = source_id.split("/", 1)
        metrics_path = root / f"raw/thunderstore/metrics/{namespace}/{name}.json"
        detail_path = root / f"raw/thunderstore/packages/{namespace}/{name}.html"
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


NEXUS_QUERY = """query ValheimMods {
  mods(filter: {gameDomainName: [{value: \"valheim\", op: EQUALS}]},
       sort: [{updatedAt: {direction: DESC}}], count: 80, offset: OFFSET) {
    nodes { modId name summary author downloads endorsements adultContent createdAt
            updatedAt version fileSize category pictureUrl thumbnailUrl }
  }
}"""


def capture_nexus_page(
    root: Path, mod_id: str, *, cookie_header: str, fetch=http_fetch
) -> dict:
    """Capture an actual Nexus detail page using caller-supplied auth cookies."""
    url = f"https://www.nexusmods.com/valheim/mods/{mod_id}"
    try:
        body = fetch(url, headers={"Cookie": cookie_header})
        lower = body[:20000].lower()
        if b"just a moment" in lower or b"cf-chl" in lower or len(body) < 100:
            raise ValueError("received Cloudflare interstitial or undersized page")
        atomic_write_bytes(root / f"raw/nexus/pages/{mod_id}.html", body)
        return {"status": "captured", "kind": "authenticated-detail-html"}
    except Exception as exc:  # persisted status is evidence; the run remains resumable
        return {"status": "failed", "reason": str(exc)}


def collect_nexus(
    root: Path,
    api_key: str,
    collected_at: str,
    *,
    cookie_header: str | None = None,
    fetch=http_fetch,
    pause=lambda: time.sleep(1),
) -> list[dict]:
    """Collect exactly one 80-item Nexus GraphQL listing and v1 details."""
    headers = {"Content-Type": "application/json", "apikey": api_key}
    query = NEXUS_QUERY.replace("OFFSET", "0")
    listing_body = fetch(
        "https://api.nexusmods.com/v2/graphql",
        headers=headers,
        data=json.dumps({"query": query}, separators=(",", ":")).encode(),
    )
    pause()
    listing = json.loads(listing_body)
    if listing.get("errors"):
        raise RuntimeError("Nexus GraphQL errors: " + json.dumps(listing["errors"]))
    atomic_write_json(root / "raw/nexus/listing-page-1.json", listing)
    for stale in (root / "raw/nexus").glob("listing-page-*.json"):
        if stale.name != "listing-page-1.json":
            stale.unlink()
    nodes = listing.get("data", {}).get("mods", {}).get("nodes", [])
    normalized = []
    seen = set()
    for rank, node in enumerate(nodes, 1):
        mod_id = str(node["modId"])
        if mod_id in seen:
            continue
        seen.add(mod_id)
        detail_path = root / f"raw/nexus/mods/{mod_id}.json"
        is_new = not detail_path.exists()
        if is_new:
            body = fetch(
                f"https://api.nexusmods.com/v1/games/valheim/mods/{mod_id}.json",
                headers={"apikey": api_key},
            )
            pause()
            atomic_write_bytes(detail_path, body)
        detail = _load_json(detail_path, {})
        if is_new and cookie_header:
            detail["_raw_page_capture"] = capture_nexus_page(
                root, mod_id, cookie_header=cookie_header, fetch=fetch
            )
            pause()
        elif (root / f"raw/nexus/pages/{mod_id}.html").exists():
            detail["_raw_page_capture"] = {
                "status": "captured", "kind": "authenticated-detail-html"
            }
        normalized.append(normalize_nexus(node, detail, rank, collected_at))
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


def render_report(
    mods: list[dict],
    generated_at: str,
    *,
    embed_thumbnails: bool = False,
    thumbnail_fetch=http_fetch,
) -> str:
    """Render a standalone searchable, sortable, cross-source HTML report."""
    now = parse_datetime(generated_at)

    def card(mod: dict) -> str:
        rates = compute_rates(mod, now)
        src = "Thunderstore" if mod["source"] == "thunderstore" else "Nexus Mods"
        image = _thumbnail_src(mod, embed_thumbnails, thumbnail_fetch)
        categories = ", ".join(mod.get("categories", []))
        updated = mod.get("updated_at") or ""
        search = " ".join((mod.get("title", ""), mod.get("author", ""), categories)).lower()
        version_rate = rates["current_version_observed_downloads_per_day"]
        rate_label = "—" if version_rate is None else f"{version_rate:,.1f}"
        canonical = escape(mod["canonical_url"], quote=True)
        engagement = mod.get("endorsements") if mod.get("endorsements") is not None else mod.get("likes")
        tags = "".join(f'<span class="tag">{escape(value)}</span>' for value in mod.get("categories", []))
        return f'''<article class="mod-card{' pinned' if mod.get('pinned') else ''}"
 data-source="{escape(mod['source'])}" data-search="{escape(search, quote=True)}"
 data-url="{canonical}" tabindex="0" role="link"
 data-sort-lifetime-rate="{_sort_number(rates['lifetime_downloads_per_day'])}"
 data-sort-version-rate="{_sort_number(version_rate)}"
 data-sort-updated="{escape(updated, quote=True)}"
 data-sort-downloads="{_sort_number(mod.get('total_downloads'))}">
 <div class="media"><img class="thumb" src="{escape(image, quote=True)}" alt="" loading="lazy"><div class="badges"><span class="source {escape(mod['source'])}">{src}</span>{'<span class="pin">Pinned</span>' if mod.get('pinned') else ''}</div></div>
 <div class="body">
 <h2><a href="{canonical}">{escape(mod.get('title', ''))}</a></h2>
 <p class="by">by {escape(mod.get('author', ''))} · v{escape(str(mod.get('version') or '—'))}</p>
 <p class="summary">{escape(mod.get('summary') or '')}</p><div class="tags">{tags}</div>
 <p class="dates"><span>Updated <time>{escape(updated[:10] if updated else 'unknown')}</time></span><span>Uploaded <time>{escape((mod.get('created_at') or '')[:10] or 'unknown')}</time></span></p></div>
 <dl class="metrics"><div><dt>Total downloads</dt><dd>{int(mod.get('total_downloads') or 0):,}</dd></div>
 <div><dt>Lifetime / day</dt><dd>{rates['lifetime_downloads_per_day']:,.1f}</dd></div>
 <div title="Observed delta/day between first and latest stored observations for this version"><dt>Current version / day</dt><dd>{rate_label}</dd></div>
 <div><dt>Last updated</dt><dd>{escape(updated[:10] if updated else 'unknown')}</dd></div>
 <div><dt>Endorsements / likes</dt><dd>{int(engagement or 0):,}</dd></div></dl></article>'''

    pinned = "".join(card(mod) for mod in mods if mod.get("pinned"))
    regular = "".join(card(mod) for mod in mods if not mod.get("pinned"))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Valheim Mod Tracker</title>
<style>
:root{{--bg:#090b0e;--panel:#171a1f;--footer:#20242a;--line:#30353d;--text:#f2f4f7;--muted:#9ca3ad;--ts:#d95f2a;--nx:#d79a2d}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,-apple-system,"Segoe UI",sans-serif}}header,main{{max-width:1320px;margin:auto;padding:28px}}header{{background:var(--bg);border-bottom:1px solid var(--line)}}h1{{font-size:clamp(30px,5vw,52px);margin:0}}.subtitle{{font-size:17px;color:var(--muted);margin:8px 0 24px}}.toolbar{{border-top:1px solid var(--line);padding-top:18px;display:flex;align-items:end;gap:12px;flex-wrap:wrap}}.results{{font-weight:700;margin-right:auto;min-height:44px;display:flex;align-items:center}}.control{{display:grid;gap:4px;color:var(--muted);font-size:12px}}input,select{{min-height:44px;background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:7px;padding:10px 12px;font:inherit}}input{{min-width:min(330px,80vw)}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:18px;margin-bottom:34px}}.mod-card{{position:relative;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:8px;cursor:pointer;min-width:0}}.mod-card:hover{{border-color:#59616d;transform:translateY(-1px)}}.mod-card:focus{{outline:2px solid #7cb7ff;outline-offset:2px}}.media{{position:relative;aspect-ratio:16/8;background:#222;overflow:hidden}}.thumb{{width:100%;height:100%;object-fit:cover;display:block}}.badges{{position:absolute;left:10px;top:10px;display:flex;flex-wrap:wrap;gap:6px}}.body{{min-width:0;padding:15px}}h2{{font-size:19px;line-height:1.25;margin:0 0 5px}}h2 a{{color:var(--text)}}p{{margin:6px 0;color:var(--muted)}}.summary{{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;line-height:1.45;min-height:4.35em}}.source,.pin,.tag{{display:inline-block;padding:4px 8px;border-radius:99px;font-size:11px;font-weight:750}}.source.thunderstore{{background:var(--ts)}}.source.nexus{{background:var(--nx);color:#17100a}}.pin{{background:#7c4dcc}}.tags{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px;overflow:hidden}}.tag{{background:#292e36;color:#cbd1d9;max-width:100%;overflow-wrap:anywhere}}.dates{{display:flex;justify-content:space-between;gap:8px;font-size:12px}}.metrics{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:0;background:var(--footer);border-top:1px solid var(--line)}}.metrics div{{padding:10px 8px;min-width:0;border-right:1px solid var(--line)}}.metrics div:last-child{{border:0}}dt{{font-size:10px;line-height:1.2;color:var(--muted)}}dd{{margin:4px 0 0;font-size:12px;font-weight:750;overflow-wrap:anywhere}}section>h2{{font-size:20px;margin:12px 0 14px}}[hidden]{{display:none!important}}
@media(max-width:520px){{header,main{{padding:18px 14px}}.toolbar{{align-items:stretch}}.control,input{{width:100%}}.grid{{display:block}}.mod-card{{display:grid;grid-template-columns:88px 1fr;margin-bottom:12px;overflow:hidden}}.media{{grid-column:1;grid-row:1;aspect-ratio:1;margin:12px;border-radius:6px}}.badges{{position:absolute;left:102px;top:12px;width:calc(100vw - 146px)}}.source,.pin{{font-size:10px}}.body{{grid-column:2;grid-row:1;padding:48px 12px 12px 0}}.body h2{{font-size:17px}}.summary,.tags,.dates{{grid-column:1/-1}}.summary{{margin-left:calc(-88px - 12px);padding:0 12px;min-height:0;-webkit-line-clamp:3}}.tags,.dates{{margin-left:calc(-88px - 12px);padding:0 12px}}.dates{{flex-wrap:wrap}}.metrics{{grid-column:1/-1;grid-template-columns:repeat(2,1fr)}}.metrics div{{border-bottom:1px solid var(--line)}}.metrics div:last-child{{grid-column:1/-1}}}}
</style></head><body><header><h1>Valheim Mod Tracker</h1>
<p class="subtitle">Discover and compare recently updated Valheim mods across Thunderstore and Nexus Mods.</p><div class="toolbar"><span class="results" id="results-count">{len(mods)} results</span>
<label class="control">Search<input id="search" type="search" placeholder="Title, author, category"></label>
<label class="control">Filter<select id="source-filter"><option value="">All sources</option><option value="thunderstore">Thunderstore</option><option value="nexus">Nexus Mods</option></select></label>
<label class="control">Sort<select id="sort"><option value="lifetime-rate">Lifetime downloads/day</option><option value="version-rate">Current version observed downloads/day</option><option value="updated">Last updated</option><option value="downloads">Total downloads</option></select></label></div></header>
<main><p>Generated {escape(generated_at)}. “Current version / day” is the observed download delta/day between the first and latest stored observations with the current version; it is unavailable on the first observation.</p>
<section id="pinned-section"{' hidden' if not pinned else ''}><h2>Pinned Thunderstore mods</h2><div class="grid" id="pinned-group">{pinned}</div></section>
<section><h2>All other mods</h2><div class="grid" id="regular-group">{regular}</div></section></main>
<script>
const cards=[...document.querySelectorAll('.mod-card')], search=document.querySelector('#search'), source=document.querySelector('#source-filter'), sort=document.querySelector('#sort'), count=document.querySelector('#results-count');
function update(){{let q=search.value.toLowerCase(), visible=0; cards.forEach(c=>{{c.hidden=!(c.dataset.search.includes(q)&&(!source.value||c.dataset.source===source.value));if(!c.hidden)visible++;}});count.textContent=visible+' result'+(visible===1?'':'s'); for(const id of ['pinned-group','regular-group']){{let g=document.getElementById(id), key='sort'+sort.value.split('-').map(x=>x[0].toUpperCase()+x.slice(1)).join(''); [...g.children].sort((a,b)=>{{let av=a.dataset[key],bv=b.dataset[key]; return sort.value==='updated'?bv.localeCompare(av):(Number(bv)-Number(av));}}).forEach(c=>g.appendChild(c));}}}}
[search,source,sort].forEach(x=>x.addEventListener('input',update)); cards.forEach(c=>{{c.addEventListener('click',e=>{{if(!e.target.closest('a,button,input,select'))location.href=c.dataset.url;}});c.addEventListener('keydown',e=>{{if((e.key==='Enter'||e.key===' ')&&!e.target.closest('a,button,input,select')){{e.preventDefault();location.href=c.dataset.url;}}}})}});update();
</script></body></html>'''


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
            required = {"data-sort-lifetime-rate", "data-sort-version-rate", "data-sort-updated", "data-sort-downloads", "data-url", "data-source"}
            if not required.issubset(attrs):
                self.missing_sort += 1


def verify_report(path: Path, expected_cards: int | None = None) -> dict:
    parser = ReportVerifier()
    parser.feed(path.read_text(encoding="utf-8"))
    errors = []
    if expected_cards is not None and parser.cards != expected_cards:
        errors.append(f"expected {expected_cards} cards, found {parser.cards}")
    if not {"pinned-group", "regular-group", "search", "source-filter", "sort"}.issubset(parser.ids):
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
    root: Path, generated_at: str, *, embed_thumbnails: bool = False
) -> dict:
    mods_path = root / "data/mods.json"
    mods = _load_json(mods_path, [])
    now = parse_datetime(generated_at)
    for mod in mods:
        mod["rates"] = compute_rates(mod, now)
    atomic_write_json(mods_path, mods)
    page = render_report(mods, generated_at, embed_thumbnails=embed_thumbnails)
    atomic_write_bytes(root / "report.html", page.encode("utf-8"))
    result = verify_report(root / "report.html", expected_cards=len(mods))
    if not result["ok"]:
        raise RuntimeError("generated report failed verification: " + "; ".join(result["errors"]))
    return result


def verify_output(
    root: Path, *, expected_thunderstore_pages: int = 10, expected_nexus_pages: int = 1
) -> dict:
    errors = []
    ts_appearances = 0
    for ordering in ("last-updated", "most-downloaded"):
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
    for page in range(1, expected_nexus_pages + 1):
        path = root / f"raw/nexus/listing-page-{page}.json"
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
        if count != 80:
            errors.append(f"{path.relative_to(root)} has {count} nodes, expected 80")
    if len(nexus_ids) != len(set(nexus_ids)):
        errors.append("Nexus listing does not contain 80 distinct mod IDs")
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
    if (root / "report.html").exists():
        report_result = verify_report(root / "report.html", expected_cards=len(mods))
        errors.extend(report_result["errors"])
    return {
        "ok": not errors,
        "errors": errors,
        "mods": len(mods),
        "thunderstore_appearances": ts_appearances,
        "nexus_appearances": nexus_appearances,
        "report": report_result,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual Valheim mod tracker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="collect sources, persist data, and render report")
    collect.add_argument("--output-root", type=Path, default=Path("."))
    collect.add_argument("--sources", choices=("all", "thunderstore", "nexus"), default="all")
    collect.add_argument("--thunderstore-pages", type=int, default=10)
    collect.add_argument("--nexus-pages", type=int, default=1, choices=(1,))
    collect.add_argument("--nexus-api-key-file", type=Path, default=Path.home() / ".config/nexus-mods/api-key")
    collect.add_argument("--nexus-cookie-file", type=Path)
    collect.add_argument("--mappings", type=Path)
    collect.add_argument("--embed-thumbnails", action="store_true")
    report = subparsers.add_parser("report", help="regenerate report from persisted data")
    report.add_argument("--output-root", type=Path, default=Path("."))
    report.add_argument("--embed-thumbnails", action="store_true")
    verify = subparsers.add_parser("verify", help="verify raw inputs, normalized data, and report")
    verify.add_argument("--output-root", type=Path, default=Path("."))
    verify.add_argument("--thunderstore-pages", type=int, default=10)
    verify.add_argument("--nexus-pages", type=int, default=1, choices=(1,))
    return parser


def run_collection(args) -> dict:
    root = args.output_root.resolve()
    collected_at = utc_now()
    fresh = []
    if args.sources in ("all", "thunderstore"):
        fresh.extend(collect_thunderstore(root, args.thunderstore_pages, collected_at))
    if args.sources in ("all", "nexus"):
        api_key = args.nexus_api_key_file.read_text(encoding="utf-8").strip()
        cookie_header = load_cookie_header(args.nexus_cookie_file) if args.nexus_cookie_file else None
        fresh.extend(
            collect_nexus(
                root, api_key, collected_at, cookie_header=cookie_header,
            )
        )
    mods_path = root / "data/mods.json"
    mods = merge_mods(_load_json(mods_path, []), fresh, collected_at)
    if args.mappings:
        mods = apply_manual_mappings(mods, _load_json(args.mappings, {}))
    atomic_write_json(mods_path, mods)
    manifest = {
        "collected_at": collected_at,
        "sources": args.sources,
        "fresh_records": len(fresh),
        "stored_records": len(mods),
        "thunderstore_pages_per_sort": args.thunderstore_pages,
        "nexus_pages": args.nexus_pages,
    }
    atomic_write_json(root / "snapshots/latest.json", manifest)
    report = generate_report(root, collected_at, embed_thumbnails=args.embed_thumbnails)
    return {**manifest, "report_cards": report["cards"]}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        result = run_collection(args)
    elif args.command == "report":
        result = generate_report(args.output_root.resolve(), utc_now(), embed_thumbnails=args.embed_thumbnails)
    else:
        result = verify_output(
            args.output_root.resolve(),
            expected_thunderstore_pages=args.thunderstore_pages,
            expected_nexus_pages=args.nexus_pages,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
