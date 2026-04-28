import hashlib
import hmac
import time
import urllib.parse
from collections import deque
from typing import Optional

import pandas as pd
import requests

from config import cfg
from bot_logger import get_logger

log = get_logger("indodax")

PUBLIC_URL  = "https://indodax.com/api"
PRIVATE_URL = f"{cfg.api_base}/tapi"

MIN_ORDER_IDR = 10_000


def _smart_round(price: float) -> int:
    """Round price to an appropriate step size based on magnitude."""
    if price >= 1_000_000:  return int(round(price / 100) * 100)   # BTC etc → nearest 100
    if price >= 100_000:    return int(round(price / 10) * 10)      # → nearest 10
    if price >= 10_000:     return int(round(price))                 # → nearest 1
    if price >= 1_000:      return int(round(price))                 # → nearest 1
    if price >= 100:        return int(round(price))                 # ZKJ etc → nearest 1
    if price >= 10:         return round(price, 1)                   # → 1 decimal
    return round(price, 2)                                           # → 2 decimals

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Referer": "https://indodax.com/",
}


class PriceBuffer:
    """
    Accumulates ticker snapshots and converts them to OHLCV candles.
    Persists to disk on save() and reloads on load() so warmup
    state is preserved across restarts.
    """
    SAVE_FILE = "buffer_state.json"

    def __init__(self, maxlen: int = 500):
        self._buf: deque = deque(maxlen=maxlen)

    def add(self, price: float, volume_24h: float, ts: Optional[float] = None):
        self._buf.append({
            "ts":     ts or time.time(),
            "price":  price,
            "volume": volume_24h,
        })

    def __len__(self):
        return len(self._buf)

    def save(self, pair: str):
        """Persist buffer to disk."""
        import json, os
        data = {"pair": pair, "buf": list(self._buf)}
        try:
            with open(self.SAVE_FILE, "w") as f:
                json.dump(data, f)
            log.info(f"Buffer saved: {len(self._buf)} snapshots → {self.SAVE_FILE}")
        except Exception as e:
            log.warning(f"Could not save buffer: {e}")

    def load(self, pair: str) -> bool:
        """Reload buffer from disk. Returns True if loaded successfully."""
        import json, os
        if not os.path.exists(self.SAVE_FILE):
            return False
        try:
            with open(self.SAVE_FILE) as f:
                data = json.load(f)
            if data.get("pair") != pair:
                log.info(f"Buffer file is for pair '{data.get('pair')}', not '{pair}' — ignoring.")
                return False
            self._buf = deque(data["buf"], maxlen=self._buf.maxlen)
            log.info(f"Buffer restored: {len(self._buf)} snapshots from previous session.")
            return True
        except Exception as e:
            log.warning(f"Could not load buffer: {e}")
            return False

    def clear(self):
        self._buf.clear()

    def to_ohlcv(self, limit: int = 100) -> Optional[pd.DataFrame]:
        if len(self._buf) < 1:
            return None

        df = pd.DataFrame(list(self._buf))
        df["timestamp"] = pd.to_datetime(df["ts"], unit="s")
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)

        ohlcv = pd.DataFrame(index=df.index)
        ohlcv["close"]  = df["price"]
        ohlcv["open"]   = df["price"].shift(1).fillna(df["price"])
        ohlcv["high"]   = df["price"]
        ohlcv["low"]    = df["price"]
        ohlcv["volume"] = df["volume"]

        return ohlcv.tail(limit)


