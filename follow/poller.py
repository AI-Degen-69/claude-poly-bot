"""Poll each account's Polymarket activity and mirror new TRADE fills.

We page by `start=<last_ts>` (verified: the data-api honours it and returns
records with ts >= start), dedup on tx:asset:side:price:size, and stake each
mirrored fill proportionally to their trade, scaled to the account's bankroll.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from bot.fees import taker_fee
from follow import store
from follow.accounts import Account

log = logging.getLogger("follow.poll")
DATA_API = "https://data-api.polymarket.com/activity"


def _fetch(addr: str, start: int) -> list[dict]:
    params = {"user": addr, "limit": 500}
    if start:
        params["start"] = start
    r = requests.get(DATA_API, params=params,
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def poll_account(acct: Account) -> int:
    """Fetch + store new fills for one account. Returns count newly stored."""
    # No cursor yet = first ever poll for this account. Start at the experiment
    # epoch rather than 0, otherwise the API backfills ~500 historical trades
    # and THEIRS begins with hundreds of already-resolved markets while the
    # FOLLOWER has none -- the two sides would not be comparable.
    cursor = store.get_cursor(acct.key) or int(store.get_epoch())
    try:
        rows = _fetch(acct.addr, cursor)
    except Exception as e:
        log.warning("%s fetch failed: %s", acct.key, e)
        return 0

    new = 0
    newest = cursor
    now = time.time()
    for r in rows:
        if r.get("type") != "TRADE":
            continue
        ts = int(r.get("timestamp", 0))
        newest = max(newest, ts)
        # Hard epoch guard: the API can return records at/just before `start`,
        # and nothing before the epoch belongs in this experiment.
        if ts < cursor:
            continue
        # A fill at the exact cursor ts may already be stored; the UNIQUE
        # dedup_key makes re-inserting it harmless.
        size = float(r.get("size") or 0)
        price = float(r.get("price") or 0)
        if size <= 0 or price <= 0:
            continue
        side = (r.get("side") or "BUY").upper()
        our_shares = size * acct.copy_scale
        # Charge THEM the same taker fee the follower pays. Without this the
        # comparison was rigged: the follower was billed $157.75 of fees while
        # THEIRS was computed gross, which alone accounted for ~60% of the
        # apparent performance gap. They pay this fee in reality too.
        fee = taker_fee(our_shares, price)
        # Signed cashflow into the paper account: buying costs money (-),
        # selling returns it (+). Redemption at resolution is added later.
        gross = our_shares * price
        our_cost = (-gross - fee) if side == "BUY" else (gross - fee)
        tx = r.get("transactionHash") or ""
        asset = r.get("asset") or ""
        dedup = f"{tx}:{asset}:{side}:{price}:{size}"
        inserted = store.insert_fill(
            account=acct.key, ts=ts, detected_ts=now,
            condition_id=r.get("conditionId"), market_slug=r.get("slug"),
            title=r.get("title"), token_id=asset, outcome=r.get("outcome"),
            side=side, their_price=price, their_usdc=float(r.get("usdcSize") or 0),
            our_shares=our_shares, our_cost=our_cost, fee=fee, tx_hash=tx, dedup_key=dedup,
        )
        if inserted:
            new += 1

    if newest > cursor:
        store.set_cursor(acct.key, newest)
    if new:
        log.info("%s: +%d fills (cursor->%d)", acct.key, new, newest)
    return new
