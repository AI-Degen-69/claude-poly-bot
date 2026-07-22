"""Forward book-collector for the gate retest.

Runs 24/7 in the SAME Railway container as the live bot but writes to a
SEPARATE SQLite file (COLLECTOR_DB, default /data/collector.db). It does NOT
touch trades.db, so there is no two-writer clash (DEPLOY.md's warning is
specifically about two processes hitting the SAME db; separate files are the
documented safe pattern).

What it captures per 5-min window, at t_remaining == 120s (the moment the
strategy's entry band opens):

    bid_up, ask_up, bid_down, ask_down   -- CLOB top-of-book for both sides
    book_favored                         -- UP if bid_up > bid_down else DOWN
    spot_bps                             -- Binance move vs window open (REST)
    spot_favored                         -- UP if spot_bps >= 0 else DOWN

At resolution it records the winner (via the same gamma lookup the resolver
uses) and derives two hit flags:

    hit_book  -- did book_favored == winner?   (the ungated signal)
    hit_gate  -- did (|spot_bps| >= 5 and spot_favored == winner)?  (the gate)

That is exactly the ungated-vs-gated comparison the backtest measured, now
collected forward on live data.

This module is READ-ONLY on the live market: it fetches books and Binance
klines but never places an order, never builds a CLOB client, never signs.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

from strategy.book import fetch_book
from strategy.config import Config
from strategy.markets import fetch_live_market
from strategy.resolver import _winning_token_for

# Poll cadence. 2s is plenty to catch the t_rem==120s crossing (the band is
# 112s wide) without hammering Polymarket.
POLL_SEC = 2.0
# Snapshot the moment the entry band opens: t_remaining in [120, 124].
SNAP_T_REM_MIN = 118.0
SNAP_T_REM_MAX = 126.0
BINANCE_TICKER = "https://api.binance.com/api/v3/ticker/price"
BINANCE_KLINE = "https://api.binance.com/api/v3/klines"


def _collector_config() -> Config:
    """Config with harmless placeholders.

    The collector reads only .gamma_host, .clob_host, .series_slug -- it never
    signs or trades, so fake credentials are fine and we deliberately avoid
    config.load() (which would require real PRIVATE_KEY etc. to be present).
    """
    return Config(
        private_key="0xCOLLECTOR_PLACEHOLDER",
        wallet_address="0xCOLLECTOR_PLACEHOLDER",
        funder_address="0xCOLLECTOR_PLACEHOLDER",
        signature_type=0,
        chain_id=137,
        clob_host=os.environ.get("CLOB_HOST", "https://clob.polymarket.com"),
        gamma_host=os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        polygon_rpc=os.environ.get(
            "POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com"
        ),
        api_key="collector",
        api_secret="collector",
        api_passphrase="collector",
    )


def _db_path() -> Path:
    return Path(os.environ.get("COLLECTOR_DB", "/data/collector.db"))


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_windows (
            condition_id TEXT PRIMARY KEY,
            market_slug  TEXT,
            open_ts      REAL,
            end_ts       REAL,
            snap_ts      REAL,
            bid_up       REAL,  ask_up  REAL,
            bid_down     REAL,  ask_down REAL,
            book_favored TEXT,
            spot_bps     REAL,
            spot_favored TEXT,
            winner       TEXT,
            resolved_ts  REAL,
            status       TEXT,
            hit_book     INTEGER,
            hit_gate     INTEGER
        )
        """
    )
    con.commit()
    return con


