"""The accounts we shadow, and how each is mirrored.

Design decisions (chosen 2026-07-20):
  - fill price = THEIR exact fill price (pure copy -> measures the account's edge)
  - sizing     = fixed $5,000 paper bankroll per account, staked PROPORTIONALLY
                 to their trade (their usdc x copy_scale), with a real cash
                 constraint -- when the paper account is out of cash we skip,
                 exactly like a $5k follower would have to.
  - scope      = every TRADE they make, all markets, BUY and SELL.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Account:
    key: str          # short slug used in the DB + dashboard
    handle: str       # display name
    address: str      # proxy wallet (lowercased)
    bankroll: float   # virtual paper starting cash
    copy_scale: float # stake = their usdcSize * copy_scale

    @property
    def addr(self) -> str:
        return self.address.lower()


# copy_scale is tuned per account so a typical trade is a sane slice of the $5k:
#  - the 5-min grinders trade ~$8-150 many times/min; 0.25 keeps fills ~$2-40
#    and lets cash recycle as their fast markets resolve.
#  - anon trades $1k-10k on slower markets; 0.02 keeps a single fill from
#    swallowing the whole bankroll before it can resolve.
ACCOUNTS = [
    Account("powerwinner", "@powerwinner",
            "0xf3531b23b504cf0aed4ff21325232b2a2d496685", 5000.0, 0.25),
    Account("bonereaper", "@bonereaper",
            "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30", 5000.0, 0.25),
    # @Anon dropped 2026-07-21: 454 fills over 14h but ZERO resolved markets --
    # it trades longer-dated markets (BTC-150k-by-December), so it produces no
    # P&L signal on any useful timescale. Its rows stay in follow.db for later.
    # Account("anon", "@Anon",
    #         "0xf705fa045201391d9632b7f3cde06a5e24453ca7", 5000.0, 0.02),
]

# The account we run the full follower simulation against. powerwinner is the
# most profitable and most active of the two, so it's the cleanest test of
# whether a real follower can capture any of that edge.
SHADOW_ACCOUNT = "powerwinner"

BY_KEY = {a.key: a for a in ACCOUNTS}
BY_ADDR = {a.addr: a for a in ACCOUNTS}
