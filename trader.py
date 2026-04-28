import time
from datetime import datetime
from typing import Optional

from config import cfg
from indodax_client import IndodaxClient
from indicators import compute as compute_indicators, Indicators
from ai_agent import analyze, AIDecision, reflect_on_trade, review_position
from risk_manager import RiskManager
from bot_logger import get_logger
import server as ui
import memory

log = get_logger("trader")


class Trader:
    def __init__(self):
        self.client   = IndodaxClient()
        self.risk     = RiskManager()
        self.pair     = cfg.TRADING_PAIR
        self.base     = cfg.base_currency
        self.running  = False
        self._cycle   = 0
        self._position: Optional[dict] = None
        self._last_review_time: float  = 0

        ui.update_state(
            status="starting",
            pair=self.pair,
            dry_run=cfg.DRY_RUN,
            trade_interval=cfg.TRADE_INTERVAL_SECONDS,
            max_position_idr=cfg.MAX_POSITION_IDR,
            stop_loss_pct=cfg.STOP_LOSS_PERCENT,
            take_profit_pct=cfg.TAKE_PROFIT_PERCENT,
            min_confidence=cfg.MIN_AI_CONFIDENCE,
        )

        mode = "DRY RUN" if cfg.DRY_RUN else "LIVE"
        log.info("=" * 62)
        log.info(f"  INDODAX AI TRADER — {mode}")
        log.info(f"  Pair:         {self.pair.upper()}")
        log.info(f"  Interval:     {cfg.TRADE_INTERVAL_SECONDS}s ({cfg.TRADE_INTERVAL_SECONDS//60}min)")
        log.info(f"  Min profit:   {cfg.MIN_PROFIT_PERCENT}%")
        log.info(f"  TP / SL:      {cfg.TAKE_PROFIT_PERCENT}% / {cfg.STOP_LOSS_PERCENT}%")
        log.info(f"  Trailing SL:  {'ON' if cfg.USE_TRAILING_STOP else 'OFF'} ({cfg.TRAILING_STOP_PERCENT}%)")
        log.info(f"  Min momentum: {cfg.MIN_MOMENTUM_SCORE}/5 signals")
        log.info(f"  Min confidence: {cfg.MIN_AI_CONFIDENCE}%")
        log.info(f"  Max position: Rp {cfg.MAX_POSITION_IDR:,.0f}")
        log.info(f"  Dashboard:    http://localhost:5000")
        log.info("=" * 62)

    def run_cycle(self):
        self._cycle += 1
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        log.info(f"─── Cycle #{self._cycle} | {self.pair.upper()} | {ts} ───")
        ui.append_log(f"Cycle #{self._cycle} | {ts}")
        ui.update_state(status="running", cycle=self._cycle)

        if self.risk.daily_limit_hit():
            log.warning("Skipping — daily loss limit reached.")
            ui.append_log("Daily loss limit reached.", "WRN")
            return

        # Fetch market data
        try:
            df  = self.client.get_klines(self.pair, cfg.KLINE_INTERVAL, cfg.KLINE_LIMIT)
            ind = compute_indicators(df, self.pair.upper())
            bal = self.client.get_balance()
        except RuntimeError as e:
            if "buffer" in str(e).lower():
                buf_len = len(self.client._buffer)
                log.info(f"Warming up: {buf_len}/30 snapshots")
                ui.append_log(f"Warming up: {buf_len}/30 snapshots")
                try:
                    ticker = self.client.get_ticker(self.pair)
                    ui.update_state(price=float(ticker["last"]))
                except Exception:
                    pass
            else:
                log.error(f"Data fetch failed: {e}")
                ui.append_log(f"Data fetch failed: {e}", "ERR")
            return
        except Exception as e:
            log.error(f"Data fetch failed: {e}")
            ui.append_log(f"Data fetch failed: {e}", "ERR")
            return

        log.info(f"Market: {ind.summary()}")
        log.info(f"Balance: Rp {bal['idr']:,.0f} | {bal[self.base]:.6f} {self.base.upper()}")

        ui.update_state(
            price=ind.price,
            balance_idr=bal["idr"],
            balance_coin=bal[self.base],
            position=self._position,
            daily_loss=self.risk.daily_loss,
            trade_count=self.risk.trade_count,
            indicators={
                "rsi": ind.rsi, "macd_hist": ind.macd_hist,
                "ema_cross": ind.ema_cross, "bb_pct": ind.bb_pct,
                "atr": ind.atr, "trend": ind.trend,
                "price_change_pct": ind.price_change_pct,
            },
            coin_profile=memory.get_profile(self.pair),
            trade_stats=memory.get_stats(self.pair),
        )

        if self._position:
            pnl = self._position["amount"] * ind.price * 0.997 - self._position["idr_spent"]
            pnl_pct = (ind.price / self._position["entry_price"] - 1) * 100
            log.info(
                f"Position: {self._position['amount']:.6f} {self.base.upper()} "
                f"@ Rp {self._position['entry_price']:,.2f} | "
                f"P&L: Rp {pnl:+,.0f} ({pnl_pct:+.2f}%) | "
                f"SL: Rp {self._position['stop_loss']:,.2f} | "
                f"TP: Rp {self._position['take_profit']:,.2f}"
            )

        # Soft SL/TP (includes trailing stop update)
        if self._position:
            hit = self.risk.check_sl_tp_hit(ind.price, self._position)
            if hit:
                self._close_position(ind, "stop-loss triggered" if hit == "SL" else "take-profit triggered")
                return

        # Position review mode
        if self._position:
            now          = time.time()
            opened_ts    = self._position.get("opened_ts", now)
            elapsed_min  = (now - opened_ts) / 60
            since_review = now - self._last_review_time

            if since_review >= cfg.POSITION_REVIEW_SECONDS:
                pnl_now = self._position["amount"] * ind.price * 0.997 - self._position["idr_spent"]
                log.info(f"Position review at {elapsed_min:.0f}min | P&L: Rp {pnl_now:+,.0f}")
                ui.append_log(f"Review at {elapsed_min:.0f}min | P&L: Rp {pnl_now:+,.0f}")
                try:
                    decision = review_position(ind, self._position, elapsed_min)
                    self._last_review_time = now
                    ui.update_state(last_ai={
                        "action": decision.action, "confidence": decision.confidence,
                        "signal": decision.signal, "reasoning": decision.reasoning,
                        "stop_loss": None, "take_profit": None,
                    })
                    ui.append_log(f"[AI] {decision.action} | {decision.confidence}% | {decision.reasoning}")
                    if decision.action == "SELL":
                        self._close_position(ind, f"AI review SELL at {elapsed_min:.0f}min")
                except Exception as e:
                    log.error(f"Review failed: {e}")
                    ui.append_log(f"Review error: {e}", "ERR")
            else:
                remaining = int((cfg.POSITION_REVIEW_SECONDS - since_review) / 60)
                log.info(f"Holding | {elapsed_min:.0f}min in trade | next review ~{remaining}min")
            return

        # ── No position — check entry ─────────────────────────────────────────

        # Hard gate: momentum score check BEFORE calling AI
        passes, entry_mode, reason = self.risk.passes_entry_filter(ind)
        if not passes:
            log.info(f"Entry blocked: {reason}")
            ui.append_log(f"Entry blocked: {reason}")
            return

        score, reasons = self.risk.momentum_score(ind)
        log.info(f"Entry mode: {entry_mode.upper()} | Momentum {score}/5 — {', '.join(reasons)}")
        ui.append_log(f"[{entry_mode.upper()}] Momentum {score}/5 | {reason[:80]}")

        # AI analysis — pass entry mode so Claude can reason appropriately
        try:
            decision = analyze(ind, self._position, bal, entry_mode=entry_mode)
        except Exception as e:
            log.error(f"AI analysis failed: {e}")
            ui.append_log(f"AI failed: {e}", "ERR")
            return

        ui.update_state(last_ai={
            "action": decision.action, "confidence": decision.confidence,
            "signal": decision.signal, "reasoning": decision.reasoning,
            "stop_loss": decision.stop_loss_pct, "take_profit": decision.take_profit_pct,
        })
        ui.append_log(f"[AI] {decision.action} | {decision.confidence}% | {decision.reasoning}")

        self._execute(decision, ind, bal)

    def _execute(self, decision: AIDecision, ind: Indicators, bal: dict):
        if decision.confidence < cfg.MIN_AI_CONFIDENCE:
            log.info(f"[HOLD] Confidence {decision.confidence}% < {cfg.MIN_AI_CONFIDENCE}%")
            return
        if decision.action == "BUY":
            if self._position:
                log.info("[HOLD] BUY but already holding.")
                return
            if bal["idr"] < 10_000:
                log.warning(f"[HOLD] Insufficient IDR: Rp {bal['idr']:,.0f}")
                return
            self._open_position(decision, ind, bal)
        elif decision.action == "SELL":
            if not self._position:
                log.info("[HOLD] SELL but no position.")
                return
            self._close_position(ind, f"AI SELL ({decision.confidence}%)")
        else:
            log.info(f"[HOLD] {decision.reasoning}")

    def _open_position(self, decision: AIDecision, ind: Indicators, bal: dict):
        entry_mode = decision.entry_mode if hasattr(decision, "entry_mode") else "normal"

        if entry_mode == "overbought_momentum":
            # Overbought mode: tight scalp — quick TP, tight SL
            stop_loss, take_profit, sl_pct, tp_pct = self.risk.overbought_sl_tp(ind.price)
            idr_to_spend = self.risk.calc_idr_to_spend(bal["idr"], ind)
            decision.stop_loss_pct   = sl_pct
            decision.take_profit_pct = tp_pct
            log.info(f"Overbought scalp mode — quick TP {tp_pct:.1f}% / tight SL {sl_pct:.1f}%")
        elif cfg.USE_PROFIT_TARGET:
            idr_to_spend, tp_pct, sl_pct, expected = self.risk.calc_position_for_profit_target(ind.price)
            decision.stop_loss_pct   = sl_pct
            decision.take_profit_pct = tp_pct
            stop_loss   = self.risk.calc_stop_loss(ind.price, sl_pct)
            take_profit = self.risk.calc_take_profit(ind.price, tp_pct)
            log.info(f"Profit target: ~Rp {expected:,.0f} expected")
        else:
            idr_to_spend = self.risk.calc_idr_to_spend(bal["idr"], ind)
            stop_loss    = self.risk.calc_stop_loss(ind.price, decision.stop_loss_pct)
            take_profit  = self.risk.calc_take_profit(ind.price, decision.take_profit_pct)

        idr_to_spend = min(idr_to_spend, bal["idr"] * 0.95)
        coin_est     = (idr_to_spend * 0.997) / (ind.price * 1.005)

        # Enforce minimum profit gap (skip for overbought scalp — already set)
        if entry_mode != "overbought_momentum":
            min_tp = ind.price * (1 + cfg.MIN_PROFIT_PERCENT / 100)
            if take_profit < min_tp:
                take_profit = round(min_tp, 2)
                log.info(f"TP adjusted to enforce {cfg.MIN_PROFIT_PERCENT}% minimum: Rp {take_profit:,.2f}")

        self.risk.reset_trailing_stop(ind.price)

        log.info(
            f"[BUY] Rp {idr_to_spend:,.0f} → ~{coin_est:.6f} {self.base.upper()} "
            f"| TP: Rp {take_profit:,.2f} (+{decision.take_profit_pct:.1f}%) "
            f"| SL: Rp {stop_loss:,.2f} | Confidence: {decision.confidence}%"
        )

        if cfg.DRY_RUN:
            log.info("[DRY RUN] Order NOT sent.")
            import time as _t
            self._position = {
                "amount": coin_est, "entry_price": ind.price,
                "stop_loss": stop_loss, "take_profit": take_profit,
                "idr_spent": idr_to_spend, "opened_at": datetime.utcnow().isoformat(),
                "opened_ts": _t.time(),
            }
            trade_id = memory.record_open(
                pair=self.pair, entry_price=ind.price, amount=coin_est,
                idr_spent=idr_to_spend, stop_loss=stop_loss, take_profit=take_profit,
                indicators={"rsi": ind.rsi, "macd_hist": ind.macd_hist,
                            "ema_cross": ind.ema_cross, "trend": ind.trend, "bb_pct": ind.bb_pct},
                ai_reasoning=decision.reasoning,
            )
            self._position["trade_id"] = trade_id
            self._last_review_time = time.time()
            ui.update_state(position=self._position)
            ui.append_trade({"type": "BUY", "price": ind.price, "amount": coin_est, "pnl": None, "t": datetime.utcnow().strftime("%H:%M:%S")})
            return

        try:
            result   = self.client.buy_market(self.pair, idr_to_spend)
            received = float(result.get(f"receive_{self.base}", coin_est))
            import time as _t
            self._position = {
                "amount": received, "entry_price": ind.price,
                "stop_loss": stop_loss, "take_profit": take_profit,
                "idr_spent": idr_to_spend, "order_id": result.get("order_id"),
                "opened_at": datetime.utcnow().isoformat(), "opened_ts": _t.time(),
            }
            trade_id = memory.record_open(
                pair=self.pair, entry_price=ind.price, amount=received,
                idr_spent=idr_to_spend, stop_loss=stop_loss, take_profit=take_profit,
                indicators={"rsi": ind.rsi, "macd_hist": ind.macd_hist,
                            "ema_cross": ind.ema_cross, "trend": ind.trend, "bb_pct": ind.bb_pct},
                ai_reasoning=decision.reasoning,
            )
            self._position["trade_id"] = trade_id
            self._last_review_time = time.time()
            self.risk.increment_trades()
            ui.update_state(position=self._position, trade_count=self.risk.trade_count)
            ui.append_trade({"type": "BUY", "price": ind.price, "amount": received, "pnl": None, "t": datetime.utcnow().strftime("%H:%M:%S")})
            log.info(f"[TRADE] BUY filled: {received:.6f} {self.base.upper()} | order {result.get('order_id')}")
        except Exception as e:
            log.error(f"BUY failed: {e}")
            ui.append_log(f"BUY failed: {e}", "ERR")

    def _close_position(self, ind: Indicators, reason: str):
        if not self._position:
            return
        amount = self._position["amount"]
        idr_in = self._position["idr_spent"]
        pnl_pct = (ind.price / self._position["entry_price"] - 1) * 100

        log.info(f"[SELL] Closing {amount:.6f} | {reason} @ Rp {ind.price:,.2f} ({pnl_pct:+.2f}%)")
        ui.append_log(f"SELL — {reason} @ Rp {ind.price:,.2f} ({pnl_pct:+.2f}%)")

        if cfg.DRY_RUN:
            gross = amount * ind.price * 0.997
            pnl   = gross - idr_in
            log.info(f"[DRY RUN] PnL: Rp {pnl:+,.0f} ({pnl/idr_in*100:+.2f}%)")
            self.risk.record_pnl(pnl)
            trade_id = self._position.get("trade_id")
            closed   = None
            if trade_id:
                closed = memory.record_close(
                    trade_id=trade_id, exit_price=ind.price, pnl_idr=pnl,
                    exit_reason=reason,
                    exit_indicators={"rsi": ind.rsi, "macd_hist": ind.macd_hist,
                                     "ema_cross": ind.ema_cross, "trend": ind.trend},
                )
            self._position = None
            ui.update_state(position=None, daily_loss=self.risk.daily_loss, trade_count=self.risk.trade_count)
            ui.append_trade({"type": "SELL", "price": ind.price, "amount": amount, "pnl": pnl, "t": datetime.utcnow().strftime("%H:%M:%S")})
            if closed:
                log.info("[AI] Running post-trade reflection...")
                try:
                    reflect_on_trade(closed, ind)
                except Exception as e:
                    log.warning(f"Reflection failed: {e}")
            return

        try:
            result = self.client.sell_market(self.pair, amount)
            gross  = float(result.get("receive_idr", amount * ind.price * 0.997))
            pnl    = gross - idr_in
            self.risk.record_pnl(pnl)
            self.risk.increment_trades()
            trade_id = self._position.get("trade_id")
            closed   = None
            if trade_id:
                closed = memory.record_close(
                    trade_id=trade_id, exit_price=ind.price, pnl_idr=pnl,
                    exit_reason=reason,
                    exit_indicators={"rsi": ind.rsi, "macd_hist": ind.macd_hist,
                                     "ema_cross": ind.ema_cross, "trend": ind.trend},
                )
            self._position = None
            ui.update_state(position=None, daily_loss=self.risk.daily_loss, trade_count=self.risk.trade_count)
            ui.append_trade({"type": "SELL", "price": ind.price, "amount": amount, "pnl": pnl, "t": datetime.utcnow().strftime("%H:%M:%S")})
            log.info(f"[TRADE] SELL filled | PnL: Rp {pnl:+,.0f} ({pnl/idr_in*100:+.2f}%)")
            if closed:
                log.info("[AI] Running post-trade reflection...")
                try:
                    reflect_on_trade(closed, ind)
                except Exception as e:
                    log.warning(f"Reflection failed: {e}")
        except Exception as e:
            log.error(f"SELL failed: {e}")
            ui.append_log(f"SELL failed: {e}", "ERR")

    def start(self):
        self.running = True
        ui.update_state(status="running")
        log.info(f"Starting loop every {cfg.TRADE_INTERVAL_SECONDS}s. Press Ctrl+C to stop.")
        try:
            while self.running:
                try:
                    self.run_cycle()
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    log.error(f"Unexpected error: {e}", exc_info=True)
                    ui.append_log(f"Error: {e}", "ERR")
                if self.running:
                    try:
                        time.sleep(cfg.TRADE_INTERVAL_SECONDS)
                    except KeyboardInterrupt:
                        break
        finally:
            self.client._buffer.save(self.pair)
            ui.update_state(status="stopped")
            log.info("Trader stopped. Buffer saved.")
