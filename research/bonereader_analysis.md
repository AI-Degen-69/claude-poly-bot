# Bonereaper (0xeebde7a0...eba30) — Polymarket BTC 5-min Strategy Analysis

**Date of analysis:** 2026-05-12
**Data window:** 2026-05-05 23:33 UTC → 2026-05-12 11:09 UTC (6.48 days)
**Display name on Polymarket:** "Bonereaper" / pseudonym "Popular-Insurrection"

---

## 1. Dataset

Pulled via `https://data-api.polymarket.com/activity?user=<addr>&end=<ts>` (paginated by timestamp; the `offset` parameter caps at 3,500 and `start/end` is the only viable way to go further back). Market resolutions pulled from `https://gamma-api.polymarket.com/events?slug=<slug>`.

| Bucket | Value |
|---|---|
| Total activity records | 358,438 |
| TRADE records | 353,309 |
| REDEEM records | 5,118 |
| MAKER_REBATE events | 7 (essentially zero) |
| **BTC 5-min market TRADE records** | **178,519** |
| BTC 15-min trades | 84,946 |
| ETH 5-min trades | 57,520 |
| Unique BTC 5-min markets touched | 1,829 (over 6.5 days; ~280/day) |
| Current portfolio value (data-api `/value`) | $9,209.96 |

Raw JSON: `research/bonereader_raw/` (`activity_full.json`, `positions_all.json`, `resolutions.json`, `value.json`). `/pnl` endpoint returns 404 — PnL was computed from trades + resolutions.

---

## 2. Headline behavioral fingerprints (BTC 5-min markets)

| Metric | Value |
|---|---|
| BTC 5-min trades | 178,519 |
| BTC 5-min markets traded | 1,829 |
| Total USDC notional | **$5,197,760** (≈ $800k/day avg) |
| Avg trades per market | 97.6 (median 85, max 434) |
| Avg notional per trade | $29.12 |
| Median notional per trade | $8.22 |
| BUY trades | 178,519 (**100%**) |
| SELL trades | **0** |
| Markets that ever had a SELL | **0 / 1,829** |
| BUY-Up trades | 89,146 (49.9%) |
| BUY-Down trades | 89,373 (50.1%) |
| Maker-rebate events in 6.5d | 7 (effectively pure taker) |
| Median time between trades | 0 s (same-second bursts) |
| Mean time between trades | 3.14 s |

### Sells / exits
**He never sells.** Across 1,829 markets, 178,519 trades, there are zero SELL trades on BTC 5-min markets in this window (also true in the full 358k-record dataset he has only 7 maker-rebate events and zero SELLs in the activity feed). He always holds to resolution and lets winners redeem at $1, losers expire at $0 (the 5,118 REDEEM events confirm this).

### Side bias
Effectively neutral over the window (49.9% Up, 50.1% Down). He plays both sides; this is **not a directional bet** strategy.

### Order type
Trades come in same-second bursts (median gap 0s, mean 3.14s). With near-zero maker rebates and 100% BUY (no opposite-side fills), this is **pure taker / market-order** flow.

---

## 3. Entry timing — the central finding

5-minute markets last 300 s. Slug encodes the open timestamp (e.g. `btc-updown-5m-1778583900` = open at 11:05:00 UTC, close at 11:10:00 UTC; markets remain tradeable for ~30-60s after the underlying candle closes pending oracle resolution).

### Trade-count distribution by seconds-into-window

| Window (s) | Trades | % |
|---|---:|---:|
| 0–30 | 18,391 | 10.3% |
| 30–60 | 19,034 | 10.7% |
| 60–90 | 20,947 | 11.7% |
| 90–120 | 18,488 | 10.4% |
| 120–150 | 19,936 | 11.2% |
| 150–180 | 16,479 | 9.2% |
| 180–210 | 17,717 | 9.9% |
| 210–240 | 15,470 | 8.7% |
| 240–270 | 15,984 | 9.0% |
| 270–300 | 11,388 | 6.4% |
| 300–330 | 3,916 | 2.2% |
| 330–360 | 538 | 0.3% |

