"""Telegram command handlers — interactive bot mode.

Supported commands (all reply to the chat that sent them):
  /start       — welcome + status
  /help        — list commands
  /status      — show state, last check, enabled platforms
  /list [N]    — show last N (default 10) tracked programs
  /search X    — search tracked programs by name
  /now         — trigger an immediate check (alias for cmd_check)
  /mute <plat> — disable notifications for a platform
  /unmute <plat>
  /muted       — show muted platforms
  /filters     — show current filter config
  /set kyc on|off
  /set min_bounty <N>
  /set launch_within_days <N>
  /seen <id>   — mark a tracked program id as seen (drops from diff)
  /refresh     — re-check all enabled platforms now
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable

import telegram
from telegram import Update
from telegram.ext import ContextTypes

from ..filters import explain_filter
from ..state import Program

if TYPE_CHECKING:
    from ..config import Config
    from ..state import State

log = logging.getLogger(__name__)


def _format_prog_line(p: Program) -> str:
    bounty = f"${p.max_bounty:,}" if p.max_bounty else "N/A"
    kyc = " [KYC]" if p.kyc_required else ""
    return f"• <b>{p.name}</b> — {bounty}{kyc}\n  <code>{p.id}</code>"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>Bug Bounty Monitor</b>\n\n"
        "I'll notify you when new programs appear on the platforms you follow.\n\n"
        "Commands:\n"
        "/status — show state\n"
        "/list [N] — recent programs\n"
        "/search X — search by name\n"
        "/now — trigger immediate check\n"
        "/filters — show filter config\n"
        "/set kyc on|off\n"
        "/set min_bounty <N>\n"
        "/set launch_within_days <N>\n"
        "/mute &lt;platform&gt;\n"
        "/unmute &lt;platform&gt;\n"
        "/muted — show muted platforms\n"
        "/refresh — re-check all platforms\n"
        "/help — show this list"
    )
    await update.message.reply_text(text, parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["cfg"]
    state: State = context.bot_data["state"]

    enabled = cfg.list_enabled_platforms()
    muted = sorted(state.muted)
    last = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state.last_check_ts))
        if state.last_check_ts
        else "never"
    )

    lines = [
        f"<b>Total tracked:</b> {state.count()} programs",
        f"<b>Last check:</b> {last}",
        f"<b>Enabled platforms:</b> {len(enabled)}",
    ]
    for p in enabled:
        marker = "🔕" if state.is_muted(p) else "✓"
        lines.append(f"  {marker} {p}")
    if muted:
        lines.append(f"\n<b>Muted:</b> {', '.join(muted)}")

    # Show current filters
    f = cfg.filters
    f_lines = [
        f"<b>Filters:</b>",
        f"  • include_kyc: {f.include_kyc}",
        f"  • min_bounty: {f.min_bounty}",
        f"  • launch_within_days: {f.launch_within_days}",
    ]
    if f.blacklist_keywords:
        f_lines.append(f"  • blacklist: {', '.join(f.blacklist_keywords)}")
    if f.whitelist_languages:
        f_lines.append(f"  • whitelist_languages: {', '.join(f.whitelist_languages)}")
    if f.whitelist_ecosystems:
        f_lines.append(f"  • whitelist_ecosystems: {', '.join(f.whitelist_ecosystems)}")
    lines.append("\n" + "\n".join(f_lines))

    await update.message.reply_text("\n".join(lines), parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    args = context.args or []
    n = 10
    if args and args[0].isdigit():
        n = min(int(args[0]), 50)

    # Sort by launch date desc, fallback to name
    progs = sorted(
        state.seen.values(),
        key=lambda p: (p.launch_date or "", p.name),
        reverse=True,
    )[:n]

    if not progs:
        await update.message.reply_text("No programs tracked yet. Run /init or /now.")
        return
    text = f"<b>Last {len(progs)} tracked programs:</b>\n\n" + "\n".join(_format_prog_line(p) for p in progs)
    await update.message.reply_text(text, parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    if not context.args:
        await update.message.reply_text("Usage: /search <name fragment>")
        return
    q = " ".join(context.args).lower()
    matches = [p for p in state.seen.values() if q in p.name.lower()][:20]
    if not matches:
        await update.message.reply_text(f"No matches for '{q}'.")
        return
    text = f"<b>{len(matches)} match(es) for '{q}':</b>\n\n" + "\n".join(_format_prog_line(p) for p in matches)
    await update.message.reply_text(text, parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    check_fn: Callable[[], Awaitable[None]] = context.bot_data["check_fn"]
    await update.message.reply_text("⏳ Running check…")
    try:
        await check_fn()
        await update.message.reply_text("✓ Check complete.")
    except Exception as e:
        await update.message.reply_text(f"✗ Check failed: {e}")


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_now(update, context)


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    cfg: Config = context.bot_data["cfg"]
    if not context.args:
        await update.message.reply_text("Usage: /mute <platform>\nKnown: " + ", ".join(cfg.list_enabled_platforms()))
        return
    name = context.args[0].lower()
    if name not in {p.lower() for p in cfg.list_enabled_platforms()}:
        await update.message.reply_text(f"Unknown platform: {name}")
        return
    state.mute(name)
    state.save()
    await update.message.reply_text(f"🔕 Muted <b>{name}</b> — no more notifications from it.", parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    if not context.args:
        await update.message.reply_text("Usage: /unmute <platform>")
        return
    name = context.args[0].lower()
    if not state.is_muted(name):
        await update.message.reply_text(f"{name} is not muted.")
        return
    state.unmute(name)
    state.save()
    await update.message.reply_text(f"🔔 Unmuted <b>{name}</b>.", parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_muted(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    if not state.muted:
        await update.message.reply_text("No platforms muted.")
        return
    await update.message.reply_text("Muted platforms:\n• " + "\n• ".join(sorted(state.muted)))


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["cfg"]
    f = cfg.filters
    lines = ["<b>Active filters:</b>"]
    lines.append(f"  • include_kyc: <b>{f.include_kyc}</b>")
    lines.append(f"  • min_bounty: <b>{f.min_bounty}</b>")
    lines.append(f"  • launch_within_days: <b>{f.launch_within_days}</b>")
    if f.blacklist_keywords:
        lines.append(f"  • blacklist: {', '.join(f.blacklist_keywords)}")
    if f.whitelist_languages:
        lines.append(f"  • whitelist_languages: {', '.join(f.whitelist_languages)}")
    if f.whitelist_ecosystems:
        lines.append(f"  • whitelist_ecosystems: {', '.join(f.whitelist_ecosystems)}")
    if all(not getattr(f, a) for a in ("blacklist_keywords", "whitelist_languages", "whitelist_ecosystems")) and f.min_bounty == 0 and f.launch_within_days == 0 and not f.include_kyc:
        lines.append("\n<i>No filters active — every new program will be notified.</i>")
    lines.append("\n<b>Examples of recent programs that would be filtered:</b>")

    # Show 3 examples of programs that would be filtered out, with reason
    state: State = context.bot_data["state"]
    examples = []
    for p in list(state.seen.values())[:200]:
        reason = explain_filter(p, f)
        if reason:
            examples.append((p, reason))
            if len(examples) >= 5:
                break
    if examples:
        for p, r in examples:
            lines.append(f"  • <b>{p.name}</b> — <i>{r}</i>")
    else:
        lines.append("  <i>No examples (state empty or all pass filters).</i>")
    await update.message.reply_text("\n".join(lines), parse_mode=telegram.constants.ParseMode.HTML)


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["cfg"]
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/set kyc on|off\n"
            "/set min_bounty <N>\n"
            "/set launch_within_days <N>\n"
            "/set blacklist add|remove <keyword>\n"
            "/set whitelist_languages add|remove <lang>\n"
            "/set whitelist_ecosystems add|remove <eco>"
        )
        return
    key = context.args[0].lower()
    val = " ".join(context.args[1:])
    f = cfg.filters

    if key == "kyc":
        f.include_kyc = val.lower() in ("on", "true", "1", "yes")
    elif key == "min_bounty":
        try:
            f.min_bounty = int(val)
        except ValueError:
            await update.message.reply_text("min_bounty must be an integer")
            return
    elif key == "launch_within_days":
        try:
            f.launch_within_days = int(val)
        except ValueError:
            await update.message.reply_text("launch_within_days must be an integer")
            return
    elif key in ("blacklist", "whitelist_languages", "whitelist_ecosystems"):
        parts = val.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(f"Usage: /set {key} add|remove <value>")
            return
        op, item = parts
        target = getattr(f, key)
        if op == "add":
            if item not in target:
                target.append(item)
        elif op == "remove":
            if item in target:
                target.remove(item)
        else:
            await update.message.reply_text(f"Unknown op '{op}' — use add or remove")
            return
    else:
        await update.message.reply_text(f"Unknown setting '{key}'")
        return

    cfg.save()
    await update.message.reply_text(f"✓ Updated {key}.")


async def cmd_seen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: State = context.bot_data["state"]
    if not context.args:
        await update.message.reply_text("Usage: /seen <program_id>")
        return
    pid = " ".join(context.args)
    if pid in state.seen:
        # Mark as seen (refresh hash so it doesn't re-notify)
        state.hashes[pid] = state.seen[pid].content_hash()
        state.save()
        await update.message.reply_text(f"✓ Marked <code>{pid}</code> as seen.", parse_mode=telegram.constants.ParseMode.HTML)
    else:
        # Try fuzzy match by name
        matches = [p for p in state.seen.values() if pid.lower() in p.name.lower()][:5]
        if matches:
            ids = "\n".join(p.id for p in matches)
            await update.message.reply_text(f"Unknown id. Did you mean:\n{ids}")
        else:
            await update.message.reply_text(f"Unknown id: {pid}")


def register_handlers(app, cfg: "Config", state: "State", check_fn) -> None:
    """Register all command handlers on a python-telegram-bot Application."""
    # Stash shared state in bot_data so handlers can access it
    app.bot_data["cfg"] = cfg
    app.bot_data["state"] = state
    app.bot_data["check_fn"] = check_fn

    app.add_handler(telegram.ext.CommandHandler("start", cmd_start))
    app.add_handler(telegram.ext.CommandHandler("help", cmd_help))
    app.add_handler(telegram.ext.CommandHandler("status", cmd_status))
    app.add_handler(telegram.ext.CommandHandler("list", cmd_list))
    app.add_handler(telegram.ext.CommandHandler("search", cmd_search))
    app.add_handler(telegram.ext.CommandHandler("now", cmd_now))
    app.add_handler(telegram.ext.CommandHandler("refresh", cmd_refresh))
    app.add_handler(telegram.ext.CommandHandler("mute", cmd_mute))
    app.add_handler(telegram.ext.CommandHandler("unmute", cmd_unmute))
    app.add_handler(telegram.ext.CommandHandler("muted", cmd_muted))
    app.add_handler(telegram.ext.CommandHandler("filters", cmd_filters))
    app.add_handler(telegram.ext.CommandHandler("set", cmd_set))
    app.add_handler(telegram.ext.CommandHandler("seen", cmd_seen))
