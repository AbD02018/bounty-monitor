"""Bridge: bounty-monitor + target-data-extractor.

Uses the structured extractor as a fallback / primary enricher for platforms
that don't have a native detail scraper in monitor/detail.py — Intigriti,
Bugrap, HackenProof, and HackerOne when no API token is configured.

Public API:
    enrich_with_extractor(program, *, prefer="native") -> bool

`prefer`:
    "native"   - try monitor's native scraper first, fall back to extractor
    "extractor" - use extractor first (better scope structure), fall back to native
    "extractor-only" - only use extractor
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import Program

logger = logging.getLogger(__name__)


def enrich_with_extractor(
    program: "Program",
    *,
    prefer: str = "native",
    timeout: int = 60,
) -> bool:
    """Enrich a program with scope info via target-data-extractor.

    Returns True if the program was updated (any field changed).
    """
    try:
        from target_data_extractor.bypass import BypassClient, BypassConfig
        from target_data_extractor.platforms import detect_platform, get_platform
    except ImportError:
        logger.warning("target-data-extractor not installed; cannot enrich with extractor")
        return False

    try:
        platform_name = detect_platform(program.url)
    except Exception as exc:
        logger.debug("Could not detect platform for %s: %s", program.url, exc)
        return False

    async def _run() -> bool:
        bypass = BypassClient(BypassConfig(strategy="auto", min_delay_seconds=0, max_delay_seconds=0))
        try:
            platform = get_platform(platform_name, bypass=bypass)
            extracted = await asyncio.wait_for(platform.extract(program.url), timeout=timeout)
        except Exception as exc:
            logger.debug("Extractor failed for %s: %s", program.url, exc)
            return False
        finally:
            bypass.close()

        if not extracted:
            return False

        # Map extracted BountyProgram -> monitor's Program dataclass
        changed = False

        in_scope = [a.target for a in extracted.scope.in_scope]
        if in_scope and set(in_scope) != set(program.in_scope):
            program.in_scope = in_scope
            changed = True

        out_of_scope = [a.target for a in extracted.scope.out_of_scope]
        if out_of_scope and set(out_of_scope) != set(program.out_of_scope):
            program.out_of_scope = out_of_scope
            changed = True

        sev = [b.severity.value for b in extracted.bounty_table if b.severity]
        if sev and set(sev) != set(program.severity_tiers):
            program.severity_tiers = sev
            changed = True

        # Max bounty if missing
        if extracted.max_bounty_usd and not program.max_bounty:
            program.max_bounty = float(extracted.max_bounty_usd)
            changed = True

        return changed

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.debug("Extractor enrich exception for %s: %s", program.url, exc)
        return False


def smart_enrich(
    program: "Program",
    *,
    timeout: int = 60,
    use_extractor_for: tuple[str, ...] = ("intigriti", "bugrap", "hackenproof"),
) -> bool:
    """Top-level: pick the right enricher.

    Uses native enrich_program for platforms with good built-in scrapers
    (immunefi, bugcrowd, yeswehack). Uses target-data-extractor for the rest
    (intigriti, bugrap, hackenproof, hackerone).
    """
    from .detail import enrich_program

    platform = (program.platform or "").lower()

    if platform in use_extractor_for:
        return enrich_with_extractor(program, prefer="extractor-only", timeout=timeout)

    # For platforms with native scrapers, try native first, fall back to extractor
    if enrich_program(program, timeout=min(timeout, 30)):
        return True
    return enrich_with_extractor(program, prefer="extractor-only", timeout=timeout)
