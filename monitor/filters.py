"""Filter logic — decide which programs are worth notifying about.

A program passes all configured filters (i.e. is NOT filtered out)
when NONE of the filter rules reject it. Filters are intentionally
conservative: when in doubt, the program passes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from .state import Program


@dataclass
class FilterConfig:
    """User-configurable filters loaded from config.json.

    Semantics:
      include_kyc = True   → KEEP programs that require KYC
      include_kyc = False  → DROP programs that require KYC (default)
      min_bounty  = 0      → no lower bound
      min_bounty  = 50000  → DROP programs with max_bounty < 50000
                             (None is treated as 0 and filtered out)
      launch_within_days = 0 → no age filter
      launch_within_days = 30 → DROP programs older than 30 days
    """
    include_kyc: bool = False
    min_bounty: int = 0
    launch_within_days: int = 0
    blacklist_keywords: list[str] = field(default_factory=list)
    whitelist_languages: list[str] = field(default_factory=list)
    whitelist_ecosystems: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "FilterConfig":
        return cls(
            include_kyc=bool(d.get("include_kyc", False)),
            min_bounty=int(d.get("min_bounty", 0) or 0),
            launch_within_days=int(d.get("launch_within_days", 0) or 0),
            blacklist_keywords=list(d.get("blacklist_keywords", []) or []),
            whitelist_languages=list(d.get("whitelist_languages", []) or []),
            whitelist_ecosystems=list(d.get("whitelist_ecosystems", []) or []),
        )


def _days_since(iso_date: str | None) -> float | None:
    if not iso_date:
        return None
    try:
        s = iso_date[:19].replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (time.time() - dt.timestamp()) / 86400.0
    except (ValueError, TypeError):
        return None


def passes(p: Program, cfg: FilterConfig) -> bool:
    """Return True if program `p` should be notified about."""
    if p.kyc_required and not cfg.include_kyc:
        return False

    if cfg.min_bounty > 0:
        bounty = p.max_bounty or 0
        if bounty < cfg.min_bounty:
            return False

    if cfg.launch_within_days > 0:
        days = _days_since(p.launch_date)
        if days is None:
            pass  # unknown age — don't filter
        elif days > cfg.launch_within_days:
            return False

    if cfg.blacklist_keywords:
        hay = f"{p.name}\n{p.url}".lower()
        for kw in cfg.blacklist_keywords:
            if kw and kw.lower() in hay:
                return False

    if cfg.whitelist_languages:
        if not any(lang in cfg.whitelist_languages for lang in p.languages):
            return False

    if cfg.whitelist_ecosystems:
        if not any(eco in cfg.whitelist_ecosystems for eco in p.ecosystems):
            return False

    return True


def apply_filters(programs: Iterable[Program], cfg: FilterConfig) -> list[Program]:
    return [p for p in programs if passes(p, cfg)]


def explain_filter(p: Program, cfg: FilterConfig) -> str | None:
    """Return a human-readable reason why a program was filtered out,
    or None if it passes. Useful for /filters debugging commands."""
    if p.kyc_required and not cfg.include_kyc:
        return "KYC required"
    if cfg.min_bounty > 0:
        bounty = p.max_bounty or 0
        if bounty < cfg.min_bounty:
            return f"bounty {bounty} < min {cfg.min_bounty}"
    if cfg.launch_within_days > 0:
        days = _days_since(p.launch_date)
        if days is not None and days > cfg.launch_within_days:
            return f"launched {days:.0f}d ago > {cfg.launch_within_days}d"
    if cfg.blacklist_keywords:
        hay = f"{p.name}\n{p.url}".lower()
        for kw in cfg.blacklist_keywords:
            if kw and kw.lower() in hay:
                return f"matches blacklist keyword '{kw}'"
    if cfg.whitelist_languages:
        if not any(lang in cfg.whitelist_languages for lang in p.languages):
            return f"no language in whitelist {cfg.whitelist_languages}"
    if cfg.whitelist_ecosystems:
        if not any(eco in cfg.whitelist_ecosystems for eco in p.ecosystems):
            return f"no ecosystem in whitelist {cfg.whitelist_ecosystems}"
    return None
