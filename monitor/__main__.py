"""CLI entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import Config
from .detail import enrich_program
from .filters import apply_filters
from .notifier import TelegramNotifier
from .notifier.telegram import _format_batch
from .platforms import PLATFORMS, get_scraper
from .state import Program, State

console = Console()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bounty-monitor",
        description="Monitor new bug-bounty programs on 7 public platforms and notify via Telegram.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Run one check, notify for new programs")
    mode.add_argument("--watch", action="store_true", help="Run continuously in CLI mode (polling every --interval seconds)")
    mode.add_argument("--bot", action="store_true", help="Run interactive Telegram bot with command handlers + scheduled checks")
    mode.add_argument("--init", action="store_true", help="Snapshot current programs (no notifications)")
    mode.add_argument("--test", action="store_true", help="Send a test message to Telegram")
    mode.add_argument("--status", action="store_true", help="Show current state without making any changes")

    p.add_argument("--platforms", help="Only check specific platforms (comma-separated)")
    p.add_argument("--interval", type=int, default=1800, help="Watch/bot interval in seconds (default 1800 = 30 min)")
    p.add_argument("--state", default="./state.json", help="Path to state file")
    p.add_argument("--config", default="./config.json", help="Path to config file")
    p.add_argument("--no-enrich", action="store_true", help="Skip detail-page enrichment (faster, no scope info)")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    return p.parse_args(argv)


def load_config(path: str) -> Config:
    try:
        return Config.load(path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {path}[/red]")
        console.print("Copy config.example.json to config.json and edit.")
        sys.exit(1)


def cmd_status(cfg: Config, state: State) -> None:
    table = Table(title="Bug Bounty Monitor — Status")
    table.add_column("Platform", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Muted", style="yellow")
    table.add_column("URL", style="dim")
    for name in cfg.list_enabled_platforms():
        url = cfg.platform_url(name)
        muted = "🔕" if state.is_muted(name) else ""
        table.add_row(name, "✓", muted, url)
    table.add_row("...", "", "", "")
    table.add_row("Total tracked", str(state.count()), "", "")
    last = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(state.last_check_ts))
        if state.last_check_ts else "never"
    )
    table.add_row("Last check", last, "", "")
    f = cfg.filters
    table.add_row("Filters", f"min_bounty={f.min_bounty} | kyc={f.include_kyc} | age≤{f.launch_within_days}d", "", "")
    console.print(table)


def fetch_all(cfg: Config, state: State, platforms: list[str] | None = None) -> dict[str, list[Program]]:
    """Run all enabled unmuted scrapers in sequence. Returns platform -> programs."""
    selected = platforms or cfg.list_enabled_platforms()
    results: dict[str, list[Program]] = {}
    for name in selected:
        if not cfg.platform_enabled(name):
            console.print(f"[yellow]  · {name}: disabled in config, skipping[/yellow]")
            continue
        if state.is_muted(name):
            console.print(f"[dim]  · {name}: muted, skipping[/dim]")
            continue
        url = cfg.platform_url(name)
        if not url:
            console.print(f"[yellow]  · {name}: no URL configured, skipping[/yellow]")
            continue
        try:
            scraper = get_scraper(name, url, timeout=cfg.request.timeout_seconds,
                                  user_agent=cfg.request.user_agent)
            t0 = time.time()
            programs = scraper.run()
            elapsed = time.time() - t0
            results[name] = programs
            console.print(f"[green]  · {name}:[/green] {len(programs)} programs ({elapsed:.1f}s)")
        except Exception as e:
            console.print(f"[red]  · {name}: error: {e}[/red]")
            results[name] = []
        if cfg.request.delay_between_platforms_seconds > 0:
            time.sleep(cfg.request.delay_between_platforms_seconds)
    return results


def cmd_init(cfg: Config, state: State, enrich: bool = True) -> None:
    console.print("[bold]Initializing baseline (this may take a minute)...[/bold]")
    results = fetch_all(cfg, state)
    total_new = 0
    for name, programs in results.items():
        added = state.snapshot(programs)
        total_new += len(added)
        console.print(f"  [cyan]{name}[/cyan]: {len(programs)} programs, {len(added)} new")
    state.save()
    console.print(f"\n[green]✓ Snapshot complete.[/green] {state.count()} programs tracked.")


def cmd_check(cfg: Config, state: State, notifier: TelegramNotifier | None, enrich: bool = True) -> int:
    console.print("[bold]Checking for new programs...[/bold]")
    results = fetch_all(cfg, state)

    all_new: list[Program] = []
    for name, programs in results.items():
        new = state.diff(programs)
        all_new.extend(new)
        if new:
            console.print(f"  [green]{name}[/green]: {len(new)} new/updated program(s)")

    if not all_new:
        console.print("\n[green]✓ No new programs.[/green]")
        return 0

    # Enrich new programs with detail page (scope, etc.)
    if enrich and cfg.enrichment.enabled:
        from .enrich_bridge import smart_enrich
        for p in all_new:
            if p.id not in state.seen:
                # smart_enrich picks native vs extractor based on platform
                smart_enrich(p, timeout=cfg.enrichment.fetch_timeout)

    # Apply filters
    filtered = apply_filters(all_new, cfg.filters)
    skipped = len(all_new) - len(filtered)
    if skipped:
        console.print(f"  [yellow]({skipped} filtered out)[/yellow]")

    if not filtered:
        # Still mark them as seen so we don't re-notify
        state.mark_seen(all_new)
        state.save()
        console.print("\n[green]✓ No new programs (all filtered).[/green]")
        return 0

    console.print(f"\n[bold]Found {len(filtered)} new/updated program(s):[/bold]")
    for p in filtered[:10]:
        bounty = f"${p.max_bounty:,}" if p.max_bounty else "N/A"
        kyc = " [KYC]" if p.kyc_required else ""
        console.print(f"  • [cyan]{p.platform}[/cyan] {p.name} — {bounty}{kyc} — {p.url}")
    if len(filtered) > 10:
        console.print(f"  ... and {len(filtered) - 10} more")

    # CRITICAL: save state BEFORE attempting Telegram notification.
    state.mark_seen(all_new)
    state.save()

    if notifier is not None:
        ok = notifier.send_programs_sync(filtered)
        if ok:
            console.print(f"\n[green]✓ Telegram notification sent.[/green]")
        else:
            console.print(f"\n[red]✗ Telegram notification failed.[/red]")
            console.print("[yellow]  (State was saved — won't re-notify, but check bot/chat config)[/yellow]")
    else:
        console.print("\n[yellow]Telegram notifier not configured (set telegram.bot_token and telegram.chat_id).[/yellow]")

    return 0


def cmd_test(cfg: Config) -> None:
    if not cfg.telegram.is_configured():
        console.print("[red]Telegram not configured. Set telegram.bot_token and chat_id in config.json[/red]")
        sys.exit(1)
    notifier = TelegramNotifier(cfg.telegram)
    ok = notifier.send_test_sync()
    if ok:
        console.print("[green]✓ Test message sent to Telegram.[/green]")
    else:
        console.print("[red]✗ Failed to send test message. Check your bot token and chat id.[/red]")
        sys.exit(1)


def cmd_watch(cfg: Config, state: State, notifier: TelegramNotifier | None, interval: int, enrich: bool) -> None:
    console.print(f"[bold]Watching every {interval}s — Ctrl+C to stop[/bold]")
    stop = {"flag": False}

    def handle_sigint(*_):
        console.print("\n[yellow]Stopping...[/yellow]")
        stop["flag"] = True
    signal.signal(signal.SIGINT, handle_sigint)

    iteration = 0
    while not stop["flag"]:
        iteration += 1
        console.print(f"\n[dim]--- Check #{iteration} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---[/dim]")
        try:
            cmd_check(cfg, state, notifier, enrich=enrich)
        except Exception as e:
            console.print(f"[red]Error during check: {e}[/red]")
        if stop["flag"]:
            break
        slept = 0
        while slept < interval and not stop["flag"]:
            time.sleep(min(5, interval - slept))
            slept += 5


def cmd_bot(cfg: Config, state: State, interval: int) -> None:
    """Start the interactive Telegram bot."""
    from .notifier.runner import run_bot
    asyncio.run(run_bot(cfg, state, interval))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    state = State(args.state)
    enrich = not args.no_enrich

    if args.status:
        cmd_status(cfg, state)
        return 0
    if args.test:
        cmd_test(cfg)
        return 0
    if args.init:
        cmd_init(cfg, state, enrich=enrich)
        return 0
    if args.bot:
        if not cfg.telegram.is_configured():
            console.print("[red]Telegram not configured. Set telegram.bot_token and chat_id.[/red]")
            return 1
        cmd_bot(cfg, state, args.interval)
        return 0

    notifier = TelegramNotifier(cfg.telegram) if cfg.telegram.is_configured() else None
    if notifier is None and not args.init:
        console.print("[yellow]Telegram not configured — notifications will be skipped.[/yellow]")

    platforms = [p.strip() for p in args.platforms.split(",")] if args.platforms else None

    if args.check:
        return cmd_check(cfg, state, notifier, enrich=enrich)
    if args.watch:
        cmd_watch(cfg, state, notifier, args.interval, enrich=enrich)
        return 0

    # No mode specified — show help
    parse_args(["--help"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
