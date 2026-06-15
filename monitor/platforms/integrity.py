"""Integrity scraper — best-effort stub.

Integrity is a Web3 bug bounty / audit-competition platform. The
specific subdomain (integrity.dev, integrity.club, etc.) is not
stable; this scraper tries several common paths and returns whatever
data it can find.
"""
from __future__ import annotations

import re

from ..state import Program
from .base import BaseScraper


_NON_PROGRAM_SLUGS = frozenset({
    "programs", "bounty", "leaderboard", "submit", "login", "signup",
    "register", "about", "contact", "blog", "home", "index", "search",
    "explore", "discover", "docs", "api", "help", "faq", "terms",
    "privacy", "policy", "contests", "audits", "dashboard",
})


class IntegrityScraper(BaseScraper):
    name = "integrity"
    display_name = "Integrity"

    def parse(self, raw: str) -> list[Program]:
        programs: list[Program] = []

        # Try multiple link patterns
        slugs: set[str] = set()
        for pattern in (
            r'/programs?/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])',
            r'/bounty/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])',
            r'/contests?/([a-z0-9][a-z0-9-]{2,60}[a-z0-9])',
        ):
            slugs.update(re.findall(pattern, raw))

        slugs -= _NON_PROGRAM_SLUGS

        for s in sorted(slugs):
            programs.append(
                Program(
                    id=f"integrity:{s}",
                    platform=self.display_name,
                    name=s.replace("-", " ").title(),
                    url=f"https://integrity.dev/programs/{s}",
                    max_bounty=None,
                    kyc_required=False,
                    languages=[],
                    ecosystems=[],
                    extra={"slug": s, "note": "Integrity data may require JS or auth"},
                )
            )
        return programs