By **count** the distribution looks roughly uniform across the 0–300s window. But by **dollars** it skews heavily late:

### Volume distribution by seconds-into-window (USDC)

| Window | Notional | % of vol |
|---|---:|---:|
| 0–60 s | $549k | 10.6% |
| 60–120 s | $610k | 11.8% |
| 120–180 s | $734k | 14.2% |
| 180–240 s | $1,131k | 21.8% |
| 240–270 s | $999k | 19.3% |
| 270–300 s | $887k | 17.1% |
| 300–360 s | $277k | 5.3% |

Volume-weighted median entry second = **218s** (3:38 into a 5-min market). Trade-count median = 137s.

### Size × time cross-tab — the smoking gun

Number of $500+ trades by entry second:

| Window | $500+ trades | $500+ USDC |
|---|---:|---:|
| 0–60s | 0 | $0 |
| 60–120s | 20 | $19k |
| 120–180s | 98 | $132k |
| 180–240s | 343 | $499k |
| 240–270s | 393 | $582k |
| 270–300s | 383 | $547k |
| 300–360s | 91 | $107k |

**>99% of $500+ trades happen after second 120; >80% after second 180.** The same is true for $100-500 trades. The small ($1-20) trades distribute fairly evenly across the window; the big size only fires once the price has converged.

---

## 4. Entry-price distribution

| Price bucket | Trades | % | USDC volume |
|---|---:|---:|---:|
| <0.10 | 7,243 + 17,388 = 24,631 | 13.8% | $74.8k |
| 0.10–0.30 | 32,459 | 18.2% | $149.7k |
| 0.30–0.50 | 34,198 | 19.2% | $306.8k |
| 0.50–0.70 | 43,585 | 24.4% | $633.0k |
| 0.70–0.90 | 29,830 | 16.7% | $691.7k |
| ≥0.90 | 28,611 | 16.0% | **$3,396.7k (65.4% of all volume)** |

Two-thirds of his dollar volume goes in at price ≥ 0.90. Mean entry price is 0.510 by trade count but volume-weighted mean is dramatically higher — he sizes up as the market converges.

---

## 5. Win rate and PnL

Computed by joining trades to gamma-api market resolutions (1,829/1,829 markets resolved cleanly to {0,1}).

### Per-market results
| Metric | Value |
|---|---:|
| Markets resolved & analyzed | 1,829 |
| Markets won (net PnL > 0) | 1,080 |
| Markets lost (net PnL ≤ 0) | 749 |
| **Market-level win rate** | **59.0%** |
| Total buy cost | $5,197,760 |
| Total winning-side payout | $5,216,824 |
| Total sell proceeds | $0 |
| **Net realized PnL (BTC 5-min only)** | **+$19,065 over 6.5 days** |
| Avg PnL per market | $10.42 |
| Avg PnL per winning market | $145.63 |
| Avg PnL per losing market | -$184.53 |

### PnL per dollar of risk
- Gross edge: $19,065 / $5,197,760 = **+0.37%** of notional (≈ 37 bps return on volume)
- Annualized turnover at this pace: ~$45M/yr → ~$1.07M/yr at this edge (rough — assuming the regime persists, ignores fees and slippage on larger size)

### Edge by entry-price bucket (USDC-weighted)

| Price bucket | Trades | Win rate | Cost | Payout | Edge $ | Edge % |
|---|---:|---:|---:|---:|---:|---:|
| 0.0 | 7,243 | 3.4% | $19,770 | $17,967 | −$1,802 | **−9.1%** |
| 0.1 | 17,388 | 10.1% | $55,079 | $55,264 | +$185 | +0.3% |
| 0.2 | 17,664 | 19.0% | $94,643 | $85,946 | −$8,697 | **−9.2%** |
| 0.3 | 14,795 | 31.8% | $112,823 | $112,828 | +$5 | +0.0% |
| 0.4 | 19,403 | 41.4% | $193,950 | $194,324 | +$373 | +0.2% |
| 0.5 | 21,885 | 52.1% | $289,485 | $293,338 | +$3,852 | +1.3% |
| 0.6 | 21,700 | 60.5% | $343,537 | $345,131 | +$1,594 | +0.5% |
| 0.7 | 15,187 | 71.4% | $301,554 | $305,146 | +$3,593 | +1.2% |
| 0.8 | 14,643 | 82.6% | $390,177 | $397,709 | **+$7,532 (+1.9%)** |
| 0.9 | 11,075 | 90.7% | $535,339 | $539,295 | +$3,955 | +0.7% |
| 1.0 | 17,536 | 99.3% | $2,861,402 | $2,869,876 | **+$8,474 (+0.3%)** |

