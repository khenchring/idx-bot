# 🤖 Indodax AI Trader

An autonomous crypto trading bot for [Indodax](https://indodax.com) powered by **Claude AI (Sonnet)**. The bot analyzes real-time market indicators, learns from its own trade history, tracks BTC/ETH correlation, reads live news, and makes intelligent BUY/SELL/HOLD decisions — all without manual intervention.

![Dashboard](https://img.shields.io/badge/Dashboard-localhost:5000-blue)
![Python](https://img.shields.io/badge/Python-3.10+-green)
![License](https://img.shields.io/badge/License-MIT-gray)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🧠 Claude AI | Every decision made by Claude analyzing 6+ indicators |
| 📚 Persistent memory | Learns from past trades, builds coin behavior profile |
| 📰 Live news | Fetches ZKJ/coin news every 30 min via web search |
| 📊 Correlation tracking | Tracks ZKJ vs BTC/ETH correlation in real-time |
| 🎯 Profit targeting | Auto-sizes position to hit your IDR profit target |
| 📈 Trailing stop-loss | Locks in profit as price rises |
| 🔍 Momentum scoring | 5-signal gate blocks weak setups before calling AI |
| 🔄 Position reviews | Reviews open position every 5 min — sell or hold? |
| 💾 Buffer persistence | Indicator warmup saved to disk — survives restarts |
| 🖥️ Web dashboard | Live UI at http://localhost:5000 |

---

## 📁 File Structure

```
indodax-bot/
├── main.py              # Entry point + CLI
├── trader.py            # Main trading loop
├── indodax_client.py    # Indodax API (public ticker + private TAPI)
├── indicators.py        # RSI, MACD, EMA, BB, ATR (pure numpy/pandas)
├── ai_agent.py          # Claude AI — analysis, review, reflection
├── risk_manager.py      # Position sizing, trailing SL, momentum filter
├── memory.py            # Trade journal + coin behavior profile
├── market_context.py    # BTC/ETH correlation + live news
├── config.py            # All settings from .env
├── bot_logger.py        # Colored console + file logging
├── server.py            # Flask web dashboard
├── requirements.txt     # Python dependencies
└── .env.example         # Config template — copy to .env
```

**Auto-created at runtime (not committed to git):**
```
.env                  ← your API keys, never share this
buffer_state.json     ← price buffer for indicator warmup
journal.json          ← full trade history with AI reflections
coin_profile.json     ← Claude's learned coin behavior knowledge
news_cache.json       ← cached news to save API credits
trader.log            ← full log history
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

Fill in your keys — minimum required:
```env
INDODAX_API_KEY=your_key
INDODAX_API_SECRET=your_secret
INDODAX_DEMO=false
ANTHROPIC_API_KEY=your_anthropic_key
TRADING_PAIR=zkj_idr
DRY_RUN=true
```

### 4. Test with dry run (safe — no real orders)
```bash
python main.py
```
Open **http://localhost:5000** to see the dashboard.

### 5. Go live
```bash
# Edit .env: DRY_RUN=false
python main.py --live
```

---

## ⚙️ Full Configuration

```env
# ── Indodax API ───────────────────────────────────────────────
INDODAX_API_KEY=your_api_key
INDODAX_API_SECRET=your_api_secret
INDODAX_DEMO=false              # true = use demo-indodax.com

# ── Anthropic ─────────────────────────────────────────────────
ANTHROPIC_API_KEY=your_anthropic_key

# ── Trading ───────────────────────────────────────────────────
TRADING_PAIR=zkj_idr            # pair to trade
TRADE_INTERVAL_SECONDS=300      # scan every 5 minutes
POSITION_REVIEW_SECONDS=300     # review open position every 5 min

# ── Position sizing ───────────────────────────────────────────
MAX_POSITION_IDR=100000         # max IDR per trade
RISK_PER_TRADE_PERCENT=2.0      # % of balance to risk
MAX_DAILY_LOSS_IDR=50000        # stop trading if daily loss hits this

# ── Safety ────────────────────────────────────────────────────
DRY_RUN=false
MIN_AI_CONFIDENCE=70            # minimum Claude confidence to act

# ── Profit targeting ──────────────────────────────────────────
USE_PROFIT_TARGET=true
MIN_PROFIT_PERCENT=2.0          # hard minimum 2% per trade
TARGET_PROFIT_MIN_IDR=1000      # minimum target profit (IDR)
TARGET_PROFIT_MAX_IDR=5000      # maximum target profit (IDR)
STOP_LOSS_PERCENT=1.5
TAKE_PROFIT_PERCENT=2.5

# ── Trailing stop-loss ────────────────────────────────────────
USE_TRAILING_STOP=true
TRAILING_STOP_PERCENT=1.0       # trail 1% below price peak

# ── Entry filters ─────────────────────────────────────────────
MIN_VOLUME_RATIO=1.2            # volume must be 1.2x average
MIN_MOMENTUM_SCORE=3            # at least 3/5 signals aligned
MAX_RSI_ENTRY=68.0              # don't buy overbought
MIN_RSI_ENTRY=35.0              # don't buy in freefall
```

---

## 🧠 How the AI Learns

**Every cycle:**
1. Fetches live ticker → builds OHLCV in memory
2. Computes RSI, MACD, EMA, Bollinger Bands, ATR, trend
3. Checks BTC/ETH correlation + fetches latest news
4. Runs 5-signal momentum gate (free — no AI cost)
5. If gate passes → sends everything to Claude
6. Claude returns BUY/SELL/HOLD with confidence + reasoning

**After each closed trade:**
1. Claude reflects on what worked and what didn't
2. Updates `coin_profile.json` with insights like:
   - Typical RSI reversal levels for this coin
   - Daily volatility range
   - Best entry conditions observed
   - Conditions to avoid
3. Every future analysis includes this profile → Claude improves over time

---

## 📊 Trading Logic

```
Every 5 minutes:
├── Safety check (daily loss limit)
├── Fetch price + compute indicators
│
├── If HOLDING position:
│   ├── Check trailing stop → SELL if hit
│   ├── Check take-profit → SELL if hit
│   └── Every 5 min: AI review → SELL or HOLD?
│
└── If NO position:
    ├── Momentum gate (3/5 signals must align)
    ├── If gate passes → Claude analyzes
    └── If BUY + confidence ≥ 70% → place order
```

---

## 🖥️ Web Dashboard

Run the bot then open **http://localhost:5000**

- Live price chart with sparkline
- 6 indicators with color-coded status
- AI decision panel with confidence bar
- Portfolio balance and P&L
- Open position with trailing stop tracker
- Trade history with P&L per trade
- Live console log

---

## 🔑 Getting API Keys

**Indodax:**
1. Login → Profile → Trade API → Create Key
2. Enable: **View + Trade** only (never enable Withdraw)
3. Whitelist your IP for security

**Anthropic:**
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. API Keys → Create Key
3. Model used: `claude-sonnet-4-6` (~$0.15–0.35/hour)

---

## 💰 Running Cost Estimate

| Interval | Est. Cost/hour | $8 credit lasts |
|---|---|---|
| 60s scan | ~$0.38/hr | ~21 hours |
| 300s scan (default) | ~$0.15/hr | ~53 hours |
| 120s scan | ~$0.25/hr | ~32 hours |

---

## CLI Options

```bash
python main.py                  # start with .env settings
python main.py --dry-run        # force safe mode
python main.py --live           # force live (asks confirmation)
python main.py --pair eth_idr   # override trading pair
python main.py --once           # single cycle then exit
python main.py --no-ui          # disable web dashboard
```

---

## ⚠️ Risk Warning

- Crypto trading involves **significant financial risk**
- Always start with `DRY_RUN=true` to test first
- Start with small amounts (`MAX_POSITION_IDR=50000`)
- Set `MAX_DAILY_LOSS_IDR` and never disable it
- Past performance does not guarantee future results
- You are solely responsible for your own funds

---

## 📄 License

MIT License — use at your own risk.
