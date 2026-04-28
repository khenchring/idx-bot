"""
ai_agent.py — Claude AI trading agent with memory and learning.

Each analysis cycle includes:
- Current market indicators
- Recent trade history and outcomes
- Coin behavior profile built from past experience
- Claude's own strategy notes and lessons learned

After each closed trade, Claude reflects on what happened and
updates its coin profile and strategy notes.
"""
import json
import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from config import cfg
from indicators import Indicators
from bot_logger import get_logger
import memory
import market_context

log    = get_logger("ai_agent")
client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

SYSTEM = """You are an expert quantitative crypto trading agent specialized in Indonesian Rupiah (IDR) spot markets on Indodax.

You have persistent memory — you learn from your past trades and build knowledge of each coin's behavior over time. You use this accumulated experience to make better decisions with every trade.

Your core principles:
1. Capital preservation above all — a trade not taken is never a loss
2. Learn from every outcome — update your mental model after each trade
3. Spot patterns in THIS specific coin's behavior — every coin has personality
4. HOLD is correct most of the time — only act on strong conviction
5. Never chase — if you missed the move, wait for the next setup

You trade spot only (IDR pairs) — no leverage, no shorting. You can only profit from price going UP.

Respond ONLY with valid JSON. No markdown, no explanation outside the JSON."""


@dataclass
class AIDecision:
    action: str
    confidence: int
    signal: str
    reasoning: str
    stop_loss_pct: Optional[float]
    take_profit_pct: Optional[float]
    risk_reward: Optional[float]


def _format_trade_history(trades: list) -> str:
    if not trades:
        return "No closed trades yet for this pair."
    lines = []
    for t in trades[-8:]:
        outcome = f"PnL: Rp {t['pnl_idr']:+,.0f} ({t['pnl_pct']:+.2f}%)"
        ind = t.get("entry_indicators", {})
        rsi = f"RSI {ind.get('rsi', '?'):.1f}" if isinstance(ind.get('rsi'), float) else ""
        lines.append(
            f"  [{t['id']}] {t['exit_reason']} | {outcome} | "
            f"Entry: Rp {t['entry_price']:,.0f} → Exit: Rp {t['exit_price']:,.0f} | "
            f"{rsi} | Reason: {t.get('ai_entry_reason','?')[:60]}"
        )
        if t.get("ai_reflection"):
            lines.append(f"    Reflection: {t['ai_reflection']}")
    return "\n".join(lines)


def _format_profile(profile: dict) -> str:
    if not profile:
        return "No coin profile yet — this is your first analysis of this coin."
    parts = []
    for k, v in profile.items():
        if k == "last_updated":
            continue
        parts.append(f"  {k}: {v}")
    return "\n".join(parts) if parts else "Profile exists but is empty."