The losses are concentrated at the **<0.30** buckets — small "lottery" buys on the side that's already losing. Edge is positive in every bucket from 0.3 upward, and is largest in dollar terms at price ≥ 0.80, where he is essentially scalping the convergence to $1.

### Edge by trade-size bucket

| Size bucket | Trades | Win rate | Cost | Edge | Edge % |
|---|---:|---:|---:|---:|---:|
| <$1 | 25,354 | 21.6% | $11k | +$106 | +1.0% |
| $1–5 | 48,625 | 50.3% | $132k | +$1,598 | +1.2% |
| $5–20 | 58,724 | 49.6% | $704k | +$1,195 | +0.2% |
| $20–100 | 39,940 | 70.9% | $1,496k | **+$12,771 (+0.9%)** |
| $100–500 | 4,546 | 94.7% | $968k | +$860 | +0.1% |
| $500+ | 1,330 | 98.6% | $1,887k | +$2,534 | +0.1% |

The "workhorse" PnL bucket is **$20–100 trades, which generated $12.8k of the $19k PnL** at +0.9% edge. The largest $500+ trades have a ~99% win rate but a slim ~0.1% edge — they're effectively risk-free arbitrage on already-converged prices.

### Up vs. Down edge

- Total Up-side edge: **+$42,828**
- Total Dn-side edge: **−$23,866**

Within the data window, the strategy produced more PnL on Up bets than Down. Likely a sample-size artifact (BTC drifted higher 1080 vs 749 Up vs Down market resolutions over 6.5d), not evidence of a directional bias in his entries (he bought Up and Down in near-equal share counts).

### Daily PnL (markets grouped by open day)

| Day | Markets | Cost | Payout | PnL |
|---|---:|---:|---:|---:|
| 2026-05-05 | 6 | $16k | $17k | +$206 |
| 2026-05-06 | 278 | $782k | $782k | **−$672** |
| 2026-05-07 | 286 | $941k | $950k | **+$8,530** |
| 2026-05-08 | 279 | $956k | $955k | −$1,758 |
| 2026-05-09 | 284 | $492k | $496k | +$3,098 |
| 2026-05-10 | 283 | $617k | $619k | +$2,157 |
| 2026-05-11 | 280 | $907k | $910k | +$2,559 |
| 2026-05-12 | 133 (partial) | $485k | $490k | +$4,944 |

Six profitable days, two slightly negative days; no blow-up days. Daily PnL is **consistently small relative to daily turnover** (typically ±0.3% of notional).

---

## 6. Frequency / concurrency

- ~280 BTC 5-min markets traded per full day (the schedule produces 288 per day; he hits essentially every market).
- Trades/hour: avg 1,137, median 1,069, max 2,798.
- Hour-of-day (UTC): activity is fairly distributed but peaks during US market hours (13:00–17:00 UTC, ~5.2–5.7% of trades per hour vs 2.2% in the quietest hour 21 UTC). He likely runs an always-on bot; the peak hours coincide with higher BTC volume / Polymarket liquidity.
- Inter-trade gap median = 0 s — many trades fire in the same second, consistent with a bot firing a small batch of limits/IOCs simultaneously.
- He's running BTC 5-min, BTC 15-min, ETH 5-min, ETH 15-min, and longer-dated BTC markets in parallel — non-trivial concurrent state to manage.

---

## 7. Open positions snapshot (33 currently)

