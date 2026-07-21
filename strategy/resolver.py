"""Resolve filled orders by polling gamma for the winning outcome."""
from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from strategy import store
from strategy.config import Config

log = logging.getLogger("bot.resolver")


def _winning_token_for(cfg: Config, market_slug: str) -> Optional[str]:
    try:
        # Use /events, NOT /markets. Measured 2026-07-20: for these 5-min
        # markets `/markets?slug=<slug>&closed=true` returns an EMPTY list once
        # the market ages out of that index -- so positions hung unresolved
        # forever and their PnL never realized. `/events?slug=<slug>` returns
        # the event with the market nested inside, and resolved 584/584 windows
        # in the spot-gate backtest.
        r = requests.get(
            f"{cfg.gamma_host}/events",
            params={"slug": market_slug},
            headers={"User-Agent": "Mozilla/5.0"},  # gamma 403s some clients
            # gamma's closed-market lookup routinely takes >4s; the old timeout
            # silently failed every resolution, leaving PnL permanently pending.
            timeout=20,
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
        token_ids = m.get("clobTokenIds")
        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if not token_ids or len(token_ids) != 2:
            return None
        winner_idx = 0 if float(prices[0]) > float(prices[1]) else 1
        return str(token_ids[winner_idx])
    except Exception as e:
        # NB: this handler used to reference `condition_id`, which is not in
        # scope here -- so any lookup failure raised NameError instead of
        # returning None, aborting the entire resolve pass.
        log.debug("resolution lookup failed for %s: %s", market_slug, e)
        return None


def resolve_pending(cfg: Config, dry_run: bool) -> int:
    """Walk unresolved filled orders and record any that closed. Returns count newly resolved."""
    pending = store.unresolved_with_slug(dry_run)
    n = 0
    for condition_id, slug in pending:
        if not slug:
            continue
        winner = _winning_token_for(cfg, slug)
        if winner is not None:
            store.record_resolution(condition_id, winner)
            log.info("resolved %s -> winner=%s", slug, winner[:14])
            n += 1
    return n