def analyze(ind: Indicators, position: Optional[dict], balance: dict) -> AIDecision:
    base  = cfg.base_currency.upper()
    pair  = cfg.TRADING_PAIR
    idr_balance  = balance.get("idr", 0)
    coin_balance = balance.get(cfg.base_currency, 0)

    # Load memory
    recent_trades = memory.get_recent_trades(pair, limit=8)
    stats         = memory.get_stats(pair)
    profile       = memory.get_profile(pair)
    trade_history = _format_trade_history(recent_trades)
    profile_text  = _format_profile(profile)

    stats_text = (
        f"Total trades: {stats.get('total', 0)} | "
        f"Win rate: {stats.get('win_rate', 0)}% | "
        f"Total P&L: Rp {stats.get('total_pnl', 0):+,.0f} | "
        f"Avg P&L: Rp {stats.get('avg_pnl', 0):+,.0f}"
        if stats.get("total", 0) > 0
        else "No trade history yet."
    )

    pos_str = "None"
    if position:
        pnl_pct = (ind.price / position["entry_price"] - 1) * 100
        pos_str = (
            f"{position['amount']} {base} @ Rp {position['entry_price']:,.0f} "
            f"(P&L: {pnl_pct:+.2f}%, SL: Rp {position['stop_loss']:,.0f}, "
            f"TP: Rp {position['take_profit']:,.0f})"
        )

    # Fetch market correlation + news (cached, non-blocking)
    ctx = market_context.get_full_context(pair, ind.price)

    prompt = f"""Analyze {base}/IDR and decide: BUY, SELL, or HOLD.

=== CURRENT MARKET ===
Price:        Rp {ind.price:,.2f}  ({ind.price_change_pct:+.3f}% last candle)
RSI(14):      {ind.rsi:.1f}
MACD:         {ind.macd:.4f} | Signal: {ind.macd_signal:.4f} | Hist: {ind.macd_hist:.4f}
EMA{cfg.EMA_FAST}/{cfg.EMA_SLOW}:     Rp {ind.ema_fast:,.2f} / Rp {ind.ema_slow:,.2f} ({ind.ema_cross})
BB:           Rp {ind.bb_lower:,.2f} – Rp {ind.bb_mid:,.2f} – Rp {ind.bb_upper:,.2f} (BB%: {ind.bb_pct:.3f})
ATR(14):      Rp {ind.atr:,.2f}
Volume ratio: {ind.volume_ratio:.2f}x
Trend:        {ind.trend}

=== PORTFOLIO ===
IDR balance:  Rp {idr_balance:,.0f}
{base} balance: {coin_balance:.6f}
Open Position: {pos_str}
Max trade:    Rp {cfg.MAX_POSITION_IDR:,.0f}

=== YOUR TRADING HISTORY FOR {base}/IDR ===
{stats_text}

Recent trades:
{trade_history}

=== YOUR COIN KNOWLEDGE PROFILE ===
{profile_text}

{ctx}

=== PROFIT TARGET ===
Target profit per trade: Rp {cfg.TARGET_PROFIT_MIN_IDR:,.0f} – Rp {cfg.TARGET_PROFIT_MAX_IDR:,.0f} IDR
The position size and TP% will be auto-calculated to hit this range.
Only enter trades where you believe price has enough momentum to reach the TP.
Avoid entering near resistance or when momentum is fading.

=== DECISION RULES ===
- BUY only if: no open position AND confidence >= {cfg.MIN_AI_CONFIDENCE} AND RSI < 72
  AND price has clear upward momentum to hit TP target
- SELL only if: holding {base} AND (confidence >= {cfg.MIN_AI_CONFIDENCE} OR RSI > 78)
- HOLD otherwise — better to miss a trade than enter a weak setup

Use your trade history and coin profile to make a SMARTER decision than last time.
If past trades show a pattern (e.g. "RSI bounces at 35 for this coin"), use it.

Respond ONLY with this JSON:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": <integer 0-100>,
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "reasoning": "<specific reasoning using history and profile, max 150 chars>",
  "stop_loss_pct": <float or null>,
  "take_profit_pct": <float or null>,
  "risk_reward": <float or null>
}}"""

    log.debug(f"[AI] Analyzing {base}/IDR with {len(recent_trades)} trade history records")

    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=500,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
        else:
            log.error(f"[AI] Cannot parse: {raw[:200]}")
            return AIDecision("HOLD", 0, "NEUTRAL", "parse error", None, None, None)

    decision = AIDecision(
        action=data.get("action", "HOLD").upper(),
        confidence=int(data.get("confidence", 0)),
        signal=data.get("signal", "NEUTRAL").upper(),
        reasoning=data.get("reasoning", ""),
        stop_loss_pct=data.get("stop_loss_pct"),
        take_profit_pct=data.get("take_profit_pct"),
        risk_reward=data.get("risk_reward"),
    )
    log.info(f"[AI] {decision.action} | {decision.confidence}% | {decision.signal} | {decision.reasoning}")
    return decision


