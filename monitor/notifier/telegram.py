"""Telegram notifier."""
from __future__ import annotations

import asyncio
import time
from typing import Iterable

import telegram
from telegram.constants import ParseMode

from ..config import TelegramConfig
from ..state import Program


TELEGRAM_MAX_LEN = 4000


def _format_bounty(amount: int | None) -> str:
    if amount is None:
        return "N/A"
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount // 1_000}K"
    return f"${amount:,}"


def _scope_block(items: list[str], emoji: str, label: str) -> str:
    """Render a list of scope items as a compact block."""
    if not items:
        return ""
    # Cap to 8 items inline to stay under message length
    shown = items[:8]
    more = f"\n  <i>…and {len(items) - 8} more</i>" if len(items) > 8 else ""
    return f"\n{emoji} <b>{label}:</b>\n  " + "\n  ".join(shown) + more


def _format_program(p: Program, scope_change: dict | None = None) -> str:
    """Render a single new/changed program as a Telegram HTML message.

    scope_change, if provided, is the dict returned by
    Program.scope_diff() and adds an additional "scope changed" block
    to the message.
    """
    parts: list[str] = []
    title = "🔔 <b>New Bug Bounty Program Detected</b>"
    if scope_change:
        added = scope_change.get("added_in_scope", [])
        if added:
            title = f"🔔 <b>Scope Expanded: {len(added)} new asset(s)</b>"
        else:
            title = "🔔 <b>Bug Bounty Program Updated</b>"
    parts.append(f"{title}\n")
    parts.append(f"<b>Platform:</b> {p.platform}")
    parts.append(f"<b>Project:</b>  {p.name}")
    parts.append(f"<b>Bounty:</b>   {_format_bounty(p.max_bounty)}")
    if p.kyc_required:
        parts.append(f"<b>KYC:</b>      Required")
    if p.launch_date:
        parts.append(f"<b>Launch:</b>   {p.launch_date[:10]}")
    if p.languages:
        parts.append(f"<b>Languages:</b> {', '.join(p.languages[:5])}")
    if p.ecosystems:
        parts.append(f"<b>Ecosystem:</b> {', '.join(p.ecosystems[:5])}")

    # Scope enrichment
    if p.in_scope:
        parts.append(_scope_block(p.in_scope, "✅", "In Scope"))
    if p.out_of_scope:
        parts.append(_scope_block(p.out_of_scope, "❌", "Out of Scope"))
    if p.severity_tiers:
        parts.append(f"\n💰 <b>Severities:</b> {', '.join(p.severity_tiers[:5])}")

    # Highlight scope changes
    if scope_change:
        added = scope_change.get("added_in_scope", [])
        if added:
            parts.append("\n🆕 <b>Newly added to scope:</b>")
            for item in added[:8]:
                parts.append(f"  • {item}")
            if len(added) > 8:
                parts.append(f"  <i>…and {len(added) - 8} more</i>")

    parts.append(f"\n<b>URL:</b>      {p.url}")
    return "\n".join(parts)


def _format_batch(programs: list[Program]) -> list[str]:
    """Render a batch of new programs as one or more Telegram messages."""
    if not programs:
        return []
    if len(programs) == 1:
        return [_format_program(programs[0])]

    header = f"🔔 <b>{len(programs)} New Bug Bounty Programs Detected</b>\n"
    chunks: list[str] = [header]
    cur = header

    for i, p in enumerate(programs, 1):
        bounty = _format_bounty(p.max_bounty) if p.max_bounty is not None else "N/A"
        kyc = " (KYC)" if p.kyc_required else ""
        block = (
            f"<b>{i}. {p.name}</b> — {p.platform}{kyc}\n"
            f"   {bounty} • {p.url}"
        )
        if len(cur) + len(block) + 2 > TELEGRAM_MAX_LEN:
            chunks.append(cur.rstrip())
            cur = block
        else:
            cur = cur + "\n\n" + block if cur != header else block

    if cur and cur != header:
        chunks.append(cur.rstrip())

    return chunks


class TelegramNotifier:
    def __init__(self, cfg: TelegramConfig):
        self.cfg = cfg
        self._bot: telegram.Bot | None = None

    def _ensure_bot(self) -> telegram.Bot:
        if self._bot is None:
            self._bot = telegram.Bot(token=self.cfg.bot_token)
        return self._bot

    async def _send(self, text: str) -> bool:
        bot = self._ensure_bot()
        try:
            if len(text) > TELEGRAM_MAX_LEN:
                text = text[: TELEGRAM_MAX_LEN - 20] + "\n\n[truncated]"
            await bot.send_message(
                chat_id=self.cfg.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=self.cfg.disable_web_page_preview,
            )
            return True
        except telegram.error.TelegramError as e:
            print(f"[telegram] error: {e}")
            return False

    async def send_message(self, text: str) -> bool:
        if len(text) > TELEGRAM_MAX_LEN:
            text = text[: TELEGRAM_MAX_LEN - 20] + "\n\n[truncated]"
        return await self._send(text)

    async def send_programs(self, programs: list[Program]) -> bool:
        if not programs:
            return True
        chunks = _format_batch(programs)
        if not chunks:
            return True
        for i, chunk in enumerate(chunks):
            ok = await self._send(chunk)
            if not ok:
                return False
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)
        return True

    async def send_test(self) -> bool:
        return await self._send(
            "✅ <b>Bug Bounty Monitor</b>\n\n"
            "Telegram notifier is configured correctly. You will receive notifications here when new programs are detected."
        )

    def send_programs_sync(self, programs: list[Program]) -> bool:
        return asyncio.run(self.send_programs(programs))

    def send_test_sync(self) -> bool:
        return asyncio.run(self.send_test())
