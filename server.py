"""
server.py — Web dashboard for the Indodax AI Trader
Runs the trader in a background thread and serves a live UI at http://localhost:5000
"""
import threading
import time
import json
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from bot_logger import get_logger

log = get_logger("server")

# ─── Shared state (thread-safe via lock) ──────────────────────────────────────

_lock = threading.Lock()
_state = {
    "status":       "starting",   # starting | running | stopped | error
    "pair":         "—",
    "price":        0,
    "balance_idr":  0,
    "balance_coin": 0,
    "position":     None,
    "last_action":  "—",
    "last_ai":      None,
    "daily_loss":   0,
    "trade_count":  0,
    "trades":       [],           # last 50 trades
    "logs":         [],           # last 100 log lines
    "cycle":        0,
    "dry_run":      True,
    "updated_at":   "—",
    "indicators":   None,
    "coin_profile": None,
    "trade_stats":  None,
}


def update_state(**kwargs):
    with _lock:
        _state.update(kwargs)
        _state["updated_at"] = datetime.utcnow().strftime("%H:%M:%S UTC")


def append_log(msg: str, level: str = "INF"):
    with _lock:
        _state["logs"].append({
            "t": datetime.utcnow().strftime("%H:%M:%S"),
            "level": level,
            "msg": msg,
        })
        _state["logs"] = _state["logs"][-100:]


def append_trade(trade: dict):
    with _lock:
        _state["trades"].insert(0, trade)
        _state["trades"] = _state["trades"][:50]


def get_state():
    with _lock:
        return dict(_state)


# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.logger.disabled = True
import logging
log_werkzeug = logging.getLogger("werkzeug")
log_werkzeug.setLevel(logging.ERROR)


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/state")
def api_state():
    return jsonify(get_state())


