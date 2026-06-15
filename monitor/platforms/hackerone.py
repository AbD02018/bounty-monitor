"""HackerOne scraper — best-effort stub.

HackerOne heavily protects their directory behind authentication and
GraphQL introspection. The main page returns 1.8 KB of shell HTML with
no program data. Without authentication or a public API, we cannot
reliably enumerate the directory.

This scraper attempts two public endpoints and returns what it can find.
"""
from __future__ import annotations

import re

from ..state import Program
from .base import BaseScraper


class HackerOneScraper(BaseScraper):
    name = "hackerone"
    display_name = "HackerOne"

    def parse(self, raw: str) -> list[Program]:
        # The directory page is a JavaScript SPA — no program data is
        # in the initial HTML. We attempt a couple of fallbacks below.
        programs: list[Program] = []

        # Fallback 1: look for any program handles in inline JSON
        handles = set(re.findall(r'"handle":"([a-z0-9][a-z0-9_]{2,40})"', raw))

        # Filter out common non-program strings
        ignore = {"signup", "login", "logout", "settings", "profile",
                  "directory", "programs", "opportunities", "hacktivity"}
        handles -= ignore

        for h in sorted(handles):
            programs.append(
                Program(
                    id=f"hackerone:{h}",
                    platform=self.display_name,
                    name=h,
                    url=f"https://hackerone.com/{h}",
                    max_bounty=None,
                    kyc_required=False,
                    languages=[],
                    ecosystems=[],
                    extra={"handle": h, "note": "HackerOne requires auth for full data"},
                )
            )
        return programs
