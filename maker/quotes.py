"""Where to rest bids. The decision layer of the maker sim.

Mirrors powerwinner's measured behaviour: quote BOTH outcomes, stay ~92%
balanced, never let the pair cost reach $1.00 (it pays exactly $1.00, so a pair
bought at >= 1.00 is a guaranteed loss), and keep quotes inside the rebate
window (>= 50 shares, within 4.5c of mid).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from maker.config import MakerConfig


@dataclass
class QuoteIntent:
    side: str            # 'UP' | 'DOWN'
    token_id: str
    price: float
    size: int
    mid: float
    edge_vs_mid: float   # mid - price, our theoretical capture per share
    reason: str = ""


@dataclass
class Inventory:
    up_shares: float = 0.0
    down_shares: float = 0.0
    up_cost: float = 0.0
    down_cost: float = 0.0
    fills: int = 0

    @property
    def cost(self) -> float:
        return self.up_cost + self.down_cost

    @property
    def balance(self) -> float:
        """min/max of the two legs. 1.0 = perfectly hedged."""
        hi = max(self.up_shares, self.down_shares)
        return (min(self.up_shares, self.down_shares) / hi) if hi > 0 else 1.0

    def avg(self, side: str) -> float:
        sh = self.up_shares if side == "UP" else self.down_shares
        c = self.up_cost if side == "UP" else self.down_cost
        return (c / sh) if sh > 0 else 0.0

    def pair_cost(self) -> float:
        """avg(UP) + avg(DOWN). Under 1.00 means the hedged part is locked in."""
        if self.up_shares <= 0 or self.down_shares <= 0:
            return 0.0
        return self.avg("UP") + self.avg("DOWN")


def mid_price(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


def decide_quotes(
    cfg: MakerConfig,
    up_book: dict,
    down_book: dict,
    inv: Inventory,
    t_remaining: float,
) -> tuple[list[QuoteIntent], str]:
    """Return the bids we want resting right now, plus a reason if we want none.

    `*_book` is {'best_bid','best_ask'} for that outcome's token.
    """
    if t_remaining < cfg.min_t_remaining_sec:
        return [], f"t_remaining {t_remaining:.0f}s < {cfg.min_t_remaining_sec:.0f}s"
    if inv.fills >= cfg.max_fills_per_market:
        return [], f"hit {cfg.max_fills_per_market} fills for this market"
    if inv.cost >= cfg.max_cost_per_market:
        return [], f"market cost cap ${cfg.max_cost_per_market:.0f} reached"

    out: list[QuoteIntent] = []
    for side, book, tok in (
        ("UP", up_book, up_book.get("token_id")),
        ("DOWN", down_book, down_book.get("token_id")),
    ):
        bb, ba = book.get("best_bid"), book.get("best_ask")
        mid = mid_price(bb, ba)
        if mid is None or ba is None:
            continue

        # Rest one tick inside the ask -- passive, never crossing.
        price = round(ba - cfg.ticks_below_ask * cfg.tick_size, 4)
        if price <= 0.0 or price >= 1.0:
            continue

        # Rebate window: must be within 4.5c of mid, else no rebate and the
        # whole point of being a maker is gone.
        if abs(mid - price) > cfg.max_spread_from_mid:
            continue

        # Never build a pair that costs >= $1.00 for a $1.00 payout.
        other = "DOWN" if side == "UP" else "UP"
        other_avg = inv.avg(other)
        if other_avg > 0 and (price + other_avg) >= cfg.max_pair_cost:
            continue

        # Inventory control: if we're already heavy on this side, only quote
        # the lighter one until balance recovers.
        if inv.up_shares > 0 or inv.down_shares > 0:
            mine = inv.up_shares if side == "UP" else inv.down_shares
            theirs = inv.down_shares if side == "UP" else inv.up_shares
            if mine > theirs and inv.balance < cfg.target_balance:
                continue

        out.append(QuoteIntent(
            side=side, token_id=tok, price=price, size=cfg.quote_shares,
            mid=mid, edge_vs_mid=mid - price,
            reason=f"rest {cfg.ticks_below_ask} tick under ask {ba:.2f}",
        ))

    if not out:
        return [], "no side passed the quote filters"
    return out, ""
