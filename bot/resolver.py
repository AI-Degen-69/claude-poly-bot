"""Resolve filled orders by polling gamma for the winning outcome."""
from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from bot import store
from bot.config import Config

log = logging.getLogger("bot.resolver")


def _winning_token_for(cfg: Config, market_slug: str) -> Optional[str]:
    try:
        # gamma's condition_ids filter hides closed markets; slug + closed=true works.
        r = requests.get(
            f"{cfg.gamma_host}/markets",
            params={"slug": market_slug, "closed": "true"},
            timeout=4,
        )
        if r.status_code != 200:
            return None
        markets = r.json()
        if not markets:
            return None
        m = markets[0] if isinstance(markets, list) else markets
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
        log.debug("resolution lookup failed for %s: %s", condition_id, e)
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
