"""Per-account P&L from the mirrored fill ledger.

Cashflow model (handles BUY, SELL, hold-to-resolution together):
  - each fill contributes signed cashflow: BUY negative, SELL positive.
  - at resolution, NET shares held on the winning token redeem at $1.00 each.
    Net shares per (condition, token) = sum(BUY) - sum(SELL).

The important split, learned the hard way on the main bot: an unresolved BUY is
NOT a loss. Its cash went out but the market hasn't paid yet. So:

  realized_pnl = cashflow of RESOLVED markets + their redemptions   (locked in)
  open_value   = net shares still held in UNRESOLVED markets, valued at the
                 average price we entered (neutral -- worth what we paid)
  cash         = bankroll + all cashflows + resolved redemptions
  equity       = cash + open_value

For Anon (longer-dated markets, nothing resolved yet) realized_pnl is ~0 and
equity ~ bankroll, which is the truth -- not a $3,700 phantom loss.
"""
from __future__ import annotations

from collections import defaultdict

from follow import store
from follow.accounts import ACCOUNTS, BY_KEY


def account_pnl(account_key: str) -> dict:
    acct = BY_KEY[account_key]
    with store.db() as c:
        fills = c.execute(
            "SELECT condition_id, token_id, side, our_shares, our_cost, their_price "
            "FROM follow_fills WHERE account=? ORDER BY ts", (account_key,)
        ).fetchall()
        res = dict(c.execute(
            "SELECT r.condition_id, r.winning_token FROM follow_resolutions r "
            "JOIN follow_fills f ON f.condition_id=r.condition_id "
            "WHERE f.account=? GROUP BY r.condition_id", (account_key,)
        ).fetchall())

    cashflow_all = 0.0
    # per (cond, token): net shares, and buy cost/qty for average entry price
    net = defaultdict(float)
    buy_cost = defaultdict(float)
    buy_qty = defaultdict(float)
    # per market cashflow, to split realized vs open
    mkt_cashflow = defaultdict(float)
    for cond, tok, side, shares, cost, price in fills:
        cashflow_all += cost
        mkt_cashflow[cond] += cost
        net[(cond, tok)] += shares if side == "BUY" else -shares
        if side == "BUY":
            buy_cost[(cond, tok)] += shares * price
            buy_qty[(cond, tok)] += shares

    redeemed = 0.0
    open_value = 0.0
    for (cond, tok), shares in net.items():
        if shares <= 1e-9:
            continue
        if cond in res:
            if res[cond] == tok:
                redeemed += shares * 1.0
        else:
            avg = (buy_cost[(cond, tok)] / buy_qty[(cond, tok)]) if buy_qty[(cond, tok)] else 0.0
            open_value += shares * avg

    # realized = cashflow of resolved markets + their redemptions
    realized = redeemed + sum(cf for cond, cf in mkt_cashflow.items() if cond in res)

    cash = acct.bankroll + cashflow_all + redeemed
    equity = cash + open_value

    # market-level win/loss (resolved only)
    wins = losses = 0
    per_mkt_net = defaultdict(lambda: defaultdict(float))
    for cond, tok, side, shares, cost, price in fills:
        per_mkt_net[cond][tok] += shares if side == "BUY" else -shares
    for cond in res:
        if cond not in per_mkt_net:
            continue
        payout = sum(s for t, s in per_mkt_net[cond].items() if t == res[cond] and s > 0)
        if payout + mkt_cashflow[cond] > 0:
            wins += 1
        else:
            losses += 1

    open_markets = len({cond for (cond, tok), s in net.items()
                        if s > 1e-9 and cond not in res})

    return {
        "account": account_key,
        "handle": acct.handle,
        "bankroll": acct.bankroll,
        "cash": cash,
        "open_value": open_value,
        "equity": equity,
        "realized_pnl": realized,
        "total_pnl": equity - acct.bankroll,   # realized + open (marked at cost)
        "return_pct": (equity - acct.bankroll) / acct.bankroll * 100.0,
        "fills": len(fills),
        "markets_resolved": wins + losses,
        "markets_open": open_markets,
        "markets_won": wins,
        "markets_lost": losses,
        "win_rate": (wins / (wins + losses)) if (wins + losses) else None,
    }


def all_accounts_pnl() -> list[dict]:
    return [account_pnl(a.key) for a in ACCOUNTS]