def reflect_on_trade(trade: dict, ind: Indicators):
    """
    After closing a trade, ask Claude to reflect on what happened,
    extract lessons, and update the coin behavior profile.
    """
    pair    = cfg.TRADING_PAIR
    base    = cfg.base_currency.upper()
    profile = memory.get_profile(pair)
    stats   = memory.get_stats(pair)

    entry_ind = trade.get("entry_indicators", {})

    prompt = f"""You just closed a trade on {base}/IDR. Reflect on it and update your knowledge.

=== CLOSED TRADE ===
Trade ID:      {trade['id']}
Entry:         Rp {trade['entry_price']:,.2f} (RSI: {entry_ind.get('rsi', '?')}, Trend: {entry_ind.get('trend', '?')})
Exit:          Rp {trade['exit_price']:,.2f}
Exit reason:   {trade['exit_reason']}
P&L:           Rp {trade['pnl_idr']:+,.0f} ({trade['pnl_pct']:+.2f}%)
Entry reason:  {trade['ai_entry_reason']}

=== CURRENT INDICATORS (at exit) ===
Price: Rp {ind.price:,.2f} | RSI: {ind.rsi:.1f} | MACD hist: {ind.macd_hist:.4f}
EMA cross: {ind.ema_cross} | Trend: {ind.trend} | BB%: {ind.bb_pct:.3f}

=== EXISTING COIN PROFILE ===
{_format_profile(profile)}

=== OVERALL STATS ===
{stats.get('total', 0)} trades | Win rate: {stats.get('win_rate', 0)}% | Total P&L: Rp {stats.get('total_pnl', 0):+,.0f}

Based on this trade outcome:
1. What worked or didn't work?
2. What does this tell us about {base}/IDR behavior?
3. Update the coin profile with any new patterns or insights.

Respond ONLY with this JSON:
{{
  "reflection": "<2-3 sentence honest assessment of this trade, max 200 chars>",
  "lesson": "<one specific actionable lesson for next time, max 120 chars>",
  "profile_updates": {{
    "volatility":       "<low/medium/high and any pattern observed>",
    "rsi_behavior":     "<how RSI behaves for this coin, e.g. 'oversold at 35, not 30'>",
    "trend_reliability":"<how reliable EMA/trend signals are>",
    "best_entry_conditions": "<what conditions tend to produce winning trades>",
    "avoid_conditions":      "<what conditions to avoid>",
    "typical_move_pct":      "<typical % move after entry>",
    "notes":                 "<any other behavioral patterns noticed>"
  }}
}}"""

    try:
        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw  = msg.content[0].text.strip()
        data = json.loads(raw.replace("```json", "").replace("```", "").strip())

        reflection = data.get("reflection", "")
        lesson     = data.get("lesson", "")
        updates    = data.get("profile_updates", {})

        # Save reflection to journal
        memory.save_reflection(trade["id"], f"{reflection} | Lesson: {lesson}")

        # Update coin profile
        if updates:
            memory.update_profile(pair, updates)

        log.info(f"[AI] Reflection: {reflection}")
        log.info(f"[AI] Lesson: {lesson}")
        log.info(f"[AI] Coin profile updated for {base}/IDR")

    except Exception as e:
        log.warning(f"Reflection failed (non-critical): {e}")


