"""Centralized config loaded from .env. Strategy knobs live here too."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    private_key: str
    wallet_address: str
    funder_address: str
    signature_type: int
    chain_id: int
    clob_host: str
    gamma_host: str
    polygon_rpc: str
    api_key: str
    api_secret: str
    api_passphrase: str

    series_slug: str = "btc-up-or-down-5m"

    # --- entry band -------------------------------------------------------
    # Measured from bonereaper's own fills over 2026-07-18..20 (13,914 BTC-5m
    # trades, see research/bonereaper_live_2026-07-20.md). He trades 0.80-0.99
    # and puts 35% of his DOLLARS through the 0.98-0.99 bucket alone, which the
    # old 0.98 cap excluded entirely.
    max_entry_price: float = 0.99
    loser_floor: float = 0.80          # was 0.85 in strategy.py; his band starts at 0.80

    # --- entry timing -----------------------------------------------------
    # His volume-weighted median entry is 196s into the 300s window, i.e.
    # t_remaining ~104s. The old 35s window missed most of his flow.
    seconds_before_close: int = 120
    min_t_remaining_sec: float = 8.0   # avoid races to resolution

    # --- sizing -----------------------------------------------------------
    # He scales size UP as price converges. Ladder is USDC notional per tier,
    # mirroring his measured medians; shares = notional / price (min 5).
    # size_scale lets you run at a fraction of his scale.
    # Polymarket's 5-share minimum is a hard floor, so scaling down too far
    # CLAMPS the lower tiers and destroys the size ladder entirely. At 0.035
    # the tiers came out 5/5/5/7 -- ratio 1:1:1:1.4 instead of 1:2:4:13.3,
    # i.e. flat sizing, which is not the strategy.
    # 0.283 is the smallest scale where the cheapest tier still clears 5 shares,
    # giving 5/9/17/57 (ratio 1:1.8:3.4:11.4) at ~$409/market.
    size_scale: float = 0.283
    size_ladder_usdc: tuple = (
        (0.80, 0.90, 15.0),
        (0.90, 0.95, 30.0),
        (0.95, 0.98, 60.0),
        (0.98, 1.01, 200.0),
    )
    min_order_shares: int = 5          # Polymarket minimum

    # --- concurrency ------------------------------------------------------
    # He averages 23.8 fills per market (median 20) and touches ~292 markets/day.
    # A single entry per market is NOT his strategy.
    max_entries_per_market: int = 25
    min_seconds_between_entries: float = 2.0
    max_open_positions: int = 50       # he holds ~33-40 open at any moment

    max_daily_loss_usd: float = 10_000.0
    consecutive_loss_kill: int = 999   # disabled in sim: we want the full sample
    poll_interval_sec: float = 0.25

    # --- simulation -------------------------------------------------------
    # sim mode never builds a CLOB client and never signs anything.
    sim_only: bool = True
    # Virtual paper bankroll. Cash is debited on every simulated fill and
    # credited back at resolution, so the account can actually run out.
    # $5,000 is what the ladder-preserving scale needs: ~$409/market is ~8% of
    # bankroll at risk per window, ~12 markets of full-loss runway.
    sim_bankroll_usd: float = 5000.0
    # Assume we only get filled for what's actually resting on the ask.
    respect_book_depth: bool = True

    # --- Binance spot gate (wired 2026-07-20) -----------------------------
    # Only buy the side that BTC's actual move already favours. Backtested on
    # 584 resolved windows: ungated the book's favoured side wins 81.3% at
    # t_rem 60s; gated at >=5bps it wins 96.0% [92.0, 98.1].
    # 5bps keeps ~25-30% coverage (~70-88 markets/day). Raising to 10bps
    # measured 100% on n=57 ([93.7, 100]) but drops coverage to ~10%.
    use_spot_gate: bool = True
    min_spot_offset_bps: float = 5.0

    def size_for_price(self, price: float) -> int:
        """Shares to buy at `price`, per the measured size ladder."""
        notional = 0.0
        for lo, hi, usd in self.size_ladder_usdc:
            if lo <= price < hi:
                notional = usd
                break
        if notional <= 0:
            return 0
        shares = (notional * self.size_scale) / price
        return max(self.min_order_shares, int(shares))


def load() -> Config:
    return Config(
        private_key=os.environ["PRIVATE_KEY"],
        wallet_address=os.environ["WALLET_ADDRESS"],
        funder_address=os.environ["FUNDER_ADDRESS"],
        signature_type=int(os.environ.get("SIGNATURE_TYPE", "0")),
        chain_id=int(os.environ.get("CHAIN_ID", "137")),
        clob_host=os.environ.get("CLOB_HOST", "https://clob.polymarket.com"),
        gamma_host=os.environ.get("GAMMA_HOST", "https://gamma-api.polymarket.com"),
        polygon_rpc=os.environ.get(
            "POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com"
        ),
        api_key=os.environ["CLOB_API_KEY"],
        api_secret=os.environ["CLOB_API_SECRET"],
        api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
    )
