import json
import os
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker
from tests.test_tracker import CARD_PAGE


DETAIL_HTML = r'''<html><script>"package_created\",\"2021-02-14T18:07:34.498403Z\",\"version_created\",\"2026-09-09T12:30:43.920443Z\"</script><div class="markdown-body"><h1>Read me</h1></div></html>'''


class CollectorTests(unittest.TestCase):
    def test_thunderstore_current_readme_keeps_void_tags_and_excludes_page_chrome(self):
        source = '''<nav>Ignore nav</nav><div class="package-listing__content"><div class="markdown-wrapper"><div class="markdown"><h1>Current</h1><img src="x"><br>Body</div></div></div><footer>Ignore footer</footer>'''
        detail = tracker.parse_thunderstore_detail(source)
        self.assertEqual(detail["readme_html"], '<h1>Current</h1><img src="x"><br>Body')

    def test_thunderstore_readme_uses_first_complete_candidate_and_fails_closed(self):
        first = '<div class="markdown-body"><p>First</p></div><div class="markdown-body"><p>Second</p></div>'
        self.assertEqual(tracker.parse_thunderstore_detail(first)["readme_html"], '<p>First</p>')
        for source in (
            '<script>package_created 2021-02-14T18:07:34Z</script><div class="markdown-body"><p>Truncated',
            '<script>package_created 2021-02-14T18:07:34Z</script><div class="markdown-body"><p>Wrong</div></p>',
            '<script>package_created 2021-02-14T18:07:34Z</script><div class="markdown-body">No close',
        ):
            detail = tracker.parse_thunderstore_detail(source)
            self.assertEqual(detail["readme_html"], "")
            self.assertEqual(detail["package_created"], "2021-02-14T18:07:34Z")

    def test_thunderstore_readme_skips_malformed_candidate_before_complete_readme(self):
        sources = (
            (
                '<div class="markdown-body"><p>Broken</div></p>'
                '<div class="markdown-body"><p>Complete</p></div>'
            ),
            (
                '<div class="package-listing__content"><div class="markdown-wrapper">'
                '<div class="markdown"><p>Broken</div></p>'
                '<div class="markdown"><p>Complete</p></div>'
                '</div></div>'
            ),
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(
                    tracker.parse_thunderstore_detail(source)["readme_html"],
                    "<p>Complete</p>",
                )

    def test_nexus_detail_refreshes_only_when_listing_freshness_changes(self):
        listing = {"data": {"mods": {"nodes": [{
            "modId": 79, "name": "Circlet", "updatedAt": "2026-09-09T19:23:08Z",
        }]}}}
        detail = {"description": "old", "updated_timestamp": 1788981788,
                  "updated_time": "2026-09-09T19:23:08Z"}
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            if url.endswith("/v2/graphql"):
                return json.dumps(listing).encode()
            return json.dumps({**detail, "description": "new"}).encode()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "raw/nexus/mods").mkdir(parents=True)
            (root / "raw/nexus/mods/79.json").write_text(json.dumps(detail))
            tracker.collect_nexus(root, "key", "2026-09-09T20:00:00Z", pages=1,
                                  require_full_pages=False, fetch=fetch, pause=lambda: None)
        self.assertEqual(sum("/v1/games/valheim/mods/79.json" in url for url in calls), 0)

    def test_nexus_invalid_or_advanced_freshness_refreshes_once(self):
        listing = {"data": {"mods": {"nodes": [{
            "modId": 79, "name": "Circlet", "updatedAt": "2026-09-10T19:23:08Z",
        }]}}}
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            if url.endswith("/v2/graphql"):
                return json.dumps(listing).encode()
            return json.dumps({"description": "fresh", "updated_time": "2026-09-10T19:23:08Z"}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "raw/nexus/mods/79.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"description": "stale", "updated_timestamp": 999999999999999999999}))
            tracker.collect_nexus(root, "key", "2026-09-10T20:00:00Z", pages=1,
                                  require_full_pages=False, fetch=fetch, pause=lambda: None)
        self.assertEqual(sum("/v1/games/valheim/mods/79.json" in url for url in calls), 1)

    def test_nexus_invalid_listing_freshness_refreshes_once(self):
        listing = {"data": {"mods": {"nodes": [{"modId": 79, "updatedAt": "bad"}]}}}
        calls = []

        def fetch(url, **kwargs):
            calls.append(url)
            if url.endswith("/v2/graphql"):
                return json.dumps(listing).encode()
            return json.dumps({"description": "fresh", "updated_timestamp": 1}).encode()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "raw/nexus/mods/79.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"description": "stale", "updated_timestamp": 1}))
            tracker.collect_nexus(root, "key", "2026-09-10T20:00:00Z", pages=1,
                                  require_full_pages=False, fetch=fetch, pause=lambda: None)
        self.assertEqual(sum("/v1/games/valheim/mods/79.json" in url for url in calls), 1)

    def test_http_fetch_retries_transient_timeout(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"ok"
        with mock.patch.object(
            tracker, "urlopen", side_effect=[TimeoutError("slow"), response]
        ) as opened, mock.patch.object(tracker.time, "sleep") as slept:
            payload = tracker.http_fetch("https://example.test/data")

        self.assertEqual(payload, b"ok")
        self.assertEqual(opened.call_count, 2)
        slept.assert_called_once_with(1)

    def test_http_fetch_does_not_retry_permanent_http_error(self):
        error = HTTPError("https://example.test/missing", 404, "missing", Message(), None)
        with mock.patch.object(tracker, "urlopen", side_effect=error) as opened, \
             mock.patch.object(tracker.time, "sleep") as slept:
            with self.assertRaises(HTTPError):
                tracker.http_fetch("https://example.test/missing")

        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()

    def test_parses_and_normalizes_thunderstore_exact_metrics(self):
        detail = tracker.parse_thunderstore_detail(DETAIL_HTML)
        card = tracker.parse_listing(CARD_PAGE)[0]
        metrics = {"downloads": 774617, "rating_score": 121, "latest_version": "18.4.1"}

        mod = tracker.normalize_thunderstore(
            card, detail, metrics,
            ranks={"last-updated": 1, "most-downloaded": 4},
            collected_at="2026-09-09T20:00:00Z",
        )

        self.assertEqual(detail["package_created"], "2021-02-14T18:07:34.498403Z")
        self.assertEqual(detail["version_created"], "2026-09-09T12:30:43.920443Z")
        self.assertIn("Read me", detail["readme_html"])
        self.assertEqual(mod["key"], "thunderstore:ExampleAuthor/ExampleMod")
        self.assertEqual(mod["source_id"], "ExampleAuthor/ExampleMod")
        self.assertEqual(mod["total_downloads"], 774617)
        self.assertEqual(mod["likes"], 121)
        self.assertEqual(mod["version"], "18.4.1")
        self.assertEqual(mod["updated_at"], "2026-09-09T12:30:43.920443Z")
        self.assertTrue(mod["pinned"])

    def test_thunderstore_collection_saves_raw_and_fetches_detail_only_for_new_version(self):
        calls = []
        metrics = {"downloads": 100, "rating_score": 2, "latest_version": "1.0"}

        def fetch(url, **kwargs):
            calls.append(url)
            if "package-metrics" in url:
                return json.dumps(metrics).encode()
            if "/p/ExampleAuthor/ExampleMod/" in url:
                return DETAIL_HTML.encode()
            return CARD_PAGE.encode()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "raw/thunderstore/listings/last-updated/page-2.html"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale")
            first = tracker.collect_thunderstore(root, pages=1, collected_at="2026-09-09T20:00:00Z", fetch=fetch, pause=lambda: None)
            second = tracker.collect_thunderstore(root, pages=1, collected_at="2026-09-09T21:00:00Z", fetch=fetch, pause=lambda: None)

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertTrue((root / "raw/thunderstore/listings/last-updated/page-1.html").exists())
            self.assertFalse(stale.exists())
            self.assertTrue((root / "raw/thunderstore/metrics/ExampleAuthor/ExampleMod.json").exists())
            self.assertTrue((root / "raw/thunderstore/packages/ExampleAuthor/ExampleMod.html").exists())
            detail_calls = [url for url in calls if "/p/ExampleAuthor/ExampleMod/" in url]
            self.assertEqual(len(detail_calls), 1)

    def test_thunderstore_collection_records_terminal_404_and_removes_stale_pages(self):
        metrics = {"downloads": 100, "rating_score": 2, "latest_version": "1.0"}

        def fetch(url, **kwargs):
            if "ordering=" in url:
                page = int(url.rsplit("page=", 1)[1])
                if page == 3:
                    raise HTTPError(url, 404, "missing", Message(), None)
                return CARD_PAGE.encode()
            if "package-metrics" in url:
                return json.dumps(metrics).encode()
            if "/p/ExampleAuthor/ExampleMod/" in url:
                return DETAIL_HTML.encode()
            self.fail(f"unexpected request: {url}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for ordering in ("last-updated", "most-downloaded"):
                stale = root / f"raw/thunderstore/listings/{ordering}/page-4.html"
                stale.parent.mkdir(parents=True, exist_ok=True)
                stale.write_text("stale")

            tracker.collect_thunderstore(
                root,
                pages=4,
                collected_at="2026-09-10T00:00:00Z",
                fetch=fetch,
                pause=lambda: None,
            )

            scope = json.loads(
                (root / "raw/thunderstore/listings/manifest.json").read_text()
            )
            self.assertEqual(scope["requested_pages_per_sort"], 4)
            self.assertEqual(
                scope["rankings"],
                {
                    "last-updated": {"fetched_pages": 2, "terminal_http_status": 404},
                    "most-downloaded": {"fetched_pages": 2, "terminal_http_status": 404},
                },
            )
            for ordering in ("last-updated", "most-downloaded"):
                self.assertTrue(
                    (root / f"raw/thunderstore/listings/{ordering}/page-2.html").exists()
                )
                self.assertFalse(
                    (root / f"raw/thunderstore/listings/{ordering}/page-4.html").exists()
                )

    def test_thunderstore_collection_rejects_page_one_404(self):
        def fetch(url, **kwargs):
            raise HTTPError(url, 404, "missing", Message(), None)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HTTPError):
                tracker.collect_thunderstore(
                    Path(tmp),
                    pages=4,
                    collected_at="2026-09-10T00:00:00Z",
                    fetch=fetch,
                    pause=lambda: None,
                )

    def test_thunderstore_collection_rejects_unrelated_permanent_http_error(self):
        def fetch(url, **kwargs):
            if "page=1" in url:
                return CARD_PAGE.encode()
            raise HTTPError(url, 403, "forbidden", Message(), None)

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HTTPError):
                tracker.collect_thunderstore(
                    Path(tmp),
                    pages=4,
                    collected_at="2026-09-10T00:00:00Z",
                    fetch=fetch,
                    pause=lambda: None,
                )

    def test_thunderstore_collection_uses_configured_community(self):
        calls = []
        metrics = {"downloads": 100, "rating_score": 2, "latest_version": "1.0"}

        def fetch(url, **kwargs):
            calls.append(url)
            if "package-metrics" in url:
                return json.dumps(metrics).encode()
            if "/p/ExampleAuthor/ExampleMod/" in url:
                return DETAIL_HTML.encode()
            return CARD_PAGE.replace("/c/valheim/", "/c/peak/").encode()

        with tempfile.TemporaryDirectory() as tmp:
            tracker.collect_thunderstore(
                Path(tmp),
                pages=1,
                collected_at="2026-09-09T20:00:00Z",
                community="peak",
                fetch=fetch,
                pause=lambda: None,
            )

        listing_calls = [url for url in calls if "ordering=" in url]
        self.assertTrue(listing_calls)
        self.assertTrue(all("/c/peak/" in url for url in listing_calls))

    def test_nexus_collection_uses_two_graphql_pages_and_caches_v1_details(self):
        calls = []
        listing = {"data": {"mods": {"nodes": [{
            "modId": 79, "name": "Circlet", "summary": "Light", "author": "Randy",
            "downloads": 10737, "endorsements": 699, "adultContent": False,
            "createdAt": "2021-02-22T06:04:51Z", "updatedAt": "2026-09-09T19:23:08Z",
            "version": "1.0.7", "fileSize": 349, "category": "Gameplay",
            "pictureUrl": "https://staticdelivery.nexusmods.com/79.png",
        }]}}}
        detail = {"unique_downloads": 7059, "views": 61114, "description": "Full",
                  "updated_time": "2026-09-09T19:23:08Z"}

        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            payload = listing if url.endswith("/v2/graphql") else detail
            return json.dumps(payload).encode()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "raw/nexus/listing-page-3.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}")
            first = tracker.collect_nexus(root, "secret-runtime-key", "2026-09-09T20:00:00Z", fetch=fetch, pause=lambda: None)
            second = tracker.collect_nexus(root, "secret-runtime-key", "2026-09-09T21:00:00Z", fetch=fetch, pause=lambda: None)

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertEqual(sum(url.endswith("/v2/graphql") for url, _ in calls), 4)
            self.assertEqual(sum("/v1/games/valheim/mods/79.json" in url for url, _ in calls), 1)
            self.assertTrue((root / "raw/nexus/listing-page-1.json").exists())
            self.assertTrue((root / "raw/nexus/listing-page-2.json").exists())
            self.assertFalse((root / "raw/nexus/listing-page-3.json").exists())
            self.assertTrue((root / "raw/nexus/mods/79.json").exists())
            self.assertNotIn("secret-runtime-key", (root / "raw/nexus/listing-page-1.json").read_text())
            graphql_calls = [kwargs for url, kwargs in calls if url.endswith("/v2/graphql")]
            self.assertIn(b"count: 80", graphql_calls[0]["data"])
            self.assertIn(b"offset: 0", graphql_calls[0]["data"])
            self.assertIn(b"offset: 80", graphql_calls[1]["data"])
            self.assertEqual(graphql_calls[0]["headers"]["apikey"], "secret-runtime-key")

    def test_nexus_collection_supports_a_small_nexus_only_game(self):
        calls = []
        listing = {"data": {"mods": {"nodes": [{
            "modId": 12,
            "name": "Retro Mod",
            "createdAt": "2026-09-01T00:00:00Z",
            "updatedAt": "2026-09-09T00:00:00Z",
        }]}}}

        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/v2/graphql"):
                return json.dumps(listing).encode()
            return json.dumps({"description": "Full"}).encode()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "raw/nexus/listing-page-2.json"
            stale.parent.mkdir(parents=True)
            stale.write_text("{}")
            mods = tracker.collect_nexus(
                root,
                "secret-runtime-key",
                "2026-09-09T20:00:00Z",
                game_domain="retrorewindvideostoresimulator",
                pages=2,
                require_full_pages=False,
                fetch=fetch,
                pause=lambda: None,
            )

            self.assertEqual(len(mods), 1)
            self.assertEqual(sum(url.endswith("/v2/graphql") for url, _ in calls), 1)
            graphql_data = calls[0][1]["data"]
            self.assertIn(b'retrorewindvideostoresimulator', graphql_data)
            self.assertTrue((root / "raw/nexus/listing-page-1.json").exists())
            self.assertFalse((root / "raw/nexus/listing-page-2.json").exists())
            self.assertTrue(any(
                "/v1/games/retrorewindvideostoresimulator/mods/12.json" in url
                for url, _ in calls
            ))
            self.assertEqual(
                mods[0]["canonical_url"],
                "https://www.nexusmods.com/retrorewindvideostoresimulator/mods/12",
            )

    def test_nexus_rejects_non_numeric_mod_id_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "escape.json"
            outside.unlink(missing_ok=True)

            def fetch(url, *, headers=None, data=None):
                if url.endswith("/v2/graphql"):
                    return json.dumps({
                        "data": {"mods": {"nodes": [{"modId": "../../escape"}]}}
                    }).encode()
                self.fail(f"unexpected detail request: {url}")

            with self.assertRaisesRegex(ValueError, "Nexus mod ID"):
                tracker.collect_nexus(
                    root,
                    "secret-runtime-key",
                    "2026-09-10T00:00:00Z",
                    pages=1,
                    require_full_pages=False,
                    fetch=fetch,
                    pause=lambda: None,
                )
            self.assertFalse(outside.exists())

    def test_thunderstore_rejects_unsafe_package_url_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = CARD_PAGE.replace(
                "/c/valheim/p/ExampleAuthor/ExampleMod/",
                "/c/peak/p/../../escape/",
            ).encode()

            with self.assertRaisesRegex(ValueError, "Thunderstore package URL"):
                tracker.collect_thunderstore(
                    root,
                    1,
                    "2026-09-10T00:00:00Z",
                    community="peak",
                    fetch=lambda url: html,
                    pause=lambda: None,
                )

    def test_cookie_header_detail_capture_records_success_without_persisting_cookie(self):
        seen = {}

        def fetch(url, **kwargs):
            seen.update(kwargs["headers"])
            return (b"<html><title>Actual mod</title><main>description</main>" + b"x" * 200 + b"</html>")

        with tempfile.TemporaryDirectory() as tmp:
            result = tracker.capture_nexus_page(
                Path(tmp), "79", cookie_header="session=private", fetch=fetch
            )
            saved = (Path(tmp) / "raw/nexus/pages/79.html").read_text()

        self.assertEqual(result["status"], "captured")
        self.assertEqual(seen["Cookie"], "session=private")
        self.assertNotIn("session=private", saved)


if __name__ == "__main__":
    unittest.main()
