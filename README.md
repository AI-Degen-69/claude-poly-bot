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

## Current state

See [research/RESEARCH_SUMMARY.md](research/RESEARCH_SUMMARY.md). At 74 settled
markets the strategy is **inconclusive and currently negative**: win rate 91.9%
[83.4–96.2] against a 94.2% breakeven.
