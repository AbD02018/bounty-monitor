# Bug Bounty Monitor

Monitor new bug-bounty programs across 7 public platforms and get notified on
Telegram when something new appears. Includes filters, scope enrichment, and
an interactive bot mode for managing everything from your phone.

## Features

- **7 platforms**: HackerOne, Bugcrowd, Immunefi, YesWeHack, HackenProof, BugRap, Integrity
- **Telegram notifications** with new-program + scope-change detection
- **Interactive bot mode** (`/status`, `/list`, `/mute`, `/filters`, `/now`, `/set`, ...)
- **Program enrichment**: fetches detail pages to extract in-scope assets, out-of-scope, severity tiers
- **Filters**: KYC toggle, min bounty, age limit, language/ecosystem whitelist, keyword blacklist
- **State persistence**: atomic writes, recoverable from corruption
- **HTTP retry**: exponential backoff on transient errors
- **65 tests**, atomic state writes, scope-change notifications

## Quick start

```bash
cd /root/projects/bounty-monitor
pip install -r requirements.txt

cp config.example.json config.json
# Edit config.json: set telegram.bot_token and telegram.chat_id
#   - Get a bot token: @BotFather on Telegram → /newbot
#   - Get your chat id: send /start to your bot, then visit
#     https://api.telegram.org/bot<TOKEN>/getUpdates

# 1. Build the baseline (no notifications)
python -m monitor --init

# 2. Test Telegram
python -m monitor --test

# 3. Run a one-shot check
python -m monitor --check

# 4. Run continuously (every 30 min)
python -m monitor --watch

# 5. OR: run the interactive bot (recommended)
python -m monitor --bot
```

## CLI

```
python -m monitor [OPTIONS]

  --check              Run one check, notify for new programs
  --watch              Run continuously, polling every --interval seconds
  --bot                Run interactive Telegram bot (commands + scheduled checks)
  --init               Snapshot current programs (no notifications)
  --test               Send a test message to Telegram
  --status             Show current state without making any changes

  --platforms X,Y      Only check specific platforms
  --interval N         Watch/bot interval in seconds (default 1800 = 30 min)
  --state PATH         Path to state file
  --config PATH        Path to config file
  --no-enrich          Skip detail-page enrichment (faster, no scope info)
  --verbose, -v        Verbose output
```

## Bot mode commands

When running `python -m monitor --bot`, you can interact with the bot on
Telegram:

| Command | Description |
|---|---|
| `/start` | Welcome + command list |
| `/status` | Show state, last check, enabled platforms, current filters |
| `/list [N]` | Show last N (default 10) tracked programs |
| `/search <name>` | Search tracked programs by name |
| `/now` | Trigger an immediate check |
| `/refresh` | Alias for `/now` |
| `/mute <platform>` | Disable notifications for a platform (persists across restarts) |
| `/unmute <platform>` | Re-enable notifications |
| `/muted` | Show muted platforms |
| `/filters` | Show current filter config + examples of filtered programs |
| `/set kyc on\|off` | Toggle KYC filter |
| `/set min_bounty <N>` | Set minimum bounty floor |
| `/set launch_within_days <N>` | Set max program age |
| `/set blacklist add\|remove <kw>` | Manage keyword blacklist |
| `/set whitelist_languages add\|remove <lang>` | Manage language whitelist |
| `/set whitelist_ecosystems add\|remove <eco>` | Manage ecosystem whitelist |
| `/seen <id>` | Mark a tracked program as seen |
| `/help` | Show command list |

## Configuration

### `telegram`
```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": "YOUR_CHAT_ID",
  "parse_mode": "HTML",
  "disable_web_page_preview": false
}
```

### `platforms`
Each platform has an `enabled` flag and a `url`. HackerOne, BugRap, and
Integrity are disabled by default (require auth or JS rendering).

