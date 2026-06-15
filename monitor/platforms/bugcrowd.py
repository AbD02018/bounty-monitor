"""Bugcrowd scraper — uses the public /engagements.json API."""
from __future__ import annotations

import json

from ..state import Program
from .base import BaseScraper, safe_int


class BugcrowdScraper(BaseScraper):
    name = "bugcrowd"
    display_name = "Bugcrowd"

    def parse(self, raw: str) -> list[Program]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        items = data.get("engagements") or data.get("programs") or []
        programs: list[Program] = []
        for e in items:
            # Skip demo, banned, and private programs
            if e.get("isDemo") or e.get("isBanned") or e.get("isPrivate"):
                continue

            name = e.get("name", "").strip()
            url_path = e.get("briefUrl", "")
            if not name or not url_path:
                continue

            # Bugcrowd's URL field is a relative path
            full_url = f"https://bugcrowd.com{url_path}" if url_path.startswith("/") else url_path

            # Parse rewards — fields can be empty string, None, or
            # formatted as "$1,000". safe_int handles all of those.
            reward = e.get("rewardSummary", {}) or {}
            min_r = safe_int(reward.get("minReward"))
            max_r = safe_int(reward.get("maxReward"))
            # Use max as the headline bounty; fall back to min if max is missing
            max_b = max_r if max_r else min_r

            # Industry as a tag
            industry = e.get("industryName", "")
            tags = [industry] if industry else []

            # Detect KYC: Bugcrowd doesn't expose a "kyc" field directly,
            # but a non-empty maxReward strongly implies a paid bounty
            # (which is the only case where KYC might be requested).
            # Without a public KYC signal we leave it as False.
            kyc = bool(reward.get("maxReward") and max_r and max_r > 0)

            # Use a stable id derived from URL
            pid = url_path.strip("/").replace("/", "-")

            programs.append(
                Program(
                    id=f"bugcrowd:{pid}",
                    platform=self.display_name,
                    name=name,
                    url=full_url,
                    max_bounty=max_b,
                    kyc_required=kyc,
                    languages=[],
                    ecosystems=tags,
                    extra={
                        "min_reward": min_r,
                        "max_reward": max_r,
                        "type": (e.get("productEngagementType") or {}).get("iconVariant", ""),
                        "industry": industry,
                    },
                )
            )
        return programs
