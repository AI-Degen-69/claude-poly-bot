"""Storage for the copy-trade tracker. Turso when configured, else local sqlite.

Reuses the same backend-selection + connection-reuse + batched-write pattern
proven for bot/store.py (per-call reconnect on Turso measured 1.4s/write).
Tables are prefixed `follow_` so this can share one Turso database with the
bonereaper sim without colliding.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "follow.db"

try:
    from libsql import connect as _libsql_connect
    _HAVE_LIBSQL = True
except Exception:
    _HAVE_LIBSQL = False

_TURSO_URL = os.environ.get("TURSO_URL")
_TURSO_TOKEN = os.environ.get("TURSO_TOKEN")
USE_TURSO = bool(_TURSO_URL) and _HAVE_LIBSQL


def _db_path() -> Path:
    return Path(os.environ.get("POLYFOLLOW_DB", str(DB_PATH)))


def backend_name() -> str:
    if USE_TURSO:
        return "turso"
    if _TURSO_URL and not _HAVE_LIBSQL:
        return "sqlite (TURSO_URL set but libsql NOT installed!)"
    return "sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS follow_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,          -- account.key
    ts REAL NOT NULL,               -- THEIR trade timestamp (unix)
    detected_ts REAL NOT NULL,      -- when we saw it
    condition_id TEXT,
    market_slug TEXT,
    title TEXT,
    token_id TEXT,                  -- asset
    outcome TEXT,                   -- 'Up'/'Down'/'Yes'/'No'
    side TEXT,                      -- 'BUY' | 'SELL'
    their_price REAL,
    their_usdc REAL,                -- their usdcSize
    our_shares REAL,                -- their size * copy_scale
    our_cost REAL,                  -- signed cashflow: -shares*price (BUY), +(SELL)
    fee REAL DEFAULT 0,
    tx_hash TEXT,
    dedup_key TEXT UNIQUE           -- tx:asset:side:price:size, INSERT OR IGNORE
);

CREATE TABLE IF NOT EXISTS follow_resolutions (
    condition_id TEXT PRIMARY KEY,
    winning_token TEXT,
    resolved_ts REAL
);

CREATE TABLE IF NOT EXISTS follow_cursor (
    account TEXT PRIMARY KEY,
    last_ts INTEGER                 -- newest trade ts we've stored, for start=
);

-- Single-row table holding the experiment epoch: the instant this run began.
-- Both sides of the comparison (THEIRS and FOLLOWER) only count activity from
-- here onward, so neither gets a head start.
CREATE TABLE IF NOT EXISTS follow_meta (
    k TEXT PRIMARY KEY,
    v REAL
);

-- The FOLLOWER simulation: what a real copy-trader could actually have got.
-- One row per attempted follow of a follow_fills row. Price comes from the
-- LIVE CLOB book at the moment we detected their trade, not from their fill.
CREATE TABLE IF NOT EXISTS follow_shadow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id INTEGER UNIQUE,         -- follow_fills.id we tried to copy
    account TEXT NOT NULL,
    condition_id TEXT,
    market_slug TEXT,
    token_id TEXT,
    outcome TEXT,
    side TEXT,
    their_ts REAL,                  -- when THEY traded
    detect_ts REAL,                 -- when we saw it
    exec_ts REAL,                   -- when we priced our follow
    their_price REAL,
    our_price REAL,                 -- real book price we'd have taken
    our_shares REAL,                -- capped by real resting depth
    slippage REAL,                  -- our_price - their_price (BUY: +ve is worse)
    fee REAL DEFAULT 0,
    cashflow REAL,                  -- signed: -shares*price (BUY), + (SELL)
    lag_sec REAL,                   -- exec_ts - their_ts, total follow latency
    status TEXT                     -- filled | missed_closed | no_book | no_depth
);

CREATE INDEX IF NOT EXISTS idx_follow_fills_acct ON follow_fills(account, ts);
CREATE INDEX IF NOT EXISTS idx_follow_fills_cond ON follow_fills(condition_id);
CREATE INDEX IF NOT EXISTS idx_shadow_acct ON follow_shadow(account, their_ts);
CREATE INDEX IF NOT EXISTS idx_shadow_cond ON follow_shadow(condition_id);
"""


def _conn():
    c = _libsql_connect(_TURSO_URL, auth_token=_TURSO_TOKEN) if USE_TURSO \
        else sqlite3.connect(str(_db_path()))
    c.executescript(SCHEMA)
    return c


_shared = None
_lock = threading.Lock()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    global _shared
    if not USE_TURSO:
        c = _conn()
        try:
            yield c
            c.commit()
        finally:
            c.close()
        return
    with _lock:
        if _shared is None:
            _shared = _conn()
        try:
            yield _shared
            _shared.commit()
        except Exception:
            try:
                _shared.close()
            except Exception:
                pass
            _shared = None
            raise


def get_epoch() -> float:
    """The instant this experiment started. Set once, on first run.

    Everything is measured from here so THEIRS and FOLLOWER start level. Without
    it the first poll backfills ~500 historical trades, handing the THEIRS side
    hundreds of already-resolved markets while the follower has none.
    """
    with db() as c:
        r = c.execute("SELECT v FROM follow_meta WHERE k='epoch'").fetchone()
        if r:
            return float(r[0])
        now = time.time()
        c.execute("INSERT INTO follow_meta (k,v) VALUES ('epoch',?)", (now,))
        return now


