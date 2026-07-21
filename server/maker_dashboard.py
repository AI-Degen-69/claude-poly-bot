"""Maker dashboard. Separate app, separate port (8788), separate DB.

Self-contained HTML -- no build step, no shared components with the taker UI, so
the two can never drift into each other.

Layout mirrors what proved useful on the taker side (live market, order flow,
decision log) plus the maker-only panels: fill quality, edge decomposition,
inventory discipline, and a sample-size tracker so you can see at a glance
whether the data is anywhere near conclusive.
"""
from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from maker import kpi, store
from maker.config import load as load_cfg

cfg = load_cfg()
app = FastAPI(title="maker sim")

_cache = {"ts": 0.0, "data": None}


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


@app.get("/api/state")
def state():
    now = time.time()
    if _cache["data"] is None or now - _cache["ts"] > 4:
        try:
            _cache["data"] = kpi.report()
            _cache["ts"] = now
        except Exception as e:
            return {"error": str(e)}
    d = dict(_cache["data"])
    d["now"] = now
    d["live"] = store.get_live_state()
    d["decisions"] = kpi.recent_decisions(50)
    d["recent_fills"] = kpi.recent_fills(25)
    d["config"] = {
        "quote_shares": cfg.quote_shares,
        "ticks_below_ask": cfg.ticks_below_ask,
        "target_balance": cfg.target_balance,
        "max_pair_cost": cfg.max_pair_cost,
        "max_fills_per_market": cfg.max_fills_per_market,
        "max_cost_per_market": cfg.max_cost_per_market,
    }
    return d


