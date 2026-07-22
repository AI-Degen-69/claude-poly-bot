"""Gate retest harness — historical spot-signal audit (Option B, fresh data).

WHY THIS EXISTS
--------------
The taker's Binance spot gate (strategy/spot.py, strategy_rules.py:103) is the
entire thesis: only buy the side BTC's own move already favours, at >=5bps.
The original backtest (research/RESEARCH_LOG.md, 2026-07-20) claimed the
book's favoured side wins 81.3% alone vs 96.0% gated (>=5bps) over 584
windows. Live data has NOT reproduced that gap (RESEARCH_SUMMARY 22/07:
>=10bps 94.4% vs <10bps 94.6% — basically identical). This harness
answers the open question on a FRESH, non-overlapping window range.

WHAT IT TESTS (scope, read this)
---------------------------------
Polymarket's CLOB /book endpoint is LIVE-ONLY — no timestamp param — so the
historical *book-favoured side* cannot be reconstructed from stored data. The
original 81->96 number required polling books in real time as windows resolved.
Therefore this harness audits the SPOT SIGNAL IN ISOLATION, which IS
historically reconstructable, and which is the gate's actual predictive claim:

    predicted = UP if Binance BTC moved >=0 bps vs window open else DOWN
    actual    = UP if outcomePrices[0] > outcomePrices[1] else DOWN
    ungated accuracy = P(predicted == actual)            over ALL windows
    gated accuracy   = P(predicted == actual | |bps| >= threshold)
    coverage       = P(|bps| >= threshold)

If gated >> ungated on a fresh range, the spot direction carries real signal and
the gate earns its place. If gated ~= ungated, the gate is DEAD (simplify: set
use_spot_gate=False) — exactly the simplification win program.md rewards.

FAITHFUL 81->96 REPRODUCTION (not done here, documented)
------------------------------------------------------
To reproduce the book-favoured-side + gate combo you must collect books
FORWARD: run a collector that, at t-120s of each NEW window, records the
book-favoured side + spot_bps + eventual resolution. ~300 windows x 5min =
~25h. That is the only honest way; offline replay of historical books is
impossible via public API.

This module is read-only against live APIs and writes nothing to store.db, so it
never touches or invalidates the live 110-market sample.

ENUMERATION
------------
Polymarket's /events?series_slug= returns the oldest windows first and is
unreliable for deep history, so we instead GENERATE aligned window-open
timestamps (every 300s, UTC) across the requested date range and resolve each
directly via /events?slug=btc-updown-5m-<open_ts>. Verified 2026-07-21
returned live, resolved outcomePrices. This is the same per-window slug path the
resolver uses (resolver.py:18, proven 584/584 reliable).

USAGE
-----
    python -m strategy.backtest_gate --start 2026-07-21 --end 2026-07-23
    python -m strategy.backtest_gate --start 2026-07-21 --end 2026-07-23 \
        --threshold 5 --eval-t-rem 120 --out research/gate_retest.json

Requires network (Binance + Polymarket gamma). No .env / live creds needed.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

import requests

# Hosts taken from strategy/config.py defaults — imported here directly so this
# harness does NOT require a .env / live credentials (config.load() would).
GAMMA_HOST = "https://gamma-api.polymarket.com"
BINANCE_REST = "https://api.binance.com/api/v3/klines"
# Market slug prefix. NB: the per-window market slug is `btc-updown-5m-<ts>`
# (NO "or"); "btc-up-or-down-5m" is the *series* value used only as a
# gamma query param. Do not conflate the two — using the series string
# here maks every slug lookup 404 (resolved=0).
SERIES_SLUG = "btc-updown-5m"
WINDOW_SECONDS = 300
UA = {"User-Agent": "Mozilla/5.0"}  # gamma 403s some clients without this


def _binance_bps(open_ts: int, decision_ts: int) -> float | None:
    """Signed bps move from window open to decision time, via Binance 1m klines."""
    try:
        def _kline(ts: int) -> float | None:
            r = requests.get(
                BINANCE_REST,
                params={"symbol": "BTCUSDT", "interval": "1m",
                        "startTime": ts * 1000, "limit": 1},
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                return None
            return float(data[0][1])  # kline open
        open_px = _kline(open_ts)
        now_px = _kline(decision_ts)
        if not open_px or not now_px:
            return None
        return (now_px - open_px) / open_px * 10_000.0
    except Exception:
        return None


def _resolve_window(open_ts: int) -> bool | None:
    """Return True if UP (token_ids[0]) wins, False if DOWN wins, None if unknown."""
    slug = f"{SERIES_SLUG}-{open_ts}"
    try:
        r = requests.get(
            f"{GAMMA_HOST}/events",
            params={"slug": slug},
            headers=UA, timeout=20,
        )
        if r.status_code != 200:
            return None
        events = r.json()
        if not events:
            return None
        ev = events[0] if isinstance(events, list) else events
        markets = ev.get("markets") or []
        if not markets:
            return None
        m = markets[0]
        if not m.get("closed"):
            return None
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices or len(prices) != 2:
            return None
        return float(prices[0]) > float(prices[1])  # UP = token_ids[0]
    except Exception:
        return None


def run(start: str, end: str, threshold: float, eval_t_rem: int,
        max_windows: int, out: str | None) -> dict:
    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc)

    # Align to the 300s window grid (windows open on :00/:05/:10/:15/... UTC).
    grid0 = int(start_dt.timestamp()) // WINDOW_SECONDS * WINDOW_SECONDS
    grid1 = int(end_dt.timestamp())
    opens = list(range(grid0, grid1 + 1, WINDOW_SECONDS))

    ungated_n = ungated_hit = 0
    gated_n = gated_hit = 0
    resolved = 0
    missing_spot = 0

    for open_ts in opens:
        if resolved >= max_windows:
            break
        up_wins = _resolve_window(open_ts)
        if up_wins is None:
            continue
        resolved += 1
        decision_ts = open_ts + (WINDOW_SECONDS - eval_t_rem)
        bps = _binance_bps(open_ts, decision_ts)
        if bps is None:
            missing_spot += 1
            continue
        predicted_up = bps >= 0.0  # spot.favored_side(): >=0 -> UP
        ungated_n += 1
        if predicted_up == up_wins:
            ungated_hit += 1
        if abs(bps) >= threshold:
            gated_n += 1
            if predicted_up == up_wins:
                gated_hit += 1
        time.sleep(0.05)  # be polite to Binance

    res = {
        "range": [start, end],
        "threshold_bps": threshold,
        "eval_t_remaining_s": eval_t_rem,
        "windows_on_grid": len(opens),
        "windows_resolved": resolved,
        "spot_data_missing": missing_spot,
        "ungated": {
            "n": ungated_n,
            "accuracy_pct": round(100.0 * ungated_hit / ungated_n, 1) if ungated_n else None,
        },
        "gated": {
            "n": gated_n,
            "coverage_pct": round(100.0 * gated_n / ungated_n, 1) if ungated_n else None,
            "accuracy_pct": round(100.0 * gated_hit / gated_n, 1) if gated_n else None,
        },
    }
    if out:
        with open(out, "w") as f:
            json.dump(res, f, indent=2)
    return res


def main() -> None:
    p = argparse.ArgumentParser(description="Historical spot-gate signal audit (Option B).")
    p.add_argument("--start", required=True, help="YYYY-MM-DD (UTC) range start")
    p.add_argument("--end", required=True, help="YYYY-MM-DD (UTC) range end")
    p.add_argument("--threshold", type=float, default=5.0, help="gate bps threshold")
    p.add_argument("--eval-t-rem", type=int, default=120, help="decision time before close (s)")
    p.add_argument("--max-windows", type=int, default=10_000, help="safety cap on resolved windows")
    p.add_argument("--out", default=None, help="write JSON results here")
    a = p.parse_args()

    r = run(a.start, a.end, a.threshold, a.eval_t_rem, a.max_windows, a.out)
    print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
