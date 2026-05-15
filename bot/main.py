"""Main event loop. Dry-run by default; --live to actually trade."""
from __future__ import annotations

import argparse
import logging
import time
from typing import Optional

from bot import config, store
from bot.book import fetch_book
from bot.markets import LiveMarket, fetch_live_market
from bot.orders import build_client, place_buy_fok
from bot.resolver import resolve_pending
from bot.risk import allowed_to_trade
from bot.strategy import decide

log = logging.getLogger("bot")


def loop(live: bool) -> None:
    cfg = config.load()
    dry_run = not live
    client = build_client(cfg) if live else None

    # Materialize the DB schema up front.
    with store.db():
        pass

    log.info("starting bot dry_run=%s cap=$%s size=%s", dry_run, cfg.max_entry_price, cfg.order_size_shares)

    current: Optional[LiveMarket] = None
    last_market_refresh = 0.0
    last_resolve_check = 0.0
    traded_this_window: set[str] = set()  # condition_ids we've bought this window

    # Settle anything left unresolved from prior runs before we start.
    resolve_pending(cfg, dry_run)

    while True:
        now = time.time()

        # Periodically resolve filled positions whose markets have closed.
        if now - last_resolve_check > 30:
            try:
                resolve_pending(cfg, dry_run)
            except Exception as e:
                log.warning("resolve_pending failed: %s", e)
            last_resolve_check = now

        # Refresh live market every 5s, or when the current one expires.
        if current is None or now > current.end_ts + 5 or (now - last_market_refresh) > 5:
            try:
                m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
            except Exception as e:
                log.warning("market discovery failed: %s", e)
                m = None
            last_market_refresh = now
            if m and (current is None or m.condition_id != current.condition_id):
                current = m
                log.info("new live market: %s end_ts=%.0f", current.market_slug, current.end_ts)
            elif m is None:
                current = None

        if current is None:
            time.sleep(1.0)
            continue

        t_rem = current.t_remaining(now)
        if t_rem <= 0:
            time.sleep(0.5)
            continue

        # Skip if already traded this market.
        if current.condition_id in traded_this_window:
            time.sleep(cfg.poll_interval_sec)
            continue

        # Only fetch books when we're in (or near) the buy window — save bandwidth.
        if t_rem > cfg.seconds_before_close + 10:
            time.sleep(min(t_rem - cfg.seconds_before_close, 5.0))
            continue

        try:
            book_up = fetch_book(cfg.clob_host, current.up_token)
            book_down = fetch_book(cfg.clob_host, current.down_token)
        except Exception as e:
            log.warning("book fetch failed: %s", e)
            time.sleep(cfg.poll_interval_sec)
            continue

        d = decide(cfg, current, book_up, book_down, t_rem)

        if d.action != "BUY":
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=None,
                action=d.action,
                reason=d.reason,
                dry_run=dry_run,
            )
            time.sleep(cfg.poll_interval_sec)
            continue

        ok, why = allowed_to_trade(cfg, dry_run)
        if not ok:
            store.log_decision(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                t_remaining=t_rem,
                ask_price=d.price,
                ask_size=d.size,
                action="SKIP_RISK",
                reason=why,
                dry_run=dry_run,
            )
            log.info("risk gate: %s", why)
            time.sleep(cfg.poll_interval_sec)
            continue

        log.info(
            "BUY %s %s sz=%s @ %s  t_rem=%.1fs  dry=%s",
            d.side, current.market_slug, d.size, d.price, t_rem, dry_run,
        )
        store.log_decision(
            market_slug=current.market_slug,
            condition_id=current.condition_id,
            token_id=d.token_id,
            side=d.side,
            t_remaining=t_rem,
            ask_price=d.price,
            ask_size=d.size,
            action="BUY",
            reason=d.reason,
            dry_run=dry_run,
        )

        if dry_run:
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                size=d.size,
                price=d.price,
                order_id=None,
                status="dry_run",
                filled_size=0.0,
                dry_run=True,
            )
        else:
            assert client is not None
            result = place_buy_fok(
                client,
                token_id=d.token_id,
                price=d.price,
                size=d.size,
                tick_size=current.tick_size,
                neg_risk=current.neg_risk,
            )
            store.log_order(
                market_slug=current.market_slug,
                condition_id=current.condition_id,
                token_id=d.token_id,
                side=d.side,
                size=d.size,
                price=d.price,
                order_id=result.order_id,
                status="filled" if result.filled_size and result.filled_size > 0 else result.status,
                filled_size=result.filled_size,
                error=result.error,
                dry_run=False,
            )
            log.info("order result: status=%s filled=%s id=%s err=%s",
                     result.status, result.filled_size, result.order_id, result.error)

        traded_this_window.add(current.condition_id)
        time.sleep(cfg.poll_interval_sec)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="actually place orders (default: dry-run)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        loop(live=args.live)
    except KeyboardInterrupt:
        log.info("shutdown")


if __name__ == "__main__":
    main()
