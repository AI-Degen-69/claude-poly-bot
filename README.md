# polybot_beginner

Your first trading bot on **Polymarket**. It trades the 5-minute "Bitcoin Up
or Down" market on Polygon and comes with a real-time
Bloomberg-terminal-style dashboard for watching it work.

The strategy is **late-window convergence scalping**: when the market has
clearly chosen a winner in the last few seconds of a 5-minute window, the
bot takes the winning side's offer for a small residual edge, then holds to
resolution. The pattern is reverse-engineered from a profitable Polymarket
trader — see [`research/bonereader_analysis.md`](research/bonereader_analysis.md).

This repo is built for learning. Real-money parts are kept small, every
risky action has a kill switch, and every setup step is a one-line script.

---

## Quick orientation — what you'll do

```
 1. install deps                  (5 min)
 2. generate a fresh bot wallet   (10 sec)
 3. fund it with MATIC + USDC.e   (5 min)
 4. import wallet into MetaMask   (1 min)
 5. log into polymarket.com       (2 min)  -- deploys your "deposit wallet"
 6. wrap USDC.e -> pUSD           (1 min)
 7. move pUSD to deposit wallet   (1 min)
 8. derive API credentials        (10 sec)
 9. verify setup                  (5 sec)
10. launch dashboard + bot        (10 sec)
```

End-to-end: ~30 minutes if everything goes smoothly.

> **Want to try it without funding a wallet?** Skip to step 9 once
> `verify_setup.py` complains. Then run `scripts/run_paper.sh` — the bot
> watches live markets and logs decisions but never places real orders.
> Useful for learning what the bot does before risking money.

## Heads up before you start

- **Polymarket is geo-restricted.** The CLOB is unavailable in many
  jurisdictions (US, UK, France, others). If polymarket.com blocks you, the
  bot won't work either.
- **This is real money on a public blockchain.** Setup costs ~$0.50 in
  Polygon gas for a handful of transactions. Trading risks whatever you
  fund the wallet with — start with $30 to learn.