def run_server(host="0.0.0.0", port=5000):
    log.info(f"Dashboard: http://localhost:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


# ─── Dashboard HTML ───────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Indodax Trader</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@300;400;500&family=Geist:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:        #f7f5f2;
    --surface:   #ffffff;
    --border:    #e8e4df;
    --text:      #2c2825;
    --muted:     #9c9188;
    --faint:     #c8c0b8;
    --green:     #2d7d52;
    --green-bg:  #edf7f2;
    --red:       #b84040;
    --red-bg:    #fdf0f0;
    --amber:     #a06020;
    --amber-bg:  #fdf6ed;
    --blue:      #2858a0;
    --blue-bg:   #edf2fc;
    --mono:      'Geist Mono', 'Courier New', monospace;
    --sans:      'Geist', 'Helvetica Neue', sans-serif;
    --radius:    10px;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 13.5px;
    line-height: 1.6;
    min-height: 100vh;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    position: sticky; top: 0; z-index: 10;
  }
  .header-left  { display: flex; align-items: center; gap: 12px; }
  .header-right { display: flex; align-items: center; gap: 16px; }
  .logo {
    font-family: var(--mono); font-size: 12px; font-weight: 500;
    letter-spacing: 2px; color: var(--text); text-transform: uppercase;
  }
  .dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--faint); flex-shrink: 0;
  }
  .dot.running { background: var(--green); animation: breathe 2.5s ease-in-out infinite; }
  .dot.error   { background: var(--red); }
  @keyframes breathe { 0%,100%{opacity:1} 50%{opacity:0.4} }

  .badge {
    font-family: var(--mono); font-size: 10px; letter-spacing: 1px;
    padding: 3px 9px; border-radius: 20px; font-weight: 500;
  }
  .badge-dry  { background: var(--amber-bg); color: var(--amber); }
  .badge-live { background: var(--green-bg); color: var(--green); }

  .updated { font-family: var(--mono); font-size: 10px; color: var(--faint); }

  /* ── Layout ── */
  .layout {
    display: grid;
    grid-template-columns: 280px 1fr;
    grid-template-rows: auto auto;
    gap: 20px;
    padding: 20px 24px;
    max-width: 1200px;
    margin: 0 auto;
  }

  /* ── Cards ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
  }
  .card-title {
    font-family: var(--mono); font-size: 10px; font-weight: 500;
    letter-spacing: 2px; color: var(--faint); text-transform: uppercase;
    margin-bottom: 16px;
  }

  /* ── Sidebar ── */
  .sidebar { grid-row: 1 / 3; display: flex; flex-direction: column; gap: 16px; }

  /* ── Price ── */
  .price-value {
    font-family: var(--mono); font-size: 28px; font-weight: 400;
    color: var(--text); letter-spacing: -1px; line-height: 1;
  }
  .price-change {
    font-family: var(--mono); font-size: 11px; margin-top: 6px;
    color: var(--muted);
  }
  .price-change.up   { color: var(--green); }
  .price-change.down { color: var(--red); }

  /* ── Sparkline ── */
  .spark { width: 100%; height: 44px; margin: 12px 0; display: block; }

  /* ── Stat rows ── */
  .stat { display: flex; justify-content: space-between; align-items: baseline; padding: 7px 0; border-bottom: 1px solid var(--border); }
  .stat:last-child { border-bottom: none; }
  .stat-label { font-size: 12px; color: var(--muted); }
  .stat-value { font-family: var(--mono); font-size: 12px; font-weight: 500; }
  .stat-value.up    { color: var(--green); }
  .stat-value.down  { color: var(--red); }
  .stat-value.amber { color: var(--amber); }

  /* ── Indicators grid ── */
  .ind-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  }
  .ind-card {
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px;
  }
  .ind-label { font-size: 10px; color: var(--faint); letter-spacing: 1px; margin-bottom: 5px; text-transform: uppercase; }
  .ind-value { font-family: var(--mono); font-size: 14px; font-weight: 500; }
  .ind-value.up    { color: var(--green); }
  .ind-value.down  { color: var(--red); }
  .ind-value.neutral { color: var(--muted); }

  /* ── AI box ── */
  .ai-row { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
  .ai-action {
    font-family: var(--mono); font-size: 24px; font-weight: 500;
    letter-spacing: 1px; min-width: 70px;
  }
  .ai-action.up    { color: var(--green); }
  .ai-action.down  { color: var(--red); }
  .ai-action.neutral { color: var(--muted); }
  .ai-conf-wrap { flex: 1; }
  .ai-conf-label {
    display: flex; justify-content: space-between;
    font-family: var(--mono); font-size: 10px; color: var(--muted); margin-bottom: 5px;
  }
  .conf-bar {
    height: 4px; background: var(--border); border-radius: 2px; overflow: hidden;
  }
  .conf-fill { height: 100%; border-radius: 2px; transition: width 0.5s ease; }
  .ai-signal {
    font-family: var(--mono); font-size: 10px; padding: 3px 9px;
    border-radius: 20px; font-weight: 500; white-space: nowrap;
  }
  .ai-signal.bull { background: var(--green-bg); color: var(--green); }
  .ai-signal.bear { background: var(--red-bg);   color: var(--red); }
  .ai-signal.neu  { background: var(--bg);        color: var(--muted); border: 1px solid var(--border); }

  .ai-reason {
    font-size: 12.5px; color: var(--muted); line-height: 1.6;
    padding: 10px 14px; background: var(--bg); border-radius: 8px;
    border-left: 3px solid var(--border); margin-bottom: 12px;
  }
  .ai-reason.up   { border-left-color: var(--green); }
  .ai-reason.down { border-left-color: var(--red); }

  .sl-tp { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .sl-box, .tp-box {
    border-radius: 8px; padding: 10px 12px;
  }
  .sl-box { background: var(--red-bg);   border: 1px solid #f0d0d0; }
  .tp-box { background: var(--green-bg); border: 1px solid #c0e0d0; }
  .sl-label { font-size: 10px; letter-spacing: 1px; color: #c07070; margin-bottom: 3px; text-transform: uppercase; }
  .tp-label { font-size: 10px; letter-spacing: 1px; color: #508060; margin-bottom: 3px; text-transform: uppercase; }
  .sl-val { font-family: var(--mono); font-size: 13px; font-weight: 500; color: var(--red); }
  .tp-val { font-family: var(--mono); font-size: 13px; font-weight: 500; color: var(--green); }

  /* ── Position card ── */
  .pos-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .pos-item-label { font-size: 10px; color: var(--faint); letter-spacing: 1px; text-transform: uppercase; margin-bottom: 3px; }
  .pos-item-value { font-family: var(--mono); font-size: 13px; font-weight: 500; }

  /* ── Trade table ── */
  .trade-table { width: 100%; border-collapse: collapse; }
  .trade-table th {
    font-size: 10px; letter-spacing: 1px; color: var(--faint); text-transform: uppercase;
    text-align: left; padding-bottom: 10px; border-bottom: 1px solid var(--border); font-weight: 400;
  }
  .trade-table td {
    font-family: var(--mono); font-size: 12px;
    padding: 8px 0; border-bottom: 1px solid var(--bg); color: var(--text);
  }
  .trade-scroll { max-height: 220px; overflow-y: auto; }

  /* ── Console ── */
  .console {
    background: #faf9f7; border-radius: 8px; padding: 14px;
    font-family: var(--mono); font-size: 11.5px; line-height: 2;
    max-height: 200px; overflow-y: auto; border: 1px solid var(--border);
  }
  .log-row { display: flex; gap: 12px; }
  .log-t   { color: var(--faint); flex-shrink: 0; }
  .log-INF { color: #504840; }
  .log-WRN { color: var(--amber); }
  .log-ERR { color: var(--red); }
  .log-DBG { color: var(--faint); }

  /* ── Main content ── */
  .main { display: flex; flex-direction: column; gap: 16px; }
  .row  { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

  /* ── Momentum bar ── */
  .momentum-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .momentum-dots { display: flex; gap: 4px; }
  .m-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--border); }
  .m-dot.on { background: var(--green); }
  .momentum-label { font-size: 12px; color: var(--muted); }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--faint); }

  .empty { color: var(--faint); font-size: 12px; padding: 8px 0; }
  .divider { height: 1px; background: var(--border); margin: 14px 0; }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="dot" id="statusDot"></div>
    <div class="logo" id="pairLabel">Indodax Trader</div>
    <span class="badge badge-dry" id="modeBadge">DRY RUN</span>
  </div>
  <div class="header-right">
    <span class="updated" id="cycleLabel">cycle —</span>
    <span class="updated" id="updatedAt">—</span>
  </div>
</div>

<div class="layout">

  <!-- ── Sidebar ── -->
  <div class="sidebar">

    <!-- Price card -->
    <div class="card">
      <div class="card-title">Price</div>
      <div class="price-value" id="priceVal">Rp —</div>
      <div class="price-change" id="priceChange">—</div>
      <svg class="spark" id="sparkSvg" viewBox="0 0 240 44" preserveAspectRatio="none">
        <path id="sparkPath" fill="none" stroke-width="1.5" stroke-linejoin="round" stroke="var(--border)"/>
      </svg>
    </div>

    <!-- Portfolio card -->
    <div class="card">
      <div class="card-title">Portfolio</div>
      <div id="portfolioStats"></div>
    </div>

    <!-- Config card -->
    <div class="card">
      <div class="card-title">Settings</div>
      <div id="configStats"></div>
    </div>

  </div>

  <!-- ── Main ── -->
  <div class="main">

    <!-- Row 1: Indicators + AI -->
    <div class="row">

      <div class="card">
        <div class="card-title">Indicators</div>
        <div class="momentum-row">
          <div class="momentum-dots" id="mDots">
            <div class="m-dot"></div><div class="m-dot"></div>
            <div class="m-dot"></div><div class="m-dot"></div><div class="m-dot"></div>
          </div>
          <div class="momentum-label" id="mLabel">Momentum — / 5</div>
        </div>
        <div class="ind-grid" id="indGrid">
          <div class="ind-card"><div class="ind-label">RSI</div><div class="ind-value neutral">—</div></div>
          <div class="ind-card"><div class="ind-label">MACD</div><div class="ind-value neutral">—</div></div>
          <div class="ind-card"><div class="ind-label">EMA</div><div class="ind-value neutral">—</div></div>
          <div class="ind-card"><div class="ind-label">BB %</div><div class="ind-value neutral">—</div></div>
          <div class="ind-card"><div class="ind-label">ATR</div><div class="ind-value neutral">—</div></div>
          <div class="ind-card"><div class="ind-label">Trend</div><div class="ind-value neutral">—</div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">AI Decision</div>
        <div id="aiBox">
          <div class="ai-row">
            <div class="ai-action neutral" id="aiAction">WAIT</div>
            <div class="ai-conf-wrap">
              <div class="ai-conf-label">
                <span>Confidence</span>
                <span id="aiConfPct">—</span>
              </div>
              <div class="conf-bar"><div class="conf-fill" id="confFill" style="width:0%;background:var(--faint)"></div></div>
            </div>
            <div class="ai-signal neu" id="aiSignal">—</div>
          </div>
          <div class="ai-reason" id="aiReason">Waiting for first analysis...</div>
          <div class="sl-tp">
            <div class="sl-box"><div class="sl-label">Stop Loss</div><div class="sl-val" id="aiSL">—</div></div>
            <div class="tp-box"><div class="tp-label">Take Profit</div><div class="tp-val" id="aiTP">—</div></div>
          </div>
        </div>
      </div>

    </div>

    <!-- Row 2: Position + Trades -->
    <div class="row">

      <div class="card">
        <div class="card-title">Open Position</div>
        <div id="posBox"><div class="empty">No open position</div></div>
      </div>

      <div class="card">
        <div class="card-title">Trade History</div>
        <div class="trade-scroll">
          <table class="trade-table">
            <thead><tr>
              <th>Type</th><th>Price</th><th>Amount</th><th>P&amp;L</th><th>Time</th>
            </tr></thead>
            <tbody id="tradeBody"><tr><td colspan="5" class="empty">No trades yet</td></tr></tbody>
          </table>
        </div>
      </div>

    </div>

    <!-- Console -->
    <div class="card">
      <div class="card-title">Log</div>
      <div class="console" id="console"></div>
    </div>

  </div>
</div>

<script>
const fmt   = n => new Intl.NumberFormat('id-ID').format(Math.round(n));
const fmtD  = (n, d=2) => Number(n).toFixed(d);
const spark  = [];

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const s = await r.json();
    render(s);
  } catch(e) {}
}

function render(s) {
  // Header
  document.getElementById('updatedAt').textContent  = s.updated_at || '—';
  document.getElementById('cycleLabel').textContent = `cycle ${s.cycle || '—'}`;
  document.getElementById('pairLabel').textContent  = (s.pair || 'Indodax Trader').toUpperCase();

  const dot  = document.getElementById('statusDot');
  dot.className = 'dot ' + (s.status === 'running' ? 'running' : s.status === 'error' ? 'error' : '');

  const badge = document.getElementById('modeBadge');
  badge.textContent  = s.dry_run ? 'DRY RUN' : 'LIVE';
  badge.className    = 'badge ' + (s.dry_run ? 'badge-dry' : 'badge-live');

  // Price
  if (s.price > 0) {
    document.getElementById('priceVal').textContent = `Rp ${fmt(s.price)}`;
    spark.push(s.price);
    if (spark.length > 60) spark.shift();
    drawSpark();
  }

  const ind = s.indicators;
  if (ind) {
    const up = ind.price_change_pct >= 0;
    const pc = document.getElementById('priceChange');
    pc.textContent  = `${up ? '▲' : '▼'} ${Math.abs(ind.price_change_pct).toFixed(3)}% last candle`;
    pc.className    = 'price-change ' + (up ? 'up' : 'down');

    // Indicators
    const rc = ind.rsi > 68 ? 'down' : ind.rsi < 35 ? 'down' : 'up';
    const mc = ind.macd_hist > 0 ? 'up' : 'down';
    const ec = ind.ema_cross === 'BULL' ? 'up' : 'down';
    const bc = ind.bb_pct > 0.5 ? 'up' : 'neutral';
    const tc = ind.trend === 'UP' ? 'up' : ind.trend === 'DOWN' ? 'down' : 'neutral';

    document.getElementById('indGrid').innerHTML = `
      <div class="ind-card"><div class="ind-label">RSI 14</div><div class="ind-value ${rc}">${fmtD(ind.rsi,1)}</div></div>
      <div class="ind-card"><div class="ind-label">MACD</div><div class="ind-value ${mc}">${fmtD(ind.macd_hist,4)}</div></div>
      <div class="ind-card"><div class="ind-label">EMA Cross</div><div class="ind-value ${ec}">${ind.ema_cross}</div></div>
      <div class="ind-card"><div class="ind-label">BB %</div><div class="ind-value ${bc}">${fmtD(ind.bb_pct,2)}</div></div>
      <div class="ind-card"><div class="ind-label">ATR</div><div class="ind-value neutral">${fmt(ind.atr)}</div></div>
      <div class="ind-card"><div class="ind-label">Trend</div><div class="ind-value ${tc}">${ind.trend}</div></div>
    `;
  }

  // Momentum dots (from trade stats or last AI)
  if (s.last_ai) {
    const score = Math.round((s.last_ai.confidence || 0) / 20);
    const dots  = document.querySelectorAll('.m-dot');
    dots.forEach((d, i) => d.classList.toggle('on', i < score));
    document.getElementById('mLabel').textContent = `Momentum ${score}/5`;
  }

  // AI
  const ai = s.last_ai;
  if (ai) {
    const ac = ai.action === 'BUY' ? 'up' : ai.action === 'SELL' ? 'down' : 'neutral';
    const sc = ai.signal === 'BULLISH' ? 'bull' : ai.signal === 'BEARISH' ? 'bear' : 'neu';
    const fc = ai.confidence > 70 ? 'var(--green)' : ai.confidence > 50 ? 'var(--amber)' : 'var(--faint)';

    document.getElementById('aiAction').textContent = ai.action;
    document.getElementById('aiAction').className   = `ai-action ${ac}`;
    document.getElementById('aiConfPct').textContent = `${ai.confidence}%`;
    document.getElementById('confFill').style.width      = `${ai.confidence}%`;
    document.getElementById('confFill').style.background = fc;
    document.getElementById('aiSignal').textContent = ai.signal;
    document.getElementById('aiSignal').className   = `ai-signal ${sc}`;
    document.getElementById('aiReason').textContent = ai.reasoning || '—';
    document.getElementById('aiReason').className   = `ai-reason ${ac}`;
    document.getElementById('aiSL').textContent = ai.stop_loss ? `Rp ${fmt(ai.stop_loss)}` : '—';
    document.getElementById('aiTP').textContent = ai.take_profit ? `Rp ${fmt(ai.take_profit)}` : '—';
  }

  // Portfolio
  const pos    = s.position;
  const posVal = pos && s.price ? pos.amount * s.price * 0.997 : 0;
  const total  = s.balance_idr + posVal;
  const coin   = (s.pair || '').replace('_idr','').replace('_IDR','').toUpperCase();

  document.getElementById('portfolioStats').innerHTML = [
    ['IDR Balance',   `Rp ${fmt(s.balance_idr || 0)}`,  ''],
    [coin + ' Balance', (s.balance_coin||0).toFixed(6),  ''],
    ['Total Value',   `Rp ${fmt(total)}`,                ''],
    ['Daily Loss',    `Rp ${fmt(s.daily_loss||0)}`,      s.daily_loss > 0 ? 'down' : ''],
    ['Trades',        s.trade_count || 0,                ''],
  ].map(([l,v,c]) => `<div class="stat"><span class="stat-label">${l}</span><span class="stat-value ${c}">${v}</span></div>`).join('');

  // Config
  document.getElementById('configStats').innerHTML = [
    ['Interval',   `${s.trade_interval || 300}s`],
    ['Max Trade',  `Rp ${fmt(s.max_position_idr || 0)}`],
    ['TP / SL',    `${s.take_profit_pct || 2.5}% / ${s.stop_loss_pct || 1.5}%`],
    ['Min Conf',   `${s.min_confidence || 70}%`],
  ].map(([l,v]) => `<div class="stat"><span class="stat-label">${l}</span><span class="stat-value">${v}</span></div>`).join('');

  // Position
  if (pos && s.price) {
    const pnl    = pos.amount * s.price * 0.997 - pos.idr_spent;
    const pnlPct = (s.price / pos.entry_price - 1) * 100;
    const pc     = pnlPct >= 0 ? 'up' : 'down';
    document.getElementById('posBox').innerHTML = `
      <div class="pos-grid">
        <div><div class="pos-item-label">Amount</div><div class="pos-item-value">${pos.amount.toFixed(6)}</div></div>
        <div><div class="pos-item-label">Entry</div><div class="pos-item-value">Rp ${fmt(pos.entry_price)}</div></div>
        <div><div class="pos-item-label">P&amp;L</div><div class="pos-item-value ${pc}">${pnlPct >= 0?'+':''}${pnlPct.toFixed(2)}%</div></div>
      </div>
      <div style="height:10px"></div>
      <div class="pos-grid">
        <div><div class="pos-item-label">Stop Loss</div><div class="pos-item-value down">Rp ${fmt(pos.stop_loss)}</div></div>
        <div><div class="pos-item-label">Take Profit</div><div class="pos-item-value up">Rp ${fmt(pos.take_profit)}</div></div>
        <div><div class="pos-item-label">Unrealized</div><div class="pos-item-value ${pc}">Rp ${pnl>=0?'+':''}${fmt(pnl)}</div></div>
      </div>`;
  } else {
    document.getElementById('posBox').innerHTML = '<div class="empty">No open position</div>';
  }

  // Trades
  if (s.trades && s.trades.length) {
    document.getElementById('tradeBody').innerHTML = s.trades.map(t => {
      const tc = t.type === 'BUY' ? 'up' : 'down';
      const pc = t.pnl === null ? '' : t.pnl >= 0 ? 'up' : 'down';
      const pnlStr = t.pnl === null ? '—' : `${t.pnl>=0?'+':''}Rp ${fmt(t.pnl)}`;
      return `<tr>
        <td class="${tc}" style="font-weight:500">${t.type}</td>
        <td>${fmt(t.price)}</td>
        <td>${Number(t.amount).toFixed(4)}</td>
        <td class="${pc}">${pnlStr}</td>
        <td style="color:var(--faint)">${t.t}</td>
      </tr>`;
    }).join('');
  }

  // Console
  const cons = document.getElementById('console');
  cons.innerHTML = s.logs.slice().reverse().map(l =>
    `<div class="log-row"><span class="log-t">${l.t}</span><span class="log-${l.level}">${l.msg}</span></div>`
  ).join('');
}

function drawSpark() {
  if (spark.length < 2) return;
  const W = 240, H = 44;
  const min = Math.min(...spark), max = Math.max(...spark), r = max - min || 1;
  const d = spark.map((v,i) => {
    const x = (i / (spark.length-1)) * W;
    const y = H - ((v-min)/r) * (H-6) - 3;
    return `${i===0?'M':'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ');
  const path = document.getElementById('sparkPath');
  path.setAttribute('d', d);
  const last = spark[spark.length-1], first = spark[0];
  path.style.stroke = last >= first ? 'var(--green)' : 'var(--red)';
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""