def _spot_offset_bps(open_ts: int) -> float | None:
    """REST-only Binance move vs the window open. Avoids running a 2nd WS feed."""
    try:
        r = requests.get(BINANCE_TICKER, params={"symbol": "BTCUSDT"}, timeout=5)
        r.raise_for_status()
        now_px = float(r.json()["price"])
    except Exception:
        return None
    # Window open price from the 1m kline at open_ts (mirrors spot.open_price).
    try:
        r = requests.get(
            BINANCE_KLINE,
            params={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": open_ts * 1000,
                "limit": 1,
            },
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        open_px = float(data[0][1])
    except Exception:
        return None
    if not open_px:
        return None
    return (now_px - open_px) / open_px * 10_000.0


def _book_favored(up: object, down: object) -> str | None:
    bu = getattr(up, "best_bid", None)
    bd = getattr(down, "best_bid", None)
    if bu is None or bd is None:
        return None
    return "UP" if bu > bd else "DOWN"


def _snapshot(con: sqlite3.Connection, cfg: Config, m, now: float) -> None:
    """Record the t_rem==120s book + spot snapshot for the live window."""
    up = fetch_book(cfg.clob_host, m.up_token)
    down = fetch_book(cfg.clob_host, m.down_token)
    off = _spot_offset_bps(int(m.start_ts))
    book_fav = _book_favored(up, down)
    spot_fav = None if off is None else ("UP" if off >= 0 else "DOWN")
    con.execute(
        """
        INSERT OR REPLACE INTO collector_windows
            (condition_id, market_slug, open_ts, end_ts, snap_ts,
             bid_up, ask_up, bid_down, ask_down, book_favored,
             spot_bps, spot_favored, status)
        VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?, 'OPEN')
        """,
        (
            m.condition_id, m.market_slug, m.start_ts, m.end_ts, now,
            up.best_bid, up.best_ask, down.best_bid, down.best_ask, book_fav,
            off, spot_fav,
        ),
    )
    con.commit()
    print(
        f"[collect] snapshot {m.market_slug} book_fav={book_fav} "
        f"spot_bps={None if off is None else round(off, 2)} spot_fav={spot_fav}",
        flush=True,
    )


def _resolve_pending(con: sqlite3.Connection, cfg: Config) -> int:
    """Fill in winners for any snapshotted window that has now closed."""
    rows = con.execute(
        "SELECT condition_id, market_slug, spot_bps, spot_favored, book_favored "
        "FROM collector_windows WHERE status='OPEN'"
    ).fetchall()
    now = time.time()
    n = 0
    for condition_id, slug, spot_bps, spot_favored, book_favored in rows:
        # Give gamma a few seconds past close to mark it resolved.
        end_ts = con.execute(
            "SELECT end_ts FROM collector_windows WHERE condition_id=?",
            (condition_id,),
        ).fetchone()[0]
        if now < end_ts + 15:
            continue
        winner_token = _winning_token_for(cfg, slug)
        if winner_token is None:
            continue
        # Determine winner side by matching the token to the market's tokens.
        m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
        # fetch_live_market returns the CURRENT market; for a just-closed one it
        # may be None. Fall back to comparing via a fresh gamma lookup of tokens.
        winner = _side_for_token(cfg, slug, winner_token)
        if winner is None:
            continue
        hit_book = book_favored is not None and book_favored == winner
        hit_gate = (
            spot_bps is not None
            and abs(spot_bps) >= 5.0
            and spot_favored is not None
            and spot_favored == winner
        )
        con.execute(
            """
            UPDATE collector_windows
            SET winner=?, resolved_ts=?, status='RESOLVED',
                hit_book=?, hit_gate=?
            WHERE condition_id=?
            """,
            (winner, now, int(hit_book), int(hit_gate), condition_id),
        )
        con.commit()
        n += 1
        print(
            f"[collect] resolved {slug} winner={winner} "
            f"hit_book={hit_book} hit_gate={hit_gate}",
            flush=True,
        )
    return n


def _side_for_token(cfg: Config, slug: str, winner_token: str) -> str | None:
    """Map a winning token_id back to UP/DOWN using gamma's market record."""
    try:
        r = requests.get(
            f"{cfg.gamma_host}/events",
            params={"slug": slug},
            headers={"User-Agent": "Mozilla/5.0"},
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
        token_ids = m.get("clobTokenIds")
        import json

        if isinstance(token_ids, str):
            token_ids = json.loads(token_ids)
        if not token_ids or len(token_ids) != 2:
            return None
        return "UP" if str(token_ids[0]) == winner_token else "DOWN"
    except Exception:
        return None


def main() -> None:
    cfg = _collector_config()
    con = _open_db(_db_path())
    dry_run = int(os.environ.get("COLLECTOR_DRY_RUN", "0"))
    snapped = 0
    print(
        f"[collect] started; db={_db_path()} dry_run={dry_run} "
        f"gamma={cfg.gamma_host} clob={cfg.clob_host}",
        flush=True,
    )
    try:
        while True:
            now = time.time()
            m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
            if m:
                t_rem = m.t_remaining(now)
                # Snapshot at the entry-band open.
                if SNAP_T_REM_MIN <= t_rem <= SNAP_T_REM_MAX:
                    already = con.execute(
                        "SELECT 1 FROM collector_windows WHERE condition_id=?",
                        (m.condition_id,),
                    ).fetchone()
                    if not already:
                        _snapshot(con, cfg, m, now)
                        snapped += 1
                        if dry_run and snapped >= dry_run:
                            print(
                                f"[collect] DRY_RUN limit {dry_run} reached; exiting",
                                flush=True,
                            )
                            return
                # Resolve any closed windows (cheap; no-op when none).
                _resolve_pending(con, cfg)
            time.sleep(POLL_SEC)
    except KeyboardInterrupt:
        print("[collect] interrupted", flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    main()
