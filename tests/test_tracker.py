import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tracker


CARD_PAGE = """<!doctype html><html><body>
<div class="card-package card-package--variant--card">
  <a class="link card-package__media" href="/c/valheim/p/ExampleAuthor/ExampleMod/">
    <div class="card-package__image-tags"><div class="tag"><svg data-icon="thumbtack"></svg>Pinned</div></div>
    <img src="https://gcdn.thunderstore.io/icons/example.png" alt="">
  </a>
  <div class="card-package__content">
    <div class="card-package__heading">
      <a class="card-package__title" href="/c/valheim/p/ExampleAuthor/ExampleMod/">Example Mod</a>
    </div>
    <div class="card-package__author">by <a class="card-package__link" href="/c/valheim/p/ExampleAuthor/">ExampleAuthor</a></div>
    <p class="card-package__description">An example &amp; useful mod.</p>
    <div class="card-package__tags">
      <a class="tag tag--hoverable" href="/c/valheim/?includedCategories=17"><span>Mods</span></a>
      <a class="tag tag--hoverable" href="/c/valheim/?includedCategories=30"><span>Client-side</span></a>
    </div>
    <div class="card-package__footer">
      <div class="meta-item"><svg data-icon="download"></svg>1.5K</div>
      <button class="meta-item"><svg data-icon="thumbs-up"></svg>23</button>
      <span class="card-package__updated" aria-label="Last Updated"><svg data-icon="clock-rotate-left"></svg><span>7 minutes ago</span></span>
    </div>
  </div>
</div>
</body></html>"""


class ParseListingTests(unittest.TestCase):
    def test_parses_all_stable_card_fields(self):
        cards = tracker.parse_listing(CARD_PAGE, "https://thunderstore.io")

        self.assertEqual(len(cards), 1)
        self.assertEqual(
            cards[0],
            {
                "title": "Example Mod",
                "author": "ExampleAuthor",
                "description": "An example & useful mod.",
                "thumbnail_url": "https://gcdn.thunderstore.io/icons/example.png",
                "package_url": "https://thunderstore.io/c/valheim/p/ExampleAuthor/ExampleMod/",
                "author_url": "https://thunderstore.io/c/valheim/p/ExampleAuthor/",
                "downloads_display": "1.5K",
                "downloads": 1500,
                "likes_display": "23",
                "likes": 23,
                "last_updated_display": "7 minutes ago",
                "categories": [
                    {
                        "name": "Mods",
                        "id": 17,
                        "url": "https://thunderstore.io/c/valheim/?includedCategories=17",
                    },
                    {
                        "name": "Client-side",
                        "id": 30,
                        "url": "https://thunderstore.io/c/valheim/?includedCategories=30",
                    },
                ],
                "pinned": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