def review_position(ind: Indicators, position: dict, elapsed_minutes: float) -> AIDecision:
    """
    Dedicated 15-minute position review.
    Claude focuses only on: sell now to lock in profit, or hold longer?
    """
    pair    = cfg.TRADING_PAIR
    base    = cfg.base_currency.upper()
    profile = memory.get_profile(pair)

    entry   = position["entry_price"]
    amount  = position["amount"]
    idr_in  = position["idr_spent"]
    gross   = amount * ind.price * 0.997
    pnl     = gross - idr_in
    pnl_pct = (ind.price / entry - 1) * 100
    target_min = cfg.TARGET_PROFIT_MIN_IDR
    target_max = cfg.TARGET_PROFIT_MAX_IDR
    target_mid = (target_min + target_max) / 2

    tp_price = position.get("take_profit", entry * 1.03)
    sl_price = position.get("stop_loss",   entry * 0.985)
    dist_to_tp  = ((tp_price - ind.price) / ind.price) * 100
    dist_to_sl  = ((ind.price - sl_price) / ind.price) * 100

    in_profit  = pnl >= target_min
    hit_target = pnl >= target_mid

    ctx = market_context.get_full_context(pair, ind.price)

    prompt = f"""You are reviewing an open position on {base}/IDR after {elapsed_minutes:.0f} minutes.
Your ONLY decision: SELL now to lock in profit/cut loss, or HOLD for more time.

=== OPEN POSITION ===
Entry price:    Rp {entry:,.2f}
Current price:  Rp {ind.price:,.2f}
Amount held:    {amount:.6f} {base}
IDR invested:   Rp {idr_in:,.0f}
Current gross:  Rp {gross:,.0f}
Unrealized P&L: Rp {pnl:+,.0f} ({pnl_pct:+.2f}%)
Time in trade:  {elapsed_minutes:.0f} minutes

=== PROFIT TARGET ===
Target range:   Rp {target_min:,.0f} – Rp {target_max:,.0f}
Target mid:     Rp {target_mid:,.0f}
In profit zone: {"YES ✓" if in_profit else "NOT YET"}
Target reached: {"YES ✓" if hit_target else "NOT YET"}
Distance to TP: {dist_to_tp:.2f}% away (Rp {tp_price:,.2f})
Distance to SL: {dist_to_sl:.2f}% cushion (Rp {sl_price:,.2f})

=== CURRENT INDICATORS ===
Price change:  {ind.price_change_pct:+.3f}% last candle
RSI(14):       {ind.rsi:.1f}
MACD hist:     {ind.macd_hist:.4f}
EMA cross:     {ind.ema_cross}
BB%:           {ind.bb_pct:.3f}
Trend:         {ind.trend}
Volume ratio:  {ind.volume_ratio:.2f}x

=== COIN PROFILE ===
{_format_profile(profile)}

{ctx}

=== DECISION LOGIC ===
Consider SELL if any of:
- P&L >= Rp {target_min:,.0f} AND momentum is slowing (RSI dropping, MACD hist falling)
- P&L >= Rp {target_max:,.0f} (max target hit — always take it)
- RSI > 75 (overbought — likely to reverse)
- Trade has been open > 60 min with no progress toward target
- Price is falling back toward stop-loss

Consider HOLD if:
- P&L still below target but momentum is still strong
- RSI trending up, MACD hist positive and growing
- Price recently bounced and looks to continue up
- Less than 30 min in trade and setup still valid

Respond ONLY with this JSON:
{{
  "action": "SELL" | "HOLD",
  "confidence": <integer 0-100>,
  "signal": "BULLISH" | "BEARISH" | "NEUTRAL",
  "reasoning": "<specific reasoning about THIS position, max 150 chars>",
  "stop_loss_pct": null,
  "take_profit_pct": null,
  "risk_reward": null
}}"""

    log.info(f"[AI] Position review at {elapsed_minutes:.0f}min | P&L: Rp {pnl:+,.0f} ({pnl_pct:+.2f}%)")

    msg = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=400,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group()) if m else {}

    decision = AIDecision(
        action=data.get("action", "HOLD").upper(),
        confidence=int(data.get("confidence", 50)),
        signal=data.get("signal", "NEUTRAL").upper(),
        reasoning=data.get("reasoning", ""),
        stop_loss_pct=None,
        take_profit_pct=None,
        risk_reward=None,
    )
    log.info(f"[AI] Review: {decision.action} | {decision.confidence}% | {decision.reasoning}")
    return decision