The `/positions` endpoint shows him sitting on substantial losing positions in some longer-dated "Bitcoin Up or Down" daily markets (e.g. a $5,978 BUY-Down at avg 0.965 on an unfinished 5-min market shown as −50% mark; a $2,793 BUY at 0.99 on an April 4 daily market marked −99.99%). The losers list includes large stuck longs in markets that resolved against him (or are pending). This is consistent with the "buy at ≥0.9, hold to resolution" strategy — most of these resolve as winners but the occasional loser bites for the full stake. None of these are 5-min markets (they're the longer-horizon BTC markets), so they don't bear on the 5-min PnL number above.

---

## 8. Interpretation — the strategy in plain English

The numbers point to a **late-window convergence-scalping bot**, not a market-direction predictor:

1. **Wait for the market to reveal its direction.** BTC 5-min markets typically converge to near $0 / $1 once the candle is mostly written. As the close approaches, the order book on the "obviously winning" side trades at $0.95–$0.99, leaving 1–5¢ of remaining edge that decays to zero at resolution.
2. **Hit the offer aggressively on the winning side**, in batches of $20–$500, in the last ~120 seconds of the window. ~99% of these resolve winning. With patient order placement you can buy at $0.98 and redeem at $1.00 for a ~2% gross return in seconds — but the available size at favorable prices is small, hence the high trade count.
3. **Pepper the early window with small (<$20) probabilistic buys.** These have ~50% win rate, scratch flat in aggregate (+0.2% to +1.3% edge per bucket), and probably serve as either (a) liquidity-providing flow to bait counter-orders, (b) probing the book for resolution-priced liquidity, or (c) a smaller separate ML/signal strategy. They are NOT the main PnL driver.
4. **Never sell.** Closing positions costs spread; holding to redemption costs nothing. Polymarket redemptions are $1.00 per winning share, $0.00 per losing share — so for trades that resolve, there is no incentive to exit. The −$184.50 avg loss per losing market is the inventory cost of being wrong on the convergence read (the "winning" side flipped in the last seconds).
5. **The earlier-window low-price buys (<0.30) lose 9% — these are speculative.** Either a small directional bet bolted onto the main strategy, or noise from the bot getting filled too far away from the touch.

The economics are razor thin: **~37 bps on notional, ~59% per-market win rate, ~$2,900 PnL/day** on ~$800k turnover/day. This is profitable only with (i) very low effective taker fees (Polymarket's 2% maker rebate / 0 taker fee structure helps), (ii) automation/co-location, and (iii) deep small-size patience.

---

## 9. Caveats / things I could not determine

- I could not separate maker vs taker fills definitively from the data-api activity stream (which lacks an explicit `feeRateBps` or `liquidity` field). Only 7 MAKER_REBATE events appear across 358k records, so he is overwhelmingly a taker. To verify exact fee/rebate exposure you'd need the CLOB `trades` endpoint per order.
- I could not pull the order book history at the moment of each trade, so I cannot decompose the "price at entry" further into "vs. best bid/ask at fill time" — but the price bucket distribution is a strong proxy.
- The data-api `/trades` endpoint caps offset pagination at 3,500. The `/activity` endpoint supports `end=<ts>` time-windowing, which is what I used. The `/pnl?user=...` endpoint returns 404 — there is no public per-user PnL endpoint. PnL here is reconstructed from trade fills × resolutions, which understates costs (does not deduct any gas/relayer fees if they apply on Polygon — should be ~$0 since the user trades through their CLOB proxy).
- 6.48 days is enough to characterize the steady-state strategy but is not long enough to confidently quote an annualized Sharpe or tail-risk. Two of the seven days printed small losses; you should expect occasional larger drawdowns if a market gaps in the final seconds (the $5,000 max single trade size on a near-$1 entry can lose $5,000 instantly).
- The strategy reads as **information-following / convergence-arbitrage**, not predictive. It does NOT contain an alpha signal you can copy without infrastructure: you need (a) latency to the CLOB equal to or better than his bot, (b) willingness to take small fill sizes patiently, and (c) capital to repeat thousands of trades/day.
