import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from github_evidence import extract_github_evidence


class GithubEvidenceTests(unittest.TestCase):
    def test_extracts_html_bbcode_and_plaintext_with_normalized_roots(self):
        fields = {
            "description": (
                '<a href="https://github.com/Acme/Widget/issues/7?x=1#top">issue</a> '
                "[url=https://github.com/acme/widget/releases/tag/v1]release[/url] "
                "See https://github.com/acme/widget.git."
            ),
            "source": "https://github.com/Other/Tool/tree/main/src",
        }
        result = extract_github_evidence(fields)
        self.assertEqual([c["repository_url"] for c in result["candidates"]], [
            "https://github.com/acme/widget", "https://github.com/other/tool"
        ])
        widget = result["candidates"][0]
        self.assertEqual([o["link_type"] for o in widget["occurrences"]], ["html_href", "bbcode_url", "plaintext_url"])
        self.assertEqual(widget["occurrences"][0]["exact_url"], "https://github.com/Acme/Widget/issues/7?x=1#top")
        self.assertEqual(widget["occurrences"][0]["source_field"], "description")

    def test_accepts_trailing_slash_case_insensitive_scheme_and_other_repo_paths(self):
        result = extract_github_evidence({
            "body": (
                "HTTPS://github.com/Owner/Repo/ "
                "https://github.com/owner/repo/packages/example"
            )
        })
        self.assertEqual(
            [candidate["repository_url"] for candidate in result["candidates"]],
            ["https://github.com/owner/repo"],
        )
        self.assertEqual(
            {item["path_type"] for item in result["candidates"][0]["occurrences"]},
            {"root", "other"},
        )

    def test_rejects_profiles_routes_invalid_urls_and_other_hosts(self):
        text = " ".join([
            "https://github.com/owner", "https://github.com/owner/", "https://github.com/owner/repo/",
            "https://github.com/owner/repo/topics", "https://github.com/owner/repo/settings",
            "https://github.com/owner/repo/marketplace", "https://github.com/owner/repo/issues/1",
            "https://github.com/owner/repo", "https://gist.github.com/owner/1",
            "https://notgithub.com/owner/repo", "https://github.com.evil.test/owner/repo",
            "https://user:pass@github.com/owner/repo", "https://github.com:443/owner/repo",
            "http://github.com/owner/repo", "https://github.com/owner/re%70o",
            "https://github.com/owner/repo/../other", "https://github.com//repo",
            "https://github.com/topics/python", "https://github.com/orgs/acme",
            "https://github.com/settings/profile", "https://github.com/marketplace/actions",
            "https://github.com/gists/123", "https://github.com/gist/123",
            "https://github.com/u/name", "https://github.com/account/name",
        ])
        result = extract_github_evidence({"body": text})
        self.assertEqual([c["repository_url"] for c in result["candidates"]], ["https://github.com/owner/repo"])
        self.assertEqual(len(result["candidates"][0]["occurrences"]), 3)
        self.assertEqual(result["candidates"][0]["occurrences"][0]["link_type"], "plaintext_url")

    def test_html_comments_and_non_anchor_attributes_are_not_plaintext_evidence(self):
        result = extract_github_evidence({"description": (
            '<!-- <a href="https://github.com/fake/comment">hidden</a> -->'
            '<img src="https://github.com/fake/image">'
            '<p>Visible https://github.com/real/mod</p>'
        )})
        self.assertEqual(
            [candidate["repository_url"] for candidate in result["candidates"]],
            ["https://github.com/real/mod"],
        )
        self.assertEqual(
            result["candidates"][0]["occurrences"][0]["link_type"],
            "plaintext_url",
        )

    def test_context_is_bounded_normalized_and_occurrences_are_preserved(self):
        prefix = "x" * 300
        fields = {"description": prefix + " See https://github.com/A/B/issues/2, and again https://github.com/a/b. " + "y" * 300}
        occurrence = extract_github_evidence(fields)["candidates"][0]["occurrences"][0]
        self.assertLessEqual(len(occurrence["context"]), 240)
        self.assertNotIn("  ", occurrence["context"])
        self.assertEqual(len(extract_github_evidence(fields)["candidates"][0]["occurrences"]), 2)

    def test_oversized_url_context_retains_the_repository_url_prefix(self):
        url = "https://github.com/owner/repo/issues/1?" + "x" * 300
        occurrence = extract_github_evidence({"description": url})["candidates"][0]["occurrences"][0]
        self.assertLessEqual(len(occurrence["context"]), 240)
        self.assertTrue(occurrence["context"].startswith("https://github.com/owner/repo"))

    def test_order_and_fingerprint_are_independent_of_field_order(self):
        a = {"z": "https://github.com/Zed/Repo", "a": "https://github.com/Ace/Repo"}
        b = {"a": a["a"], "z": a["z"]}
        self.assertEqual(extract_github_evidence(a), extract_github_evidence(b))
        self.assertRegex(extract_github_evidence(a)["fingerprint"], r"^sha256:[0-9a-f]{64}$")

    def test_fingerprint_tracks_candidates_and_relevant_context_not_unrelated_prose(self):
        base = {"body": "unrelated " * 100 + " https://github.com/a/b useful context"}
        changed_far = {"body": "DIFFERENT " * 100 + "unrelated " * 100 + " https://github.com/a/b useful context"}
        changed_near = {"body": "unrelated " * 100 + " https://github.com/a/b changed context"}
        self.assertEqual(extract_github_evidence(base)["fingerprint"], extract_github_evidence(changed_far)["fingerprint"])
        self.assertNotEqual(extract_github_evidence(base)["fingerprint"], extract_github_evidence(changed_near)["fingerprint"])
        empty = extract_github_evidence({})
        self.assertRegex(empty["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(empty["candidates"], [])


if __name__ == "__main__":
    unittest.main()