PAGE = r"""
<style>
 :root{--bg:#0b0d0e;--pan:#13171a;--bd:#232a2e;--tx:#d6dbd8;--dim:#79847f;
       --am:#eda92c;--gn:#46c46a;--rd:#e2564f;--bl:#5b9bd5;--hi:#f2f5f3}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--tx);
      font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace}
 /* ---- top bars ---- */
 .bar{display:flex;align-items:center;gap:12px;padding:7px 14px;
      border-bottom:1px solid var(--bd);background:var(--pan)}
 .bar b{color:var(--am);letter-spacing:1.4px}
 .chip{border:1px solid var(--gn);color:var(--gn);padding:1px 8px;font-size:10px;letter-spacing:1.4px}
 .samp{display:flex;align-items:center;gap:16px;padding:6px 14px;
       border-bottom:1px solid var(--bd);background:#0e1214;flex-wrap:wrap}
 .samp .lab{color:var(--dim);font-size:10px;letter-spacing:1.2px}
 .tgt{display:flex;align-items:center;gap:6px;font-size:11px}
 .track{width:120px;height:7px;background:#1c2225;border:1px solid var(--bd);position:relative}
 .fillbar{height:100%;background:var(--bl)}
 /* ---- grid ---- */
 .wrap{display:grid;grid-template-columns:1.05fr 1.15fr 1.15fr;gap:9px;padding:9px;align-items:start}
 @media(max-width:1180px){.wrap{grid-template-columns:1fr}}
 .col{display:flex;flex-direction:column;gap:9px}
 .p{border:1px solid var(--bd);background:var(--pan)}
 .p h3{margin:0;padding:5px 10px;font-size:9.5px;letter-spacing:1.3px;color:var(--am);
       border-bottom:1px solid var(--bd);font-weight:700;display:flex;justify-content:space-between}
 .p .b{padding:7px 10px}
 .r{display:flex;justify-content:space-between;padding:2px 0;gap:10px;align-items:baseline}
 .r span:first-child{color:var(--dim);font-size:10.5px}
 .r span:last-child{font-variant-numeric:tabular-nums}
 .big{font-size:19px;font-weight:700}
 .g{color:var(--gn)}.r_{color:var(--rd)}.a{color:var(--am)}.d{color:var(--dim)}.bl{color:var(--bl)}
 table{width:100%;border-collapse:collapse;font-size:10.5px}
 th{color:var(--dim);text-align:right;font-weight:400;padding:3px 4px;border-bottom:1px solid var(--bd)}
 th:first-child,td:first-child{text-align:left}
 td{padding:2px 4px;text-align:right;font-variant-numeric:tabular-nums;
    border-bottom:1px solid #171c1f}
 .note{color:var(--dim);font-size:9.5px;padding:5px 10px 0;line-height:1.55}
 .scroll{max-height:290px;overflow:auto}
 .bookrow{display:flex;align-items:baseline;gap:10px;padding:3px 0;border-top:1px dashed var(--bd)}
 .warn{color:var(--am);font-size:10px;padding:4px 10px;border-top:1px solid var(--bd)}
</style>

<div class="bar">
  <b>MAKER_SIM</b><span class="d">·</span><span>BTC 5MIN</span>
  <span class="chip">PAPER · NO REAL ORDERS</span>
  <span id="live" class="d"></span>
  <span style="flex:1"></span>
  <span id="clock" class="d"></span>
</div>
<div class="samp" id="samp"></div>
<div class="wrap" id="w">loading…</div>

<script>
const $=(x)=>document.getElementById(x);
const usd=(v,d=2)=>v==null?'—':(v<0?'-':'')+'$'+Math.abs(v).toFixed(d);
const pct=(v,d=1)=>v==null?'—':(v*100).toFixed(d)+'%';
const num=(v,d=0)=>v==null?'—':Number(v).toFixed(d);
const cls=(v)=>v==null?'':(v>=0?'g':'r_');
const ago=(t)=>{if(!t)return'—';const s=Math.max(0,Date.now()/1000-t);
  return s<60?Math.round(s)+'s':Math.round(s/60)+'m'};
function row(k,v,c){return `<div class="r"><span>${k}</span><span class="${c||''}">${v}</span></div>`}
function P(t,inner,extra){return `<div class="p"><h3><span>${t}</span><span class="d">${extra||''}</span></h3><div class="b">${inner}</div></div>`}

function sampleBar(s){
  const sm=s.sample||{}; const n=sm.n||0;
  if(!sm.targets||!Object.keys(sm.targets).length){
    return `<span class="lab">SAMPLE</span><span>${n} settled markets · need ≥2 to estimate targets</span>`;
  }
  let h=`<span class="lab">SAMPLE SIZE</span>
    <span><b class="bl">${n}</b> settled</span>
    <span class="d">mean ${usd(sm.mean)}/mkt · σ ${usd(sm.stdev)}</span>`;
  for(const [lvl,t] of Object.entries(sm.targets)){
    const need=t.need, prog=need?Math.min(100,100*n/need):0;
    h+=`<span class="tgt"><span class="d">${lvl}</span>
      <span class="track"><span class="fillbar" style="width:${prog}%;
        background:${t.reached?'var(--gn)':'var(--bl)'}"></span></span>
      <span class="${t.reached?'g':''}">${t.reached?'REACHED':num(n)+'/'+(need==null?'∞':num(need))}</span>
      ${t.reached?'':`<span class="d">(${t.eta_hours==null?'—':num(t.eta_hours,0)+'h)'}</span>`}</span>`;
  }
  return h;
}

async function tick(){
  let s; try{ s=await (await fetch('/api/state',{cache:'no-store'})).json(); }catch(e){ return; }
  $('clock').textContent=new Date().toLocaleTimeString();
  if(s.error){ $('w').innerHTML=P('ERROR',s.error); return; }
  const c=s.config||{}, L=s.live||{}, inv=L.inventory||{};
  $('live').textContent = (L._age!=null && L._age<15) ? '● bot running' : '● bot idle';
  $('live').className = (L._age!=null && L._age<15) ? 'g' : 'r_';
  $('samp').innerHTML=sampleBar(s);

  /* ---------- column 1: money ---------- */
  const acct=P('PAPER ACCOUNT',
     row('EQUITY',usd(s.equity),'big '+cls(s.realized_pnl))
   + row('starting',usd(s.bankroll),'d')
   + row('realized P&L',usd(s.realized_pnl),cls(s.realized_pnl))
   + row('ROI on turnover',pct(s.roi_on_cost,2),cls(s.roi_on_cost))
   + row('rebate (est, not counted)',usd(s.rebate_est),'a')
   + row('capital deployed',usd(s.cost),'d'));

  const edge=P('WHERE THE MONEY COMES FROM',
     row('spread capture',usd(s.spread_capture),'g')
   + row('adverse selection',usd(s.adverse_selection),cls(s.adverse_selection))
   + row('= realized P&L',usd(s.realized_pnl),'big '+cls(s.realized_pnl))
   + row('avg edge vs mid',s.avg_edge_cents==null?'—':num(s.avg_edge_cents,2)+'¢','bl')
   + `<div class="note">resting below mid earns the spread; getting picked off
      pays some back. Their sum is the trading result.</div>`);

  const fq=P('FILL QUALITY',''
   + row('FILL RATE',pct(s.fill_rate),'big '+((s.fill_rate||0)>0.05?'g':'a'))
   + row('posted / filled',num(s.posted_shares)+' / '+num(s.filled_shares)+' sh','d')
   + row('median queue ahead',num(s.median_queue_ahead)+' sh')
   + row('median time to fill',s.median_seconds_to_fill==null?'—':num(s.median_seconds_to_fill,1)+'s')
   + `<div class="note">queue ahead = shares that had to clear before us.
      A model that ignored this would report 100% and mean nothing.</div>`);

  const invp=P('INVENTORY DISCIPLINE',
     row('median balance',num(s.median_balance,3)+' / '+c.target_balance,
        (s.median_balance||0)>=c.target_balance?'g':'a')
   + row('median pair cost',num(s.median_pair_cost,4),
        (s.median_pair_cost||9)<1?'g':'r_')
   + row('pairs under $1.00',s.pairs_under_1==null?'—':num(s.pairs_under_1,0)+'%')
   + `<div class="note">a pair pays exactly $1.00. Buying it below that is
      locked profit on the hedged part — powerwinner runs 0.9990 at 0.923 balance.</div>`);

  const res=P('RESULT',
     row('markets settled',num(s.markets_settled))
   + row('win / loss',num(s.wins)+' / '+num(s.losses))
   + row('win rate',pct(s.win_rate))
   + row('avg win',usd(s.avg_win),'g')
   + row('avg loss',usd(s.avg_loss),'r_')
   + `<div class="note">a maker normally LOSES more markets than it wins —
      the spread makes up the difference. powerwinner wins just 41.4%.</div>`);

  const pace=P('PACE · vs powerwinner',
     row('markets quoted / filled',num(s.markets_quoted)+' / '+num(s.markets_filled))
   + row('fills',num(s.fills))
   + row('fills/day',s.fills_per_day==null?'—':num(s.fills_per_day),'d')
   + row('his fills/day','8,351','d')
   + row('notional/day',s.notional_per_day==null?'—':usd(s.notional_per_day,0),'d')
   + row('his notional/day','$398k','d')
   + row('running',num(s.days,2)+'d','d'));

  /* ---------- column 2: live market ---------- */
  let book='<div class="d">waiting for the bot…</div>';
  if(L.market_slug){
    const mk=(sd,o)=>`<div class="bookrow">
      <span class="d" style="width:44px">${sd}</span>
      <span class="d" style="font-size:10px">BID</span>
      <span class="g" style="font-weight:700">${o.best_bid==null?'—':o.best_bid.toFixed(2)}</span>
      <span class="d" style="font-size:10px">ASK</span>
      <span class="a" style="font-weight:700">${o.best_ask==null?'—':o.best_ask.toFixed(2)}</span>
      <span style="flex:1"></span>
      <span class="d" style="font-size:10px">depth ${num(o.bid_depth)}</span></div>`;
    book = row('COUNTDOWN', num(Math.max(0,L.t_remaining),0)+'s','big '+((L.t_remaining||0)<60?'a':''))
      + mk('UP',L.up||{}) + mk('DOWN',L.down||{});
  }
  const liveP=P(L.market_slug?('LIVE MARKET · '+L.market_slug):'LIVE MARKET', book,
                L.market_slug?('<a style="color:var(--am);text-decoration:none" target="_blank" href="https://polymarket.com/event/'+L.market_slug+'">open ↗</a>'):'');

  let oq='<div class="d">no resting quotes</div>';
  if((L.open_quotes||[]).length){
    oq='<table><tr><th>SIDE</th><th>PRICE</th><th>SIZE</th><th>FILLED</th><th>QUEUE AHEAD</th></tr>';
    L.open_quotes.forEach(q=>{oq+=`<tr>
      <td class="${q.side==='UP'?'g':'r_'}">${q.side}</td><td>${q.price.toFixed(2)}</td>
      <td>${num(q.size)}</td><td>${num(q.filled)}</td>
      <td class="${q.queue_ahead>0?'a':'g'}">${num(q.queue_ahead)}</td></tr>`});
    oq+='</table>';
  }
  const invNow=P('OUR BOOK · this market',
      row('UP',num(inv.up_shares)+' sh @ '+num(inv.up_avg,3),'g')
    + row('DOWN',num(inv.down_shares)+' sh @ '+num(inv.down_avg,3),'r_')
    + row('pair cost',num(inv.pair_cost,4),(inv.pair_cost||9)<1?'g':'d')
    + row('balance',num(inv.balance,2),(inv.balance||0)>=c.target_balance?'g':'a')
    + row('cost / fills',usd(inv.cost)+' / '+num(inv.fills),'d'));

  const quotesP=P('RESTING QUOTES',oq);

  /* ---------- column 3: flow ---------- */
  let fl='<div class="d">no fills yet</div>';
  if((s.recent_fills||[]).length){
    fl='<div class="scroll"><table><tr><th>TIME</th><th>SIDE</th><th>PX</th><th>SH</th><th>EDGE</th><th>QUEUE</th></tr>';
    s.recent_fills.forEach(f=>{fl+=`<tr>
      <td class="d">${new Date(f.ts*1000).toLocaleTimeString()}</td>
      <td class="${f.side==='UP'?'g':'r_'}">${f.side}</td>
      <td>${(f.price||0).toFixed(2)}</td><td>${num(f.size)}</td>
      <td class="bl">${f.edge_vs_mid==null?'—':(f.edge_vs_mid*100).toFixed(2)+'¢'}</td>
      <td class="d">${num(f.queue_waited)}</td></tr>`});
    fl+='</table></div>';
  }
  const fillsP=P('FILL FLOW','' + fl);

  let dl='<div class="d">no decisions yet</div>';
  if((s.decisions||[]).length){
    dl='<div class="scroll"><table><tr><th>TIME</th><th>ACTION</th><th>SIDE</th><th>PX</th><th>REASON</th></tr>';
    s.decisions.forEach(d=>{
      const isQ=d.action==='QUOTE';
      dl+=`<tr><td class="d">${new Date(d.ts*1000).toLocaleTimeString()}</td>
        <td class="${isQ?'g':'d'}">${d.action}${d.count>1?' <span class="d">×'+d.count+'</span>':''}</td>
        <td class="${d.side==='UP'?'g':(d.side==='DOWN'?'r_':'d')}">${d.side||'—'}</td>
        <td>${d.price==null?'—':d.price.toFixed(2)}</td>
        <td class="d" style="text-align:left">${(d.reason||'').slice(0,44)}</td></tr>`});
    dl+='</table></div>';
  }
  const decP=P('DECISION LOG · why we quote or skip', dl);

  let t='<div class="d">no settled markets yet</div>';
  if((s.settlements||[]).length){
    t='<div class="scroll"><table><tr><th>MARKET</th><th>UP/DN</th><th>BAL</th><th>COST</th><th>PAID</th><th>P&L</th></tr>';
    s.settlements.forEach(x=>{t+=`<tr>
      <td class="d">…${(x.slug||'').slice(-8)}</td>
      <td class="d">${num(x.up_sh)}/${num(x.dn_sh)}</td>
      <td>${num(x.balance,2)}</td><td>${usd(x.cost,0)}</td><td>${usd(x.payout,0)}</td>
      <td class="${x.pnl>=0?'g':'r_'}">${x.pnl>=0?'+':''}${usd(x.pnl)}</td></tr>`});
    t+='</table></div>';
  }
  const setP=P('SETTLEMENTS',t);

  $('w').innerHTML =
     `<div class="col">${acct}${edge}${fq}${invp}</div>`
   + `<div class="col">${liveP}${invNow}${quotesP}${res}${pace}</div>`
   + `<div class="col">${fillsP}${decP}${setP}</div>`;
}
tick(); setInterval(tick,2000);
</script>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
