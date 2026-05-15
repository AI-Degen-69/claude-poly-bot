"""SQLite logger for every decision and order outcome."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,                  -- 'UP' or 'DOWN'
    t_remaining REAL,
    ask_price REAL,
    ask_size REAL,
    action TEXT,                -- 'BUY', 'SKIP_PRICE', 'SKIP_TIME', 'SKIP_SIZE', 'SKIP_AMBIGUOUS', 'SKIP_RISK'
    reason TEXT,
    dry_run INTEGER NOT NULL    -- 1 if shadow, 0 if live
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,
    size REAL,
    price REAL,
    order_id TEXT,
    status TEXT,
    filled_size REAL,
    error TEXT,
    dry_run INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS resolutions (
    condition_id TEXT PRIMARY KEY,
    winning_token TEXT,
    resolved_ts REAL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_orders_ts ON orders(ts);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    c = _conn()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def log_decision(
    *,
    market_slug: str,
    condition_id: str,
    token_id: Optional[str],
    side: Optional[str],
    t_remaining: float,
    ask_price: Optional[float],
    ask_size: Optional[float],
    action: str,
    reason: str,
    dry_run: bool,
) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO decisions (ts, market_slug, condition_id, token_id, side, "
            "t_remaining, ask_price, ask_size, action, reason, dry_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                market_slug,
                condition_id,
                token_id,
                side,
                t_remaining,
                ask_price,
                ask_size,
                action,
                reason,
                int(dry_run),
            ),
        )


def log_order(
    *,
    market_slug: str,
    condition_id: str,
    token_id: str,
    side: str,
    size: float,
    price: float,
    order_id: Optional[str],
    status: str,
    filled_size: float = 0.0,
    error: Optional[str] = None,
    dry_run: bool,
) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO orders (ts, market_slug, condition_id, token_id, side, "
            "size, price, order_id, status, filled_size, error, dry_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(),
                market_slug,
                condition_id,
                token_id,
                side,
                size,
                price,
                order_id,
                status,
                filled_size,
                error,
                int(dry_run),
            ),
        )


def unresolved_condition_ids(dry_run: bool) -> list[str]:
    """All condition_ids we hold a filled order in but have no resolution recorded."""
    with db() as c:
        rows = c.execute(
            "SELECT DISTINCT o.condition_id FROM orders o "
            "LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "WHERE o.status IN ('filled','matched') AND o.dry_run=? AND r.condition_id IS NULL",
            (int(dry_run),),
        ).fetchall()
        return [r[0] for r in rows]


def unresolved_with_slug(dry_run: bool) -> list[tuple[str, str]]:
    """(condition_id, market_slug) pairs we still need to resolve."""
    with db() as c:
        rows = c.execute(
            "SELECT DISTINCT o.condition_id, o.market_slug FROM orders o "
            "LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "WHERE o.status IN ('filled','matched') AND o.dry_run=? AND r.condition_id IS NULL",
            (int(dry_run),),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]


def record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO resolutions (condition_id, winning_token, resolved_ts) "
            "VALUES (?,?,?)",
            (condition_id, winning_token, time.time()),
        )


def open_positions_count(dry_run: bool) -> int:
    """Count distinct condition_ids where we've bought but not yet resolved."""
    return len(unresolved_condition_ids(dry_run))


def consecutive_losses(dry_run: bool, limit: int = 10) -> int:
    """Count consecutive losing resolved markets from most recent backwards."""
    with db() as c:
        rows = c.execute(
            "SELECT o.token_id, r.winning_token FROM orders o "
            "JOIN resolutions r ON r.condition_id=o.condition_id "
            "WHERE o.status IN ('filled','matched') AND o.dry_run=? "
            "ORDER BY r.resolved_ts DESC LIMIT ?",
            (int(dry_run), limit),
        ).fetchall()
        streak = 0
        for token, winner in rows:
            if token == winner:
                break
            streak += 1
        return streak


def realized_pnl_today(dry_run: bool) -> float:
    """Sum gain/loss across resolved markets in the last 24h."""
    cutoff = time.time() - 86400
    with db() as c:
        rows = c.execute(
            "SELECT o.size, o.price, o.token_id, r.winning_token "
            "FROM orders o JOIN resolutions r ON r.condition_id=o.condition_id "
            "WHERE o.status IN ('filled','matched') AND o.dry_run=? AND r.resolved_ts > ?",
            (int(dry_run), cutoff),
        ).fetchall()
        pnl = 0.0
        for size, price, token, winner in rows:
            if token == winner:
                pnl += size * (1.0 - price)
            else:
                pnl -= size * price
        return pnl