def shadow_pnl(account_key: str) -> dict:
    """P&L of the FOLLOWER simulation (real book prices), same cashflow model.

    Directly comparable to account_pnl() for the same account: identical
    resolution data, identical accounting. The only difference is the price we
    paid -- theirs vs what was actually resting on the book when we saw it.
    """
    acct = BY_KEY[account_key]
    with store.db() as c:
        rows = c.execute(
            "SELECT condition_id, token_id, side, our_shares, cashflow, "
            "       our_price, slippage, status, lag_sec, their_price "
            "FROM follow_shadow WHERE account=?", (account_key,)
        ).fetchall()
        res = dict(c.execute(
            "SELECT r.condition_id, r.winning_token FROM follow_resolutions r "
            "JOIN follow_shadow s ON s.condition_id=r.condition_id "
            "WHERE s.account=? GROUP BY r.condition_id", (account_key,)
        ).fetchall())

    status = defaultdict(int)
    slips, lags = [], []
    cashflow_all = 0.0
    net = defaultdict(float)
    buy_cost = defaultdict(float)
    buy_qty = defaultdict(float)
    mkt_cashflow = defaultdict(float)

    for cond, tok, side, shares, cash, our_px, slip, st, lag, their_px in rows:
        status[st] += 1
        if st == "filled":
            # Lag/slippage are only meaningful for fills we actually priced.
            # Including `too_old` backlog rows here put median lag at 9,834s,
            # which describes our processing queue, not follow latency.
            if lag is not None:
                lags.append(lag)
            if slip is not None:
                slips.append(slip)
            cashflow_all += cash or 0.0
            mkt_cashflow[cond] += cash or 0.0
            net[(cond, tok)] += shares if side == "BUY" else -shares
            if side == "BUY":
                buy_cost[(cond, tok)] += shares * our_px
                buy_qty[(cond, tok)] += shares

    redeemed = 0.0
    open_value = 0.0
    for (cond, tok), shares in net.items():
        if shares <= 1e-9:
            continue
        if cond in res:
            if res[cond] == tok:
                redeemed += shares
        else:
            avg = (buy_cost[(cond, tok)] / buy_qty[(cond, tok)]) if buy_qty[(cond, tok)] else 0.0
            open_value += shares * avg

    realized = redeemed + sum(cf for cond, cf in mkt_cashflow.items() if cond in res)
    cash_bal = acct.bankroll + cashflow_all + redeemed
    equity = cash_bal + open_value

    wins = losses = 0
    per_mkt = defaultdict(lambda: defaultdict(float))
    for cond, tok, side, shares, cash, our_px, slip, st, lag, their_px in rows:
        if st == "filled":
            per_mkt[cond][tok] += shares if side == "BUY" else -shares
    for cond in res:
        if cond not in per_mkt:
            continue
        payout = sum(s for t, s in per_mkt[cond].items() if t == res[cond] and s > 0)
        if payout + mkt_cashflow[cond] > 0:
            wins += 1
        else:
            losses += 1

    # A real follow OPPORTUNITY is one we saw in time to act on. `too_old` rows
    # are fills that aged out of the queue (mostly the historical backlog from
    # before shadowing existed) -- counting them as missed opportunities would
    # understate the fill rate to ~2%, which is an artifact, not a finding.
    filled = status.get("filled", 0)
    attempted = (filled + status.get("no_book", 0)
                 + status.get("no_depth", 0) + status.get("missed_closed", 0))
    return {
        "account": account_key,
        "bankroll": acct.bankroll,
        "equity": equity,
        "realized_pnl": realized,
        "open_value": open_value,
        "attempted": attempted,
        "filled": filled,
        "fill_rate": (filled / attempted) if attempted else None,
        "missed_closed": status.get("missed_closed", 0),
        "no_book": status.get("no_book", 0),
        "no_depth": status.get("no_depth", 0),
        "backlog_skipped": status.get("too_old", 0),
        "markets_resolved": wins + losses,
        "markets_won": wins,
        "markets_lost": losses,
        "win_rate": (wins / (wins + losses)) if (wins + losses) else None,
        "avg_slippage": (sum(slips) / len(slips)) if slips else None,
        "median_lag": (sorted(lags)[len(lags) // 2] if lags else None),
    }
