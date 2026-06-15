"""Bot runner — runs the Telegram bot with command handlers + scheduled checks.

This is the interactive mode. It keeps a long-polling bot alive and
schedules a check job at the configured interval. The same check
logic as the CLI's --check is used, so behavior is identical.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import telegram
from telegram.ext import Application, ApplicationBuilder

from ..detail import enrich_program
from ..filters import apply_filters
from ..notifier.telegram import _format_batch
from ..platforms import get_scraper
from . import commands

if TYPE_CHECKING:
    from ..config import Config
    from ..state import State

log = logging.getLogger(__name__)


async def run_bot(cfg: "Config", state: "State", interval: int) -> None:
    """Build the bot, register handlers, schedule checks, and run forever."""
    if not cfg.telegram.is_configured():
        raise RuntimeError("Telegram is not configured. Set telegram.bot_token and telegram.chat_id.")

    app: Application = (
        ApplicationBuilder()
        .token(cfg.telegram.bot_token)
        .build()
    )

    async def check_and_notify() -> None:
        """Single check cycle — fetch, diff, enrich, filter, notify."""
        try:
            new_programs = await _run_check(cfg, state)
            if new_programs:
                chat_id = cfg.telegram.chat_id
                chunks = _format_batch(new_programs)
                for chunk in chunks:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode=telegram.constants.ParseMode.HTML,
                            disable_web_page_preview=cfg.telegram.disable_web_page_preview,
                        )
                        await asyncio.sleep(0.5)
                    except telegram.error.TelegramError as e:
                        log.error("telegram send failed: %s", e)
        except Exception as e:
            log.exception("check cycle failed: %s", e)

    commands.register_handlers(app, cfg, state, check_and_notify)

    # Schedule the check — first run after 5s, then every `interval` seconds
    app.job_queue.run_repeating(
        callback=_job_wrapper(check_and_notify),
        interval=interval,
        first=5,
    )

    log.info("Starting bot (interval=%ds, chat=%s)", interval, cfg.telegram.chat_id)
    async with app:
        await app.start()
        await app.updater.start_polling()
        # Block forever
        await asyncio.Event().wait()


def _job_wrapper(coro_fn):
    """Wrap an async function so the job queue can call it (it expects a coroutine, not a coroutine-returning function)."""
    async def _wrap(context):
        await coro_fn()
    return _wrap


async def _run_check(cfg: "Config", state: "State") -> list:
    """Run one full check cycle. Returns the list of new programs to notify about."""
    selected = [
        p for p in cfg.list_enabled_platforms()
        if not state.is_muted(p)
    ]
    if not selected:
        log.info("no enabled unmuted platforms, skipping check")
        return []

    # Fetch all platforms
    results = []
    for name in selected:
        url = cfg.platform_url(name)
        if not url:
            continue
        try:
            scraper = get_scraper(
                name, url,
                timeout=cfg.request.timeout_seconds,
                user_agent=cfg.request.user_agent,
            )
            programs = scraper.run()
            results.extend(programs)
        except Exception as e:
            log.error("scraper %s failed: %s", name, e)

    # Diff
    new = state.diff(results)

    # Enrich new programs with detail (scope, etc.)
    if cfg.enrichment.enabled and new:
        for p in new:
            if p.id not in state.seen:
                # Only fetch detail for genuinely new programs (not updates)
                enrich_program(p, timeout=cfg.enrichment.fetch_timeout, user_agent=cfg.request.user_agent)

    # Compute scope changes for known programs
    scope_changes = {}
    for p in new:
        if p.id in state.seen:
            old = state.seen[p.id]
            if old.in_scope or old.out_of_scope:
                change = old.scope_diff(p)
                if change:
                    scope_changes[p.id] = change
                    # Enrich the new version
                    enrich_program(p, timeout=cfg.enrichment.fetch_timeout, user_agent=cfg.request.user_agent)

    # Apply filters
    filtered = apply_filters(new, cfg.filters)

    # Save state BEFORE sending notifications
    state.mark_seen(new)
    state.save()

    return filtered
