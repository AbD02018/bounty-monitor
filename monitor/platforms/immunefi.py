"""Immunefi scraper — extracts programs from the /explore page.

The /explore page is a Next.js app that ships program data as JSON
inside RSC (React Server Components) `__next_f.push(...)` chunks.
We extract the JSON payload with a tolerant regex, then parse it
with the real JSON parser so we don't break when the field order
changes.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..state import Program
from .base import BaseScraper


class ImmunefiScraper(BaseScraper):
    name = "immunefi"
    display_name = "Immunefi"

    # Each program object starts with `{"contentfulId":...` (with
    # RSC escaping) but the field order is not stable across deploys,
    # so we find every top-level `{...}` and let JSON parsing decide
    # whether it's a program. To narrow the haystack we look for any
    # object that has BOTH `contentfulId` and either `slug` or
    # `maxBounty` somewhere inside.
    _OBJECT_HINT_RE = re.compile(r'\{[^{}]{0,200}"contentfulId":')

    def parse(self, raw: str) -> list[Program]:
        # The page is RSC-serialized: keys/values are escaped.
        unescaped = (
            raw.replace('\\"', '"')
               .replace('\\\\', '\\')
               .replace('\\n', '\n')
               .replace('\\u002F', '/')
        )

        programs: list[Program] = []
        seen_ids: set[str] = set()

        for m in self._OBJECT_HINT_RE.finditer(unescaped):
            start = m.start()
            obj = self._extract_balanced_object(unescaped, start)
            if obj is None:
                continue
            try:
                data = json.loads(obj)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            # Must look like a program object
            if "contentfulId" not in data or "slug" not in data:
                continue
            slug = data.get("slug", "")
            if not slug or slug in seen_ids:
                continue
            seen_ids.add(slug)

            programs.append(self._to_program(data))

        return programs

    @staticmethod
    def _extract_balanced_object(text: str, start: int) -> str | None:
        """Given text starting with '{', return the substring up to
        and including the matching '}'. Tolerates braces inside strings.
        """
        if start >= len(text) or text[start] != "{":
            return None
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

    @staticmethod
    def _to_program(data: dict[str, Any]) -> Program:
        tags = data.get("tags") or {}
        langs = list(tags.get("language") or [])
        ecos = list(tags.get("ecosystem") or [])
        return Program(
            id=f"immunefi:{data.get('slug', '')}",
            platform=ImmunefiScraper.display_name,
            name=str(data.get("project") or data.get("slug") or ""),
            url=f"https://immunefi.com{data.get('url', '')}",
            max_bounty=int(data["maxBounty"]) if data.get("maxBounty") else None,
            launch_date=data.get("launchDate"),
            updated_date=data.get("updatedDate"),
            kyc_required=bool(data.get("kyc", False)),
            languages=langs,
            ecosystems=ecos,
        )
