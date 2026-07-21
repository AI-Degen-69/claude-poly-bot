"""Copy-trade dashboard: THEIR actual trades vs a realistic FOLLOWER simulation.

Two things are shown side by side for the shadowed account:
  THEIRS   -- their fills at their own prices (what the activity page shows,
              turned into P&L). This is the account's own edge.
  FOLLOWER -- our simulated follow: on detecting each trade we price against
              the REAL live CLOB book, capped by real resting depth.

The gap between the two columns is the cost of being a follower: detection
latency, price drift during that latency, and depth that isn't there any more.
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from follow import store, pnl, metrics
from follow.accounts import ACCOUNTS, SHADOW_ACCOUNT, BY_KEY

app = FastAPI(title="poly copy-trade tracker")


def _tracker_alive() -> bool:
    p = Path(__file__).resolve().parent.parent / "follow.pid"
    if not p.exists():
        return False
    try:
        import sys
        pid = int(p.read_text().strip())
        if sys.platform == "win32":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return bool(ok) and code.value == 259
        os.kill(pid, 0)
        return True
    except Exception:
        return False


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


@app.get("/api/follow/state")
async def state():
    def build():
        acct = BY_KEY[SHADOW_ACCOUNT]
        theirs = pnl.account_pnl(SHADOW_ACCOUNT)
        follower = pnl.shadow_pnl(SHADOW_ACCOUNT)
        return {
            "now": time.time(),
            "backend": store.backend_name(),
            "tracker_running": _tracker_alive(),
            "shadow_account": SHADOW_ACCOUNT,
            "handle": acct.handle,
            "address": acct.address,
            "theirs": theirs,
            "follower": follower,
            "epoch": store.get_epoch(),
            "profile": metrics.profile(SHADOW_ACCOUNT),
            "shadow_feed": store.recent_shadow(SHADOW_ACCOUNT, 20),
            "others": [pnl.account_pnl(a.key) for a in ACCOUNTS
                       if a.key != SHADOW_ACCOUNT],
        }
    return await asyncio.to_thread(build)


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>COPY-TRADE · THEIRS vs FOLLOWER</title>
<style>
  :root{
    --bg:#0b0d0e; --panel:#14181a; --panel2:#0f1214; --border:#242a2c;
    --txt:#d7dcd9; --dim:#7c8783; --hi:#f0f4f2;
    --amber:#eda92c; --green:#46c46a; --red:#e2564f; --blue:#5aa9d6;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font:13px/1.45 system-ui,sans-serif;-webkit-font-smoothing:antialiased}
  .bar{display:flex;align-items:center;gap:14px;padding:9px 16px;
    border-bottom:1px solid var(--border);background:var(--panel2);
    position:sticky;top:0;z-index:3}
  .bar b{color:var(--amber);letter-spacing:1.2px}
  .bar a{color:var(--dim);text-decoration:none;font-size:11px}
  .bar a:hover{color:var(--amber)}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
  .wrap{max-width:1400px;margin:0 auto;padding:12px}
  .vs{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media(max-width:900px){.vs{grid-template-columns:1fr}}
  .card{border:1px solid var(--border);background:var(--panel)}
  .card h2{margin:0;padding:10px 14px;font-size:12px;letter-spacing:1px;
    border-bottom:1px solid var(--border);display:flex;justify-content:space-between}
  .theirs h2{color:var(--blue)} .follow h2{color:var(--amber)}
  .stat{display:flex;justify-content:space-between;padding:7px 14px;
    font-family:var(--mono);font-variant-numeric:tabular-nums}
  .stat span:first-child{color:var(--dim);font-size:11px;letter-spacing:.4px}
  .big{font-size:24px;font-weight:700;padding:12px 14px 8px}
  .sep{height:1px;background:var(--border)}
  .g{color:var(--green)} .r_{color:var(--red)} .d{color:var(--dim)} .a{color:var(--amber)}
  .full{margin-top:12px}
  table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
  th{color:var(--dim);font-weight:400;text-align:left;padding:5px 14px;
    font-size:10px;letter-spacing:.6px;border-bottom:1px solid var(--border)}
  td{padding:3px 14px;white-space:nowrap;font-variant-numeric:tabular-nums}
  td.r,th.r{text-align:right}
  table.mirror td{padding:7px 14px;font-size:13px}
  table.mirror td.lab{color:var(--dim);font-size:11px;letter-spacing:.5px;
    font-family:system-ui,sans-serif}
  table.mirror tr.strong td{font-size:19px;font-weight:700;padding:12px 14px}
  table.mirror tr:not(:last-child) td{border-bottom:1px solid #1b2022}
  table.mirror th{padding:8px 14px}
  th.blue{color:var(--blue)} th.amb{color:var(--amber)}
  .sub{color:var(--dim);font-size:9px;letter-spacing:0;font-weight:400}
  .gap{background:var(--panel2);border:1px solid var(--border);padding:12px 14px;
    margin-top:12px;font-family:var(--mono);font-size:12px}
  .gap b{color:var(--amber)}
  .bars{display:flex;flex-direction:column;gap:3px;padding:8px 14px 12px}
  .brow{display:grid;grid-template-columns:64px 1fr 92px;gap:8px;align-items:center;
    font-family:var(--mono);font-size:10px}
  .btrack{height:9px;background:#1b2022;position:relative}
  .bfill{height:100%;background:var(--blue);opacity:.8}
  .muted{color:var(--dim);padding:10px 14px;font-family:var(--mono);font-size:11px}
</style></head><body>
<div class="bar">
  <b>COPY-TRADE LAB</b>
  <span id="who" class="d"></span>
  <span id="run"></span>
  <a id="prof" href="#" target="_blank" rel="noopener">profile ↗</a>
  <span style="margin-left:auto" class="d" id="clock"></span>
</div>
<div class="wrap">
  <div class="card">
    <h2><span>THEIRS vs FOLLOWER · same clock, same $5,000 start</span>
        <span class="d" id="since"></span></h2>
    <table class="mirror"><thead><tr>
      <th></th><th class="r blue">THEIRS<br><span class="sub">at their price</span></th>
      <th class="r amb">FOLLOWER<br><span class="sub">at real book price</span></th>
      <th class="r">GAP</th>
    </tr></thead><tbody id="mirror"></tbody></table>
  </div>

  <div class="gap" id="gapline"></div>

  <div class="card full">
    <h2><span>FOLLOW ATTEMPTS · live</span><span class="d">their price vs what we'd get</span></h2>
    <div style="max-height:300px;overflow:auto">
      <table><thead><tr>
        <th>TIME</th><th>SIDE</th><th>OUT</th>
        <th class="r">THEIR PX</th><th class="r">OUR PX</th><th class="r">SLIP</th>
        <th class="r">SH</th><th class="r">LAG</th><th>STATUS</th>
      </tr></thead><tbody id="feed"></tbody></table>
    </div>
  </div>

  <div class="vs full">
    <div class="card">
      <h2><span>EXECUTION QUALITY · follower only</span><span class="d">why the gap exists</span></h2>
      <div id="exq"></div>
    </div>
    <div class="card">
      <h2><span>PROFILE · how they trade</span><span class="d" id="pwin"></span></h2>
      <div id="prof2"></div>
    </div>
    <div class="card">
      <h2><span>WHERE THEIR MONEY GOES</span><span class="d">by entry price</span></h2>
      <div class="bars" id="dist"></div>
    </div>
  </div>
</div>
<script>
const money=(n)=>((n<0?'-':'+')+'$'+Math.abs(n).toFixed(2));
const cls=(n)=>n>0?'g':(n<0?'r_':'d');
const t2=(ts)=>new Date(ts*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});
const pct=(n)=>n==null?'—':(n*100).toFixed(0)+'%';
const row=(k,v,c)=>`<div class="stat"><span>${k}</span><span class="${c||''}">${v}</span></div>`;

// Mirrored rows: each metric on ONE line with THEIRS and FOLLOWER directly
// opposite each other, so the comparison reads across instead of between cards.
function mrow(label, a, b, gap, opt){
  opt = opt || {};
  const f = opt.fmt || ((v)=>v);
  const ca = opt.colorA ? cls(a) : '';
  const cb = opt.colorB ? cls(b) : '';
  const g = gap===null||gap===undefined ? '' :
    `<span class="${cls(gap)}">${opt.gapFmt?opt.gapFmt(gap):money(gap)}</span>`;
  return `<tr class="${opt.strong?'strong':''}">
    <td class="lab">${label}</td>
    <td class="r ${ca}">${a===null||a===undefined?'—':f(a)}</td>
    <td class="r ${cb}">${b===null||b===undefined?'—':f(b)}</td>
    <td class="r">${g}</td></tr>`;
}

async function tick(){
  try{
    const s = await (await fetch('/api/follow/state',{cache:'no-store'})).json();
    const T=s.theirs, F=s.follower;
    const usd=(v)=>'$'+v.toFixed(2);
    document.getElementById('mirror').innerHTML =
      mrow('REALIZED P&L', T.realized_pnl, F.realized_pnl,
           F.realized_pnl - T.realized_pnl,
           {fmt:money, colorA:1, colorB:1, strong:1}) +
      mrow('EQUITY', T.equity, F.equity, F.equity - T.equity, {fmt:usd}) +
      mrow('OPEN (at cost)', T.open_value, F.open_value, null, {fmt:usd}) +
      mrow('MARKETS RESOLVED', T.markets_resolved, F.markets_resolved, null) +
      mrow('MARKETS WON / LOST', `${T.markets_won}/${T.markets_lost}`,
           `${F.markets_won}/${F.markets_lost}`, null) +
      mrow('WIN RATE', T.win_rate, F.win_rate,
           (T.win_rate!=null&&F.win_rate!=null)?(F.win_rate-T.win_rate):null,
           {fmt:pct, gapFmt:(g)=>((g>0?'+':'')+(g*100).toFixed(0)+'pts')}) +
      mrow('FILLS', T.fills, F.filled, null,
           {fmt:(v)=>Number(v).toLocaleString()});
    document.getElementById('since').textContent =
      s.epoch ? 'since '+t2(s.epoch)+' · '+((s.now-s.epoch)/60).toFixed(0)+' min' : '';
    document.getElementById('who').textContent = s.handle;
    document.getElementById('prof').href='https://polymarket.com/profile/'+s.address;
    const r=document.getElementById('run');
    r.innerHTML=`<span class="dot" style="background:${s.tracker_running?'var(--green)':'var(--red)'}"></span>`+
                (s.tracker_running?'TRACKER RUNNING':'TRACKER STOPPED');
    r.style.color=s.tracker_running?'var(--green)':'var(--red)';
    document.getElementById('clock').textContent=t2(s.now);

    const d=T.realized_pnl - F.realized_pnl;
    document.getElementById('gapline').innerHTML =
      `THE COST OF FOLLOWING &nbsp;→&nbsp; they made <b>${money(T.realized_pnl)}</b>, ` +
      `a follower made <b>${money(F.realized_pnl)}</b> &nbsp;·&nbsp; gap <b>${money(-d)}</b>` +
      (F.median_lag!=null?` &nbsp;·&nbsp; median lag <b>${F.median_lag.toFixed(1)}s</b>`:'') +
      (F.avg_slippage!=null?` &nbsp;·&nbsp; avg slippage <b>${(F.avg_slippage*100).toFixed(2)}¢</b> per share`:'');

    document.getElementById('feed').innerHTML = (s.shadow_feed||[]).map(f=>{
      const ok=f.status==='filled';
      return `<tr>
        <td class="d">${t2(f.their_ts)}</td>
        <td class="${f.side==='BUY'?'g':'a'}">${f.side}</td>
        <td>${f.outcome||''}</td>
        <td class="r">${f.their_price!=null?f.their_price.toFixed(3):'—'}</td>
        <td class="r">${f.our_price!=null?f.our_price.toFixed(3):'—'}</td>
        <td class="r ${f.slippage>0?'r_':(f.slippage<0?'g':'d')}">${f.slippage!=null?(f.slippage>0?'+':'')+f.slippage.toFixed(3):'—'}</td>
        <td class="r d">${f.our_shares?f.our_shares.toFixed(0):'—'}</td>
        <td class="r d">${f.lag_sec!=null?f.lag_sec.toFixed(0)+'s':'—'}</td>
        <td class="${ok?'g':'d'}">${f.status}</td></tr>`;
    }).join('') || '<tr><td class="d" colspan=9>no follow attempts yet</td></tr>';

    document.getElementById('exq').innerHTML =
      row('FILLED / OPPORTUNITIES', `${F.filled} / ${F.attempted}`) +
      row('FILL RATE', pct(F.fill_rate), F.fill_rate!=null&&F.fill_rate<0.5?'r_':'g') +
      row('AVG SLIPPAGE', F.avg_slippage==null?'—':
          ((F.avg_slippage>0?'+':'')+(F.avg_slippage*100).toFixed(2)+'¢ /share'),
          F.avg_slippage>0?'r_':'g') +
      row('MEDIAN FOLLOW LAG', F.median_lag==null?'—':F.median_lag.toFixed(1)+'s','a') +
      '<div class="sep"></div>' +
      row('MISSED · market closed', F.missed_closed,'d') +
      row('MISSED · no depth', F.no_depth,'d') +
      row('MISSED · no book', F.no_book,'d');

    const p=s.profile||{};
    document.getElementById('pwin').textContent = p.n? `last ${p.window_h}h · ${p.n.toLocaleString()} fills`:'';
    document.getElementById('prof2').innerHTML = p.n? (
      row('TRADES / HOUR', p.trades_per_hour.toFixed(0)) +
      row('MARKETS / HOUR', p.markets_per_hour.toFixed(1)) +
      row('FILLS / MARKET', p.fills_per_market.toFixed(1)) +
      row('MEDIAN GAP', p.median_gap_sec!=null?p.median_gap_sec.toFixed(1)+'s':'—') +
      '<div class="sep"></div>' +
      row('BUY / SELL', p.buy_pct.toFixed(0)+'% / '+p.sell_pct.toFixed(0)+'%') +
      row('MEDIAN TRADE', '$'+p.median_usd.toFixed(2)) +
      row('AVG TRADE', '$'+p.avg_usd.toFixed(2)) +
      row('LARGEST', '$'+p.max_usd.toFixed(0)) +
      row('TOTAL TURNOVER', '$'+p.total_usd.toLocaleString(undefined,{maximumFractionDigits:0})) +
      row('MARKETS', (p.families||[]).map(f=>f[0]+' '+f[1]).join(' · '),'d')
    ) : '<div class="muted">no data</div>';

    const mx=Math.max(...(p.price_dist||[{pct_usd:1}]).map(x=>x.pct_usd),1);
    document.getElementById('dist').innerHTML=(p.price_dist||[]).map(b=>`
      <div class="brow"><span class="d">${b.label}</span>
        <span class="btrack"><span class="bfill" style="width:${100*b.pct_usd/mx}%"></span></span>
        <span class="d">${b.pct_usd.toFixed(1)}% $ · ${b.n}</span></div>`).join('');
  }catch(e){ document.getElementById('run').textContent='API ERROR: '+e; }
}
tick(); setInterval(tick,3000);
</script></body></html>"""
