"""Maker dashboard. Separate app, separate port (8788), separate DB.

Self-contained HTML -- no build step, no shared components with the taker UI, so
the two can never drift into each other.

Laid out as a KANBAN PIPELINE: every market flows left to right through the
stages it actually passes through --
    DECIDE -> REST (quote on book) -> FILL -> HOLD (position) -> SETTLE
New cards animate in, so you can watch work move down the pipeline rather than
reading five disconnected tables.
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
    d["decisions"] = kpi.recent_decisions(40)
    d["recent_fills"] = kpi.recent_fills(30)
    d["config"] = {
        "quote_shares": cfg.quote_shares,
        "target_balance": cfg.target_balance,
        "max_pair_cost": cfg.max_pair_cost,
        "max_cost_per_market": cfg.max_cost_per_market,
    }
    return d


PAGE = r"""
<style>
 :root{--bg:#0a0c0d;--pan:#121618;--pan2:#161b1e;--bd:#232a2e;--tx:#d6dbd8;
       --dim:#79847f;--am:#eda92c;--gn:#46c46a;--rd:#e2564f;--bl:#5b9bd5;
       --pu:#9b7fd4}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--tx);
      font:14.5px ui-monospace,SFMono-Regular,Menlo,monospace}
 .bar{display:flex;align-items:center;gap:12px;padding:7px 14px;
      border-bottom:1px solid var(--bd);background:var(--pan)}
 .bar b{color:var(--am);letter-spacing:1.4px;font-size:16px}
 .chip{border:1px solid var(--gn);color:var(--gn);padding:2px 9px;font-size:11.5px;letter-spacing:1.4px}

 /* ---------- sample-size bars (were broken: spans are inline, so width/height
    were ignored entirely and the bar never reflected progress) ---------- */
 .samp{display:flex;align-items:center;gap:18px;padding:7px 14px;
       border-bottom:1px solid var(--bd);background:#0d1113;flex-wrap:wrap}
 .lab{color:var(--dim);font-size:11.5px;letter-spacing:1.2px}
 .tgt{display:inline-flex;align-items:center;gap:7px;font-size:12.5px}
 .track{display:inline-block;width:150px;height:11px;background:#1b2124;
        border:1px solid var(--bd);position:relative;overflow:hidden;vertical-align:middle}
 .fillbar{display:block;height:100%;background:var(--bl);transition:width .6s ease}

 /* ---------- kpi strip ---------- */
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));
       gap:7px;padding:9px 12px;border-bottom:1px solid var(--bd)}
 .k{border:1px solid var(--bd);background:var(--pan);padding:6px 9px}
 .k .n{color:var(--dim);font-size:10.5px;letter-spacing:.8px}
 .k .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums;margin-top:2px}
 .k .s{color:var(--dim);font-size:11px}

 /* ---------- kanban ---------- */
 .kan{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;padding:10px 12px;
      align-items:start}
 @media(max-width:1250px){.kan{grid-template-columns:repeat(2,1fr)}}
 .lane{border:1px solid var(--bd);background:var(--pan);display:flex;
       flex-direction:column;min-height:150px}
 .lane h3{margin:0;padding:8px 11px;font-size:11.5px;letter-spacing:1.3px;
          border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;
          align-items:center;font-weight:700}
 .lane .body{padding:6px;display:flex;flex-direction:column;gap:5px;
             max-height:520px;overflow-y:auto}
 .cnt{background:#1c2225;color:var(--dim);padding:1px 7px;border-radius:8px;font-size:10.5px}

 /* stage colours */
 .l1 h3{color:var(--dim)}   .l1{border-top:2px solid #3a4145}
 .l2 h3{color:var(--bl)}    .l2{border-top:2px solid var(--bl)}
 .l3 h3{color:var(--pu)}    .l3{border-top:2px solid var(--pu)}
 .l4 h3{color:var(--am)}    .l4{border-top:2px solid var(--am)}
 .l5 h3{color:var(--gn)}    .l5{border-top:2px solid var(--gn)}

 .card{background:var(--pan2);border:1px solid var(--bd);border-left:2px solid var(--bd);
       padding:7px 9px;font-size:12.5px;line-height:1.55}
 .card .top{display:flex;justify-content:space-between;gap:6px;align-items:baseline}
 .card .sub{color:var(--dim);font-size:11px}
 .card.up{border-left-color:var(--gn)} .card.dn{border-left-color:var(--rd)}
 .card.win{border-left-color:var(--gn)} .card.loss{border-left-color:var(--rd)}
 .card.skip{opacity:.62}
 .num{font-variant-numeric:tabular-nums}
 .g{color:var(--gn)}.r_{color:var(--rd)}.a{color:var(--am)}.d{color:var(--dim)}.bl{color:var(--bl)}.pu{color:var(--pu)}

 /* cards slide in from the previous lane as work advances */
 @keyframes flowin{
   0%{opacity:0;transform:translateX(-26px) scale(.97)}
   60%{opacity:1}
   100%{opacity:1;transform:none}
 }
 .enter{animation:flowin .55s cubic-bezier(.22,.9,.3,1)}
 @media (prefers-reduced-motion: reduce){ .enter{animation:none} }

 .note{color:var(--dim);font-size:11px;padding:6px 10px;line-height:1.5;
       border-top:1px solid var(--bd)}
 .livebar{display:flex;gap:18px;align-items:center;padding:7px 14px;
          border-bottom:1px solid var(--bd);background:var(--pan);flex-wrap:wrap}
</style>

<div class="bar">
  <b>MAKER_SIM</b><span class="d">·</span><span>BTC 5MIN</span>
  <span class="chip">PAPER · NO REAL ORDERS</span>
  <span id="live" class="d"></span>
  <span style="flex:1"></span><span id="clock" class="d"></span>
</div>
<div class="samp" id="samp"></div>
<div class="livebar" id="livebar"></div>
<div class="kpis" id="kpis"></div>
<div class="kan" id="kan"></div>

<script>
const $=(x)=>document.getElementById(x);
const usd=(v,d=2)=>v==null?'—':(v<0?'-':'')+'$'+Math.abs(v).toFixed(d);
const pct=(v,d=1)=>v==null?'—':(v*100).toFixed(d)+'%';
const num=(v,d=0)=>v==null?'—':Number(v).toFixed(d);
const cls=(v)=>v==null?'':(v>=0?'g':'r_');
const hhmm=(t)=>t?new Date(t*1000).toLocaleTimeString():'—';
const seen={};                       // lane -> Set of ids already rendered

function lane(id,title,cls_,cards,note){
  const s=seen[id]=seen[id]||new Set();
  const html=cards.map(c=>{
    const isNew=!s.has(c.key); s.add(c.key);
    return `<div class="card ${c.cls||''} ${isNew?'enter':''}">${c.html}</div>`;
  }).join('');
  return `<div class="lane ${cls_}"><h3><span>${title}</span>
    <span class="cnt">${cards.length}</span></h3>
    <div class="body">${html||'<div class="d" style="padding:6px">—</div>'}</div>
    ${note?`<div class="note">${note}</div>`:''}</div>`;
}

function sampleBar(s){
  const sm=s.sample||{}, n=sm.n||0;
  if(!sm.targets||!Object.keys(sm.targets).length)
    return `<span class="lab">SAMPLE</span><span>${n} settled · need ≥2 to estimate</span>`;
  let h=`<span class="lab">SAMPLE SIZE</span><span><b class="bl">${n}</b> settled</span>
         <span class="d">mean ${usd(sm.mean)}/mkt · σ ${usd(sm.stdev)}</span>`;
  for(const [lvl,t] of Object.entries(sm.targets)){
    const need=t.need, prog=need?Math.min(100,100*n/need):0;
    h+=`<span class="tgt"><span class="d">${lvl}</span>
      <span class="track"><span class="fillbar" style="width:${prog.toFixed(1)}%;
        background:${t.reached?'var(--gn)':'var(--bl)'}"></span></span>
      <span class="${t.reached?'g':''}">${t.reached?'REACHED':n+'/'+(need==null?'∞':need)}</span>
      ${t.reached?'':`<span class="d">${t.eta_hours==null?'':'('+num(t.eta_hours,0)+'h)'}</span>`}</span>`;
  }
  return h;
}

async function tick(){
  let s; try{ s=await (await fetch('/api/state',{cache:'no-store'})).json(); }catch(e){ return; }
  $('clock').textContent=new Date().toLocaleTimeString();
  if(s.error){ $('kan').innerHTML='<div class="lane"><h3>ERROR</h3><div class="body">'+s.error+'</div></div>'; return; }
  const c=s.config||{}, L=s.live||{}, inv=L.inventory||{};
  const alive=(L._age!=null&&L._age<15);
  $('live').textContent=alive?'● bot running':'● bot idle';
  $('live').className=alive?'g':'r_';
  $('samp').innerHTML=sampleBar(s);

  /* ---- live market strip ---- */
  const u=L.up||{},d=L.down||{};
  $('livebar').innerHTML = L.market_slug ? `
    <span class="lab">LIVE</span>
    <a href="https://polymarket.com/event/${L.market_slug}" target="_blank"
       style="color:var(--am);text-decoration:none">${L.market_slug} ↗</a>
    <span class="a" style="font-size:20px;font-weight:700">${num(Math.max(0,L.t_remaining))}s</span>
    <span class="d">UP</span><span class="g">${u.best_bid==null?'—':u.best_bid.toFixed(2)}</span>
      <span class="d">/</span><span class="a">${u.best_ask==null?'—':u.best_ask.toFixed(2)}</span>
    <span class="d">DOWN</span><span class="g">${d.best_bid==null?'—':d.best_bid.toFixed(2)}</span>
      <span class="d">/</span><span class="a">${d.best_ask==null?'—':d.best_ask.toFixed(2)}</span>
    <span style="flex:1"></span>
    <span class="d">our book</span>
    <span class="g">UP ${num(inv.up_shares)}@${num(inv.up_avg,3)}</span>
    <span class="r_">DOWN ${num(inv.down_shares)}@${num(inv.down_avg,3)}</span>
    <span class="d">pair</span><span class="${(inv.pair_cost||9)<1?'g':'d'}">${num(inv.pair_cost,4)}</span>
    <span class="d">balance</span><span class="${(inv.balance||0)>=c.target_balance?'g':'a'}">${num(inv.balance,2)}</span>`
    : '<span class="d">waiting for the bot…</span>';

  /* ---- kpi strip ---- */
  const K=(n,v,sub,cl)=>`<div class="k"><div class="n">${n}</div>
      <div class="v ${cl||''}">${v}</div><div class="s">${sub||''}</div></div>`;
  $('kpis').innerHTML =
      K('EQUITY',usd(s.equity),'from '+usd(s.bankroll),cls(s.realized_pnl))
    + K('REALIZED P&L',usd(s.realized_pnl),pct(s.roi_on_cost,2)+' of turnover',cls(s.realized_pnl))
    + K('SPREAD CAPTURE',usd(s.spread_capture),num(s.avg_edge_cents,2)+'¢ avg edge','g')
    + K('ADVERSE SELECTION',usd(s.adverse_selection),'cost of being picked off',cls(s.adverse_selection))
    + K('FILL RATE',pct(s.fill_rate),num(s.median_queue_ahead)+' sh queue ahead','bl')
    + K('BALANCE',num(s.median_balance,3),'target '+c.target_balance,
        (s.median_balance||0)>=c.target_balance?'g':'a')
    + K('PAIR COST',num(s.median_pair_cost,4),'pays $1.00',
        (s.median_pair_cost||9)<1?'g':'r_')
    + K('WIN RATE',pct(s.win_rate),s.wins+'W / '+s.losses+'L')
    + K('REBATE (est)',usd(s.rebate_est),'not counted in P&L','a');

  /* ---- kanban: DECIDE -> REST -> FILL -> HOLD -> SETTLE ---- */
  const decide=(s.decisions||[]).slice(0,14).map(x=>({
    key:'d'+x.id, cls:(x.action==='QUOTE'?'':'skip'),
    html:`<div class="top"><span class="${x.action==='QUOTE'?'bl':'d'}">${x.action}${x.count>1?' <span class="d">×'+x.count+'</span>':''}</span>
      <span class="d">${hhmm(x.ts)}</span></div>
      <div class="sub">${(x.reason||'').slice(0,42)}</div>`}));

  const rest=(L.open_quotes||[]).map((q,i)=>({
    key:'q'+q.side+q.price, cls:(q.side==='UP'?'up':'dn'),
    html:`<div class="top"><span class="${q.side==='UP'?'g':'r_'}">${q.side} @ ${q.price.toFixed(2)}</span>
      <span class="num">${num(q.size)} sh</span></div>
      <div class="sub">queue ahead <span class="${q.queue_ahead>0?'a':'g'}">${num(q.queue_ahead)}</span>
      · filled ${num(q.filled)}</div>`}));

  const fills=(s.recent_fills||[]).slice(0,14).map(f=>({
    key:'f'+f.id, cls:(f.side==='UP'?'up':'dn'),
    html:`<div class="top"><span class="${f.side==='UP'?'g':'r_'}">${f.side} @ ${(f.price||0).toFixed(2)}</span>
      <span class="num">${num(f.size)} sh</span></div>
      <div class="sub">edge <span class="bl">${f.edge_vs_mid==null?'—':(f.edge_vs_mid*100).toFixed(2)+'¢'}</span>
      · waited ${num(f.queue_waited)} sh · ${hhmm(f.ts)}</div>`}));

  const hold=[];
  if(inv.fills){
    const risk=(inv.up_shares||0)-(inv.down_shares||0);
    hold.push({key:'h'+(L.condition_id||''),cls:(inv.balance>=c.target_balance?'win':''),
      html:`<div class="top"><span class="a">${(L.market_slug||'').slice(-8)}</span>
        <span class="num">${num(inv.fills)} fills</span></div>
        <div class="sub">UP ${num(inv.up_shares)} · DOWN ${num(inv.down_shares)}</div>
        <div class="sub">pair <span class="${(inv.pair_cost||9)<1?'g':'d'}">${num(inv.pair_cost,4)}</span>
          · balance <span class="${(inv.balance||0)>=c.target_balance?'g':'a'}">${num(inv.balance,2)}</span></div>
        <div class="sub">unhedged <span class="${Math.abs(risk)>60?'r_':'d'}">${num(Math.abs(risk))} sh</span>
          · cost ${usd(inv.cost,0)}</div>`});
  }

  const settle=(s.settlements||[]).slice(0,14).map(x=>({
    key:'s'+x.slug, cls:(x.pnl>=0?'win':'loss'),
    html:`<div class="top"><span class="d">…${(x.slug||'').slice(-8)}</span>
      <span class="${x.pnl>=0?'g':'r_'}" style="font-weight:700">${x.pnl>=0?'+':''}${usd(x.pnl)}</span></div>
      <div class="sub">UP ${num(x.up_sh)} / DN ${num(x.dn_sh)} · bal ${num(x.balance,2)}</div>
      <div class="sub">cost ${usd(x.cost,0)} → paid ${usd(x.payout,0)}</div>`}));

  $('kan').innerHTML =
      lane('l1','① DECIDE','l1',decide,'why we quote or skip')
    + lane('l2','② REST ON BOOK','l2',rest,'our bids waiting in the queue')
    + lane('l3','③ FILL','l3',fills,'someone traded against us')
    + lane('l4','④ HOLD','l4',hold,'position carried into resolution')
    + lane('l5','⑤ SETTLE','l5',settle,'market resolved · $1.00 or $0.00');
}
tick(); setInterval(tick,2000);
</script>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE
