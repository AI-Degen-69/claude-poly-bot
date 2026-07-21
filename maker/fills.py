"""Queue-aware fill simulation for resting maker bids, driven by BOOK DELTAS.

WHY THIS IS THE WHOLE PROJECT
-----------------------------
A maker's edge is buying at the bid instead of crossing to the mid. Measured
from powerwinner's 56,768 fills, spread capture is ~68% of his gross; the
"buy both sides" pair clears only 0.10% and is favourable just 51% of the time,
so the arbitrage story is NOT the business. The business is: rest, don't cross.

That makes one question decisive -- do we actually get filled? A naive model
("the ask touched my price, so I filled") answers yes every time and therefore
invents 100% of the edge. This module refuses to do that.

WHY BOOK DELTAS AND NOT THE TRADE TAPE
--------------------------------------
First attempt keyed fills off the trade tape's `side` field: a taker SELL lifts
a bid. Measured on the live tape, 194 of 200 rows were "BUY". The reason is that
data-api /trades reports each PARTICIPANT's own side, not the aggressor's -- a
maker whose bid gets lifted appears as a "BUY" too (it's powerwinner's own fills
in that feed). So aggressor direction is not recoverable from it, and a
SELL-only rule would report almost no fills and wrongly kill the strategy.

Book deltas avoid the problem entirely. We poll the book; the size resting at
our price level is directly observable, and its decrease is exactly the queue
moving. Verified live: levels move materially every few seconds (60 -> 0 in 6s).

THE MODEL
---------
Posting a bid at price P puts us at the BACK of the queue at that level:
    queue_ahead = size currently resting at P

Each book poll:
  * size at P DECREASED by X  -> the queue ahead of us shrank by X. Once
    queue_ahead reaches 0, any further decrease is us being filled.
  * P is gone from the book / best bid fell below P -> the level was cleared
    outright, so our remainder filled.
  * size at P INCREASED -> people joined BEHIND us. Irrelevant to our fills;
    queue_ahead never grows.

STATED BIASES (each makes us OPTIMISTIC -- treat output as an upper bound)
  1. A decrease may be a CANCEL rather than a fill. Cancels do move us up the
     queue (correct), but we also credit the post-queue remainder as our fill,
     which over-fills us when the level is being cancelled rather than traded.
  2. We assume strict price-time priority and that we joined at the exact
     moment of the snapshot.
  3. Adverse selection is NOT softened anywhere: we get filled precisely when
     someone wants to sell to us, which is disproportionately when the market
     is about to move against us. That cost shows up in the resolution outcome,
     which is the honest place for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RestingOrder:
    """One of our bids sitting on the book."""
    token_id: str
    side: str                 # 'UP' | 'DOWN' -- which outcome we are buying
    price: float
    size: float               # shares we want
    filled: float = 0.0
    queue_ahead: float = 0.0  # shares resting ahead of us when we joined
    posted_ts: float = 0.0
    cancelled: bool = False

    @property
    def remaining(self) -> float:
        return max(0.0, self.size - self.filled)

    @property
    def is_open(self) -> bool:
        return (not self.cancelled) and self.remaining > 1e-9


@dataclass
class Fill:
    token_id: str
    side: str
    price: float
    size: float
    ts: float
    queue_waited: float = 0.0   # shares that had to clear ahead of us


@dataclass
class QueueFillEngine:
    """Applies observed book changes to our resting orders, queue-first."""

    orders: list[RestingOrder] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    # token_id -> {price: size} as of the previous poll
    _last_book: dict[str, dict[float, float]] = field(default_factory=dict)

    # -- order management --------------------------------------------------
    def post(self, token_id: str, side: str, price: float, size: float,
             book_bids: dict[float, float], ts: float) -> RestingOrder:
        """Join the back of the queue at `price`."""
        o = RestingOrder(
            token_id=token_id, side=side, price=round(price, 4), size=size,
            queue_ahead=float(book_bids.get(round(price, 4), 0.0)), posted_ts=ts,
        )
        self.orders.append(o)
        return o

    def cancel(self, token_id: Optional[str] = None) -> int:
        n = 0
        for o in self.orders:
            if o.is_open and (token_id is None or o.token_id == token_id):
                o.cancelled = True
                n += 1
        return n

    def open_orders(self, token_id: Optional[str] = None) -> list[RestingOrder]:
        return [o for o in self.orders
                if o.is_open and (token_id is None or o.token_id == token_id)]

    # -- the core ----------------------------------------------------------
    def on_book(self, token_id: str, bids: dict[float, float], ts: float) -> list[Fill]:
        """Feed a fresh bid-side snapshot; returns any fills it implies."""
        bids = {round(p, 4): float(s) for p, s in bids.items()}
        prev = self._last_book.get(token_id)
        self._last_book[token_id] = bids
        if prev is None:
            return []          # need two snapshots to see a delta

        best_bid = max(bids) if bids else 0.0
        made: list[Fill] = []

        for o in self.open_orders(token_id):
            before = prev.get(o.price, 0.0)
            now = bids.get(o.price, 0.0)

            # Level cleared outright and the market moved below us -> our
            # remainder must have traded.
            if now <= 1e-9 and best_bid < o.price - 1e-9:
                made.append(self._fill(o, o.remaining, ts))
                continue

            consumed = before - now
            if consumed <= 1e-9:
                continue        # level grew or held: people joined behind us

            # Queue ahead absorbs first.
            if o.queue_ahead > 0:
                eaten = min(o.queue_ahead, consumed)
                o.queue_ahead -= eaten
                consumed -= eaten
            if consumed > 1e-9:
                made.append(self._fill(o, min(o.remaining, consumed), ts))

        return [f for f in made if f is not None and f.size > 1e-9]

    def _fill(self, o: RestingOrder, qty: float, ts: float) -> Optional[Fill]:
        qty = min(qty, o.remaining)
        if qty <= 1e-9:
            return None
        o.filled += qty
        f = Fill(token_id=o.token_id, side=o.side, price=o.price, size=qty,
                 ts=ts, queue_waited=o.queue_ahead)
        self.fills.append(f)
        return f

    # -- reporting ---------------------------------------------------------
    def filled_shares(self, side: Optional[str] = None) -> float:
        return sum(f.size for f in self.fills if side is None or f.side == side)

    def cost(self, side: Optional[str] = None) -> float:
        return sum(f.size * f.price for f in self.fills
                   if side is None or f.side == side)

    def avg_price(self, side: Optional[str] = None) -> float:
        sh = self.filled_shares(side)
        return (self.cost(side) / sh) if sh else 0.0

    def posted_shares(self) -> float:
        return sum(o.size for o in self.orders)

    def fill_rate(self) -> Optional[float]:
        """Filled / posted. The number optimistic models quietly set to 1.0."""
        p = self.posted_shares()
        return (self.filled_shares() / p) if p else None
