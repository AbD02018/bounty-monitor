"""Platform scrapers package."""
from .base import BaseScraper, safe_int
from .immunefi import ImmunefiScraper
from .bugcrowd import BugcrowdScraper
from .yeswehack import YesWeHackScraper
from .hackenproof import HackenProofScraper
from .hackerone import HackerOneScraper
from .bugrap import BugRapScraper
from .integrity import IntegrityScraper

__all__ = [
    "BaseScraper",
    "safe_int",
    "ImmunefiScraper",
    "BugcrowdScraper",
    "YesWeHackScraper",
    "HackenProofScraper",
    "HackerOneScraper",
    "BugRapScraper",
    "IntegrityScraper",
]


# Convenience: registry mapping name -> class
PLATFORMS: dict[str, type[BaseScraper]] = {
    "immunefi": ImmunefiScraper,
    "bugcrowd": BugcrowdScraper,
    "yeswehack": YesWeHackScraper,
    "hackenproof": HackenProofScraper,
    "hackerone": HackerOneScraper,
    "bugrap": BugRapScraper,
    "integrity": IntegrityScraper,
}


def get_scraper(name: str, url: str, **kwargs) -> BaseScraper:
    cls = PLATFORMS.get(name)
    if cls is None:
        raise ValueError(f"Unknown platform: {name}")
    return cls(url=url, **kwargs)
