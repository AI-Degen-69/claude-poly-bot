"""Maker strategy config. Numbers derived from powerwinner's measured fills.

Source: 56,768 of his BTC/ETH 5-min fills over 2026-07-14..21 (2,970 markets).
See research/powerwinner_analysis.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MakerConfig:
    series_slug: str = "btc-up-or-down-5m"

    # --- virtual account --------------------------------------------------
    bankroll_usd: float = 5000.0

    # --- quoting ----------------------------------------------------------
    # He posts on BOTH outcomes. In a binary market a bid on DOWN at 0.40 is
    # economically a sell of UP at 0.60, so bidding both sides IS two-sided
    # market making expressed as buys only. He never sells (0 SELLs in 56,768).
    quote_both_sides: bool = True

    # How far below the best ask to rest. 1 tick = passive, at the touch.
    # Deeper = better price but far lower fill probability.
    ticks_below_ask: int = 1
    tick_size: float = 0.01

    # Rebate qualification (research/btc_5min_market_spec.md):
    #   rewardsMinSize = 50 shares, rewardsMaxSpread = 4.5c from mid.
    # Quotes outside these earn no rebate, so they must not be posted casually.
    min_quote_shares: int = 50
    max_spread_from_mid: float = 0.045

    # His fill sizes: median 120sh, p10 20, p90 160. 61% were >=50sh.
    quote_shares: int = 120

    # --- inventory --------------------------------------------------------
    # He finishes markets ~92% balanced between UP and DOWN (median 0.923).
    # Below this we stop adding to the heavy side and only quote the light one.
    target_balance: float = 0.92
    # Stop quoting a side once the pair would cost more than this. The pair
    # pays exactly $1.00, so anything at/above 1.00 is a guaranteed loss.
    max_pair_cost: float = 0.995

    # --- pacing -----------------------------------------------------------
    # He averages 19.1 fills/market (median 17), one every ~5s.
    max_fills_per_market: int = 25
    requote_interval_sec: float = 2.0
    poll_interval_sec: float = 1.0

    # Only quote while the window is open enough to resolve sensibly.
    min_t_remaining_sec: float = 15.0

    # --- risk -------------------------------------------------------------
    max_cost_per_market: float = 400.0
    max_open_markets: int = 3

    # --- economics --------------------------------------------------------
    # crypto_fees_v2: takerOnly=true -> makers pay NO fee. Rebate pool is 20%
    # of taker fees, shared pro-rata among qualifying makers. We cannot see the
    # pool, so rebates are ESTIMATED and reported separately from trading PnL,
    # never blended in.
    maker_fee: float = 0.0
    rebate_rate: float = 0.20
    fee_rate: float = 0.07          # taker fee rate, for the rebate estimate

    sim_only: bool = True

    def db_path(self) -> Path:
        return Path(os.environ.get("MAKER_DB", str(ROOT / "maker.db")))


def load() -> MakerConfig:
    return MakerConfig()
