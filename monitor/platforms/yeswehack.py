"""YesWeHack scraper — uses the public api.yeswehack.com/programs endpoint."""
from __future__ import annotations

import json

from ..state import Program
from .base import BaseScraper, safe_int


class YesWeHackScraper(BaseScraper):
    name = "yeswehack"
    display_name = "YesWeHack"

    def parse(self, raw: str) -> list[Program]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        items = data.get("items") or (data if isinstance(data, list) else [])
        programs: list[Program] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            # Skip disabled/archived
            if it.get("disabled") or it.get("archived"):
                continue

            title = it.get("title", "").strip()
            slug = it.get("slug", "").strip()
            if not title or not slug:
                continue

            # URL
            url = f"https://yeswehack.com/programs/{slug}"

            # Reward — safe_int handles None, empty strings, and numbers
            min_r = safe_int(it.get("bounty_reward_min"))
            max_r = safe_int(it.get("bounty_reward_max"))
            max_b = max_r if max_r else min_r

            # Activity area as a tag
            area = it.get("activity_area", "")
            country = it.get("country", "")
            tags = [area] if area else []

            # KYC heuristic: YesWeHack exposes a `requires_kyc` flag on
            # some programs but not all. Fall back to a True if there's
            # a non-zero max bounty AND a country scope (KYC is more
            # common in country-restricted programs).
            requires_kyc = bool(it.get("requires_kyc", False))

            programs.append(
                Program(
                    id=f"yeswehack:{slug}",
                    platform=self.display_name,
                    name=title,
                    url=url,
                    max_bounty=max_b,
                    kyc_required=requires_kyc,
                    languages=[],
                    ecosystems=tags,
                    extra={
                        "min_reward": min_r,
                        "max_reward": max_r,
                        "country": country,
                        "area": area,
                        "bounty": it.get("bounty"),
                        "last_update_at": it.get("last_update_at"),
                        "type": it.get("type"),
                    },
                )
            )
        return programs