### `filters`
```json
{
  "include_kyc": false,            // Set true to keep KYC-required programs
  "min_bounty": 0,                  // Drop programs below this USD
  "launch_within_days": 0,          // Drop programs older than N days (0 = no limit)
  "blacklist_keywords": [],         // Drop programs matching any keyword (case-insensitive)
  "whitelist_languages": [],        // Only notify if program uses one of these languages
  "whitelist_ecosystems": []        // Only notify if program targets one of these ecosystems
}
```

### `enrichment`
```json
{
  "enabled": true,            // Fetch detail pages for scope info
  "fetch_timeout": 15,        // Per-detail-page timeout
  "cache_hours": 24           // How long to remember scope info
}
```

## Notification format

A new-program notification looks like:

```
🔔 New Bug Bounty Program Detected

Platform:     Immunefi
Project:      NewProtocol
Bounty:       $500K
Launch:       2026-06-15
KYC:          Required
Languages:    Solidity
Ecosystem:    Ethereum

✅ In Scope:
  LendingPool
  LiquidationManager
  PriceOracle

❌ Out of Scope:
  Frontend
  Documentation

💰 Severities: Critical: $250K, High: $50K

URL: https://immunefi.com/...
```

A scope-change notification looks like:

```
🔔 Scope Expanded: 2 new asset(s)

Platform:     Immunefi
Project:      Aave
…

🆕 Newly added to scope:
  • GHO Facilitator V2
  • Cross-chain Bridge V2

URL: https://immunefi.com/...
```

## Architecture

```
monitor/
├── __main__.py             # CLI entrypoint
├── config.py               # Config loader + FilterConfig
├── state.py                # State persistence (atomic writes)
├── filters.py              # Filter logic
├── detail.py               # Detail-page scrapers (scope extraction)
├── platforms/              # One scraper per platform
│   ├── base.py             # Base with HTTP retry
│   ├── immunefi.py         # JSON parser for RSC
│   ├── bugcrowd.py
│   ├── yeswehack.py
│   ├── hackenproof.py
│   ├── hackerone.py        # Stub (requires auth)
│   ├── bugrap.py           # Stub (JS-rendered)
│   └── integrity.py        # Stub (URL unconfirmed)
├── notifier/
│   ├── telegram.py         # Notification format + sender
│   ├── commands.py         # Bot command handlers
│   └── runner.py           # Bot runner (long-polling + job queue)
└── tests/
    └── test_monitor.py     # 65 tests
```

## State file format

```json
{
  "seen": {
    "immunefi:aave": { /* full Program */ },
    ...
  },
  "hashes": {
    "immunefi:aave": "sha256-prefix"
  },
  "muted": ["bugcrowd"],
  "last_check_ts": 1718443200.0
}
```

Atomic writes: writes go to `state.json.tmp`, then `os.replace()` renames
to `state.json`. Safe to interrupt at any point.

## Tests

```bash
# All tests (requires network)
python -m unittest discover tests/

# Skip network tests
SKIP_NETWORK=1 python -m unittest discover tests/
```

65 tests cover: state persistence, filter logic, notification format, scope
diff detection, Telegram batching, scraper edge cases, detail parsers,
muted-platform persistence, atomic saves, corrupt-state recovery.

## Limitations

- **HackerOne/BugRap/Integrity**: require auth or JS rendering. The scrapers
  exist as best-effort stubs and may return nothing.
- **Immunefi scope parsing**: Immunefi's detail pages use a complex layout
  where asset names are sometimes inline text rather than `<li>` elements.
  The parser tries 3 strategies (list, inline, GitHub-URL fallback) and
  returns what it can find. The notifications will always include a link
  to the detail page so you can verify.
- **Cross-platform dedup**: a project on both Immunefi and Bugcrowd will
  produce 2 notifications. Deduplication is a planned feature.
- **HackerOne authentication**: required for the full program directory.
  Add a token to your config to enable (not implemented yet).

## Recommended workflow

1. `python -m monitor --init` — baseline
2. `python -m monitor --bot --interval 1800` — start bot (30-min check)
3. From Telegram: `/filters` then `/set min_bounty 50000` to filter noise
4. `/list` to browse tracked programs
5. `/now` to trigger an immediate check after coming back
