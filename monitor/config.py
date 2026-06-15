"""Configuration loader."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .filters import FilterConfig


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = False

    def is_configured(self) -> bool:
        return bool(
            self.bot_token
            and self.bot_token != "YOUR_BOT_TOKEN_FROM_BOTFATHER"
            and self.chat_id
            and self.chat_id != "YOUR_CHAT_ID"
        )


@dataclass
class RequestConfig:
    timeout_seconds: int = 30
    user_agent: str = "Mozilla/5.0 (BugBountyMonitor/1.0)"
    delay_between_platforms_seconds: int = 2


@dataclass
class EnrichmentConfig:
    enabled: bool = True
    fetch_timeout: int = 15
    cache_hours: int = 24


class Config:
    """Loads config from JSON file with environment variable overrides.

    Filter and enrichment sub-objects are stored as typed configs so
    callers can use `cfg.filters.min_bounty` etc. directly.
    """

    def __init__(self, raw: dict[str, Any], path: Path | None = None):
        self.path = path
        self.telegram = TelegramConfig(
            bot_token=os.environ.get("BOT_TOKEN", raw.get("telegram", {}).get("bot_token", "")),
            chat_id=os.environ.get("CHAT_ID", raw.get("telegram", {}).get("chat_id", "")),
            parse_mode=raw.get("telegram", {}).get("parse_mode", "HTML"),
            disable_web_page_preview=raw.get("telegram", {}).get("disable_web_page_preview", False),
        )
        self.request = RequestConfig(
            timeout_seconds=raw.get("request", {}).get("timeout_seconds", 30),
            user_agent=raw.get("request", {}).get("user_agent", "Mozilla/5.0 (BugBountyMonitor/1.0)"),
            delay_between_platforms_seconds=raw.get("request", {}).get("delay_between_platforms_seconds", 2),
        )
        self.platforms: dict[str, dict[str, Any]] = raw.get("platforms", {})
        self.filters = FilterConfig.from_dict(raw.get("filters", {}) or {})
        self.enrichment = EnrichmentConfig(
            enabled=bool(raw.get("enrichment", {}).get("enabled", True)),
            fetch_timeout=int(raw.get("enrichment", {}).get("fetch_timeout", 15) or 15),
            cache_hours=int(raw.get("enrichment", {}).get("cache_hours", 24) or 24),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(raw, path=p)

    def save(self) -> None:
        """Persist current config back to disk (for /set command)."""
        if self.path is None:
            return
        raw = {
            "telegram": {
                "bot_token": self.telegram.bot_token,
                "chat_id": self.telegram.chat_id,
                "parse_mode": self.telegram.parse_mode,
                "disable_web_page_preview": self.telegram.disable_web_page_preview,
            },
            "platforms": self.platforms,
            "request": {
                "timeout_seconds": self.request.timeout_seconds,
                "user_agent": self.request.user_agent,
                "delay_between_platforms_seconds": self.request.delay_between_platforms_seconds,
            },
            "filters": {
                "include_kyc": self.filters.include_kyc,
                "min_bounty": self.filters.min_bounty,
                "launch_within_days": self.filters.launch_within_days,
                "blacklist_keywords": self.filters.blacklist_keywords,
                "whitelist_languages": self.filters.whitelist_languages,
                "whitelist_ecosystems": self.filters.whitelist_ecosystems,
            },
            "enrichment": {
                "enabled": self.enrichment.enabled,
                "fetch_timeout": self.enrichment.fetch_timeout,
                "cache_hours": self.enrichment.cache_hours,
            },
        }
        self.path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    def platform_enabled(self, name: str) -> bool:
        return self.platforms.get(name, {}).get("enabled", False)

    def platform_url(self, name: str) -> str:
        return self.platforms.get(name, {}).get("url", "")

    def list_enabled_platforms(self) -> list[str]:
        return [n for n, cfg in self.platforms.items() if cfg.get("enabled", False)]