def get_cursor(account: str) -> int:
    with db() as c:
        r = c.execute("SELECT last_ts FROM follow_cursor WHERE account=?",
                      (account,)).fetchone()
        return int(r[0]) if r and r[0] else 0


def set_cursor(account: str, last_ts: int) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO follow_cursor (account,last_ts) VALUES (?,?) "
            "ON CONFLICT(account) DO UPDATE SET last_ts=excluded.last_ts",
            (account, int(last_ts)),
        )


def insert_fill(**f) -> bool:
    """Insert one mirrored fill. Returns True if newly inserted, False if a dup.

    Uses SELECT changes() rather than cursor.rowcount, which libsql does not
    report reliably. changes() returns rows affected by the last INSERT, so it
    is 1 on a real insert and 0 when the UNIQUE dedup_key made it a no-op.
    """
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO follow_fills "
            "(account,ts,detected_ts,condition_id,market_slug,title,token_id,"
            " outcome,side,their_price,their_usdc,our_shares,our_cost,fee,"
            " tx_hash,dedup_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["account"], f["ts"], f["detected_ts"], f["condition_id"],
             f["market_slug"], f["title"], f["token_id"], f["outcome"],
             f["side"], f["their_price"], f["their_usdc"], f["our_shares"],
             f["our_cost"], f.get("fee", 0.0), f["tx_hash"], f["dedup_key"]),
        )
        changed = c.execute("SELECT changes()").fetchone()[0]
    return bool(changed)


def record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO follow_resolutions "
            "(condition_id,winning_token,resolved_ts) VALUES (?,?,?)",
            (condition_id, winning_token, time.time()),
        )


def unshadowed_fills(account: str, limit: int = 60) -> list[dict]:
    """Their fills we haven't yet attempted to follow. Newest first -- a stale
    fill is unfollowable anyway, so there is no value in working backwards."""
    with db() as c:
        cur = c.execute(
            "SELECT f.id, f.account, f.ts, f.detected_ts, f.condition_id, "
            "       f.market_slug, f.token_id, f.outcome, f.side, f.their_price, "
            "       f.our_shares "
            "FROM follow_fills f LEFT JOIN follow_shadow s ON s.fill_id=f.id "
            "WHERE f.account=? AND s.fill_id IS NULL "
            "ORDER BY f.ts DESC LIMIT ?", (account, limit),
        )
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def insert_shadow(**s) -> bool:
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO follow_shadow "
            "(fill_id,account,condition_id,market_slug,token_id,outcome,side,"
            " their_ts,detect_ts,exec_ts,their_price,our_price,our_shares,"
            " slippage,fee,cashflow,lag_sec,status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["fill_id"], s["account"], s["condition_id"], s["market_slug"],
             s["token_id"], s["outcome"], s["side"], s["their_ts"], s["detect_ts"],
             s["exec_ts"], s["their_price"], s["our_price"], s["our_shares"],
             s["slippage"], s["fee"], s["cashflow"], s["lag_sec"], s["status"]),
        )
        return bool(c.execute("SELECT changes()").fetchone()[0])


def recent_shadow(account: str, limit: int = 20) -> list[dict]:
    with db() as c:
        cur = c.execute(
            "SELECT their_ts, side, outcome, their_price, our_price, slippage, "
            "       our_shares, status, lag_sec, market_slug FROM follow_shadow "
            "WHERE account=? ORDER BY their_ts DESC LIMIT ?", (account, limit),
        )
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def recent_fills(account: str, limit: int = 25) -> list[dict]:
    with db() as c:
        cur = c.execute(
            "SELECT ts, side, outcome, their_price, our_shares, their_usdc, "
            "       market_slug, title FROM follow_fills WHERE account=? "
            "ORDER BY ts DESC LIMIT ?", (account, limit),
        )
        cols = [d[0].lower() for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def recent_settlements(account: str, limit: int = 15) -> list[dict]:
    """Resolved markets for this account, newest first, with net P&L."""
    with db() as c:
        cur = c.execute(
            "SELECT f.condition_id, f.market_slug, f.title, "
            "       SUM(f.our_cost) cashflow, r.winning_token, r.resolved_ts "
            "FROM follow_fills f JOIN follow_resolutions r "
            "  ON r.condition_id=f.condition_id "
            "WHERE f.account=? GROUP BY f.condition_id "
            "ORDER BY r.resolved_ts DESC LIMIT ?", (account, limit),
        )
        cols = [d[0].lower() for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    # add redemption (net winning shares) per market
    out = []
    for row in rows:
        with db() as c:
            net = c.execute(
                "SELECT token_id, SUM(CASE WHEN side='BUY' THEN our_shares "
                "ELSE -our_shares END) FROM follow_fills "
                "WHERE account=? AND condition_id=? GROUP BY token_id",
                (account, row["condition_id"]),
            ).fetchall()
        payout = sum(s for t, s in net if t == row["winning_token"] and s and s > 0)
        row["payout"] = payout
        row["pnl"] = row["cashflow"] + payout
        row["won"] = payout > 0
        out.append(row)
    return out


def unresolved_conditions() -> list[tuple[str, str]]:
    """(condition_id, market_slug) we hold fills in but haven't resolved."""
    with db() as c:
        rows = c.execute(
            "SELECT DISTINCT f.condition_id, f.market_slug FROM follow_fills f "
            "LEFT JOIN follow_resolutions r ON r.condition_id=f.condition_id "
            "WHERE r.condition_id IS NULL AND f.condition_id IS NOT NULL"
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
