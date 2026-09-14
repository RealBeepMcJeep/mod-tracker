"""Pure, deterministic extraction of GitHub repository evidence."""

from __future__ import annotations

import hashlib
import html
import json
import re
from urllib.parse import urlsplit


_URL_RE = re.compile(r"https://[^\s<>\"']+", re.I)
_HREF_RE = re.compile(r"<a\b[^>]*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
_BBCODE_RE = re.compile(r"\[url(?:\s*=\s*([^\]]+))?\][\s\S]*?\[/url\]", re.I)
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")
_BOUND = 240
_SITE_ROUTES = {
    "about", "account", "apps", "collections", "customer-stories", "enterprise",
    "explore", "features", "login", "marketplace", "new", "orgs",
    "organizations", "pricing", "security", "settings", "signup", "gist",
    "gists", "site", "sponsors", "topics", "u", "users",
}


def _context(text: str, start: int, end: int) -> str:
    """Return a bounded, whitespace-normalized window containing the URL."""
    if end - start >= _BOUND:
        return _SPACE_RE.sub(" ", text[start:start + _BOUND]).strip()[:_BOUND]
    half = (_BOUND - (end - start)) // 2
    left = max(0, start - half)
    right = min(len(text), end + half)
    value = _SPACE_RE.sub(" ", text[left:right]).strip()
    return value[:_BOUND]


def _repository(url: str) -> tuple[str, str] | None:
    """Validate a URL and return (canonical root, normalized path kind)."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or port:
        return None
    if parsed.query or parsed.fragment:
        # Query and fragment are evidence, but never repository path components.
        pass
    path = parsed.path
    if "%" in path or "\\" in path or not path.startswith("/"):
        return None
    parts = path.split("/")[1:]
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    owner, repo = parts[0], parts[1]
    component = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    if (
        not component.fullmatch(owner)
        or not component.fullmatch(repo)
        or owner in {".", ".."}
        or repo in {".", ".."}
        or owner.lower() in _SITE_ROUTES
    ):
        return None
    tail = parts[2:]
    if any(part in {"", ".", ".."} for part in tail):
        return None
    if any(part.lower() in {"topics", "settings", "marketplace"} for part in tail):
        return None
    lowered_tail = [part.lower() for part in tail]
    kind = "root"
    if tail:
        if lowered_tail[0] in {"issues", "pull", "pulls", "releases", "tree", "blob", "commit", "commits", "actions", "wiki", "discussions", "compare"}:
            kind = lowered_tail[0]
        else:
            kind = "other"
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
        if not repo:
            return None
    return f"https://github.com/{owner.lower()}/{repo.lower()}", kind


def _trim_url(value: str) -> str:
    value = html.unescape(value).strip()
    while value and value[-1] in ".,;:!?)]}>\"'":
        value = value[:-1]
    return value


def _masked(text: str, ranges) -> str:
    chars = list(text)
    for start, end in ranges:
        chars[start:end] = [" "] * (end - start)
    return "".join(chars)


def extract_github_evidence(fields: dict[str, str]) -> dict:
    """Extract deterministic GitHub repository candidates from named text fields."""
    found: dict[str, list[dict]] = {}
    for source_field in sorted(fields):
        text = str(fields[source_field])
        spans: list[tuple[int, int]] = []
        extracted: list[tuple[int, int, str, str]] = []
        comment_spans = [match.span() for match in _COMMENT_RE.finditer(text)]
        visible_markup = _masked(text, comment_spans)

        for match in _HREF_RE.finditer(visible_markup):
            group_index = next(
                index for index in range(1, 4) if match.group(index) is not None
            )
            raw = match.group(group_index)
            start, end = match.span(group_index)
            extracted.append((start, end, _trim_url(raw), "html_href"))
            spans.append((match.start(), match.end()))
        for match in _BBCODE_RE.finditer(visible_markup):
            raw = match.group(1)
            if raw is None:
                inner = re.search(r"https://[^\s\[]+", match.group(0), re.I)
                raw = inner.group(0) if inner else ""
            extracted.append((match.start(), match.end(), _trim_url(raw), "bbcode_url"))
            spans.append((match.start(), match.end()))

        tag_spans = [match.span() for match in _TAG_RE.finditer(visible_markup)]
        plain = _masked(visible_markup, [*spans, *tag_spans])
        for match in _URL_RE.finditer(plain):
            extracted.append((match.start(), match.end(), _trim_url(match.group(0)), "plaintext_url"))

        for start, end, url, path_type in sorted(extracted, key=lambda item: (item[0], item[1], item[3], item[2])):
            parsed = _repository(url)
            if parsed is None:
                continue
            root, path_kind = parsed
            occurrence = {
                "exact_url": url,
                "link_type": path_type,
                "path_type": path_kind,
                "source_field": source_field,
                "context": _context(text, start, end),
            }
            found.setdefault(root, []).append(occurrence)

    candidates = []
    for root in sorted(found):
        occurrences = sorted(found[root], key=lambda item: (
            item["source_field"], item["context"], item["exact_url"], item["path_type"],
        ))
        candidates.append({"repository_url": root, "occurrences": occurrences})
    payload = json.dumps(candidates, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return {
        "fingerprint": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "candidates": candidates,
    }
