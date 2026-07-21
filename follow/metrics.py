"""Profile metrics — how each account actually trades, from their fill history.

These describe the trader, not our P&L: cadence, sizing, price preference,
side balance, market mix. Useful for judging whether an account's edge is
something a follower could plausibly capture, or something structural
(speed, size, market access) that cannot be copied.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter

from follow import store


def profile(account_key: str, window_h: float = 24.0) -> dict:
    cutoff = time.time() - window_h * 3600
    with store.db() as c:
        rows = c.execute(
            "SELECT ts, side, their_price, their_usdc, market_slug, condition_id, outcome "
            "FROM follow_fills WHERE account=? AND ts>?", (account_key, cutoff)
        ).fetchall()
    if not rows:
        return {"account": account_key, "n": 0}

    ts = [r[0] for r in rows]
    span_h = max((max(ts) - min(ts)) / 3600.0, 1e-6)
    prices = [r[2] for r in rows if r[2]]
    usdc = [r[3] for r in rows if r[3]]
    sides = Counter(r[1] for r in rows)
    conds = {r[5] for r in rows}

    # market family: btc-5m / eth-5m / other
    fam = Counter()
    for r in rows:
        s = r[4] or ""
        if "btc-updown-5m" in s:
            fam["BTC 5m"] += 1
        elif "eth-updown-5m" in s:
            fam["ETH 5m"] += 1
        elif "updown-15m" in s:
            fam["15m"] += 1
        else:
            fam["other"] += 1

    # entry price distribution — where they put their money
    buckets = [(0, .1), (.1, .3), (.3, .5), (.5, .7), (.7, .9), (.9, 1.01)]
    dist = []
    tot_usd = sum(usdc) or 1.0
    for lo, hi in buckets:
        sel = [r for r in rows if r[2] and lo <= r[2] < hi]
        dist.append({
            "label": f"{lo:.1f}-{hi:.1f}" if hi <= 1 else "0.9-1.0",
            "n": len(sel),
            "pct_trades": 100.0 * len(sel) / len(rows),
            "pct_usd": 100.0 * sum(r[3] or 0 for r in sel) / tot_usd,
        })

    # inter-trade gap = how fast they fire
    st = sorted(ts)
    gaps = [b - a for a, b in zip(st, st[1:])]

    return {
        "account": account_key,
        "n": len(rows),
        "window_h": round(span_h, 1),
        "trades_per_hour": len(rows) / span_h,
        "markets": len(conds),
        "markets_per_hour": len(conds) / span_h,
        "fills_per_market": len(rows) / max(len(conds), 1),
        "buy_pct": 100.0 * sides.get("BUY", 0) / len(rows),
        "sell_pct": 100.0 * sides.get("SELL", 0) / len(rows),
        "avg_usd": statistics.mean(usdc) if usdc else 0.0,
        "median_usd": statistics.median(usdc) if usdc else 0.0,
        "max_usd": max(usdc) if usdc else 0.0,
        "total_usd": sum(usdc),
        "avg_price": statistics.mean(prices) if prices else 0.0,
        "median_gap_sec": statistics.median(gaps) if gaps else None,
        "price_dist": dist,
        "families": fam.most_common(),
    }
