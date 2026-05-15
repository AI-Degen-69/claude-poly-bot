"""FastAPI dashboard backend.

Polls the local SQLite (trades.db), the CLOB book of the live market, the
deposit wallet's positions, and on-chain pUSD balance. Serves /api/state for
the UI to poll, and /api/events for incremental new-row pulls.

Run:  .venv/bin/uvicorn server.dashboard:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from bot.book import fetch_book
from bot.config import load as load_cfg
from bot.markets import LiveMarket, fetch_live_market

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "trades.db"

cfg = load_cfg()

# In-memory rolling state, refreshed by background tasks.
_state: dict[str, Any] = {
    "ts": 0.0,
    "market": None,           # LiveMarket as dict
    "book_up": None,
    "book_down": None,
    "balance_pusd": None,     # on-chain pUSD in deposit wallet
    "positions": [],          # data-api positions for deposit wallet
    "value_usd": None,        # data-api value endpoint
    "bot_running": False,
    "errors": {},             # last error per poller for debugging
}


# ---------------------------------------------------------------------------
# SQLite reads


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


def recent_decisions(limit: int = 50, since_id: int = 0) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with db() as c:
        rows = c.execute(
            "SELECT id, ts, market_slug, side, t_remaining, ask_price, ask_size, "
            "action, reason, dry_run FROM decisions WHERE id > ? "
            "ORDER BY id DESC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [_row(r) for r in rows]


def recent_orders(limit: int = 50, since_id: int = 0) -> list[dict]:
    if not DB_PATH.exists():
        return []
    with db() as c:
        rows = c.execute(
            "SELECT id, ts, market_slug, condition_id, token_id, side, size, "
            "price, order_id, status, filled_size, error, dry_run FROM orders "
            "WHERE id > ? ORDER BY id DESC LIMIT ?",
            (since_id, limit),
        ).fetchall()
        return [_row(r) for r in rows]


def realized_pnl_today() -> dict:
    """Compute realized PnL from filled orders. Uses the bot's resolutions table
    (populated by bot.resolver) and back-fills any new resolutions on demand."""
    if not DB_PATH.exists():
        return {"realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0}
    cutoff = time.time() - 86400
    with db() as c:
        orders = c.execute(
            "SELECT o.condition_id, o.market_slug, o.token_id, o.size, o.price, "
            "r.winning_token "
            "FROM orders o LEFT JOIN resolutions r ON r.condition_id = o.condition_id "
            "WHERE o.dry_run=0 AND o.status IN ('filled','matched') AND o.ts > ?",
            (cutoff,),
        ).fetchall()
    if not orders:
        return {"realized_usd": 0.0, "wins": 0, "losses": 0, "pending": 0}

    realized = 0.0
    wins = 0
    losses = 0
    pending = 0
    for o in orders:
        winner = o["winning_token"]
        if winner is None:
            winner = _resolved_winning_token(o["market_slug"])
            if winner is not None:
                _record_resolution(o["condition_id"], winner)
        if winner is None:
            pending += 1
            continue
        if winner == o["token_id"]:
            realized += float(o["size"]) * (1.0 - float(o["price"]))
            wins += 1
        else:
            realized -= float(o["size"]) * float(o["price"])
            losses += 1
    return {"realized_usd": realized, "wins": wins, "losses": losses, "pending": pending}


_resolved_cache: dict[str, Optional[str]] = {}


def _resolved_winning_token(market_slug: str) -> Optional[str]:
    """Return the winning token_id for a resolved market, or None if unresolved.

    Gamma's `condition_ids` filter hides closed markets — query by slug instead.
    Cached in-process; markets resolve immutably so cache hits are safe.
    """
    if not market_slug:
        return None
    if market_slug in _resolved_cache:
        return _resolved_cache[market_slug]
    try:
        r = requests.get(
            f"{cfg.gamma_host}/markets",
            params={"slug": market_slug, "closed": "true"},
            timeout=3,
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
            import json as _json
            prices = _json.loads(prices)
        if not prices or len(prices) != 2:
            return None
        token_ids = m.get("clobTokenIds")
        if isinstance(token_ids, str):
            import json as _json
            token_ids = _json.loads(token_ids)
        if not token_ids or len(token_ids) != 2:
            return None
        winner_idx = 0 if float(prices[0]) > float(prices[1]) else 1
        winner = str(token_ids[winner_idx])
        _resolved_cache[market_slug] = winner
        return winner
    except Exception:
        return None


def _record_resolution(condition_id: str, winning_token: str) -> None:
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO resolutions (condition_id, winning_token, resolved_ts) "
            "VALUES (?,?,?)",
            (condition_id, winning_token, time.time()),
        )


# ---------------------------------------------------------------------------
# Background pollers


async def poll_market_loop():
    while True:
        try:
            m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
            _state["market"] = (
                {
                    "condition_id": m.condition_id,
                    "market_slug": m.market_slug,
                    "up_token": m.up_token,
                    "down_token": m.down_token,
                    "start_ts": m.start_ts,
                    "end_ts": m.end_ts,
                    "tick_size": m.tick_size,
                    "neg_risk": m.neg_risk,
                }
                if m
                else None
            )
            _state["errors"].pop("market", None)
        except Exception as e:
            _state["errors"]["market"] = str(e)
        await asyncio.sleep(2.0)


async def poll_book_loop():
    while True:
        m = _state.get("market")
        if not m:
            await asyncio.sleep(0.5)
            continue
        try:
            bu = fetch_book(cfg.clob_host, m["up_token"])
            bd = fetch_book(cfg.clob_host, m["down_token"])
            _state["book_up"] = {
                "best_bid": bu.best_bid,
                "bid_size": bu.bid_size,
                "best_ask": bu.best_ask,
                "ask_size": bu.ask_size,
            }
            _state["book_down"] = {
                "best_bid": bd.best_bid,
                "bid_size": bd.bid_size,
                "best_ask": bd.best_ask,
                "ask_size": bd.ask_size,
            }
            _state["errors"].pop("book", None)
        except Exception as e:
            _state["errors"]["book"] = str(e)
        await asyncio.sleep(0.25)


async def poll_positions_loop():
    while True:
        try:
            r = requests.get(
                "https://data-api.polymarket.com/positions",
                params={"user": cfg.funder_address},
                timeout=3,
            )
            r.raise_for_status()
            _state["positions"] = r.json()
            _state["errors"].pop("positions", None)
        except Exception as e:
            _state["errors"]["positions"] = str(e)

        try:
            r = requests.get(
                "https://data-api.polymarket.com/value",
                params={"user": cfg.funder_address},
                timeout=3,
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                _state["value_usd"] = float(data[0].get("value") or 0.0)
            _state["errors"].pop("value", None)
        except Exception as e:
            _state["errors"]["value"] = str(e)

        await asyncio.sleep(2.0)


async def poll_balance_loop():
    """Read pUSD balance of deposit wallet on-chain."""
    PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
    SELECTOR = "0x70a08231"
    while True:
        try:
            data = SELECTOR + cfg.funder_address.lower().replace("0x", "").rjust(64, "0")
            r = requests.post(
                cfg.polygon_rpc,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_call",
                    "params": [{"to": PUSD, "data": data}, "latest"],
                },
                timeout=5,
            )
            r.raise_for_status()
            raw = r.json().get("result")
            if raw:
                _state["balance_pusd"] = int(raw, 16) / 1e6
            _state["errors"].pop("balance", None)
        except Exception as e:
            _state["errors"]["balance"] = str(e)
        await asyncio.sleep(5.0)


async def poll_bot_running_loop():
    pid_path = ROOT / "bot.pid"
    mode_path = ROOT / "bot.mode"
    while True:
        running = False
        if pid_path.exists():
            try:
                pid = int(pid_path.read_text().strip())
                import os
                os.kill(pid, 0)  # signal 0 = check existence
                running = True
            except (ProcessLookupError, ValueError, PermissionError):
                running = False
        mode = "unknown"
        if mode_path.exists():
            try:
                mode = mode_path.read_text().strip() or "unknown"
            except Exception:
                pass
        if not running:
            mode = "stopped"
        _state["bot_running"] = running
        _state["bot_mode"] = mode
        await asyncio.sleep(2.0)


# ---------------------------------------------------------------------------
# FastAPI app

app = FastAPI(title="poly_hft dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(poll_market_loop())
    asyncio.create_task(poll_book_loop())
    asyncio.create_task(poll_positions_loop())
    asyncio.create_task(poll_balance_loop())
    asyncio.create_task(poll_bot_running_loop())


@app.get("/api/health")
def health():
    return {"ok": True, "ts": time.time()}


def _risk_state(pnl: dict) -> str:
    """Approximate the bot's risk-gate state for UI display."""
    if pnl["realized_usd"] <= -cfg.max_daily_loss_usd:
        return "LOSS_CAP"
    # consecutive-loss kill detection
    with db() as c:
        rows = c.execute(
            "SELECT o.token_id, r.winning_token FROM orders o "
            "JOIN resolutions r ON r.condition_id=o.condition_id "
            "WHERE o.status IN ('filled','matched') AND o.dry_run=0 "
            "ORDER BY r.resolved_ts DESC LIMIT 10"
        ).fetchall()
    streak = 0
    for token, winner in rows:
        if token == winner:
            break
        streak += 1
    if streak >= cfg.consecutive_loss_kill:
        return f"LOSS_STREAK({streak})"
    return "OK"


