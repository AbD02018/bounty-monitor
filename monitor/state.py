"""State persistence — track which programs we've already seen."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Program:
    """Normalized program representation across all platforms."""
    id: str  # platform-specific unique ID (e.g., "immunefi:layerzero")
    platform: str
    name: str
    url: str
    max_bounty: int | None = None
    launch_date: str | None = None
    updated_date: str | None = None
    kyc_required: bool = False
    languages: list[str] = field(default_factory=list)
    ecosystems: list[str] = field(default_factory=list)
    # Scope enrichment (populated by detail scrapers)
    in_scope: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    severity_tiers: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def content_hash(self) -> str:
        """Stable hash of notification-relevant fields.

        Includes scope so that a scope change is detected as a
        notification-worthy update.
        """
        payload = {
            "name": self.name,
            "max_bounty": self.max_bounty,
            "kyc_required": self.kyc_required,
            "languages": sorted(self.languages),
            "ecosystems": sorted(self.ecosystems),
            "launch_date": self.launch_date,
            "updated_date": self.updated_date,
            "in_scope": sorted(self.in_scope),
            "out_of_scope": sorted(self.out_of_scope),
            "severity_tiers": sorted(self.severity_tiers),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def scope_diff(self, other: "Program") -> dict:
        """Return what changed in scope between two snapshots of the
        same program. Empty dict means no scope change.

        Keys:
          added_in_scope  — new in-scope assets (good: more surface)
          removed_in_scope — assets dropped from scope (rare)
          added_out_of_scope — new exclusions
        """
        old_in = set(self.in_scope)
        new_in = set(other.in_scope)
        old_out = set(self.out_of_scope)
        new_out = set(other.out_of_scope)
        result = {}
        if new_in - old_in:
            result["added_in_scope"] = sorted(new_in - old_in)
        if old_in - new_in:
            result["removed_in_scope"] = sorted(old_in - new_in)
        if new_out - old_out:
            result["added_out_of_scope"] = sorted(new_out - old_out)
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "Program":
        return cls(
            id=d["id"],
            platform=d["platform"],
            name=d["name"],
            url=d["url"],
            max_bounty=d.get("max_bounty"),
            launch_date=d.get("launch_date"),
            updated_date=d.get("updated_date"),
            kyc_required=d.get("kyc_required", False),
            languages=d.get("languages", []),
            ecosystems=d.get("ecosystems", []),
            in_scope=d.get("in_scope", []),
            out_of_scope=d.get("out_of_scope", []),
            severity_tiers=d.get("severity_tiers", []),
            extra=d.get("extra", {}),
        )


class State:
    """Persistent state: which programs we've already notified about."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.seen: dict[str, Program] = {}  # program_id -> Program
        self.hashes: dict[str, str] = {}  # program_id -> content_hash at last notify
        self.muted: set[str] = set()  # platform names muted via /mute
        self.last_check_ts: float = 0.0
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.seen = {pid: Program.from_dict(p) for pid, p in raw.get("seen", {}).items()}
            self.hashes = raw.get("hashes", {})
            self.muted = set(raw.get("muted", []) or [])
            self.last_check_ts = raw.get("last_check_ts", 0.0)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[state] warning: failed to load state: {e}; starting fresh")
            self.seen = {}
            self.hashes = {}
            self.muted = set()
            self.last_check_ts = 0.0

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "seen": {pid: p.to_dict() for pid, p in self.seen.items()},
            "hashes": self.hashes,
            "muted": sorted(self.muted),
            "last_check_ts": self.last_check_ts,
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent),
            prefix=self.path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def diff(self, current: list[Program]) -> list[Program]:
        """Return programs in `current` that are NOT in state OR whose
        content_hash has changed since last notification."""
        out: list[Program] = []
        for p in current:
            if p.id not in self.seen:
                out.append(p)
                continue
            if self.hashes.get(p.id) != p.content_hash():
                out.append(p)
        return out

    def snapshot(self, current: list[Program]) -> list[Program]:
        new = []
        for p in current:
            if p.id not in self.seen:
                new.append(p)
            self.seen[p.id] = p
            self.hashes[p.id] = p.content_hash()
        self.last_check_ts = time.time()
        return new

    def mark_seen(self, programs: list[Program]) -> None:
        for p in programs:
            self.seen[p.id] = p
            self.hashes[p.id] = p.content_hash()
        self.last_check_ts = time.time()

    def count(self) -> int:
        return len(self.seen)

    def is_muted(self, platform: str) -> bool:
        return platform.lower() in {m.lower() for m in self.muted}

    def mute(self, platform: str) -> None:
        self.muted.add(platform.lower())

    def unmute(self, platform: str) -> None:
        self.muted.discard(platform.lower())
