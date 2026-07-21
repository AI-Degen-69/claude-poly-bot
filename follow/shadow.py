"""The FOLLOWER simulation — what a real copy-trader could actually have got.

The difference from follow/poller.py, which is the whole point of this module:

  poller  -> records THEIR fill at THEIR price. Measures the account's own edge.
             It is effectively the activity page turned into P&L.
  shadow  -> when we DETECT their fill, fetches the LIVE CLOB order book and
             fills at the price actually resting there, capped by real depth.
             Measures what a follower with real latency could capture.

Measured on 25,062 stored fills before building this:
    detection lag   median 10.9s, mean 23.5s, p90 30s
    price moves     median 4.58c over a ~13s gap
On a 0.95 entry the edge is 5c, so the slippage is about the size of the whole
edge. This module quantifies exactly that, per fill.

Every outcome is recorded, including the ones where following was impossible:
    filled        -> we got a real book price
    missed_closed -> their market had already closed by the time we saw it
    no_book       -> no ask/bid resting on that side
    no_depth      -> book existed but under our minimum size

NOTE: this places NO real orders. It prices against the real book and records
the result. Nothing is signed and no funds move.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bot.fees import taker_fee
from follow import store

log = logging.getLogger("follow.shadow")

CLOB = "https://clob.polymarket.com"
MIN_SHARES = 5.0          # Polymarket minimum order
BOOK_TTL = 1.5            # seconds; many fills share a token within a cycle
_book_cache: dict[str, tuple[float, object]] = {}

# A real follower does not chase a minute-old trade -- by then it is simply a
# different, already-converged market. Anything older than this is recorded as
# `too_old` WITHOUT a book fetch, so a processing backlog can never masquerade
# as realistic follow latency (the first run of this module ground through a
# 7,976-fill overnight backlog and produced 100s "lags", which are an artifact
# of the queue, not of following).
MAX_FOLLOW_AGE_SEC = 45.0


def _ladder(token_id: str) -> dict:
    """Full depth ladder, not just top-of-book.

    bot.book.fetch_book collapses the book to the best price only, which made
    this simulation reject fills that a real taker would simply walk into: a
    live BTC-5m book routinely shows 460 shares at the touch and 7,000+ within
    two ticks. A taker order eats levels in order, so we must model that.
    """
    now = time.time()
    hit = _book_cache.get(token_id)
    if hit and now - hit[0] < BOOK_TTL:
        return hit[1]
    r = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=5)
    r.raise_for_status()
    d = r.json()
    lad = {
        "asks": sorted((float(a["price"]), float(a["size"])) for a in (d.get("asks") or [])),
        "bids": sorted(((float(b["price"]), float(b["size"])) for b in (d.get("bids") or [])),
                       reverse=True),
    }
    _book_cache[token_id] = (now, lad)
    if len(_book_cache) > 500:
        for k in [k for k, v in _book_cache.items() if now - v[0] > 30]:
            _book_cache.pop(k, None)
    return lad


def walk(levels: list[tuple[float, float]], want: float) -> tuple[float, float, float]:
    """Consume `want` shares across price levels like a real taker order.

    Returns (shares_filled, vwap, worst_price_touched). This is what makes the
    follower honest: you don't get the touch price for size, you get the
    volume-weighted average of every level you had to eat.
    """
    got = 0.0
    spend = 0.0
    worst = 0.0
    for px, sz in levels:
        if got >= want:
            break
        take = min(want - got, sz)
        if take <= 0:
            continue
        got += take
        spend += take * px
        worst = px
    return got, (spend / got if got else 0.0), worst


def _window_end(slug: str) -> float | None:
    """5-min markets encode their open ts in the slug; they close 300s later."""
    try:
        if "updown-5m-" in slug:
            return float(slug.rsplit("-", 1)[1]) + 300.0
    except Exception:
        pass
    return None


def shadow_one(row: dict) -> dict | None:
    """Price one follow attempt against the live book. Returns the record."""
    now = time.time()
    slug = row["market_slug"] or ""
    end = _window_end(slug)
    age = now - (row["ts"] or now)
    if age > MAX_FOLLOW_AGE_SEC:
        rec = dict(status="too_old", our_price=None, our_shares=0.0,
                   slippage=None, cashflow=0.0, fee=0.0)
    # Trading continues ~90s past endDate while the oracle settles, but a
    # market well past close cannot be followed at all.
    elif end is not None and now > end + 60:
        rec = dict(status="missed_closed", our_price=None, our_shares=0.0,
                   slippage=None, cashflow=0.0, fee=0.0)
    else:
        try:
            lad = _ladder(row["token_id"])
        except Exception as e:
            log.debug("book fetch failed %s: %s", row["token_id"][:12], e)
            lad = None
        if not lad:
            rec = dict(status="no_book", our_price=None, our_shares=0.0,
                       slippage=None, cashflow=0.0, fee=0.0)
        else:
            side = row["side"]
            # BUY -> walk the asks.  SELL -> walk the bids.
            levels = lad["asks"] if side == "BUY" else lad["bids"]
            # A real follower whose proportional size lands under the exchange
            # minimum buys the minimum -- they do not skip the trade. Rejecting
            # these as "no_depth" was wrong: 203 of 204 such rejections had a
            # deep book and merely a 2.5-share intent.
            want = max(float(row["our_shares"] or 0.0), MIN_SHARES)
            got, vwap, worst = walk(levels, want)
            if got < MIN_SHARES or vwap <= 0:
                rec = dict(status="no_depth", our_price=(vwap or None),
                           our_shares=0.0,
                           slippage=(vwap - row["their_price"]) if vwap else None,
                           cashflow=0.0, fee=0.0)
            else:
                fee = taker_fee(got, vwap)
                cash = -(got * vwap) - fee if side == "BUY" else (got * vwap) - fee
                rec = dict(status="filled", our_price=vwap, our_shares=got,
                           slippage=vwap - row["their_price"], cashflow=cash, fee=fee)

    rec.update(
        fill_id=row["id"], account=row["account"], condition_id=row["condition_id"],
        market_slug=slug, token_id=row["token_id"], outcome=row["outcome"],
        side=row["side"], their_ts=row["ts"], detect_ts=row["detected_ts"],
        exec_ts=now, their_price=row["their_price"], lag_sec=now - row["ts"],
    )
    return rec


def run_shadow(account: str, limit: int = 60, workers: int = 8) -> int:
    """Shadow any of `account`'s fills we haven't attempted yet."""
    pending = store.unshadowed_fills(account, limit)
    if not pending:
        return 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        recs = list(ex.map(shadow_one, pending))
    n = 0
    for r in recs:
        if r and store.insert_shadow(**r):
            n += 1
    if n:
        log.info("shadowed %d fills for %s", n, account)
    return n
