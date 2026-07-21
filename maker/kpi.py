"""Maker KPIs.

A taker asks "was I right?". A maker asks "did I get filled, at what price
relative to fair, and did I get picked off?". These are the metrics that tell
you whether to keep going, and they have no equivalent in the taker dashboard.

The headline decomposition splits P&L into the two things that actually pay:
  SPREAD CAPTURE   shares x (mid_at_post - fill_price)  -- the maker's edge
  DIRECTIONAL      what the resolution did to us        -- the maker's cost
  REBATE (est.)    volume-based estimate, never blended into realized PnL
"""
from __future__ import annotations

import statistics
import time
from typing import Optional

from maker import store
from maker.config import load as load_cfg

cfg = load_cfg()


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with store.db() as c:
        cur = c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def report() -> dict:
    quotes = _rows("SELECT * FROM quotes")
    fills = _rows("SELECT * FROM fills")
    _res_rows = _rows("SELECT * FROM resolutions")
    res = {r["condition_id"]: r["winning_token"] for r in _res_rows}
    res_ts = {r["condition_id"]: r["resolved_ts"] for r in _res_rows}

    posted_sh = sum(q["size"] or 0 for q in quotes)
    filled_sh = sum(f["size"] or 0 for f in fills)
    cost = sum((f["size"] or 0) * (f["price"] or 0) for f in fills)

    # --- the maker's edge: how far below mid did we buy? ------------------
    cap = [(f["size"] or 0) * (f["edge_vs_mid"] or 0) for f in fills if f.get("edge_vs_mid") is not None]
    spread_capture = sum(cap)
    edges = [f["edge_vs_mid"] for f in fills if f.get("edge_vs_mid") is not None]

    # --- fill quality ------------------------------------------------------
    waits = [f["seconds_to_fill"] for f in fills if f.get("seconds_to_fill") is not None]
    queues = [f["queue_waited"] for f in fills if f.get("queue_waited") is not None]

    # --- per-market: inventory balance, pair cost, realized outcome --------
    by_mkt: dict[str, dict] = {}
    for f in fills:
        m = by_mkt.setdefault(f["condition_id"], {
            "slug": f["market_slug"], "up_sh": 0.0, "dn_sh": 0.0,
            "up_cost": 0.0, "dn_cost": 0.0, "fills": 0, "tokens": {},
        })
        if f["side"] == "UP":
            m["up_sh"] += f["size"]; m["up_cost"] += f["size"] * f["price"]
        else:
            m["dn_sh"] += f["size"]; m["dn_cost"] += f["size"] * f["price"]
        m["fills"] += 1
        m["tokens"][f["side"]] = f["token_id"]

    settled, pnls, balances, pairs = [], [], [], []
    for cond, m in by_mkt.items():
        hi = max(m["up_sh"], m["dn_sh"])
        if hi > 0:
            balances.append(min(m["up_sh"], m["dn_sh"]) / hi)
        if m["up_sh"] > 0 and m["dn_sh"] > 0:
            pairs.append(m["up_cost"] / m["up_sh"] + m["dn_cost"] / m["dn_sh"])
        win = res.get(cond)
        if not win:
            continue
        payout = 0.0
        for side in ("UP", "DOWN"):
            tok = m["tokens"].get(side)
            sh = m["up_sh"] if side == "UP" else m["dn_sh"]
            if tok and tok == win:
                payout += sh
        c = m["up_cost"] + m["dn_cost"]
        pnl = payout - c            # maker pays no taker fee
        pnls.append(pnl)
        settled.append({"slug": m["slug"], "cost": c, "payout": payout,
                        "pnl": pnl, "fills": m["fills"],
                        "ts": res_ts.get(cond) or 0,
                        "up_sh": m["up_sh"], "dn_sh": m["dn_sh"],
                        "balance": (min(m["up_sh"], m["dn_sh"]) / hi) if hi else 1.0})

    realized = sum(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # --- rebate estimate ---------------------------------------------------
    # Rebate pool = rebate_rate x taker fees on matched volume. We only see our
    # own side, so this is an ESTIMATE and is reported separately, never added
    # into realized PnL.
    rebate_est = sum(
        (f["size"] or 0) * cfg.fee_rate * (f["price"] or 0) * (1 - (f["price"] or 0))
        * cfg.rebate_rate for f in fills
    )

    ts = [f["ts"] for f in fills if f.get("ts")]
    days = ((max(ts) - min(ts)) / 86400) if len(ts) > 1 else 0.0

    # --- how big a sample do we actually need? -----------------------------
    # Question: is mean P&L per market reliably above zero? For a mean, the CI
    # half-width is z*sigma/sqrt(n). It excludes zero once
    #     n > (z * sigma / |mean|)^2
    # sigma and mean are estimated from what we've settled so far, so these
    # targets MOVE as the data comes in -- that's expected, not a bug. A noisy
    # strategy (big sigma relative to its edge) needs far more markets.
    sample = {"n": len(pnls), "mean": None, "stdev": None, "targets": {}}
    if len(pnls) >= 2:
        mu = statistics.mean(pnls)
        sd = statistics.stdev(pnls)
        sample["mean"] = mu
        sample["stdev"] = sd
        for label, z in (("90%", 1.645), ("95%", 1.960), ("99%", 2.576)):
            if abs(mu) < 1e-9 or sd <= 0:
                need = None
            else:
                need = int((z * sd / abs(mu)) ** 2) + 1
            sample["targets"][label] = {
                "need": need,
                "remaining": (max(0, need - len(pnls)) if need else None),
                "reached": (need is not None and len(pnls) >= need),
            }
        # rough ETA from observed market pace
        if days > 0.01 and len(by_mkt) > 0:
            per_day = len(by_mkt) / days
            sample["markets_per_day"] = per_day
            for label in sample["targets"]:
                rem = sample["targets"][label]["remaining"]
                sample["targets"][label]["eta_hours"] = (
                    round(rem / per_day * 24, 1) if (rem and per_day > 0) else 0
                )

    return {
        # pace (compare against powerwinner: 437 mkts/day, 8351 fills/day)
        "markets_quoted": len({q["condition_id"] for q in quotes}),
        "markets_filled": len(by_mkt),
        "markets_settled": len(settled),
        "fills": len(fills),
        "quotes": len(quotes),
        "days": days,
        "fills_per_day": (len(fills) / days) if days > 0.01 else None,
        "notional_per_day": (cost / days) if days > 0.01 else None,

        # THE maker metric
        "fill_rate": (filled_sh / posted_sh) if posted_sh else None,
        "posted_shares": posted_sh,
        "filled_shares": filled_sh,
        "median_seconds_to_fill": statistics.median(waits) if waits else None,
        "median_queue_ahead": statistics.median(queues) if queues else None,

        # the edge
        "spread_capture": spread_capture,
        "avg_edge_cents": (statistics.mean(edges) * 100) if edges else None,
        "cost": cost,

        # inventory discipline
        "median_balance": statistics.median(balances) if balances else None,
        "median_pair_cost": statistics.median(pairs) if pairs else None,
        "pairs_under_1": (100 * sum(1 for p in pairs if p < 1.0) / len(pairs)) if pairs else None,

        # outcome
        "realized_pnl": realized,
        "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / len(pnls)) if pnls else None,
        "avg_win": statistics.mean(wins) if wins else 0.0,
        "avg_loss": statistics.mean(losses) if losses else 0.0,
        "roi_on_cost": (realized / cost) if cost else None,

        # adverse selection: spread we captured vs what direction cost us
        "adverse_selection": realized - spread_capture,
        "rebate_est": rebate_est,
        "total_with_rebate": realized + rebate_est,

        "equity": cfg.bankroll_usd + realized,
        "bankroll": cfg.bankroll_usd,
        "sample": sample,
        "settlements": sorted(settled, key=lambda x: -x.get("ts", 0))[:60] or settled[:60],
    }


def recent_decisions(limit: int = 60) -> list[dict]:
    return _rows("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))


def recent_fills(limit: int = 40) -> list[dict]:
    return _rows("SELECT * FROM fills ORDER BY id DESC LIMIT ?", (limit,))


def recent_quotes(limit: int = 40) -> list[dict]:
    return _rows("SELECT * FROM quotes ORDER BY id DESC LIMIT ?", (limit,))
