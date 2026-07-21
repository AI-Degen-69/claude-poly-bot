"""Resolve the markets we've mirrored fills in, via gamma /events by slug.

Uses /events (not /markets) for the same reason bot/resolver.py does:
/markets?slug= returns empty once a 5-min market ages out of that index.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from follow import store

log = logging.getLogger("follow.resolve")
GAMMA = "https://gamma-api.polymarket.com/events"


def winning_token(market_slug: str) -> Optional[str]:
    if not market_slug:
        return None
    try:
        r = requests.get(GAMMA, params={"slug": market_slug},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
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
        toks = m.get("clobTokenIds")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if isinstance(toks, str):
            toks = json.loads(toks)
        if not prices or not toks or len(prices) != 2 or len(toks) != 2:
            return None
        return str(toks[0] if float(prices[0]) > float(prices[1]) else toks[1])
    except Exception as e:
        log.debug("resolve %s failed: %s", market_slug, e)
        return None


def resolve_pending(limit: int = 40) -> int:
    n = 0
    for cond, slug in store.unresolved_conditions()[:limit]:
        w = winning_token(slug)
        if w is not None:
            store.record_resolution(cond, w)
            n += 1
    return n