def _filter_active_positions(positions: list[dict]) -> list[dict]:
    """data-api keeps resolved positions in the list at curPrice=0; drop them."""
    out: list[dict] = []
    for p in positions:
        cp = p.get("curPrice")
        sz = p.get("size")
        if cp is None or sz is None:
            continue
        try:
            if float(cp) <= 0.0 or float(sz) <= 0.0:
                continue
        except Exception:
            continue
        out.append(p)
    return out


@app.get("/api/state")
def state():
    m = _state.get("market")
    now = time.time()
    pnl = realized_pnl_today()
    return {
        "now": now,
        "bot_running": _state["bot_running"],
        "bot_mode": _state.get("bot_mode", "stopped"),
        "risk_state": _risk_state(pnl),
        "wallet": {
            "eoa": cfg.wallet_address,
            "deposit": cfg.funder_address,
            "balance_pusd": _state.get("balance_pusd"),
            "value_usd": _state.get("value_usd"),
        },
        "market": (
            None
            if not m
            else {
                **m,
                "t_remaining": m["end_ts"] - now,
            }
        ),
        "book_up": _state.get("book_up"),
        "book_down": _state.get("book_down"),
        "positions": _filter_active_positions(_state.get("positions") or []),
        "pnl": pnl,
        "config": {
            "max_entry_price": cfg.max_entry_price,
            "loser_floor": 0.85,
            "seconds_before_close": cfg.seconds_before_close,
            "min_t_remaining_sec": cfg.min_t_remaining_sec,
            "order_size_shares": cfg.order_size_shares,
            "max_open_positions": cfg.max_open_positions,
            "max_daily_loss_usd": cfg.max_daily_loss_usd,
        },
        "decisions": recent_decisions(limit=80),
        "orders": recent_orders(limit=30),
        "errors": _state.get("errors") or {},
    }


@app.get("/api/events")
def events(since_decision: int = Query(0), since_order: int = Query(0)):
    return {
        "decisions": recent_decisions(limit=200, since_id=since_decision),
        "orders": recent_orders(limit=50, since_id=since_order),
    }