- **The strategy as shipped is not consistently profitable.** Read the
  ["Expectations"](#expectations) section before you commit any real
  capital. This is a starting point you'll want to tune.

---

## Prerequisites

| | version | install |
|---|---|---|
| Python | 3.11+ | macOS: `brew install python@3.11` · Linux: `apt install python3.11 python3.11-venv` · Windows: [python.org installer](https://www.python.org/downloads/) |
| Node | 18+ | macOS: `brew install node` · Linux: [nodesource setup](https://github.com/nodesource/distributions) · Windows: [nodejs.org](https://nodejs.org/) |
| MetaMask | latest | https://metamask.io/ (browser extension) |

You'll also need a way to get **MATIC** and **USDC.e** onto your wallet on
the Polygon network. The easiest path for beginners:

1. Open an account on Coinbase, Kraken, Binance, or any exchange that
   supports Polygon withdrawals.
2. Buy MATIC and USDC. Keep amounts small to start — ~$30 USDC, $1–2 MATIC.
3. Withdraw to the wallet address you'll generate in step 2 below. **On the
   network selector, choose Polygon (not Ethereum).**

If you already have USDC.e in a wallet on another chain, you can bridge it
via [app.polygon.technology](https://app.polygon.technology/).

> **USDC.e vs USDC.** Polymarket uses USDC.e (the older "bridged" USDC).
> Most exchanges send the newer "native" USDC by default — make sure the
> network is Polygon and the token symbol is **USDC.e** (or just "USDC"
> when the network is Polygon — exchanges often label it that way).

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/<your-user>/polybot_beginner
cd polybot_beginner

# Python venv + deps
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# UI deps
cd ui && npm install && cd ..
```

### 2. Generate a fresh trading wallet

```bash
.venv/bin/python scripts/generate_wallet.py
```

This creates `.env` (file mode 600 — only readable by you) with a brand-new
private key, address, and sensible defaults. The script refuses to
overwrite an existing `.env`, so a funded key can't be wiped by accident.

> You don't hand-edit `.env` (or `.env.example`). Every value is written by
> a script later in this walkthrough.

> **Why a fresh wallet?** Trading bots should run with a dedicated wallet,
> never your main account. If the bot has a bug or the key leaks, only this
> wallet is at risk. Funding it small ($30) caps your downside while
> learning.

Verify the file:

```bash
grep ^WALLET_ADDRESS .env       # your bot wallet
```

### 3. Fund the bot wallet on Polygon

You're sending two tokens from an exchange (or another wallet) **to** your
bot's `WALLET_ADDRESS` (the `0x...` you got in step 2), on the **Polygon**
network:

| token | amount | what it's for |
|---|---|---|
| **MATIC** (sometimes shown as POL) | ~1 | gas — pays for setup + months of trading |
| **USDC.e** | $30+ | trading collateral |

**On the exchange's withdrawal form:**

- **Destination address:** your `WALLET_ADDRESS` from step 2.
  Verify with: `grep ^WALLET_ADDRESS .env`
- **Network:** Polygon (not Ethereum, not BSC, not anything else).
- **Token:** MATIC for the first withdrawal, USDC.e for the second.

> **About `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`** — this is the
> **USDC.e token contract** on Polygon, NOT a destination. Some exchanges
> ask you to confirm the token contract; if so, paste this. **Never send
> funds to this address** — that would lose them.

After your withdrawals confirm (usually 1–3 minutes), check:

```bash
.venv/bin/python scripts/check_balance.py
```

If both balances show up, you're good. If they're zero, the withdrawal
hasn't arrived yet — wait a minute and re-run.

### 4. Import the bot wallet into MetaMask

This is **only used for the one-time Polymarket registration** in the next
step. After that you can remove the account from MetaMask if you like — the
bot reads the key from `.env` directly.

1. Grab the private key:
   ```bash
   grep ^PRIVATE_KEY .env
   ```
2. MetaMask → account menu (top-right circle) → **Add account or hardware
   wallet** → **Import account** → paste the private key.
3. **Verify** the imported account address matches your `WALLET_ADDRESS`
   from `.env`. If it doesn't, you imported the wrong key — stop and
   start over.

### 5. Register the bot wallet on Polymarket

Polymarket V2 doesn't let raw wallets trade directly. Instead, your wallet
needs a **deposit wallet** — a smart-contract wallet that your account
signs orders for. The simplest way to get one deployed is to sign into
polymarket.com once with your bot wallet.

1. **Log out** of any existing polymarket.com session first (avatar →
   Logout).
2. Open polymarket.com → **Log In** → choose **MetaMask**.
   If you don't have a Polymarket account yet, sign up via my referral
   link — it helps support this project at no cost to you:
   [polymarket.com/?r=allaboutai](https://polymarket.com/?r=allaboutai).
3. In the MetaMask popup, **double-check** the connected account is your
   `WALLET_ADDRESS` (from `.env`), then sign the auth message.
4. Polymarket auto-deploys your deposit wallet (no gas needed — they
   sponsor it).
5. Click your avatar (top right) → **Wallet** → copy the deposit address.
   It starts with `0x` and is *different* from your EOA.

> **Critical gotcha:** if you sign in with a different MetaMask account by
> mistake, the deposit wallet will belong to *that* account and your bot
> won't be able to sign for it. The migration script (next step) checks
> ownership and refuses to send funds if there's a mismatch.

### 6. Wrap USDC.e to pUSD

Polymarket V2 settles in pUSD (a 1:1 wrapper around USDC.e). Wrap it:

```bash
.venv/bin/python scripts/wrap_to_pusd.py
```

This is idempotent — safe to re-run if anything fails midway.

### 7. Move pUSD into the deposit wallet

Use the deposit address you copied from polymarket.com:

```bash
.venv/bin/python scripts/migrate_to_deposit_wallet.py 0xYOUR_DEPOSIT_ADDRESS
```

The script:
- verifies the address has contract code (refuses to send funds to a plain
  EOA by mistake)
- verifies its `owner()` is your bot EOA (catches the wrong-MetaMask-account
  mistake from step 5)
- transfers all your pUSD from the EOA into the deposit wallet
- updates `.env`: sets `FUNDER_ADDRESS=<deposit>` and `SIGNATURE_TYPE=3`

### 8. Derive L2 API credentials

```bash
.venv/bin/python scripts/derive_api_creds.py
```

The bot uses these to authenticate every order. Stored in `.env`.

### 9. Verify the whole setup

```bash
.venv/bin/python scripts/verify_setup.py
```

Walks through every check (wallet, balance, deposit wallet ownership,
allowances, API auth) and prints `[ OK ]` / `[FAIL]` for each. If anything
fails, the script tells you exactly what to do.

---

## Running

### Dashboard

```bash
scripts/run_dashboard.sh
```

Opens FastAPI on port 8787 and the Vite UI on port 5173. **Open
http://127.0.0.1:5173 in your browser.**

| panel | shows |
|---|---|
| Top bar | bot status (RUNNING / STOPPED / LOCKED), API health, last-trade flash |
| Wallet / Equity | pUSD cash + open position value + total equity |
| P&L 24h | realized PnL, win/loss count, win rate |
| Strategy | current entry caps + risk thresholds |
| Live Market | active 5-min market, countdown, Up/Down book (winner ask highlighted amber when in buy zone) |
| Decision Log | every decision the bot makes, live-streaming |
| Open Positions | current CTF holdings |
| Orders | recent order outcomes |

The dashboard works fine even when the bot isn't running — useful for
watching markets before going live.

### Bot: paper vs live

The bot has two modes. **Always start in paper.** When the dashboard shows
green decisions on real markets for a while and you understand what it's
doing, switch to live.

```bash
# PAPER — no real orders, logs decisions only. Safe.
scripts/run_paper.sh

# LIVE — places real orders against your funded deposit wallet.
scripts/run_live.sh

# Stop either one
scripts/stop_live.sh
```

Both modes use the same script to stop. Only one bot can run at a time
(the launcher refuses if `bot.pid` exists).

The dashboard top bar shows the mode prominently:

- `[ PAPER ]` in green = safe, no real orders
- `[ LIVE ]` in red = real money on the line
- `[ OFFLINE ]` in grey = bot not running

The 5-second screen flash only fires on **real** fills, never paper.

In the decision log and orders tables, paper entries are also flagged
internally (`dry_run=1`) so realized-PnL only counts real fills.

```bash
tail -f logs/bot_current.log    # watch the bot in real time
```

### Stopping everything

```bash
scripts/stop_live.sh
scripts/stop_dashboard.sh
```

---

## Tuning

All strategy knobs are in `bot/config.py`:

```python
max_entry_price:      0.98     # only fire when winner-side ask <= this
seconds_before_close: 35       # only fire when t_remaining <= this
min_t_remaining_sec:  8.0      # AND t_remaining >= this (avoid race-to-resolve)
order_size_shares:    5        # min is 5 per Polymarket
max_open_positions:   1
max_daily_loss_usd:   10000.0  # daily loss kill switch (10000 = effectively disabled)
```

And the convergence threshold in `bot/strategy.py`:

```python
LOSER_FLOOR = 0.85   # don't fire unless winner-side ask > this
```

Conceptually: the bot only enters when the market is convinced of a winner
(`winner ask > LOSER_FLOOR`) but hasn't fully converged
(`winner ask <= max_entry_price`). Tighter = fewer trades with more cushion;
looser = more trades with thinner per-trade edge.

Restart the bot after changes:

```bash
scripts/stop_live.sh && scripts/run_live.sh
```

---

## Troubleshooting

**`maker address not allowed, please use the deposit wallet flow`**
Your `SIGNATURE_TYPE` or `FUNDER_ADDRESS` isn't set up for the V2 deposit
wallet. Re-run `scripts/verify_setup.py` — it'll tell you which step to
re-do.

**`balance: 0` from `verify_setup.py` even though the deposit wallet
has pUSD on-chain**
Polymarket's API cache can lag for a minute. Wait 60s and re-run. If it
persists, your `FUNDER_ADDRESS` in `.env` doesn't match the deposit
wallet the CLOB knows about — check polymarket.com → Wallet to confirm.

**`order couldn't be fully filled. FOK orders are fully filled or killed`**
Not an error — that's the bot trying to take an ask that got swept by
someone else first. Normal in fast markets. The bot just moves on.

**Stuck transaction during setup (`wrap_to_pusd.py` or
`migrate_to_deposit_wallet.py` hangs)**
Polygon gas can spike. Run `.venv/bin/python scripts/bump_stuck_tx.py` to
replace the stuck tx with a higher-gas version.

**`RPC 401 Unauthorized` errors**
The default public RPC (`polygon-bor-rpc.publicnode.com`) sometimes
rate-limits. Sign up for a free Alchemy or QuickNode key and replace
`POLYGON_RPC_URL` in `.env`.

**Dashboard shows `BOT LOCKED (LOSS_CAP)`**
Daily loss exceeded `max_daily_loss_usd` in `bot/config.py`. Either wait
24 hours, raise the cap, or restart with a fresh `.env` to reset.

**Polymarket says my country is blocked**
You can't use this bot. Polymarket geo-blocks at the CLOB level — there's
no workaround that doesn't violate ToS.

---

## File map

```
polybot_beginner/
├── .env                # secrets — gitignored, never commit
├── .env.example        # reference: which script writes which field
├── bot/                # trading engine
│   ├── config.py       # all strategy knobs
│   ├── markets.py      # discover the live 5-min BTC market
│   ├── book.py         # CLOB order-book reader
│   ├── strategy.py     # decision logic
│   ├── orders.py       # SDK wrapper for FOK order placement
│   ├── risk.py         # daily-loss + open-positions caps
│   ├── store.py        # SQLite logger (trades.db)
│   ├── resolver.py     # back-fill resolutions for filled orders
│   └── main.py         # event loop
├── server/dashboard.py # FastAPI backend (port 8787)
├── ui/                 # Vite + React + TS frontend (port 5173)
├── scripts/            # setup + launch helpers
│   ├── generate_wallet.py
│   ├── check_balance.py
│   ├── wrap_to_pusd.py
│   ├── bump_stuck_tx.py
│   ├── migrate_to_deposit_wallet.py
│   ├── derive_api_creds.py
│   ├── verify_setup.py
│   ├── run_live.sh / stop_live.sh
│   └── run_dashboard.sh / stop_dashboard.sh
├── research/           # strategy analysis + market spec (MDs + .py fetchers)
└── requirements.txt
```

---

## Expectations

The 5-minute BTC market is competitive. Profitable traders here run
sub-second latency from co-located machines with paid RPC providers and
custom infrastructure. From a laptop on a public Polygon RPC, your fills
will be slower and the late-window edge is razor-thin.

**The strategy as shipped here lost ~$10 across 54 fills in an overnight
run during development.** The win rate was 89% but the breakeven needed
was ~92% at our average entry price. The shape of the problem is
asymmetric payoffs: many tiny wins (~$0.30) outweighed by occasional
full-stake losses (~$4.50).

Things you can try to improve it (in roughly increasing difficulty):

1. **Tighten the entry zone.** Set `LOSER_FLOOR` higher (e.g. 0.93) so the
   bot only takes very high-confidence trades. Fewer fills, better per-trade
   EV.
2. **Add a Binance spot-price gate.** Only fire if Binance's BTC/USDT moves
   in the favored direction by more than ~5 bps within the window. The
   stub for this lives in `bot/config.py` (`min_spot_offset_bps`).
3. **Better RPC.** Sign up for Alchemy/QuickNode for ~50% lower latency on
   reads.
4. **Reduce size when entering near $0.98+.** Asymmetric payoffs mean smaller
   stake at the marginal levels.
5. **Run shadow-mode for a week.** Add a `--dry-run` mode and collect
   thousands of "would have entered" decisions. Recompute simulated PnL
   with current fees to see if your tweaks actually help before risking
   capital.

Use this code to learn. Don't bet the house.

---

## Support

If this repo helped you, you can sign up to Polymarket through my referral
link: [polymarket.com/?r=allaboutai](https://polymarket.com/?r=allaboutai).
No obligation — it just helps me a little. Thanks.
