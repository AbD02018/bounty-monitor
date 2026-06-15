"""BugRap scraper — best-effort stub.

BugRap is a Korean bug bounty platform. The SPA returns only a 1.8 KB
shell regardless of the endpoint, with all data loaded client-side.
We attempt a few public paths and report what we find.
"""
from __future__ import annotations

import re

from ..state import Program
from .base import BaseScraper


# Slugs that are part of site navigation, footer, or chrome — never
# actual programs. Filter these out before reporting any match.
_NON_PROGRAM_SLUGS = frozenset({
    "programs", "bounty", "leaderboard", "submit", "login", "signup",
    "register", "about", "contact", "blog", "home", "index", "search",
    "explore", "discover", "docs", "api", "help", "faq", "terms",
    "privacy", "policy", "kr", "en", "ko",
})


class BugRapScraper(BaseScraper):
    name = "bugrap"
    display_name = "BugRap"

    def parse(self, raw: str) -> list[Program]:
        programs: list[Program] = []

        # Try to find program slugs from any link pattern
        slugs: set[str] = set()
        for pattern in (
            r'/programs?/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])',
            r'/bounty/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])',
        ):
            slugs.update(re.findall(pattern, raw))

        # Also try data-id attributes (SPA-rendered)
        for m in re.finditer(r'data-id="([a-z0-9][a-z0-9-]{2,60}[a-z0-9])"', raw):
            slugs.add(m.group(1))

        # Filter out navigation/footer slugs
        slugs -= _NON_PROGRAM_SLUGS

        for s in sorted(slugs):
            programs.append(
                Program(
                    id=f"bugrap:{s}",
                    platform=self.display_name,
                    name=s.replace("-", " ").title(),
                    url=f"https://bugrap.io/programs/{s}",
                    max_bounty=None,
                    kyc_required=False,
                    languages=[],
                    ecosystems=[],
                    extra={"slug": s, "note": "BugRap requires JS for full data"},
                )
            )
        return programs
