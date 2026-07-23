# Forking a bot (experiments without touching the live one)

The repo you are reading **is the template** — the running bot. To test a
different set of strategy parameters, a different gate, or a whole new idea,
fork it into an isolated copy and tune *that*. The template stays clean and
live.

## One command

From the template repo:

```bash
bash scripts/fork_bot.sh <fork-name>            # e.g. gate10 / ladder-flat / no-spot
bash scripts/fork_bot.sh <fork-name> --port 8795   # pick a dashboard port
bash scripts/fork_bot.sh <fork-name> --dest /abs/path   # custom location
```

This creates `../<fork-name>` (or `--dest`) that is **fully runnable and
isolated**:

| Concern        | How it's isolated                                            |
|----------------|--------------------------------------------------------------|
| Database       | `POLYBOT_DB=<fork>/trades.db` (set in the fork's `.env`)    |
| Dashboard port | `PORT` in the fork's `.env`; `run_dashboard.sh` is port-aware |
| Liveness files | `bot.pid` / `bot.mode` / `collector.pid` live under the fork dir |
| Secrets        | fork gets its **own** `.env` (copied from the template)      |
| Code           | independent copy; git-inited with the research hook armed    |

The UI is bundled (copied from the template's built `ui/dist`), so the
dashboard serves it on **one port** — no separate Vite dev server required.

## Run the fork

```bash
cd ../<fork-name>
bash scripts/run_paper.sh          # paper / simulation bot (never real orders)
bash scripts/run_dashboard.sh      # dashboard -> http://127.0.0.1:<PORT>
```

Then tell Hermes what to change, e.g.:

> in `../gate10`, set `min_spot_offset_bps = 10.0` and `size_scale = 0.5`,
> then run it.

Hermes edits `strategy/config.py` **in the fork only** and starts it. The
template keeps running untouched.

## Tune what

Every knob is centralized in `strategy/config.py` (`Config`, frozen
dataclass). Common experiment axes:

- `max_entry_price` / `loser_floor` — the entry price band
- `seconds_before_close` / `min_t_remaining_sec` — timing window
- `size_scale` / `size_ladder_usdc` — sizing (watch the 5-share Polymarket floor)
- `max_entries_per_market` / `max_open_positions` — concurrency
- `use_spot_gate` / `min_spot_offset_bps` — the Binance gate
- `sim_bankroll_usd` / `respect_book_depth` — simulation fidelity

## House rules (inherited from the template)

- **Never place a real order.** Paper simulation only. `sim_only` stays `True`.
- **One instance per database.** Don't point two bots at the same `POLYBOT_DB`.
- **Changing strategy parameters invalidates the current sample.** Each fork
  starts on a fresh `trades.db` — that is the point.
- **Keep the research log current** in the fork too (the pre-commit hook is
  armed): any commit touching `strategy/` or `server/` must also update
  `research/`.

## Cleanup

Forks are plain directories. To retire one: stop its bot/dashboard, then
`rm -rf ../<fork-name>`. The template is unaffected.
