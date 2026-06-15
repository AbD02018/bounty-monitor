"""Detail page scrapers — fetch and parse scope information.

Each platform has a different detail page layout. These scrapers
return a `DetailInfo` with in_scope, out_of_scope, severity_tiers.

Strategy: only fetch the detail page for programs that are new
(missing from state) or whose content_hash changed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from .platforms.base import BaseScraper


@dataclass
class DetailInfo:
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    severity_tiers: list[str] = field(default_factory=list)
    notes: str = ""

    def apply_to(self, program) -> None:
        program.in_scope = self.in_scope
        program.out_of_scope = self.out_of_scope
        program.severity_tiers = self.severity_tiers


def _extract_inline_asset_list(soup: BeautifulSoup, header_patterns: list[str], max_items: int = 50) -> list[str]:
    """When the page doesn't put assets in <li> elements (Immunefi
    does this — the asset names are in a single text run), find the
    text node that follows the header and split on common separators.
    """
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
        text = heading.get_text(strip=True).lower()
        if not any(p.lower() in text for p in header_patterns):
            continue
        # Look at the next several elements and concatenate their text
        # until we hit the next heading
        node = heading
        chunks: list[str] = []
        for _ in range(20):
            node = node.find_next()
            if node is None:
                break
            if isinstance(node, NavigableString):
                continue
            if node.name in ('h1', 'h2', 'h3', 'h4', 'h5'):
                break
            t = node.get_text(separator=' ', strip=True)
            if t:
                chunks.append(t)
            if len(chunks) >= 8:
                break
        full = ' '.join(chunks)
        # Try splitting on common separators
        for sep in [', and ', ' and ', ', ', '\n', '; ']:
            if sep in full:
                parts = [p.strip() for p in full.split(sep) if p.strip()]
                if len(parts) >= 3:
                    return _clean_asset_list(parts, max_items)
        # Try splitting on CamelCase boundary (Aave v2 LendingPool Aave v2 AToken)
        # If a sequence of consecutive CapitalCase words forms a list
        words = full.split()
        # Group consecutive capitalized names: at least 2 in a row
        groups: list[str] = []
        current: list[str] = []
        for w in words:
            if w and w[0].isupper() and not w.isupper():
                current.append(w)
            else:
                if len(current) >= 2:
                    groups.append(' '.join(current))
                current = []
        if len(current) >= 2:
            groups.append(' '.join(current))
        if len(groups) >= 3:
            return _clean_asset_list(groups, max_items)
    return []


def _clean_asset_list(items: list[str], max_items: int) -> list[str]:
    """Filter out noise and cap length."""
    out: list[str] = []
    seen: set[str] = set()
    skip_prefixes = (
        "the ", "a ", "an ", "this ", "these ", "those ", "if ", "for ",
        "in ", "on ", "at ", "by ", "with ", "without ", "from ", "to ",
        "is ", "are ", "was ", "were ", "be ", "been ",
        "all ", "any ", "some ", "no ", "not ", "only ",
        "you ", "your ", "we ", "us ", "our ", "they ", "their ",
        "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.",
    )
    for it in items:
        it = re.sub(r'\s+', ' ', it).strip()
        if not it or len(it) < 3 or len(it) > 200:
            continue
        low = it.lower()
        if any(low.startswith(p) for p in skip_prefixes):
            continue
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
        if len(out) >= max_items:
            break
    return out


def _after_heading(soup: BeautifulSoup, header_patterns: list[str], max_items: int = 50) -> list[str]:
    """Find a heading whose text matches one of the patterns, then
    collect the next batch of <li> items + <a> links until the next
    heading.

    Walks the next ~15 elements after the heading (using find_next)
    and stops at the next sibling heading. Filters out items that
    look like exclusion text (start with "Developers", "Independent",
    "Security auditors", etc.).
    """
    items: list[str] = []
    seen: set[str] = set()
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
        text = heading.get_text(strip=True).lower()
        if not any(p.lower() in text for p in header_patterns):
            continue
        node = heading
        for _ in range(20):
            node = node.find_next()
            if node is None:
                break
            if isinstance(node, NavigableString):
                continue
            if node.name in ('h1', 'h2', 'h3', 'h4', 'h5'):
                break
            for li in node.find_all('li'):
                txt = li.get_text(separator=' ', strip=True)
                txt = re.sub(r'\s+', ' ', txt)
                if not _looks_like_asset(txt):
                    continue
                if txt and 3 < len(txt) < 500 and txt not in seen:
                    seen.add(txt)
                    items.append(txt)
            if not items:
                for td in node.find_all('td'):
                    txt = td.get_text(separator=' ', strip=True)
                    txt = re.sub(r'\s+', ' ', txt)
                    if not _looks_like_asset(txt):
                        continue
                    if not re.match(r'^0x[0-9a-fA-F]{40}$', txt):
                        if 3 < len(txt) < 500 and txt not in seen:
                            seen.add(txt)
                            items.append(txt)
            if len(items) >= max_items:
                break
        if items:
            return items[:max_items]
    return []


# Phrases that mark a <li> as NOT an asset but rather an exclusion /
# rule / process note. Used to filter out false positives.
_EXCLUSION_PREFIXES = (
    "developers who have", "security auditors", "white-hats", "white hats",
    "independent security", "independent contributors", "former official",
    "no ", "any ", "must ", "should ", "the bug must", "the report",
    "all ", "only ", "if the bug", "if you", "you must", "you should",
    "we ", "us ", "our ", "they ", "their ", "this program", "this bounty",
    "https://github.com", "https://docs.", "http://", "https://",  # raw URLs (these are audit links, not assets)
    "reward", "rewards are", "rewards for", "rewards can",
    "the maximum", "the minimum", "the reward",
    "your report", "your bug",
)


def _looks_like_asset(text: str) -> bool:
    """Heuristic: is this <li> text an asset name, or a process note?
    Asset names tend to be short CamelCase identifiers like
    'Aave v2 LendingPool' or 'LendingPool contract'. Process notes
    start with verbs or contain words like 'must', 'should', etc.
    """
    low = text.lower()
    if any(low.startswith(p) for p in _EXCLUSION_PREFIXES):
        return False
    if len(text) > 200:
        return False
    # Asset names usually have at least one capital letter
    if not any(c.isupper() for c in text):
        return False
    # And not too many lowercase "stop" words
    stop_words = ("the", "and", "or", "if", "for", "with", "without", "from", "to", "of", "in", "on", "at", "by")
    words = low.split()
    if sum(1 for w in words if w in stop_words) > len(words) * 0.4:
        return False
    return True


def _extract_severity_tiers(soup: BeautifulSoup) -> list[str]:
    """Find any text matching 'Critical: $X' / 'High: $X' etc."""
    text = soup.get_text(separator=" ")
    severities: list[str] = []
    seen: set[str] = set()
    # Match patterns like "Critical: $250,000" or "Critical: up to $1,000,000"
    for m in re.finditer(
        r'(Critical|High|Medium|Low)\s*:?\s*(?:up\s*to\s*)?\$?([\d,]+)',
        text,
        re.IGNORECASE,
    ):
        sev = m.group(1).capitalize()
        amt = m.group(2).replace(",", "")
        if amt.isdigit():
            tier = f"{sev}: ${int(amt):,}"
            if tier not in seen:
                seen.add(tier)
                severities.append(tier)
    return severities[:6]


class _DetailBase(BaseScraper):
    def parse(self, raw: str) -> DetailInfo:
        raise NotImplementedError


class ImmunefiDetail(_DetailBase):
    name = "immunefi_detail"
    display_name = "Immunefi Detail"

    def parse(self, raw: str) -> DetailInfo:
        info = DetailInfo()
        soup = BeautifulSoup(raw, "lxml")

        # Strategy 1: list items after a heading
        info.in_scope = _after_heading(soup, ["mainnet assets", "testnet assets", "assets in scope", "smart contract", "in scope"])
        # Strategy 2: inline asset list (Immunefi's preferred format)
        if len(info.in_scope) < 3:
            info.in_scope = _extract_inline_asset_list(soup, ["mainnet assets", "testnet assets", "assets in scope", "smart contract", "in scope"])
        # Strategy 3: any <li> with a github URL
        if len(info.in_scope) < 3:
            for li in soup.find_all('li'):
                for a in li.find_all('a', href=True):
                    if 'github.com' in a['href']:
                        txt = li.get_text(separator=' ', strip=True)
                        if 5 < len(txt) < 300:
                            info.in_scope.append(txt)
                            break
                if len(info.in_scope) >= 20:
                    break

        info.out_of_scope = _after_heading(soup, ["out of scope", "not in scope", "out-of-scope"])
        if len(info.out_of_scope) < 3:
            info.out_of_scope = _extract_inline_asset_list(soup, ["out of scope", "not in scope", "out-of-scope"])

        info.severity_tiers = _extract_severity_tiers(soup)

        return info


class BugcrowdDetail(_DetailBase):
    name = "bugcrowd_detail"
    display_name = "Bugcrowd Detail"

    def parse(self, raw: str) -> DetailInfo:
        info = DetailInfo()
        soup = BeautifulSoup(raw, "lxml")
        info.in_scope = _after_heading(soup, ["scope", "in scope", "targets"])
        info.out_of_scope = _after_heading(soup, ["out of scope", "not in scope", "out-of-scope"])
        return info


class YesWeHackDetail(_DetailBase):
    name = "yeswehack_detail"
    display_name = "YesWeHack Detail"

    def parse(self, raw: str) -> DetailInfo:
        info = DetailInfo()
        soup = BeautifulSoup(raw, "lxml")
        info.in_scope = _after_heading(soup, ["scope", "in scope", "targets"])
        info.out_of_scope = _after_heading(soup, ["out of scope", "not in scope", "out-of-scope"])
        return info


def enrich_program(program, timeout: int = 15, user_agent: str = "Mozilla/5.0") -> bool:
    """Fetch and apply detail info to a program in place."""
    platform = program.platform.lower()
    scraper_cls = {
        "immunefi": ImmunefiDetail,
        "bugcrowd": BugcrowdDetail,
        "yeswehack": YesWeHackDetail,
    }.get(platform)

    if scraper_cls is None:
        return False

    scraper = scraper_cls(
        url=program.url,
        timeout=timeout,
        user_agent=user_agent,
    )
    try:
        raw = scraper.fetch()
        if raw is None:
            return False
        info = scraper.parse(raw)
        info.apply_to(program)
        return bool(info.in_scope or info.out_of_scope or info.severity_tiers)
    except Exception as e:
        print(f"[detail] {platform}: {program.id}: {e}")
        return False
