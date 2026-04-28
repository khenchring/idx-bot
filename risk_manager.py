import time
from datetime import datetime, date
from typing import Optional
from config import cfg
from indicators import Indicators
from bot_logger import get_logger

log = get_logger("risk")


class RiskManager:
    def __init__(self):
        self._daily_loss: float  = 0.0
        self._day: date          = datetime.utcnow().date()
        self._trade_count: int   = 0
        self._peak_price: float  = 0.0   # for trailing stop

    def _reset_if_new_day(self):
        today = datetime.utcnow().date()
        if today != self._day:
            log.info("[RISK] New day — resetting daily loss counter.")
            self._daily_loss = 0.0
            self._trade_count = 0
            self._day = today

    def record_pnl(self, pnl_idr: float):
        self._reset_if_new_day()
        if pnl_idr < 0:
            self._daily_loss += abs(pnl_idr)
            log.warning(f"[RISK] Daily loss: Rp {self._daily_loss:,.0f} / Rp {cfg.MAX_DAILY_LOSS_IDR:,.0f}")

    def daily_limit_hit(self) -> bool:
        self._reset_if_new_day()
        if self._daily_loss >= cfg.MAX_DAILY_LOSS_IDR:
            log.error(f"[RISK] Daily loss limit hit: Rp {self._daily_loss:,.0f}. No more trades today.")
            return True
        return False

    # ─── Position sizing ──────────────────────────────────────────────────────

    def calc_position_for_profit_target(self, entry_price: float) -> tuple:
        """
        Size position so that a MIN_PROFIT_PERCENT move gives TARGET profit.
        Returns (idr_to_spend, tp_pct, sl_pct, expected_profit_idr)
        """
        target_mid    = (cfg.TARGET_PROFIT_MIN_IDR + cfg.TARGET_PROFIT_MAX_IDR) / 2
        move_pct      = max(cfg.MIN_PROFIT_PERCENT, 2.0)   # at least 2%

        # position = profit / move_pct
        idr_needed   = target_mid / (move_pct / 100)
        idr_to_spend = max(10_000, min(idr_needed, cfg.MAX_POSITION_IDR))

        # TP% to hit target with this position size
        tp_pct = max((target_mid / idr_to_spend) * 100, cfg.MIN_PROFIT_PERCENT)
        tp_pct = max(tp_pct, 2.0)   # hard minimum 2%

        # SL at 50% of TP distance (2:1 R:R)
        sl_pct = max(tp_pct / 2.0, cfg.STOP_LOSS_PERCENT)

        expected = idr_to_spend * (tp_pct / 100)

        log.info(
            f"[RISK] Position: Rp {idr_to_spend:,.0f} | "
            f"TP: {tp_pct:.2f}% | SL: {sl_pct:.2f}% | "
            f"Expected: Rp {expected:,.0f}"
        )
        return idr_to_spend, tp_pct, sl_pct, expected

    def calc_idr_to_spend(self, idr_balance: float, ind: Indicators) -> float:
        risk   = idr_balance * (cfg.RISK_PER_TRADE_PERCENT / 100)
        capped = min(risk, cfg.MAX_POSITION_IDR)
        return max(capped, 10_000)

    def calc_stop_loss(self, entry_price: float, sl_pct: Optional[float] = None) -> float:
        pct = sl_pct if sl_pct else cfg.STOP_LOSS_PERCENT
        return round(entry_price * (1 - pct / 100), 2)

    def calc_take_profit(self, entry_price: float, tp_pct: Optional[float] = None) -> float:
        pct = tp_pct if tp_pct else max(cfg.TAKE_PROFIT_PERCENT, cfg.MIN_PROFIT_PERCENT)
        return round(entry_price * (1 + pct / 100), 2)

    # ─── Trailing stop ────────────────────────────────────────────────────────

    def update_trailing_stop(self, current_price: float, position: dict) -> float:
        """
        Raises the stop-loss as price moves up.
        Returns the new (potentially higher) stop-loss price.
        """
        if not cfg.USE_TRAILING_STOP:
            return position["stop_loss"]

        # Track peak price
        if current_price > self._peak_price:
            self._peak_price = current_price

        # Trail stop = peak - TRAILING_STOP_PERCENT
        trail_stop = self._peak_price * (1 - cfg.TRAILING_STOP_PERCENT / 100)

        # Only raise stop, never lower it
        current_sl = position["stop_loss"]
        if trail_stop > current_sl:
            log.info(
                f"[RISK] Trailing stop raised: Rp {current_sl:,.2f} → Rp {trail_stop:,.2f} "
                f"(peak: Rp {self._peak_price:,.2f})"
            )
            return round(trail_stop, 2)
        return current_sl

    def reset_trailing_stop(self, entry_price: float):
        self._peak_price = entry_price

    # ─── Entry filters ────────────────────────────────────────────────────────

    def momentum_score(self, ind: Indicators) -> tuple:
        """
        Score 0-5 based on how many signals are aligned for a long entry.
        Returns (score, reasons).
        """
        score   = 0
        reasons = []

        # 1. RSI in healthy zone (not oversold, not overbought)
        if cfg.MIN_RSI_ENTRY <= ind.rsi <= cfg.MAX_RSI_ENTRY:
            score += 1
            reasons.append(f"RSI {ind.rsi:.1f} in buy zone")
        else:
            reasons.append(f"RSI {ind.rsi:.1f} outside buy zone")

        # 2. MACD histogram positive and growing
        if ind.macd_hist > 0 and ind.macd > 0:
            score += 1
            reasons.append("MACD bullish")
        else:
            reasons.append("MACD bearish/flat")

        # 3. EMA cross bullish
        if ind.ema_cross == "BULL":
            score += 1
            reasons.append("EMA cross BULL")
        else:
            reasons.append("EMA cross BEAR")

        # 4. Price above BB midline (upward momentum)
        if ind.bb_pct > 0.5:
            score += 1
            reasons.append(f"Price above BB mid (BB% {ind.bb_pct:.2f})")
        else:
            reasons.append(f"Price below BB mid (BB% {ind.bb_pct:.2f})")

        # 5. Volume elevated (real move, not noise)
        if ind.volume_ratio >= cfg.MIN_VOLUME_RATIO:
            score += 1
            reasons.append(f"Volume {ind.volume_ratio:.2f}x avg ✓")
        else:
            reasons.append(f"Low volume {ind.volume_ratio:.2f}x avg")

        return score, reasons

    def passes_entry_filter(self, ind: Indicators) -> tuple:
        """
        Returns (passes: bool, reason: str).
        Hard gates that block entry regardless of AI confidence.
        """
        score, reasons = self.momentum_score(ind)

        if score < cfg.MIN_MOMENTUM_SCORE:
            return False, f"Momentum score {score}/{cfg.MIN_MOMENTUM_SCORE} required — {', '.join(reasons[:2])}"

        if ind.rsi > cfg.MAX_RSI_ENTRY:
            return False, f"RSI {ind.rsi:.1f} too high (max {cfg.MAX_RSI_ENTRY}) — overbought"

        if ind.rsi < cfg.MIN_RSI_ENTRY:
            return False, f"RSI {ind.rsi:.1f} too low (min {cfg.MIN_RSI_ENTRY}) — potential freefall"

        if ind.volume_ratio < cfg.MIN_VOLUME_RATIO:
            return False, f"Volume too low: {ind.volume_ratio:.2f}x (need {cfg.MIN_VOLUME_RATIO}x)"

        return True, f"Score {score}/5 — {', '.join(reasons)}"

    # ─── SL/TP check ──────────────────────────────────────────────────────────

    def check_sl_tp_hit(self, current_price: float, position: dict) -> Optional[str]:
        # Update trailing stop first
        new_sl = self.update_trailing_stop(current_price, position)
        position["stop_loss"] = new_sl

        if current_price <= position["stop_loss"]:
            log.warning(f"[SL] Price Rp {current_price:,.2f} ≤ SL Rp {position['stop_loss']:,.2f}")
            return "SL"
        if current_price >= position["take_profit"]:
            log.info(f"[TP] Price Rp {current_price:,.2f} ≥ TP Rp {position['take_profit']:,.2f}")
            return "TP"
        return None

    def increment_trades(self):
        self._trade_count += 1

    @property
    def daily_loss(self) -> float:
        self._reset_if_new_day()
        return self._daily_loss

    @property
    def trade_count(self) -> int:
        return self._trade_count
