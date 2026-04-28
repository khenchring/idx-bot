"""
market_context.py — Real-time market context for smarter AI decisions.

Tracks:
1. BTC and ETH price movements vs ZKJ (correlation)
2. Recent news about ZKJ / Polyhedra Network via web search
3. Overall crypto market sentiment

Fed into every AI analysis so Claude understands:
- Is ZKJ moving with or against the market?
- Is there news driving this price action?
- Is the broader market bullish or bearish right now?
"""
import time
import json
import os
from collections import deque
from datetime import datetime
from typing import Optional

import requests
import anthropic

from config import cfg
from bot_logger import get_logger

log = get_logger("market_ctx")

client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://indodax.com/",
}

NEWS_CACHE_FILE  = "news_cache.json"
NEWS_TTL_MINUTES = 30


# ─── Correlation tracker ──────────────────────────────────────────────────────

class CorrelationTracker:
    def __init__(self, maxlen: int = 60):
        self._zkj = deque(maxlen=maxlen)
        self._btc = deque(maxlen=maxlen)
        self._eth = deque(maxlen=maxlen)

    def add(self, zkj: float, btc: float, eth: float):
        self._zkj.append(zkj)
        self._btc.append(btc)
        self._eth.append(eth)

    def __len__(self):
        return len(self._zkj)

    def _pct_changes(self, buf):
        p = list(buf)
        if len(p) < 2:
            return []
        return [(p[i] - p[i-1]) / p[i-1] * 100 for i in range(1, len(p))]

    def _pearson(self, a, b):
        if len(a) < 5 or len(b) < 5 or len(a) != len(b):
            return None
        n  = len(a)
        ma = sum(a) / n
        mb = sum(b) / n
        num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
        da  = sum((x-ma)**2 for x in a) ** 0.5
        db  = sum((x-mb)**2 for x in b) ** 0.5
        if da == 0 or db == 0:
            return None
        return round(num / (da * db), 3)

    def correlations(self) -> dict:
        zc = self._pct_changes(self._zkj)
        bc = self._pct_changes(self._btc)
        ec = self._pct_changes(self._eth)
        n  = min(len(zc), len(bc), len(ec))
        if n < 5:
            return {"btc": None, "eth": None, "samples": n}
        return {
            "btc":     self._pearson(zc[-n:], bc[-n:]),
            "eth":     self._pearson(zc[-n:], ec[-n:]),
            "samples": n,
        }

    def latest_moves(self) -> dict:
        def last_chg(buf):
            b = list(buf)
            if len(b) < 2: return None
            return round((b[-1]-b[-2])/b[-2]*100, 3)
        return {
            "zkj_pct":   last_chg(self._zkj),
            "btc_pct":   last_chg(self._btc),
            "eth_pct":   last_chg(self._eth),
            "btc_price": list(self._btc)[-1] if self._btc else None,
            "eth_price": list(self._eth)[-1] if self._eth else None,
        }


_tracker = CorrelationTracker(maxlen=60)


def fetch_btc_eth_prices() -> Optional[dict]:
    try:
        prices = {}
        for pair in ["btc_idr", "eth_idr"]:
            url  = f"https://indodax.com/api/{pair}/ticker"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            resp.raise_for_status()
            prices[pair.split("_")[0]] = float(resp.json()["ticker"]["last"])
        return prices
    except Exception as e:
        log.debug(f"BTC/ETH fetch failed: {e}")
        return None


def update_correlation(zkj_price: float):
    prices = fetch_btc_eth_prices()
    if prices:
        _tracker.add(zkj=zkj_price, btc=prices.get("btc", 0), eth=prices.get("eth", 0))


def get_correlation_summary() -> str:
    corr  = _tracker.correlations()
    moves = _tracker.latest_moves()

    if corr["samples"] < 5:
        return f"Correlation: building data ({corr['samples']}/5 samples needed)"

    def interp(v):
        if v is None:  return "unknown"
        if v >  0.7:   return f"{v} (STRONG — ZKJ follows this coin closely)"
        if v >  0.4:   return f"{v} (moderate positive)"
        if v > -0.4:   return f"{v} (weak/no correlation — moves independently)"
        if v > -0.7:   return f"{v} (moderate inverse)"
        return f"{v} (STRONG inverse — ZKJ moves opposite)"

    lines = [
        f"Correlation ({corr['samples']} cycles):",
        f"  ZKJ vs BTC: {interp(corr['btc'])}",
        f"  ZKJ vs ETH: {interp(corr['eth'])}",
    ]
    if moves["btc_pct"] is not None:
        lines.append(
            f"Latest: ZKJ {moves['zkj_pct']:+.3f}% | "
            f"BTC {moves['btc_pct']:+.3f}% @ Rp {moves['btc_price']:,.0f} | "
            f"ETH {moves['eth_pct']:+.3f}% @ Rp {moves['eth_price']:,.0f}"
        )
    return "\n".join(lines)


# ─── News ──────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if not os.path.exists(NEWS_CACHE_FILE):
        return {}
    try:
        with open(NEWS_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        with open(NEWS_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _is_fresh(cache: dict, key: str) -> bool:
    ts = cache.get(f"{key}_ts")
    if not ts:
        return False
    age = (datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 60
    return age < NEWS_TTL_MINUTES


COIN_NAMES = {
    "zkj_idr":  "ZKJ Polyhedra Network",
    "btc_idr":  "Bitcoin BTC",
    "eth_idr":  "Ethereum ETH",
    "sol_idr":  "Solana SOL",
    "xrp_idr":  "XRP Ripple",
    "doge_idr": "Dogecoin DOGE",
    "bnb_idr":  "BNB Binance Coin",
}


def fetch_news(pair: str) -> str:
    """Fetch recent news. Cached for NEWS_TTL_MINUTES."""
    cache     = _load_cache()
    cache_key = pair.replace("_idr", "")

    if _is_fresh(cache, cache_key):
        log.debug(f"News cache hit for {pair} (< {NEWS_TTL_MINUTES}min old)")
        return cache.get(f"{cache_key}_summary", "No cached news.")

    coin = COIN_NAMES.get(pair, pair.replace("_idr","").upper())
    log.info(f"Fetching news for {coin}...")

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search for the latest news about {coin} from the last 48 hours. "
                    f"Focus on: price catalysts, major partnerships, exchange listings, "
                    f"whale activity, protocol updates, or regulatory news. "
                    f"Give me 4-5 bullet points. Each bullet max 100 chars. "
                    f"Include approximate timing (e.g. '2h ago', 'yesterday'). "
                    f"If nothing significant: just say 'No major news last 48h'."
                )
            }],
        )

        summary = " ".join(
            block.text for block in msg.content if hasattr(block, "text")
        ).strip() or "No significant news found."

        cache[f"{cache_key}_summary"] = summary
        cache[f"{cache_key}_ts"]      = datetime.utcnow().isoformat()
        _save_cache(cache)
        log.info(f"News cached for {pair} ({NEWS_TTL_MINUTES}min TTL)")
        return summary

    except Exception as e:
        log.warning(f"News fetch failed (non-critical): {e}")
        cached = cache.get(f"{cache_key}_summary")
        if cached:
            log.info("Using stale cached news as fallback")
            return f"[STALE] {cached}"
        return "News unavailable."


# ─── Combined context ─────────────────────────────────────────────────────────

def get_full_context(pair: str, price: float) -> str:
    update_correlation(price)
    return f"""=== MARKET CORRELATION (BTC & ETH) ===
{get_correlation_summary()}

=== RECENT NEWS ({pair.upper()}) ===
{fetch_news(pair)}"""
