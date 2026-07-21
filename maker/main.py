"""Maker simulation loop. Posts nothing real -- models resting bids only.

Cycle, once per second:
  1. find the live 5-min market
  2. pull FULL book depth for both outcomes
  3. feed the books to the queue-aware fill engine (which decides what filled)
  4. re-quote: cancel stale bids, post fresh ones
  5. when a window ends, resolve it and bank the outcome

Never touches the taker bot's files, DB, or process.
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Optional

import requests

from bot.config import load as load_bot_cfg
from bot.markets import fetch_live_market
from maker import store
from maker.config import load as load_cfg
from maker.fills import QueueFillEngine
from maker.quotes import Inventory, decide_quotes

log = logging.getLogger("maker")

# pid file for the single-instance guard
ROOT_PID = __import__("pathlib").Path(__file__).resolve().parent.parent / "maker.pid"


def full_book(clob_host: str, token_id: str) -> dict:
    """Full depth, not just top-of-book -- queue position needs the level sizes."""
    r = requests.get(f"{clob_host}/book", params={"token_id": token_id}, timeout=10)
    r.raise_for_status()
    b = r.json()
    bids = {round(float(x["price"]), 4): float(x["size"]) for x in (b.get("bids") or [])}
    asks = {round(float(x["price"]), 4): float(x["size"]) for x in (b.get("asks") or [])}
    return {
        "token_id": token_id,
        "bids": bids,
        "asks": asks,
        "best_bid": max(bids) if bids else None,
        "best_ask": min(asks) if asks else None,
    }


def resolve_finished(bot_cfg) -> int:
    n = 0
    for cond, slug in store.unresolved():
        try:
            r = requests.get(f"{bot_cfg.gamma_host}/events", params={"slug": slug},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            d = r.json()
            if not d:
                continue
            mk = (d[0].get("markets") or [{}])[0]
            if not mk.get("closed"):
                continue
            import json as _j
            pr = mk.get("outcomePrices"); toks = mk.get("clobTokenIds")
            if isinstance(pr, str): pr = _j.loads(pr)
            if isinstance(toks, str): toks = _j.loads(toks)
            if not pr or not toks or len(pr) != 2:
                continue
            store.record_resolution(cond, str(toks[0 if float(pr[0]) > float(pr[1]) else 1]))
            log.info("resolved %s", slug)
            n += 1
        except Exception as e:
            log.debug("resolve failed %s: %s", slug, e)
    return n


def _single_instance_guard() -> None:
    """Refuse to start if another maker.main is already running.

    Four copies once ran concurrently against the same maker.db. Each keeps its
    OWN in-memory inventory and fill engine, so the DB ends up holding the SUM
    of several independent strategies -- silently invalid data that still looks
    plausible. Cheap guard, expensive bug.
    """
    import os
    import sys
    pid_file = ROOT_PID
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
        except Exception:
            old = None
        if old and old != os.getpid() and _pid_alive(old):
            sys.exit(f"maker.main already running (pid {old}). Stop it first.")
    pid_file.write_text(str(os.getpid()))


def _pid_alive(pid: int) -> bool:
    import sys
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259
    import os
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def loop() -> None:
    cfg = load_cfg()
    bot_cfg = load_bot_cfg()
    _single_instance_guard()
    log.info("maker sim starting | bankroll $%.0f | quote %dsh %d tick under ask",
             cfg.bankroll_usd, cfg.quote_shares, cfg.ticks_below_ask)

    engine = QueueFillEngine()
    inv_by_market: dict[str, Inventory] = {}
    quote_ids: dict[int, dict] = {}       # id(RestingOrder) -> meta for logging
    current_cond: Optional[str] = None
    last_quote = 0.0
    last_resolve = 0.0
    last_dec_flush = 0.0

    while True:
        now = time.time()
        try:
            m = fetch_live_market(bot_cfg.gamma_host, cfg.series_slug)
        except Exception as e:
            log.warning("market fetch failed: %s", e)
            time.sleep(2.0)
            continue
        if not m:
            time.sleep(1.0)
            continue

        # New window -> drop stale quotes, start a fresh inventory.
        if m.condition_id != current_cond:
            engine.cancel()
            current_cond = m.condition_id
            inv_by_market.setdefault(m.condition_id, Inventory())
            log.info("new market %s", m.market_slug)

        inv = inv_by_market.setdefault(m.condition_id, Inventory())
        t_rem = m.end_ts - now

        try:
            up = full_book(bot_cfg.clob_host, m.up_token)
            dn = full_book(bot_cfg.clob_host, m.down_token)
        except Exception as e:
            log.warning("book fetch failed: %s", e)
            time.sleep(cfg.poll_interval_sec)
            continue

        # 1. Apply book movement -> fills.
        for bk in (up, dn):
            for f in engine.on_book(bk["token_id"], bk["bids"], now):
                meta = quote_ids.get(f.token_id + f"{f.price:.4f}", {})
                if f.side == "UP":
                    inv.up_shares += f.size; inv.up_cost += f.size * f.price
                else:
                    inv.down_shares += f.size; inv.down_cost += f.size * f.price
                inv.fills += 1
                store.log_fill(
                    quote_id=meta.get("quote_id"), market_slug=m.market_slug,
                    condition_id=m.condition_id, token_id=f.token_id, side=f.side,
                    price=f.price, size=f.size, mid_at_post=meta.get("mid"),
                    edge_vs_mid=meta.get("edge_vs_mid"), queue_waited=f.queue_waited,
                    seconds_to_fill=now - meta.get("posted_ts", now),
                )
                log.info("FILL %s %.0fsh @ %.3f (queue waited %.0f) pair=%.4f bal=%.2f",
                         f.side, f.size, f.price, f.queue_waited,
                         inv.pair_cost(), inv.balance)

        # 2. Re-quote.
        if now - last_quote >= cfg.requote_interval_sec:
            last_quote = now
            stale = [o for o in engine.open_orders()]
            engine.cancel()
            store.mark_cancelled([quote_ids.get(o.token_id + f"{o.price:.4f}", {}).get("quote_id")
                                  for o in stale
                                  if quote_ids.get(o.token_id + f"{o.price:.4f}", {}).get("quote_id")])

            intents, why = decide_quotes(cfg, up, dn, inv, t_rem)
            # ONE decision row per cycle, not one per side. Logging each side
            # separately made the run key alternate UP/DOWN every cycle, so
            # runs never built and compression stalled at ~2x. The exact
            # per-quote record still lives in the `quotes` table.
            if not intents:
                store.log_decision(
                    market_slug=m.market_slug, condition_id=m.condition_id,
                    action="SKIP_QUOTE", side=None, price=None,
                    mid=None, edge_vs_mid=None, t_remaining=t_rem,
                    balance=inv.balance, pair_cost=inv.pair_cost(), reason=why,
                )
            else:
                sides = "+".join(sorted(q.side for q in intents))
                store.log_decision(
                    market_slug=m.market_slug, condition_id=m.condition_id,
                    action="QUOTE", side=sides,
                    price=intents[0].price, mid=intents[0].mid,
                    edge_vs_mid=intents[0].edge_vs_mid, t_remaining=t_rem,
                    balance=inv.balance, pair_cost=inv.pair_cost(),
                    reason="; ".join(f"{q.side}@{q.price:.2f}" for q in intents),
                )
            if intents:
                for qi in intents:
                    bk = up if qi.side == "UP" else dn
                    o = engine.post(qi.token_id, qi.side, qi.price, qi.size, bk["bids"], now)
                    qid = store.log_quote(
                        market_slug=m.market_slug, condition_id=m.condition_id,
                        token_id=qi.token_id, side=qi.side, price=qi.price,
                        size=qi.size, queue_ahead=o.queue_ahead, mid=qi.mid,
                        edge_vs_mid=qi.edge_vs_mid, t_remaining=t_rem,
                    )
                    quote_ids[qi.token_id + f"{qi.price:.4f}"] = {
                        "quote_id": qid, "mid": qi.mid,
                        "edge_vs_mid": qi.edge_vs_mid, "posted_ts": now,
                    }
            elif why:
                log.debug("no quotes: %s", why)

        # 2b. Publish what we're looking at, so the dashboard process can render
        # the live market without duplicating market/book polling.
        store.set_live_state({
            "market_slug": m.market_slug,
            "condition_id": m.condition_id,
            "end_ts": m.end_ts,
            "t_remaining": t_rem,
            "up": {"best_bid": up["best_bid"], "best_ask": up["best_ask"],
                   "bid_depth": sum(up["bids"].values()),
                   "top_bids": sorted(up["bids"].items(), reverse=True)[:5]},
            "down": {"best_bid": dn["best_bid"], "best_ask": dn["best_ask"],
                     "bid_depth": sum(dn["bids"].values()),
                     "top_bids": sorted(dn["bids"].items(), reverse=True)[:5]},
            "inventory": {
                "up_shares": inv.up_shares, "down_shares": inv.down_shares,
                "up_avg": inv.avg("UP"), "down_avg": inv.avg("DOWN"),
                "cost": inv.cost, "balance": inv.balance,
                "pair_cost": inv.pair_cost(), "fills": inv.fills,
            },
            "open_quotes": [
                {"side": o.side, "price": o.price, "size": o.size,
                 "filled": o.filled, "queue_ahead": o.queue_ahead}
                for o in engine.open_orders()
            ],
        })

        # Flush the collapsed decision run so the log reaches the DB even
        # while the decision is unchanged.
        if now - last_dec_flush > 5:
            last_dec_flush = now
            store.flush_decision()

        # 3. Resolutions.
        if now - last_resolve > 30:
            last_resolve = now
            try:
                resolve_finished(bot_cfg)
            except Exception as e:
                log.warning("resolve pass failed: %s", e)

        time.sleep(cfg.poll_interval_sec)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S",
    )
    try:
        loop()
    except KeyboardInterrupt:
        log.info("shutdown")


if __name__ == "__main__":
    main()
