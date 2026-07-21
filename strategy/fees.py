"""Polymarket crypto taker-fee model (`crypto_fees_v2`).

Source: research/btc_5min_market_spec.md:105-112, confirmed against
docs.polymarket.com/trading/fees. The 5-min BTC series carries
`feeSchedule = {exponent: 1, rate: 0.07, takerOnly: true, rebateRate: 0.2}`.

    taker_fee = shares * rate * p * (1 - p)      # USDC
    maker_fee = 0                                # takerOnly

The bot is 100% taker (FOK BUY), so it always pays this. Fees vanish at the
price extremes and peak at 50/50 -- which is precisely why late-window
convergence entries are the cheapest place to trade this market.

This module exists because ignoring fees overstates simulated PnL by roughly
6-7% of gross edge on every fill in our entry band, which is the difference
between a strategy that looks profitable and one that is.
"""
from __future__ import annotations

# feeSchedule.rate for crypto_fees_v2. NOT makerBaseFee/takerBaseFee (=1000),
# which are legacy bps fields that are not what gets charged here.
FEE_RATE = 0.07


def taker_fee(shares: float, price: float) -> float:
    """USDC fee charged on a taker fill of `shares` at `price`."""
    return shares * FEE_RATE * price * (1.0 - price)


def fee_per_share(price: float) -> float:
    return FEE_RATE * price * (1.0 - price)


def breakeven_win_rate(price: float) -> float:
    """Win rate needed to break even buying at `price` and holding to resolution.

    Per share: a win returns (1 - p) minus fee, a loss costs p plus fee. So
        EV = w*(1-p-f) - (1-w)*(p+f) = w - p - f
    and EV = 0 exactly when w = p + f. Fees shift the bar up by f.
    """
    return price + fee_per_share(price)


def net_pnl(shares: float, price: float, won: bool) -> float:
    """Realized PnL for a resolved position, fees deducted.

    Winners redeem at $1.00/share, losers expire worthless. The fee was paid
    at entry either way.
    """
    fee = taker_fee(shares, price)
    if won:
        return shares * (1.0 - price) - fee
    return -(shares * price) - fee


def edge_bps(price: float, win_rate: float) -> float:
    """Expected edge in bps of notional at an assumed win rate."""
    ev_per_share = win_rate - price - fee_per_share(price)
    return (ev_per_share / price) * 10_000 if price else 0.0
