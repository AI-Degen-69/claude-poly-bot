"""Late-window convergence buy. Replicates bonereaper's pattern at micro-scale.

Rules:
  - only fire when t_remaining < seconds_before_close
  - find a side whose ask is in (loser_floor, max_entry_price] with enough size
  - that side is the perceived winner: market believes it wins, but supply
    still exists at <max_entry_price (residual = our edge)
  - if BOTH sides have such asks, the market is genuinely uncertain -> skip
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.book import TopOfBook
from bot.config import Config
from bot.markets import LiveMarket


@dataclass(frozen=True)
class Decision:
    action: str       # 'BUY', 'SKIP_TIME', 'SKIP_PRICE', 'SKIP_SIZE', 'SKIP_AMBIGUOUS'
    side: Optional[str] = None       # 'UP' or 'DOWN'
    token_id: Optional[str] = None
    price: Optional[float] = None
    size: Optional[float] = None
    reason: str = ""


# Side asks below this floor lack convincing market consensus. We only fire
# when the winner's ask is in (LOSER_FLOOR, max_entry_price] — at >= 0.85
# implied probability the market believes the side strongly enough that
# breakeven win rate is achievable.
LOSER_FLOOR = 0.85


def decide(
    cfg: Config,
    market: LiveMarket,
    book_up: TopOfBook,
    book_down: TopOfBook,
    t_remaining: float,
) -> Decision:
    if t_remaining > cfg.seconds_before_close:
        return Decision(action="SKIP_TIME", reason=f"t_remaining={t_remaining:.1f}s > {cfg.seconds_before_close}s")
    if t_remaining < cfg.min_t_remaining_sec:
        return Decision(action="SKIP_TIME", reason=f"t_remaining={t_remaining:.1f}s < {cfg.min_t_remaining_sec}s buffer")
    if t_remaining <= 0:
        return Decision(action="SKIP_TIME", reason="window closed")

    candidates: list[tuple[str, str, float, float]] = []  # (side, token, ask, size)
    for side, token, book in (
        ("UP", market.up_token, book_up),
        ("DOWN", market.down_token, book_down),
    ):
        ask = book.best_ask
        size = book.ask_size
        if ask is None:
            continue
        if not (LOSER_FLOOR < ask <= cfg.max_entry_price):
            continue
        if size < cfg.order_size_shares:
            continue
        candidates.append((side, token, ask, size))

    if not candidates:
        # Diagnose why neither side qualified, pick worst reason for logging.
        for side, _, book in (("UP", None, book_up), ("DOWN", None, book_down)):
            if book.best_ask is None:
                continue
            if book.best_ask > cfg.max_entry_price:
                return Decision(action="SKIP_PRICE", side=side, price=book.best_ask,
                                reason=f"{side} ask={book.best_ask} > cap {cfg.max_entry_price}")
            if book.best_ask <= LOSER_FLOOR:
                continue  # that side is the loser, expected
            if book.ask_size < cfg.order_size_shares:
                return Decision(action="SKIP_SIZE", side=side, price=book.best_ask,
                                size=book.ask_size,
                                reason=f"{side} ask_size={book.ask_size} < {cfg.order_size_shares}")
        return Decision(action="SKIP_PRICE", reason="no qualifying side")

    if len(candidates) == 2:
        # Both sides priced as plausible winners — market is uncertain. Stay out.
        return Decision(action="SKIP_AMBIGUOUS",
                        reason=f"both sides in buy zone: UP={book_up.best_ask}, DOWN={book_down.best_ask}")

    side, token, ask, size = candidates[0]
    return Decision(
        action="BUY",
        side=side,
        token_id=token,
        price=ask,
        size=cfg.order_size_shares,
        reason=f"{side} ask={ask} size={size} t_rem={t_remaining:.1f}s",
    )
