"""
memory.py — Persistent trade journal and coin behavior memory.

Stores:
  - Full trade history with outcomes
  - Coin behavior profile (updated by Claude after each closed trade)
  - Strategy notes and lessons learned
"""
import json
import os
from datetime import datetime
from typing import Optional
from bot_logger import get_logger

log = get_logger("memory")

JOURNAL_FILE  = "journal.json"
PROFILE_FILE  = "coin_profile.json"


# ─── Journal ──────────────────────────────────────────────────────────────────

def _load_journal() -> dict:
    if not os.path.exists(JOURNAL_FILE):
        return {"trades": [], "stats": {}}
    try:
        with open(JOURNAL_FILE) as f:
            return json.load(f)
    except Exception:
        return {"trades": [], "stats": {}}


def _save_journal(data: dict):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_open(pair: str, entry_price: float, amount: float,
                idr_spent: float, stop_loss: float, take_profit: float,
                indicators: dict, ai_reasoning: str) -> str:
    """Record a new BUY. Returns a trade_id."""
    journal = _load_journal()
    trade_id = f"T{len(journal['trades']) + 1:04d}"
    trade = {
        "id":           trade_id,
        "pair":         pair,
        "status":       "open",
        "entry_time":   datetime.utcnow().isoformat(),
        "entry_price":  entry_price,
        "amount":       amount,
        "idr_spent":    idr_spent,
        "stop_loss":    stop_loss,
        "take_profit":  take_profit,
        "exit_time":    None,
        "exit_price":   None,
        "pnl_idr":      None,
        "pnl_pct":      None,
        "exit_reason":  None,
        "entry_indicators": indicators,
        "exit_indicators":  None,
        "ai_entry_reason":  ai_reasoning,
        "ai_reflection":    None,
    }
    journal["trades"].append(trade)
    _save_journal(journal)
    log.info(f"Journal: opened {trade_id} — {pair} @ {entry_price:,.0f}")
    return trade_id


def record_close(trade_id: str, exit_price: float, pnl_idr: float,
                 exit_reason: str, exit_indicators: dict):
    """Update a trade with exit details."""
    journal = _load_journal()
    for t in journal["trades"]:
        if t["id"] == trade_id:
            t["status"]          = "closed"
            t["exit_time"]       = datetime.utcnow().isoformat()
            t["exit_price"]      = exit_price
            t["pnl_idr"]         = round(pnl_idr, 2)
            t["pnl_pct"]         = round((exit_price / t["entry_price"] - 1) * 100, 3)
            t["exit_reason"]     = exit_reason
            t["exit_indicators"] = exit_indicators
            _save_journal(journal)
            log.info(f"Journal: closed {trade_id} — PnL Rp {pnl_idr:+,.0f} ({t['pnl_pct']:+.2f}%)")
            return t
    log.warning(f"Journal: trade {trade_id} not found")
    return None


def get_recent_trades(pair: str, limit: int = 10) -> list:
    """Return the last N closed trades for this pair."""
    journal = _load_journal()
    closed = [t for t in journal["trades"]
              if t["pair"] == pair and t["status"] == "closed"]
    return closed[-limit:]


def get_open_trade(pair: str) -> Optional[dict]:
    """Return current open trade for this pair, if any."""
    journal = _load_journal()
    for t in reversed(journal["trades"]):
        if t["pair"] == pair and t["status"] == "open":
            return t
    return None


def get_stats(pair: str) -> dict:
    """Compute win rate, avg PnL, etc. for a pair."""
    journal = _load_journal()
    closed = [t for t in journal["trades"]
              if t["pair"] == pair and t["status"] == "closed"]
    if not closed:
        return {"total": 0}
    wins   = [t for t in closed if t["pnl_idr"] and t["pnl_idr"] > 0]
    losses = [t for t in closed if t["pnl_idr"] and t["pnl_idr"] <= 0]
    pnls   = [t["pnl_idr"] for t in closed if t["pnl_idr"] is not None]
    return {
        "total":       len(closed),
        "wins":        len(wins),
        "losses":      len(losses),
        "win_rate":    round(len(wins) / len(closed) * 100, 1),
        "total_pnl":   round(sum(pnls), 2),
        "avg_pnl":     round(sum(pnls) / len(pnls), 2),
        "best":        round(max(pnls), 2),
        "worst":       round(min(pnls), 2),
    }


def save_reflection(trade_id: str, reflection: str):
    """Save Claude's post-trade reflection."""
    journal = _load_journal()
    for t in journal["trades"]:
        if t["id"] == trade_id:
            t["ai_reflection"] = reflection
            _save_journal(journal)
            return


# ─── Coin Profile ─────────────────────────────────────────────────────────────

def _load_profile(pair: str) -> dict:
    if not os.path.exists(PROFILE_FILE):
        return {}
    try:
        with open(PROFILE_FILE) as f:
            data = json.load(f)
            return data.get(pair, {})
    except Exception:
        return {}


def _save_profile(pair: str, profile: dict):
    data = {}
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE) as f:
                data = json.load(f)
        except Exception:
            pass
    data[pair] = profile
    with open(PROFILE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_profile(pair: str) -> dict:
    return _load_profile(pair)


def update_profile(pair: str, updates: dict):
    """Merge new profile data in."""
    profile = _load_profile(pair)
    profile.update(updates)
    profile["last_updated"] = datetime.utcnow().isoformat()
    _save_profile(pair, profile)
    log.info(f"Coin profile updated for {pair.upper()}")
