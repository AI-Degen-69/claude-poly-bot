"""CLOB order book reader. HTTP polling; WSS upgrade can come later."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class TopOfBook:
    best_bid: Optional[float]
    bid_size: float
    best_ask: Optional[float]
    ask_size: float

    def ask_with_size(self, min_size: float) -> Optional[float]:
        if self.best_ask is None or self.ask_size < min_size:
            return None
        return self.best_ask


def fetch_book(clob_host: str, token_id: str) -> TopOfBook:
    r = requests.get(f"{clob_host}/book", params={"token_id": token_id}, timeout=3)
    r.raise_for_status()
    data = r.json()
    bids = data.get("bids") or []
    asks = data.get("asks") or []
    # Polymarket returns levels sorted: bids descending, asks ascending.
    # Top of book is the LAST element in each list (the closest to mid).
    # Verified empirically; some endpoints return them sorted the other way —
    # be defensive: pick max bid, min ask.
    best_bid = max((float(b["price"]) for b in bids), default=None)
    best_ask = min((float(a["price"]) for a in asks), default=None)
    bid_size = sum(float(b["size"]) for b in bids if float(b["price"]) == best_bid) if best_bid else 0.0
    ask_size = sum(float(a["size"]) for a in asks if float(a["price"]) == best_ask) if best_ask else 0.0
    return TopOfBook(
        best_bid=best_bid,
        bid_size=bid_size,
        best_ask=best_ask,
        ask_size=ask_size,
    )


if __name__ == "__main__":
    from bot.config import load
    from bot.markets import fetch_live_market

    cfg = load()
    m = fetch_live_market(cfg.gamma_host, cfg.series_slug)
    if not m:
        raise SystemExit("no live market right now")
    up = fetch_book(cfg.clob_host, m.up_token)
    dn = fetch_book(cfg.clob_host, m.down_token)
    print(f"market: {m.market_slug}  t_remaining={m.t_remaining():.1f}s")
    print(f"  UP   bid={up.best_bid}({up.bid_size:.0f})  ask={up.best_ask}({up.ask_size:.0f})")
    print(f"  DOWN bid={dn.best_bid}({dn.bid_size:.0f})  ask={dn.best_ask}({dn.ask_size:.0f})")