class IndodaxClient:
    def __init__(self):
        env = "DEMO" if cfg.INDODAX_DEMO else "LIVE"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._buffer = PriceBuffer()
        self._buffer.load(cfg.TRADING_PAIR)   # restore from previous session if available
        log.info(f"Indodax client initialized [{env}] | trade API: {cfg.api_base}")
        log.info("Market data: ticker polling mode (building candles in memory)")

    # ─── Auth ─────────────────────────────────────────────────────────────────

    def _sign(self, params: dict) -> tuple:
        params["timestamp"] = str(int(time.time() * 1000))
        params["recvWindow"] = "5000"
        body = urllib.parse.urlencode(params)
        sig  = hmac.new(
            cfg.INDODAX_API_SECRET.encode(),
            body.encode(),
            hashlib.sha512,
        ).hexdigest()
        return body, sig

    def _private(self, method: str, extra: Optional[dict] = None) -> dict:
        params = {"method": method}
        if extra:
            params.update(extra)
        body, sig = self._sign(params)
        headers = {
            **HEADERS,
            "Key":          cfg.INDODAX_API_KEY,
            "Sign":         sig,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = requests.post(PRIVATE_URL, data=body, headers=headers, timeout=10)
        resp.raise_for_status()
        if not resp.text.strip():
            raise RuntimeError(
                f"TAPI [{method}] returned empty response. "
                "Check your API key/secret and that INDODAX_DEMO matches your account type."
            )
        data = resp.json()
        if data.get("success") != 1:
            raise RuntimeError(f"TAPI error [{method}]: {data.get('error', data)}")
        return data.get("return", data)

    # ─── Public API ───────────────────────────────────────────────────────────

    def get_ticker(self, pair: str) -> dict:
        url  = f"{PUBLIC_URL}/{pair}/ticker"
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()["ticker"]

    def get_klines(self, pair: str, interval: str = "1", limit: int = 100) -> pd.DataFrame:
        """
        Fetch ticker, add to rolling buffer, return OHLCV DataFrame.
        Candles are built from accumulated ticker snapshots in memory.
        """
        ticker = self.get_ticker(pair)
        price     = float(ticker["last"])
        vol_24h   = float(ticker.get("vol_idr", ticker.get("volume", 0)))

        self._buffer.add(price=price, volume_24h=vol_24h)

        # Auto-save every 10 snapshots so progress survives a crash too
        if len(self._buffer) % 10 == 0:
            self._buffer.save(pair)

        warmup_needed = 30
        if len(self._buffer) < warmup_needed:
            remaining = warmup_needed - len(self._buffer)
            log.info(
                f"Warming up price buffer: {len(self._buffer)}/{warmup_needed} snapshots "
                f"({remaining} more cycles needed before indicators are reliable)"
            )

        df = self._buffer.to_ohlcv(limit)
        if df is None or df.empty:
            raise RuntimeError("Price buffer empty — no candles available yet.")

        log.debug(f"Candles from buffer: {len(df)} rows | price Rp {price:,.0f}")
        return df

    def get_orderbook(self, pair: str) -> dict:
        """Get best bid/ask from ticker — works on all pairs including low-cap coins."""
        ticker = self.get_ticker(pair)
        return {
            "best_bid": float(ticker["buy"]),
            "best_ask": float(ticker["sell"]),
        }

    # ─── Private API ──────────────────────────────────────────────────────────

    def get_balance(self) -> dict:
        info = self._private("getInfo")
        bal  = info.get("balance", {})
        base = cfg.base_currency
        return {
            "idr":  float(bal.get("idr", 0)),
            base:   float(bal.get(base, 0)),
            "raw":  bal,
        }

    def get_open_orders(self, pair: str) -> list:
        data   = self._private("openOrders", {"pair": pair})
        orders = data.get("orders", [])
        return list(orders.values()) if isinstance(orders, dict) else orders

    def cancel_order(self, pair: str, order_id: str, order_type: str) -> dict:
        return self._private("cancelOrder", {
            "pair": pair, "order_id": order_id, "type": order_type,
        })

    def get_trade_history(self, pair: str, count: int = 10) -> list:
        data   = self._private("tradeHistory", {"pair": pair, "count": str(count)})
        trades = data.get("trades", [])
        return list(trades.values()) if isinstance(trades, dict) else trades

    # ─── Orders ───────────────────────────────────────────────────────────────

    def buy_market(self, pair: str, idr_amount: float) -> dict:
        ob    = self.get_orderbook(pair)
        price = _smart_round(ob["best_ask"] * 1.005)
        idr   = int(round(idr_amount))
        if idr < MIN_ORDER_IDR:
            raise ValueError(f"Order too small: Rp {idr:,} < min Rp {MIN_ORDER_IDR:,}")
        log.info(f"[TRADE] BUY {pair} — Rp {idr:,} @ Rp {price:,}")
        return self._private("trade", {
            "pair": pair, "type": "buy",
            "price": str(price), "idr": str(idr),
        })

    def sell_market(self, pair: str, coin_amount: float) -> dict:
        ob    = self.get_orderbook(pair)
        price = _smart_round(ob["best_bid"] * 0.995)
        base  = cfg.base_currency
        coin  = f"{coin_amount:.8f}".rstrip("0").rstrip(".")
        log.info(f"[TRADE] SELL {coin} {base.upper()} @ Rp {price:,}")
        return self._private("trade", {
            "pair": pair, "type": "sell",
            "price": str(price), base: coin,
        })
