"""Tests for the monitor package.

Run with:
    python -m pytest tests/
or:
    python -m unittest discover tests/
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make sure we can import the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.filters import FilterConfig, apply_filters, explain_filter
from monitor.notifier.telegram import (
    TELEGRAM_MAX_LEN,
    _format_batch,
    _format_program,
)
from monitor.platforms.base import safe_int
from monitor.state import Program, State


def make_program(
    pid: str = "immunefi:test",
    name: str = "Test",
    max_bounty: int | None = 10000,
    platform: str = "Immunefi",
    kyc: bool = False,
    languages: list[str] | None = None,
    ecosystems: list[str] | None = None,
    launch_date: str | None = None,
    in_scope: list[str] | None = None,
) -> Program:
    return Program(
        id=pid,
        platform=platform,
        name=name,
        url="https://example.com/program",
        max_bounty=max_bounty,
        kyc_required=kyc,
        languages=languages or ["Solidity"],
        ecosystems=ecosystems or ["Ethereum"],
        launch_date=launch_date,
        in_scope=in_scope or [],
    )


class TestProgram(unittest.TestCase):
    def test_roundtrip(self):
        p = make_program()
        d = p.to_dict()
        p2 = Program.from_dict(d)
        self.assertEqual(p.id, p2.id)
        self.assertEqual(p.name, p2.name)
        self.assertEqual(p.max_bounty, p2.max_bounty)
        # Scope fields survive
        self.assertEqual(p.in_scope, p2.in_scope)
        p.in_scope = ["X", "Y"]
        p2 = Program.from_dict(p.to_dict())
        self.assertEqual(p.in_scope, p2.in_scope)

    def test_content_hash_stable(self):
        p1 = make_program(pid="x", max_bounty=100)
        p2 = make_program(pid="x", max_bounty=100)
        self.assertEqual(p1.content_hash(), p2.content_hash())

    def test_content_hash_changes_with_bounty(self):
        p1 = make_program(pid="x", max_bounty=100)
        p2 = make_program(pid="x", max_bounty=200)
        self.assertNotEqual(p1.content_hash(), p2.content_hash())

    def test_content_hash_changes_with_scope(self):
        p1 = make_program(pid="x", in_scope=["A", "B"])
        p2 = make_program(pid="x", in_scope=["A", "B", "C"])
        self.assertNotEqual(p1.content_hash(), p2.content_hash())

    def test_content_hash_ignores_extra(self):
        p1 = make_program(pid="x")
        p2 = make_program(pid="x")
        p1.extra = {"a": 1}
        p2.extra = {"b": 2}
        self.assertEqual(p1.content_hash(), p2.content_hash())

    def test_scope_diff_detects_additions(self):
        old = make_program(pid="x", in_scope=["A", "B"])
        new = make_program(pid="x", in_scope=["A", "B", "C"])
        diff = old.scope_diff(new)
        self.assertEqual(diff["added_in_scope"], ["C"])

    def test_scope_diff_detects_removals(self):
        old = make_program(pid="x", in_scope=["A", "B", "C"])
        new = make_program(pid="x", in_scope=["A", "B"])
        diff = old.scope_diff(new)
        self.assertEqual(diff["removed_in_scope"], ["C"])

    def test_scope_diff_detects_out_of_scope_additions(self):
        old = make_program(pid="x")
        old.in_scope = []
        old.out_of_scope = ["X"]
        new = make_program(pid="x")
        new.in_scope = []
        new.out_of_scope = ["X", "Y"]
        diff = old.scope_diff(new)
        self.assertEqual(diff["added_out_of_scope"], ["Y"])

    def test_scope_diff_empty_when_no_change(self):
        old = make_program(pid="x", in_scope=["A", "B"])
        new = make_program(pid="x", in_scope=["A", "B"])
        self.assertEqual(old.scope_diff(new), {})


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = Path(self.tmpdir) / "state.json"

    def test_empty_init(self):
        s = State(self.path)
        self.assertEqual(s.count(), 0)
        self.assertEqual(s.last_check_ts, 0.0)
        self.assertEqual(s.muted, set())

    def test_snapshot_then_save(self):
        s = State(self.path)
        programs = [make_program(pid="a"), make_program(pid="b", name="B")]
        new = s.snapshot(programs)
        self.assertEqual(len(new), 2)
        self.assertEqual(s.count(), 2)
        s.save()

        s2 = State(self.path)
        self.assertEqual(s2.count(), 2)

    def test_diff_new_programs(self):
        s = State(self.path)
        s.snapshot([make_program(pid="a")])
        s.save()

        s2 = State(self.path)
        current = [make_program(pid="a"), make_program(pid="b", name="B")]
        new = s2.diff(current)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].id, "b")

    def test_diff_no_new(self):
        s = State(self.path)
        s.snapshot([make_program(pid="a")])
        s.save()

        s2 = State(self.path)
        new = s2.diff([make_program(pid="a")])
        self.assertEqual(new, [])

    def test_diff_detects_bounty_change(self):
        s = State(self.path)
        s.snapshot([make_program(pid="x", max_bounty=100)])
        s.save()

        s2 = State(self.path)
        new = s2.diff([make_program(pid="x", max_bounty=500)])
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].max_bounty, 500)

    def test_diff_detects_scope_change(self):
        s = State(self.path)
        s.snapshot([make_program(pid="x", in_scope=["A"])])
        s.save()

        s2 = State(self.path)
        new = s2.diff([make_program(pid="x", in_scope=["A", "B"])])
        self.assertEqual(len(new), 1)

    def test_atomic_save_no_tmp_left(self):
        s = State(self.path)
        s.snapshot([make_program(pid="a")])
        s.save()
        tmp_files = list(self.path.parent.glob(self.path.name + ".*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_save_recovers_from_corrupt_state(self):
        self.path.write_text("not valid json {{{")
        s = State(self.path)
        self.assertEqual(s.count(), 0)

    def test_persistence_of_hashes(self):
        s = State(self.path)
        s.snapshot([make_program(pid="x", max_bounty=100)])
        s.save()
        s2 = State(self.path)
        self.assertIn("x", s2.hashes)
        self.assertEqual(s2.hashes["x"], s2.seen["x"].content_hash())

    def test_mute_unmute_persists(self):
        s = State(self.path)
        s.mute("immunefi")
        s.mute("bugcrowd")
        s.save()

        s2 = State(self.path)
        self.assertIn("immunefi", s2.muted)
        self.assertIn("bugcrowd", s2.muted)
        self.assertTrue(s2.is_muted("immunefi"))
        self.assertTrue(s2.is_muted("IMMUNEFI"))  # case-insensitive

        s2.unmute("immunefi")
        s2.save()
        s3 = State(self.path)
        self.assertNotIn("immunefi", s3.muted)
        self.assertIn("bugcrowd", s3.muted)


class TestFilters(unittest.TestCase):
    def test_no_filter_passes_everything(self):
        p = make_program(kyc=False, max_bounty=0)
        cfg = FilterConfig()
        self.assertTrue(apply_filters([p], cfg) == [p])

    def test_kyc_filter_drops_kyc(self):
        cfg = FilterConfig(include_kyc=False)
        kyc = make_program(kyc=True)
        no_kyc = make_program(pid="b", kyc=False)
        self.assertEqual(apply_filters([kyc, no_kyc], cfg), [no_kyc])

    def test_kyc_filter_keeps_when_included(self):
        cfg = FilterConfig(include_kyc=True)
        kyc = make_program(kyc=True, max_bounty=100_000)
        self.assertEqual(apply_filters([kyc], cfg), [kyc])

    def test_min_bounty_drops_small(self):
        cfg = FilterConfig(min_bounty=50_000)
        big = make_program(max_bounty=100_000)
        small = make_program(pid="b", max_bounty=10_000)
        none_bounty = make_program(pid="c", max_bounty=None)
        self.assertEqual(apply_filters([big, small, none_bounty], cfg), [big])

    def test_launch_within_days_drops_old(self):
        cfg = FilterConfig(launch_within_days=30)
        recent = make_program(launch_date="2024-01-01T00:00:00.000Z")
        # 2024-01-01 is more than 30 days ago as of 2026-06-15
        result = apply_filters([recent], cfg)
        # 2024-01-01 → ~890 days ago → filtered
        self.assertEqual(result, [])

    def test_launch_within_days_keeps_recent(self):
        cfg = FilterConfig(launch_within_days=365)
        p = make_program(launch_date="2026-01-01T00:00:00.000Z")
        result = apply_filters([p], cfg)
        # Within last year
        self.assertEqual(result, [p])

    def test_blacklist_keyword(self):
        cfg = FilterConfig(blacklist_keywords=["Ethereum", "EVM"])
        eth = make_program(name="Ethereum Bridge", ecosystems=["Ethereum"])
        sol = make_program(pid="b", name="Solana Program", ecosystems=["Solana"])
        self.assertEqual(apply_filters([eth, sol], cfg), [sol])

    def test_whitelist_languages(self):
        cfg = FilterConfig(whitelist_languages=["Solidity", "Vyper"])
        solidity = make_program(languages=["Solidity"])
        rust = make_program(pid="b", languages=["Rust"])
        self.assertEqual(apply_filters([solidity, rust], cfg), [solidity])

    def test_whitelist_ecosystems(self):
        cfg = FilterConfig(whitelist_ecosystems=["Ethereum"])
        eth = make_program(ecosystems=["Ethereum", "Arbitrum"])
        sol = make_program(pid="b", ecosystems=["Solana"])
        self.assertEqual(apply_filters([eth, sol], cfg), [eth])

    def test_explain_filter_kyc(self):
        cfg = FilterConfig(include_kyc=False)
        p = make_program(kyc=True)
        self.assertEqual(explain_filter(p, cfg), "KYC required")

    def test_explain_filter_min_bounty(self):
        cfg = FilterConfig(min_bounty=50_000)
        p = make_program(max_bounty=10_000)
        self.assertIn("bounty", explain_filter(p, cfg))

    def test_explain_filter_passes(self):
        cfg = FilterConfig()
        p = make_program()
        self.assertIsNone(explain_filter(p, cfg))

    def test_filter_config_from_dict(self):
        d = {
            "include_kyc": True,
            "min_bounty": 10000,
            "blacklist_keywords": ["x"],
            "whitelist_languages": ["Solidity"],
        }
        cfg = FilterConfig.from_dict(d)
        self.assertTrue(cfg.include_kyc)
        self.assertEqual(cfg.min_bounty, 10000)
        self.assertEqual(cfg.blacklist_keywords, ["x"])
        self.assertEqual(cfg.whitelist_languages, ["Solidity"])


class TestTelegramFormat(unittest.TestCase):
    def test_format_single(self):
        p = make_program(max_bounty=15000000, kyc=True)
        msg = _format_program(p)
        self.assertIn("New Bug Bounty Program", msg)
        self.assertIn("$15.0M", msg)
        self.assertIn("KYC", msg)

    def test_format_includes_in_scope(self):
        p = make_program(in_scope=["LendingPool", "AToken", "StableDebtToken"])
        msg = _format_program(p)
        self.assertIn("In Scope", msg)
        self.assertIn("LendingPool", msg)
        self.assertIn("AToken", msg)

    def test_format_includes_out_of_scope(self):
        p = make_program()
        p.in_scope = []
        p.out_of_scope = ["Frontend", "Docs"]
        msg = _format_program(p)
        self.assertIn("Out of Scope", msg)
        self.assertIn("Frontend", msg)

    def test_format_includes_severity_tiers(self):
        p = make_program()
        p.severity_tiers = ["Critical: $250K", "High: $50K"]
        msg = _format_program(p)
        self.assertIn("Severities", msg)
        self.assertIn("Critical: $250K", msg)

    def test_format_scope_expanded(self):
        p = make_program(in_scope=["A", "B", "C"])
        scope_change = {"added_in_scope": ["C"]}
        msg = _format_program(p, scope_change=scope_change)
        self.assertIn("Scope Expanded", msg)
        self.assertIn("Newly added to scope", msg)
        self.assertIn("C", msg)

    def test_format_batch(self):
        programs = [
            make_program(pid="a", name="A", max_bounty=10000),
            make_program(pid="b", name="B", max_bounty=20000),
            make_program(pid="c", name="C", max_bounty=30000),
        ]
        msgs = _format_batch(programs)
        self.assertGreaterEqual(len(msgs), 1)
        joined = "\n".join(msgs)
        self.assertIn("3 New", joined)
        self.assertIn("A", joined)
        self.assertIn("B", joined)
        self.assertIn("C", joined)

    def test_format_batch_single_uses_single_format(self):
        programs = [make_program(pid="a", name="A")]
        msgs = _format_batch(programs)
        self.assertEqual(len(msgs), 1)
        self.assertIn("New Bug Bounty Program", msgs[0])
        self.assertIn("Platform:", msgs[0])

    def test_format_handles_none_bounty(self):
        p = make_program(max_bounty=None)
        msg = _format_program(p)
        self.assertIn("N/A", msg)

    def test_format_handles_empty_batch(self):
        self.assertEqual(_format_batch([]), [])

    def test_format_batch_splits_long_lists(self):
        programs = [
            make_program(pid=f"p{i:03d}", name=f"Project {i}", max_bounty=i * 1000)
            for i in range(200)
        ]
        msgs = _format_batch(programs)
        for m in msgs:
            self.assertLessEqual(len(m), TELEGRAM_MAX_LEN)
        joined = "\n".join(msgs)
        self.assertIn("Project 0", joined)
        self.assertIn("Project 199", joined)
        self.assertGreater(len(msgs), 1)

    def test_format_in_scope_capped_at_8(self):
        p = make_program(in_scope=[f"Asset{i}" for i in range(20)])
        msg = _format_program(p)
        # Should show 8 + "and N more" indicator
        self.assertIn("and 12 more", msg)


class TestSafeInt(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(safe_int(None))

    def test_empty_string(self):
        self.assertIsNone(safe_int(""))

    def test_whitespace(self):
        self.assertIsNone(safe_int("   "))

    def test_int_passthrough(self):
        self.assertEqual(safe_int(42), 42)

    def test_float_truncates(self):
        self.assertEqual(safe_int(42.7), 42)

    def test_dollar_string(self):
        self.assertEqual(safe_int("$1,000"), 1000)

    def test_plain_string(self):
        self.assertEqual(safe_int("5000"), 5000)

    def test_garbage(self):
        self.assertIsNone(safe_int("not a number"))

    def test_bool_not_treated_as_int(self):
        self.assertEqual(safe_int(True), 1)
        self.assertEqual(safe_int(False), 0)


class TestDetailParser(unittest.TestCase):
    """Unit tests for the detail scraper helpers. No network."""

    def test_after_heading_finds_li(self):
        from monitor.detail import _after_heading
        from bs4 import BeautifulSoup
        html = """
        <h3>Assets in Scope</h3>
        <ul>
            <li>LendingPool</li>
            <li>AToken</li>
            <li>StableDebtToken</li>
        </ul>
        <h3>Out of scope</h3>
        """
        soup = BeautifulSoup(html, "lxml")
        items = _after_heading(soup, ["assets in scope"])
        self.assertEqual(items, ["LendingPool", "AToken", "StableDebtToken"])

    def test_after_heading_filters_exclusion_text(self):
        from monitor.detail import _after_heading
        from bs4 import BeautifulSoup
        html = """
        <h3>Assets in Scope</h3>
        <ul>
            <li>Developers who have worked on this protocol</li>
            <li>LendingPool</li>
            <li>Security auditors who reviewed this</li>
        </ul>
        """
        soup = BeautifulSoup(html, "lxml")
        items = _after_heading(soup, ["assets in scope"])
        self.assertIn("LendingPool", items)
        self.assertNotIn("Developers who have worked on this protocol", items)

    def test_severity_extraction(self):
        from monitor.detail import _extract_severity_tiers
        from bs4 import BeautifulSoup
        html = """
        <p>Critical: $250,000 — bugs that can drain funds</p>
        <p>High: $50,000 — significant impact</p>
        <p>Medium: $10,000 — moderate impact</p>
        """
        soup = BeautifulSoup(html, "lxml")
        tiers = _extract_severity_tiers(soup)
        self.assertEqual(len(tiers), 3)
        self.assertIn("Critical: $250,000", tiers)
        self.assertIn("High: $50,000", tiers)
        self.assertIn("Medium: $10,000", tiers)

    def test_severity_no_dupes(self):
        from monitor.detail import _extract_severity_tiers
        from bs4 import BeautifulSoup
        html = "<p>Critical: $100,000</p><p>Critical: $100,000</p><p>Critical: $200,000</p>"
        soup = BeautifulSoup(html, "lxml")
        tiers = _extract_severity_tiers(soup)
        self.assertEqual(len(tiers), 2)


class TestScrapers(unittest.TestCase):
    """Smoke tests for the scrapers — they need network."""

    @unittest.skipIf(os.environ.get("SKIP_NETWORK"), "network not available")
    def test_immunefi_returns_programs(self):
        from monitor.platforms import ImmunefiScraper
        s = ImmunefiScraper("https://immunefi.com/explore")
        programs = s.run()
        self.assertGreater(len(programs), 100)
        self.assertTrue(all(p.id.startswith("immunefi:") for p in programs))

    @unittest.skipIf(os.environ.get("SKIP_NETWORK"), "network not available")
    def test_bugcrowd_returns_programs(self):
        from monitor.platforms import BugcrowdScraper
        s = BugcrowdScraper("https://bugcrowd.com/engagements.json")
        programs = s.run()
        self.assertGreater(len(programs), 0)
        self.assertTrue(all(p.id.startswith("bugcrowd:") for p in programs))

    @unittest.skipIf(os.environ.get("SKIP_NETWORK"), "network not available")
    def test_yeswehack_returns_programs(self):
        from monitor.platforms import YesWeHackScraper
        s = YesWeHackScraper("https://api.yeswehack.com/programs")
        programs = s.run()
        self.assertGreater(len(programs), 0)
        self.assertTrue(all(p.id.startswith("yeswehack:") for p in programs))

    @unittest.skipIf(os.environ.get("SKIP_NETWORK"), "network not available")
    def test_hackenproof_returns_programs(self):
        from monitor.platforms import HackenProofScraper
        s = HackenProofScraper("https://hackenproof.com/programs")
        programs = s.run()
        self.assertGreater(len(programs), 5)
        self.assertTrue(all(p.id.startswith("hackenproof:") for p in programs))
        bad_ids = {"hackenproof:programs", "hackenproof:weekly", "hackenproof:bounty"}
        self.assertFalse(any(p.id in bad_ids for p in programs))


class TestScraperEdgeCases(unittest.TestCase):
    def test_immunefi_parses_minimal_program(self):
        from monitor.platforms import ImmunefiScraper
        json_obj = (
            '{"contentfulId":"abc123","slug":"foo","url":"/bug-bounty/foo/information/",'
            '"project":"Foo","launchDate":"2024-01-01T00:00:00.000Z",'
            '"updatedDate":"2024-06-01T00:00:00.000Z","kyc":true,'
            '"maxBounty":50000,"logo":"x"}'
        )
        escaped = json_obj.replace('"', '\\"')
        s = ImmunefiScraper("http://example.com")
        programs = s.parse(escaped)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0].id, "immunefi:foo")
        self.assertEqual(programs[0].name, "Foo")
        self.assertEqual(programs[0].max_bounty, 50000)
        self.assertTrue(programs[0].kyc_required)

    def test_immunefi_handles_field_reordering(self):
        from monitor.platforms import ImmunefiScraper
        json_obj = (
            '{"project":"Bar","slug":"bar","contentfulId":"xyz",'
            '"maxBounty":100000,"kyc":false,"url":"/b/bar/",'
            '"logo":"y","launchDate":"2023-01-01","updatedDate":"2023-02-01"}'
        )
        escaped = json_obj.replace('"', '\\"')
        s = ImmunefiScraper("http://example.com")
        programs = s.parse(escaped)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0].name, "Bar")
        self.assertEqual(programs[0].max_bounty, 100000)

    def test_bugcrowd_handles_empty_bounty_strings(self):
        from monitor.platforms import BugcrowdScraper
        raw = json.dumps({
            "engagements": [
                {
                    "name": "Empty Bounty",
                    "briefUrl": "/empty-bounty",
                    "rewardSummary": {"minReward": "", "maxReward": ""},
                    "isDemo": False, "isBanned": False, "isPrivate": False,
                },
                {
                    "name": "Real Bounty",
                    "briefUrl": "/real-bounty",
                    "rewardSummary": {"minReward": "$100", "maxReward": "$5,000"},
                    "isDemo": False, "isBanned": False, "isPrivate": False,
                },
            ]
        })
        s = BugcrowdScraper("http://example.com")
        programs = s.parse(raw)
        self.assertEqual(len(programs), 2)
        self.assertIsNone(programs[0].max_bounty)
        self.assertEqual(programs[1].max_bounty, 5000)

    def test_yeswehack_handles_none_bounty(self):
        from monitor.platforms import YesWeHackScraper
        raw = json.dumps({"items": [
            {"title": "NoBounty", "slug": "no-bounty",
             "bounty_reward_min": None, "bounty_reward_max": None, "type": "bug-bounty"},
            {"title": "HasBounty", "slug": "has-bounty",
             "bounty_reward_min": 100, "bounty_reward_max": 5000, "type": "bug-bounty"},
        ]})
        s = YesWeHackScraper("http://example.com")
        programs = s.parse(raw)
        self.assertEqual(len(programs), 2)
        self.assertIsNone(programs[0].max_bounty)
        self.assertEqual(programs[1].max_bounty, 5000)

    def test_hackenproof_filters_nav_slugs(self):
        from monitor.platforms import HackenProofScraper
        raw = (
            '<a href="/programs/real-program-1">x</a>'
            '<a href="/programs/weekly">x</a>'
            '<a href="/programs/programs">x</a>'
            '<a href="/programs/bounty">x</a>'
            '<a href="/programs/login">x</a>'
            '<a href="/programs/real-program-2/info">x</a>'
        )
        s = HackenProofScraper("http://example.com")
        programs = s.parse(raw)
        ids = {p.id for p in programs}
        self.assertIn("hackenproof:real-program-1", ids)
        self.assertIn("hackenproof:real-program-2", ids)
        self.assertNotIn("hackenproof:weekly", ids)
        self.assertNotIn("hackenproof:programs", ids)
        self.assertNotIn("hackenproof:bounty", ids)


if __name__ == "__main__":
    unittest.main()
