"""HackenProof scraper — extracts visible program slugs from the /programs page.

HackenProof loads its full program list asynchronously via Nuxt.
The main page exposes ~20 program links. This scraper captures them as
the "current set" — a new slug appearing on the main page is a NEW program.
"""
from __future__ import annotations

import re

from ..state import Program
from .base import BaseScraper


class HackenProofScraper(BaseScraper):
    name = "hackenproof"
    display_name = "HackenProof"

    # Slugs that appear in navigation/footer but are not real programs.
    # We discard these explicitly. Filter the input list of slugs.
    _NON_PROGRAM_SLUGS = frozenset({
        "weekly", "programs", "bounty", "submit", "leaderboard", "login",
        "signup", "register", "blog", "about", "contact", "faq", "help",
        "terms", "privacy", "policy", "docs", "documentation", "api",
        "home", "index", "search", "explore", "discover",
    })

    # Match /programs/<slug> with optional trailing path. We only count
    # hrefs that point to /programs/<slug> directly (not nested).
    _SLUG_RE = re.compile(
        r'href="(?:https?://hackenproof\.com)?/programs/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])(?:/[^"]*)?"'
    )

    def parse(self, raw: str) -> list[Program]:
        # Pull slugs from the HTML
        slugs = set()
        for m in self._SLUG_RE.finditer(raw):
            slugs.add(m.group(1))

        # Filter out navigation/footer slugs
        slugs -= self._NON_PROGRAM_SLUGS

        programs = []
        for slug in sorted(slugs):
            # Heuristic: title-case the slug for display
            name = slug.replace("-", " ").title()
            programs.append(
                Program(
                    id=f"hackenproof:{slug}",
                    platform=self.display_name,
                    name=name,
                    url=f"https://hackenproof.com/programs/{slug}",
                    max_bounty=None,
                    kyc_required=False,
                    languages=[],
                    ecosystems=[],
                    extra={"slug": slug},
                )
            )
        return programs
