# 🤖 Indodax AI Trader

An autonomous crypto trading bot for [Indodax](https://indodax.com) powered by **Claude AI (Sonnet 4.6)**. The bot analyzes real-time market indicators, learns from its own trade history, tracks BTC/ETH correlation, reads live news, and makes intelligent trading decisions — including smart handling of overbought market conditions.

![Python](https://img.shields.io/badge/Python-3.10+-green)
![Dashboard](https://img.shields.io/badge/Dashboard-localhost:5000-blue)
![Model](https://img.shields.io/badge/Claude-Sonnet%204.6-purple)
![License](https://img.shields.io/badge/License-MIT-gray)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 Claude AI (Sonnet 4.6) | Every trade decision analyzed by Claude |
| 📚 Persistent memory | Learns from past trades, builds coin behavior profile per pair |
| 📰 Live news | Fetches coin news every 30 min via Claude web search |
| 📊 Correlation tracking | Tracks coin vs BTC/ETH correlation in real-time |
| 🎯 Profit targeting | Auto-sizes position to hit your IDR profit target |
| 📈 Trailing stop-loss | Raises stop-loss automatically as price climbs |
| 🔥 Overbought momentum mode | Enters overbought markets as quick scalps when breakout is confirmed |
| 🔍 Momentum gate | 5-signal check blocks weak setups before spending API credits |
| 🔄 Position reviews | Reviews open position every 5 min — sell or hold longer? |
| 💾 Buffer persistence | Indicator warmup saved to disk — no loss on restart |
| 🖥️ Clean web dashboard | Live UI at http://localhost:5000 |

---

## 📁 File Structure

```
indodax-bot/
├── main.py              # Entry point + CLI flags
├── trader.py            # Main trading loop
├── indodax_client.py    # Indodax API (public ticker + private TAPI)
├── indicators.py        # RSI, MACD, EMA, BB, ATR (pure numpy/pandas)
├── ai_agent.py          # Claude AI — analysis, review, post-trade reflection
├── risk_manager.py      # Position sizing, trailing SL, momentum gate, overbought mode
├── memory.py            # Trade journal + coin behavior profile (persisted to disk)
├── market_context.py    # BTC/ETH correlation + live news fetching
├── config.py            # All settings loaded from .env
├── bot_logger.py        # Colored console + file logging
├── server.py            # Flask web dashboard
├── requirements.txt     # Python dependencies
└── .env.example         # Config template — copy to .env and fill in keys
```

**Auto-generated at runtime (never commit these):**
```
.env                  ← your API keys
buffer_state.json     ← price buffer state
journal.json          ← full trade history with AI reflections
coin_profile.json     ← Claude's learned coin knowledge
news_cache.json       ← cached news (30 min TTL)
trader.log            ← full log file
```

---

## 🚀 Quick Start

### 1. Install Python
Download from **https://python.org/downloads**
⚠️ Check **"Add Python to PATH"** during installation

### 2. Install dependencies
```bash
python -m pip install -r requirements.txt
```

### 3. Configure
```bash
copy .env.example .env
notepad .env
```

Minimum required settings:
```env
INDODAX_API_KEY=your_key
INDODAX_API_SECRET=your_secret
INDODAX_DEMO=false
ANTHROPIC_API_KEY=your_anthropic_key
TRADING_PAIR=zkj_idr
DRY_RUN=true
```

### 4. Test safely (dry run — no real orders)
```bash
python main.py
```
Open **http://localhost:5000** to see the live dashboard.

### 5. Go live
```bash
# Edit .env: set DRY_RUN=false
python main.py --live
```

---

## ⚙️ Configuration Reference

```env
# ── Indodax ───────────────────────────────────────────────────
INDODAX_API_KEY=your_key
INDODAX_API_SECRET=your_secret
INDODAX_DEMO=false              # true = use demo-indodax.com

# ── Anthropic ─────────────────────────────────────────────────
ANTHROPIC_API_KEY=your_key

# ── Trading ───────────────────────────────────────────────────
TRADING_PAIR=zkj_idr            # any Indodax pair e.g. btc_idr, eth_idr
TRADE_INTERVAL_SECONDS=300      # scan every 5 minutes
POSITION_REVIEW_SECONDS=300     # review open position every 5 minutes

# ── Position sizing ───────────────────────────────────────────
MAX_POSITION_IDR=100000
RISK_PER_TRADE_PERCENT=2.0
MAX_DAILY_LOSS_IDR=50000        # bot stops trading if this is hit

# ── Safety ────────────────────────────────────────────────────
DRY_RUN=false
MIN_AI_CONFIDENCE=70            # minimum Claude confidence % to act

# ── Profit targeting ──────────────────────────────────────────
USE_PROFIT_TARGET=true
MIN_PROFIT_PERCENT=2.0          # hard minimum 2% per trade
TARGET_PROFIT_MIN_IDR=1000
TARGET_PROFIT_MAX_IDR=5000
STOP_LOSS_PERCENT=1.5
TAKE_PROFIT_PERCENT=2.5

# ── Trailing stop-loss ────────────────────────────────────────
USE_TRAILING_STOP=true
TRAILING_STOP_PERCENT=1.0       # trail 1% below price peak

# ── Entry filters ─────────────────────────────────────────────
MIN_VOLUME_RATIO=1.2            # volume must be 1.2x average
MIN_MOMENTUM_SCORE=3            # at least 3/5 signals must align
MAX_RSI_ENTRY=68.0              # normal entry upper RSI limit
MIN_RSI_ENTRY=35.0              # don't buy in freefall
```

---

## 🧠 How the Trading Logic Works

```
Every 5 minutes:
│
├── 1. Safety check (daily loss limit)
├── 2. Fetch live price → build candles in memory
├── 3. Compute 6 indicators (RSI, MACD, EMA, BB, ATR, Trend)
├── 4. Fetch BTC/ETH prices → compute correlation
│
├── IF holding position:
│   ├── Update trailing stop-loss
│   ├── Check stop-loss hit → SELL immediately
│   ├── Check take-profit hit → SELL immediately
│   └── Every 5 min → AI reviews: SELL now or HOLD longer?
│
└── IF no position:
    ├── Momentum gate (5 signals, free — no AI cost)
    │   ├── NORMAL mode (RSI 35-68): need 3/5 signals
    │   └── OVERBOUGHT mode (RSI > 68): need 5+/7 bull signals
    │       → uses tight scalp TP/SL instead of normal sizing
    ├── Gate passes → Claude analyzes with full context:
    │   - Indicators + coin profile
    │   - Recent trade history + outcomes
    │   - BTC/ETH correlation
    │   - Latest news
    └── BUY if confidence ≥ 70%
```

---

## 🔥 Overbought Momentum Mode

Most bots refuse to enter when RSI is high. This bot handles it differently.

When RSI > 68 but the following are ALL true:
- EMA cross is BULL
- MACD histogram positive and growing
- BB% > 0.7 (price near upper band — real breakout)
- Trend is UP
- Volume ≥ 1.5x average (confirms real buying pressure)

The bot switches to **scalp mode:**
- Enters the position
- Uses tight 1% stop-loss (protect against reversal)
- Uses quick 1.5% take-profit (get out fast)
- Claude explicitly reasons about whether it's a real breakout or a bull trap

Log example:
```
[OVERBOUGHT_MOMENTUM] Momentum 5/5 | strong bull signals
[AI] BUY | 76% | [overbought_momentum] High volume breakout, MACD accelerating
Overbought scalp mode — TP 1.5% / SL 1.0%
```

---

## 📚 How Claude Learns Over Time

**After every closed trade**, Claude automatically:
1. Reviews what worked and what didn't
2. Updates `coin_profile.json` with behavioral insights:
   - Typical RSI reversal levels for this coin
   - Daily volatility patterns
   - Best entry conditions observed
   - Conditions that led to losses
3. Every future analysis includes this profile

After 10+ trades, Claude's reasoning becomes noticeably more specific:
> *"ZKJ typically reverses at RSI 72, not 80 — based on 3 previous losses at that level. Entry here at RSI 58 with BULL EMA and 1.8x volume is within the historical win zone."*

---

## 💰 API Cost Estimate

Model: `claude-sonnet-4-6`

| Scan interval | Est. cost/hr | $8 credit lasts |
|---|---|---|
| 60s | ~$0.38/hr | ~21 hours |
| 300s (default) | ~$0.15/hr | ~53 hours |
| 120s | ~$0.25/hr | ~32 hours |

Tip: news is cached for 30 min to minimize API calls.

---

## 🖥️ Web Dashboard

Open **http://localhost:5000** while the bot is running.

Shows:
- Live price + sparkline trend chart
- 6 indicators with color-coded status
- Momentum score (5 dots)
- AI decision with confidence bar + signal
- Portfolio balance + daily P&L
- Open position with trailing stop tracker
- Trade history with P&L per trade
- Live console log

---

## 🔑 Getting API Keys

**Indodax:**
1. Login to [indodax.com](https://indodax.com)
2. Profile → Trade API → Create New Key
3. Enable: **View** + **Trade** only
4. ⚠️ Never enable Withdraw permission
5. Whitelist your IP address for security

**Anthropic:**
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. API Keys → Create Key

---

## 🖥️ CLI Options

```bash
python main.py                   # start with .env settings
python main.py --dry-run         # force paper trading
python main.py --live            # force live (asks confirmation)
python main.py --pair eth_idr    # override pair from command line
python main.py --once            # run single cycle and exit
python main.py --no-ui           # disable web dashboard
```

---

## ⚠️ Risk Warning

- Crypto trading involves **significant financial risk**
- Always run `DRY_RUN=true` first to verify everything works
- Start with small amounts (`MAX_POSITION_IDR=50000`)
- Always set `MAX_DAILY_LOSS_IDR` — never disable it
- The bot is as good as the market conditions — no bot wins 100%
- Past performance does not guarantee future results
- **You are solely responsible for your own funds**

---

## 📄 License

MIT License — use at your own risk.
