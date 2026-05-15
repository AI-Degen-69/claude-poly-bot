"""Discover the currently-live BTC 5-min market via gamma-api events endpoint."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class LiveMarket:
    condition_id: str
    market_slug: str
    up_token: str
    down_token: str
    start_ts: float  # unix seconds, market opens
    end_ts: float    # unix seconds, market closes
    tick_size: float
    neg_risk: bool

    def t_remaining(self, now: Optional[float] = None) -> float:
        return self.end_ts - (now if now is not None else time.time())


def _parse_market(market: dict) -> Optional[LiveMarket]:
    token_ids_raw = market.get("clobTokenIds")
    if not token_ids_raw:
        return None
    token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw
    if len(token_ids) != 2:
        return None

    # eventStartTime is the actual trading-window open (UTC :00/:05/:10 boundary).
    # startDate is when the market was *listed*, often hours earlier.
    start_iso = market.get("eventStartTime")
    end_iso = market.get("endDate") or market.get("endDateIso")
    if not start_iso or not end_iso:
        return None

    start_ts = _iso_to_unix(start_iso)
    end_ts = _iso_to_unix(end_iso)
    return LiveMarket(
        condition_id=market["conditionId"],
        market_slug=market.get("slug", ""),
        up_token=str(token_ids[0]),
        down_token=str(token_ids[1]),
        start_ts=start_ts,
        end_ts=end_ts,
        tick_size=float(market.get("orderPriceMinTickSize") or 0.01),
        neg_risk=bool(market.get("negRisk", False)),
    )


def _iso_to_unix(s: str) -> float:
    # tolerate "Z" suffix
    from datetime import datetime
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def fetch_live_market(gamma_host: str, series_slug: str) -> Optional[LiveMarket]:
    """Return the single 5-min BTC market that's currently live, or None."""
    url = f"{gamma_host}/events"
    params = {"series_slug": series_slug, "closed": "false", "limit": 500}
    r = requests.get(url, params=params, timeout=5)
    r.raise_for_status()
    events = r.json()

    now = time.time()
    candidates: list[LiveMarket] = []
    for ev in events:
        markets = ev.get("markets") or []
        for m in markets:
            lm = _parse_market(m)
            if lm and lm.start_ts <= now < lm.end_ts:
                candidates.append(lm)
    if not candidates:
        return None
    candidates.sort(key=lambda m: m.start_ts, reverse=True)
    return candidates[0]


if __name__ == "__main__":
    from bot.config import load

    cfg = load()
    m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
    if not m:
        print("no live market right now")
    else:
        rem = m.t_remaining()
        print(f"live: {m.market_slug}  t_remaining={rem:.1f}s")
        print(f"  cond={m.condition_id}")
        print(f"  up_token={m.up_token[:18]}...")
        print(f"  down_token={m.down_token[:18]}...")
        print(f"  tick={m.tick_size}  neg_risk={m.neg_risk}")
