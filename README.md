<div align="center">

# 📡 bounty-monitor

### *Real-time bug bounty program monitor across 7 platforms.*

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Platforms](https://img.shields.io/badge/platforms-7-blueviolet?style=flat-square)](#-supported-platforms)
[![Status](https://img.shields.io/badge/status-active-success?style=flat-square)]()
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

</div>

---

## 🎯 Why

New bug bounty programs drop daily. New scope expansions. New high-TVL launches. Manually checking 7 platforms every morning is wasted time.

**bounty-monitor** watches all 7 platforms, filters by your criteria (chain, TVL, bounty size, audit status), and notifies you on Telegram / Discord / Slack the moment something matches.

---

## ✨ Features

- 🔍 **7 platforms monitored** — HackerOne, Immunefi, Cantina, Bugcrowd, YesWeHack, Bugrap, HackenProof
- 🎯 **Custom filters** — chain, TVL, bounty tier, audit status, scope keywords
- 📲 **Multi-channel notifications** — Telegram, Discord, Slack, email, webhook
- ⏰ **Real-time + scheduled** — Cron mode (every 15 min) + on-demand
- 📊 **Program diff** — Detects new programs, scope changes, bounty changes
- 💾 **SQLite cache** — Never notify twice for the same change
- 🐳 **Docker-ready** — One-line deployment

---

## 📦 Installation

```bash
pip install bounty-monitor
```

### From source

```bash
git clone https://github.com/AbD02018/bounty-monitor
cd bounty-monitor
pip install -e .
```

---

## 🚀 Quick Start

```bash
# Initialize config
bounty-monitor init

# Edit ~/.config/bounty-monitor/config.yaml with your filters + notification channels

# Run once
bounty-monitor run

# Run as daemon (every 15 min)
bounty-monitor daemon --interval 15m

# Show current programs matching your filters
bounty-monitor list --filter "tvl>=10M" --filter "chain=ethereum"
```

---

## 🏢 Supported Platforms

| Platform | Programs Tracked | Update Frequency |
|---|---|---|
| 🟢 HackerOne | ~3,500 | 15 min |
| 🔴 Immunefi | ~250 | 30 min |
| 🟣 Cantina | ~80 | 60 min |
| 🔵 Bugcrowd | ~1,200 | 15 min |
| 🟠 YesWeHack | ~600 | 15 min |
| ⚪ Bugrap | ~400 | 30 min |
| 🟡 HackenProof | ~150 | 30 min |

---

## ⚙️ Filter Examples

```yaml
# ~/.config/bounty-monitor/config.yaml

filters:
  - name: "high-tvl-eth"
    chains: [ethereum, arbitrum, base, optimism]
    min_tvl_usd: 10_000_000
    min_max_bounty_usd: 50_000

  - name: "smart-contract-audits"
    scope: smart-contract
    audit_status: "audited OR not-audited"
    bounty_tier: ">= medium"

  - name: "deFi-lending"
    keywords: [lending, borrow, supply, collateral]
    chains: [ethereum, near, solana]

notifications:
  - channel: telegram
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    chat_id: "${TELEGRAM_CHAT_ID}"
  - channel: discord
    webhook_url: "${DISCORD_WEBHOOK_URL}"
```

---

## 📲 Notification Format

```
🚨 New Program Matched: "Templar Protocol"
Platform: Immunefi
Chain: NEAR
TVL: $8.5M
Max Bounty: $250,000
Scope: Smart Contract (DeFi, Lending)
Audit: Trail of Bits 2026-04-12
Status: Live (new since 2026-06-19 14:00 UTC)

🔗 https://immunefi.com/bug-bounty/templar-protocol
```

---

## 🐳 Docker

```bash
docker run -d \
  --name bounty-monitor \
  -v ~/.config/bounty-monitor:/config \
  -e TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN \
  -e TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID \
  abd02018/bounty-monitor:latest
```

---

## 🤝 Contributing

PRs welcome for:
- New platform integrations
- New notification channels
- New filter primitives
- Performance improvements

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
  <sub>Built by <a href="https://github.com/AbD02018">@AbD02018</a> · Smart contract security researcher</sub>
</div>
