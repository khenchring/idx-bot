"""
Technical indicators implemented with pure pandas/numpy.
No pandas-ta, no numba, no C compiler required.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from config import cfg
from bot_logger import get_logger

log = get_logger("indicators")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast    = ema(close, fast)
    ema_slow    = ema(close, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(close: pd.Series, period: int = 20, std: float = 2.0):
    mid   = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return mid + std * sigma, mid, mid - std * sigma


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


@dataclass
class Indicators:
    symbol: str
    price: float
    price_change_pct: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    ema_fast: float
    ema_slow: float
    ema_cross: str
    bb_upper: float
    bb_mid: float
    bb_lower: float
    bb_pct: float
    volume: float
    volume_avg: float
    volume_ratio: float
    atr: float
    trend: str

    def summary(self) -> str:
        return (
            f"Price: {self.price:,.4f} ({self.price_change_pct:+.3f}%) | "
            f"RSI: {self.rsi:.1f} | MACD hist: {self.macd_hist:.4f} | "
            f"EMA cross: {self.ema_cross} | BB%: {self.bb_pct:.2f} | "
            f"ATR: {self.atr:,.4f} | Vol ratio: {self.volume_ratio:.2f}x | Trend: {self.trend}"
        )


def compute(df: pd.DataFrame, symbol: str) -> Indicators:
    close  = df["close"].astype(float)
    high   = df["high"].astype(float)
    low    = df["low"].astype(float)
    volume = df["volume"].astype(float)

    rsi_s       = rsi(close, cfg.RSI_PERIOD)
    rsi_val     = float(rsi_s.iloc[-1]) if not rsi_s.isna().all() else 50.0

    ml, sl, hl  = macd(close, cfg.EMA_FAST, cfg.EMA_SLOW, cfg.MACD_SIGNAL)
    macd_val    = float(ml.iloc[-1])
    macd_sig    = float(sl.iloc[-1])
    macd_hist   = float(hl.iloc[-1])

    ef          = ema(close, cfg.EMA_FAST)
    es          = ema(close, cfg.EMA_SLOW)
    ema_f       = float(ef.iloc[-1])
    ema_s       = float(es.iloc[-1])
    ema_cross   = "BULL" if ema_f > ema_s else "BEAR"

    bbu, bbm, bbl = bollinger_bands(close, cfg.BB_PERIOD, cfg.BB_STD)
    bu = float(bbu.iloc[-1]); bm = float(bbm.iloc[-1]); bl = float(bbl.iloc[-1])
    rng = bu - bl
    bbp = (float(close.iloc[-1]) - bl) / rng if rng > 0 else 0.5

    atr_s       = atr(high, low, close, 14)
    atr_val     = float(atr_s.iloc[-1]) if not atr_s.isna().all() else 0.0

    vn = float(volume.iloc[-1])
    va = float(volume.rolling(20).mean().iloc[-1])
    vr = vn / va if va > 0 else 1.0

    p0  = float(close.iloc[-1])
    p1  = float(close.iloc[-2]) if len(close) > 1 else p0
    pch = (p0 / p1 - 1) * 100

    s20 = float(close.rolling(20).mean().iloc[-1])
    s50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else s20
    trend = "UP" if s20 > s50 * 1.002 else ("DOWN" if s20 < s50 * 0.998 else "SIDEWAYS")

    return Indicators(
        symbol=symbol, price=p0, price_change_pct=pch,
        rsi=rsi_val, macd=macd_val, macd_signal=macd_sig, macd_hist=macd_hist,
        ema_fast=ema_f, ema_slow=ema_s, ema_cross=ema_cross,
        bb_upper=bu, bb_mid=bm, bb_lower=bl, bb_pct=bbp,
        volume=vn, volume_avg=va, volume_ratio=vr,
        atr=atr_val, trend=trend,
    )
