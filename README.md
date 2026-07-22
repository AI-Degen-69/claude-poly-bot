# polymarket-taker

Paper-trading simulation of a **taker** strategy on Polymarket's 5-minute
"Bitcoin Up or Down" market. It crosses the spread to buy the near-certain side
late in the window, gated on a Binance spot signal, and holds to resolution.

**Live dashboard:** https://claude-poly-bot-production.up.railway.app
· [kanban view](https://claude-poly-bot-production.up.railway.app/kanban)

> Simulation only. It never places a real order. Hosted credentials are
> placeholders — see [AGENTS.md](AGENTS.md).

## The strategy in one paragraph

Wait until the last 120s of a 5-minute window. If one side's ask sits in
0.80–0.99 *and* Binance says BTC has already moved ≥5bps in that direction,
buy it with a price-scaled size ladder, up to 25 fills per market. Never sell;
hold to redemption at $1.00 or $0.00. Every fill pays a taker fee of
`shares × 0.07 × p × (1−p)`, so breakeven is `p + fee` — at 0.95 that is 95.3%.

## Layout

    strategy/   engine (config, markets, book, spot gate, rules, orders, risk, store)
    server/     dashboard.py (API) + kanban.py (page)
    research/   lab notebook, EN + HE
    deploy/     container entrypoint + preflight
    ui/         React dashboard (classic view)

The sibling repo [`polymarket-maker`](https://github.com/AI-Degen-69/polymarket-maker)
uses the same layout.

## Running locally

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/setup-hooks.sh        # required once: research-log enforcement
.venv/bin/python -m strategy.main  # the bot
.venv/bin/uvicorn server.dashboard:app --port 8787
```

## Current state — 110 settled markets

Updated 2026-07-22. Live figures on the dashboard; this is a snapshot.

| metric | value |
|---|---|
| settled markets | 110 (104W / 6L) |
| win rate | **94.5%** [88.6–97.5] |
| breakeven required | 94.3% |
| net P&L | **+$62.85** (equity $5,062.85 from $5,000) |
| expectancy | +$0.57 per market |
| profit factor | 1.06 |
| fees paid | $87.73 |
| max drawdown | −$708.92 |
| **verdict** | **INCONCLUSIVE** — ~90 more markets needed |

The strategy is now marginally **above** its breakeven line, having been below
it for most of the run. The confidence interval [88.6–97.5] still straddles the
94.3% bar, so this is not yet a result — it is a hint with the right sign.

### Edge by entry price

| band | n | win | needed | edge |
|---|---|---|---|---|
| 0.80–0.90 | 316 | 88.6% | 86.2% | **+2.4** |
| 0.90–0.95 | 576 | 93.4% | 93.0% | +0.4 |
| 0.95–0.98 | 589 | 97.3% | 96.3% | +0.9 |
| 0.98–1.01 | 431 | 98.4% | 98.7% | **−0.3** |

The cheapest band carries most of the edge; the most expensive band is
negative, which is what the fee curve predicts.

### The spot gate is not currently earning its place

| filter | win rate | n |
|---|---|---|
| ≥10 bps | 94.4% | 18 |
| <10 bps | 94.6% | 92 |

Live data shows **no separation** — the backtest measured 96.0% vs 81.3% at
≥5bps, and that gap has not reproduced. Either the backtest overfit 584 windows
or the effect is smaller than it looked. This is the main open question for the
taker and is tracked in [research/RESEARCH_LOG.md](research/RESEARCH_LOG.md).
