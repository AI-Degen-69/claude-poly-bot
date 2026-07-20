"""Binance BTC/USDT spot feed — the directional gate for late-window entries.

WHY THIS EXISTS
---------------
These markets resolve on `close >= open` of the **Chainlink BTC/USD stream**
(research/btc_5min_market_spec.md:52-68), snapshotted at the window's open ts
and again 300s later. The outcome is therefore already determined by BTC's real
movement; the order book is just a crowd estimating it. If we track spot
ourselves we can check the book's favoured side against what the price actually
did, and refuse the trades where they disagree.

Backtested 2026-07-20 over 584 resolved windows (2026-07-18..20):

    decision      threshold   coverage   hit rate   95% CI
    t_rem 60s     none         100%       81.3%     [78.0, 84.3]
    t_rem 60s     5 bps         30%       96.0%     [92.0, 98.1]
    t_rem 120s    5 bps         25%       95.1%     [90.2, 97.6]
    t_rem 180s    5 bps         20%       88.2%     [81.2, 92.9]   <- degrades

81% -> 96% is the entire value of this module. Note the signal decays with time
remaining, which is why cfg.seconds_before_close stays at 120.

IMPORTANT CAVEAT
----------------
Binance is a PROXY. Polymarket resolves on Chainlink and the market description
explicitly says "not according to other sources or spot markets". We compare
Binance-at-open to Binance-now, so the venue basis largely cancels and only the
*direction* of the move has to agree. The bps threshold exists to stay away from
the flip point where basis could invert the sign.

FAIL-CLOSED
-----------
If the feed is stale or the window's open price is unknown, offset_bps() returns
None and the strategy refuses to trade. A silent fallback to "no gate" would put
us back at the 81% hit rate while believing we were at 96%.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

import requests

log = logging.getLogger("bot.spot")

BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
BINANCE_REST = "https://api.binance.com/api/v3/klines"

# If we haven't seen a tick in this long, treat the feed as dead.
MAX_STALENESS_SEC = 15.0


class SpotFeed:
    """Background Binance trade-stream reader with per-window open prices."""

    def __init__(self) -> None:
        self._price: Optional[float] = None
        self._price_ts: float = 0.0
        self._opens: dict[int, float] = {}      # window open_ts -> BTC price
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="spot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Imported lazily so the bot still starts if websocket-client is absent.
        from websocket import WebSocketApp

        def on_message(_ws, raw: str) -> None:
            try:
                d = json.loads(raw)
                px = float(d["p"])
            except Exception:
                return
            with self._lock:
                self._price = px
                self._price_ts = time.time()

        def on_error(_ws, err) -> None:
            log.warning("spot ws error: %s", err)

        while not self._stop.is_set():
            try:
                ws = WebSocketApp(BINANCE_WS, on_message=on_message, on_error=on_error)
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.warning("spot ws crashed: %s", e)
            if not self._stop.is_set():
                time.sleep(2.0)   # reconnect backoff

    # -- reads -------------------------------------------------------------
    def last_price(self) -> Optional[float]:
        with self._lock:
            if self._price is None:
                return None
            if time.time() - self._price_ts > MAX_STALENESS_SEC:
                return None
            return self._price

    def is_healthy(self) -> bool:
        return self.last_price() is not None

    def open_price(self, open_ts: int) -> Optional[float]:
        """BTC price at the window open. Cached; falls back to a REST kline so
        the gate still works when the bot starts mid-window."""
        with self._lock:
            if open_ts in self._opens:
                return self._opens[open_ts]
        try:
            r = requests.get(
                BINANCE_REST,
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
            px = float(data[0][1])          # kline open
        except Exception as e:
            log.debug("open price fetch failed for %s: %s", open_ts, e)
            return None
        with self._lock:
            self._opens[open_ts] = px
            if len(self._opens) > 400:      # ~1.4 days of windows
                for k in sorted(self._opens)[:200]:
                    self._opens.pop(k, None)
        return px

    def offset_bps(self, open_ts: int) -> Optional[float]:
        """Signed bps move from the window's open to now.

        Positive => BTC is above the open => UP is currently winning.
        Returns None if the feed is stale or the open price is unknown, which
        the strategy must treat as "do not trade".
        """
        now_px = self.last_price()
        if now_px is None:
            return None
        open_px = self.open_price(open_ts)
        if not open_px:
            return None
        return (now_px - open_px) / open_px * 10_000.0


# Module-level singleton; bot.main starts it, strategy reads it.
FEED = SpotFeed()


def favored_side(offset_bps: float) -> str:
    """Side the spot move currently implies. Ties resolve UP per the market
    rules (`close >= open`), so 0.0 maps to UP."""
    return "UP" if offset_bps >= 0 else "DOWN"
