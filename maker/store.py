"""SQLite store for the maker sim. Entirely separate DB from the taker bot.

Schema is maker-shaped: we record every QUOTE we post (not just fills), because
for a maker the quotes that DIDN'T fill are half the information -- fill rate,
queue depth and time-to-fill are the metrics that decide whether the strategy is
viable at all.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from maker.config import load as load_cfg

_cfg = load_cfg()
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,                 -- UP | DOWN
    price REAL,
    size REAL,                 -- shares posted
    queue_ahead REAL,          -- shares resting ahead of us when we joined
    mid REAL,                  -- market mid at post time
    edge_vs_mid REAL,          -- mid - price (our theoretical spread capture)
    t_remaining REAL,
    filled REAL DEFAULT 0,     -- shares eventually filled
    fill_ts REAL,              -- when the last fill landed
    cancelled INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    quote_id INTEGER,
    market_slug TEXT,
    condition_id TEXT,
    token_id TEXT,
    side TEXT,
    price REAL,
    size REAL,
    mid_at_post REAL,
    edge_vs_mid REAL,          -- captured spread per share
    queue_waited REAL,
    seconds_to_fill REAL
);

CREATE TABLE IF NOT EXISTS resolutions (
    condition_id TEXT PRIMARY KEY,
    winning_token TEXT,
    resolved_ts REAL
);

-- Why we quoted (or didn't) each cycle. Same idea as the taker's decision log:
-- the reasons we DIDN'T act are what you tune the strategy on. Consecutive
-- identical decisions collapse into one row with a count.
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    market_slug TEXT,
    condition_id TEXT,
    action TEXT,               -- QUOTE | SKIP_*
    side TEXT,
    price REAL,
    mid REAL,
    edge_vs_mid REAL,
    t_remaining REAL,
    balance REAL,
    pair_cost REAL,
    reason TEXT,
    count INTEGER DEFAULT 1
);

-- Single-row snapshot of what the bot is looking at right now, so the
-- dashboard (a separate process) can render the live market without doing its
-- own market/book polling.
CREATE TABLE IF NOT EXISTS live_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ts REAL,
    payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_q_ts ON quotes(ts);
CREATE INDEX IF NOT EXISTS idx_f_ts ON fills(ts);
CREATE INDEX IF NOT EXISTS idx_f_cond ON fills(condition_id);
CREATE INDEX IF NOT EXISTS idx_d_ts ON decisions(ts);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_cfg.db_path()))
    c.executescript(SCHEMA)
    return c


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = _conn()
        try:
            yield c
            c.commit()
        finally:
            c.close()


def log_quote(**kw) -> int:
    with db() as c:
        cur = c.execute(
            "INSERT INTO quotes (ts, market_slug, condition_id, token_id, side, "
            "price, size, queue_ahead, mid, edge_vs_mid, t_remaining) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), kw["market_slug"], kw["condition_id"], kw["token_id"],
             kw["side"], kw["price"], kw["size"], kw["queue_ahead"], kw["mid"],
             kw["edge_vs_mid"], kw["t_remaining"]),
        )
        return cur.lastrowid


def log_fill(**kw) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO fills (ts, quote_id, market_slug, condition_id, token_id, "
            "side, price, size, mid_at_post, edge_vs_mid, queue_waited, seconds_to_fill) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), kw.get("quote_id"), kw["market_slug"], kw["condition_id"],
             kw["token_id"], kw["side"], kw["price"], kw["size"],
             kw.get("mid_at_post"), kw.get("edge_vs_mid"), kw.get("queue_waited"),
             kw.get("seconds_to_fill")),
        )
        c.execute("UPDATE quotes SET filled = filled + ?, fill_ts = ? WHERE id = ?",
                  (kw["size"], time.time(), kw.get("quote_id")))


def mark_cancelled(quote_ids: list[int]) -> None:
    if not quote_ids:
        return
    with db() as c:
        c.executemany("UPDATE quotes SET cancelled=1 WHERE id=? AND filled=0",
                      [(q,) for q in quote_ids])


def record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO resolutions VALUES (?,?,?)",
                  (condition_id, winning_token, time.time()))


def unresolved() -> list[tuple[str, str]]:
    with db() as c:
        return [(r[0], r[1]) for r in c.execute(
            "SELECT DISTINCT f.condition_id, f.market_slug FROM fills f "
            "LEFT JOIN resolutions r ON r.condition_id=f.condition_id "
            "WHERE r.condition_id IS NULL"
        ).fetchall()]


def open_markets() -> int:
    return len(unresolved())


# --- decision log (run-collapsed, same approach as the taker bot) -----------
#
# The dedup key deliberately EXCLUDES `reason`. Reason strings embed live values
# ("t_remaining 4s < 15s", "rest 1 tick under ask 0.53") that change on nearly
# every cycle, so keying on them collapses almost nothing -- measured 2.0x here
# versus ~15x on the taker, 17,490 rows/day. Same mistake was made and fixed on
# the taker side; keying on (market, action, side) is what actually works. The
# latest reason/price is kept as the row's value, and the `quotes` table still
# holds the exact per-quote record, so no detail is lost.
# 30s, not the taker's 10s: the maker re-decides every 2s (vs 0.25s), so a
# 10s window caps a run at only 5 evaluations and compression stalls ~2.8x.
# 30s allows ~15/row. The live-market panel gives real-time visibility, so a
# decision log that lags up to 30s costs nothing.
_RUN_MAX_SEC = 30.0
_run: dict = {"key": None, "row": None, "count": 0, "started": 0.0}


def log_decision(**kw) -> None:
    """Collapse consecutive identical decisions into one row with a count."""
    global _run
    now = time.time()
    key = (kw.get("condition_id"), kw.get("action"), kw.get("side"))
    row = (now, kw.get("market_slug"), kw.get("condition_id"), kw.get("action"),
           kw.get("side"), kw.get("price"), kw.get("mid"), kw.get("edge_vs_mid"),
           kw.get("t_remaining"), kw.get("balance"), kw.get("pair_cost"), kw.get("reason"))
    if _run["key"] == key and (now - _run["started"]) < _RUN_MAX_SEC:
        _run["count"] += 1
        _run["row"] = row          # keep the freshest values
        return
    flush_decision(force=True)
    _run = {"key": key, "row": row, "count": 1, "started": now}


def flush_decision(force: bool = False) -> None:
    """Write the open run. Without `force`, only once it exceeds _RUN_MAX_SEC,
    so a persistent state still reaches the DB without spawning a row per tick."""
    global _run
    if _run["key"] is None or _run["row"] is None:
        return
    if not force and (time.time() - _run["started"]) < _RUN_MAX_SEC:
        return
    with db() as c:
        c.execute(
            "INSERT INTO decisions (ts, market_slug, condition_id, action, side, "
            "price, mid, edge_vs_mid, t_remaining, balance, pair_cost, reason, count) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            _run["row"] + (_run["count"],),
        )
    _run = {"key": None, "row": None, "count": 0, "started": 0.0}


def set_live_state(payload: dict) -> None:
    import json
    with db() as c:
        c.execute("INSERT OR REPLACE INTO live_state (id, ts, payload) VALUES (1,?,?)",
                  (time.time(), json.dumps(payload)))


def get_live_state() -> dict:
    import json
    with db() as c:
        r = c.execute("SELECT ts, payload FROM live_state WHERE id=1").fetchone()
    if not r:
        return {}
    try:
        d = json.loads(r[1])
        d["_age"] = time.time() - (r[0] or 0)
        return d
    except Exception:
        return {}
