# Bonereaper (0xeebde7a0…eba30) — live re-measurement, 2026-07-20

**Why this exists:** `bonereader_analysis.md` is dated 2026-05-12. Since then
`bonereader_public_intel.md` §4 flags a **dynamic taker-fee rollout** on crypto
markets explicitly aimed at latency arbitrage. Before copying a strategy into
the bot, I re-pulled his fills to check what he does *now* rather than what he
did in May.

**Method:** `data-api.polymarket.com/activity?user=<addr>&end=<ts>`, walked
backwards by timestamp (the `offset` param caps at 3,500). 20,500 activity rows
→ **13,914 BTC-5m TRADE records** over **2026-07-18 05:45 → 2026-07-20 06:37
UTC**. Window-open time comes from the slug (`btc-updown-5m-<open_ts>`), so
`sec_into = trade_ts - open_ts` on a 300s window.

---

## 1. What held up from the May analysis

| Fingerprint | May | Now | Verdict |
|---|---|---|---|
| BUY / SELL split | 178,519 / 0 | **13,914 / 0** | ✅ still never sells |
| Side bias | 49.9% Up | **49.3% Up** (6,866 / 7,048) | ✅ still side-neutral |
| Markets/day | ~280 | **~292** (584 in 2d) | ✅ still hits every window |
| Dollars skew late | vol-median 218s | **vol-median 196s** | ✅ (t_remaining ~104s) |
| Sizes up into convergence | yes | **yes, more extreme** | ✅ |

## 2. What changed

| Metric | May | Now |
|---|---|---|
| Fills per market | 97.6 avg | **23.8 avg** (median 20, max 291) |
| Daily notional | ~$800k | **~$144k** |
| Avg trade | $29.12 | $20.75 (median $6.60) |

He is running the same shape at roughly **1/5 the throughput**. Consistent with
the fee regime compressing how much volume is worth pushing, though this window
is too short to prove causation.

## 3. Entry timing (13,914 trades)

| sec into window | trades | % | notional | % vol |
|---|---:|---:|---:|---:|
| 0–60 | 3,329 | 23.9% | $40,905 | 14.2% |
| 60–120 | 3,029 | 21.8% | $42,396 | 14.7% |
| 120–180 | 2,793 | 20.1% | $47,889 | 16.6% |
| **180–240** | 2,577 | 18.5% | **$62,679** | **21.7%** |
| **240–270** | 1,300 | 9.3% | **$51,585** | **17.9%** |
| 270–300 | 874 | 6.3% | $42,172 | 14.6% |

Trade *count* is nearly uniform; **dollars** concentrate after 180s.
**Volume-weighted median entry = 196s ⇒ t_remaining ≈ 104s.**

## 4. Entry price — where the money actually goes

| price | trades | % | notional | % vol |
|---|---:|---:|---:|---:|
| 0.00–0.10 | 458 | 3.3% | $988 | 0.3% |
| 0.10–0.30 | 2,321 | 16.7% | $11,065 | 3.8% |
| 0.30–0.50 | 3,163 | 22.7% | $26,021 | 9.0% |
| 0.50–0.70 | 3,687 | 26.5% | $44,770 | 15.5% |
| 0.70–0.80 | 1,692 | 12.2% | $32,909 | 11.4% |
| 0.80–0.90 | 1,505 | 10.8% | $43,858 | 15.2% |
| 0.90–0.98 | 586 | 4.2% | $26,865 | 9.3% |
| **0.98–1.01** | **502** | **3.6%** | **$102,272** | **35.4%** |

**The single most important line:** 3.6% of his trades carry 35.4% of his
dollars, at 0.98–0.99. Average ticket there ≈ **$204**. The old bot config
capped entries at 0.98, which excluded this bucket entirely.

**Late + high** (sec≥180 **and** price≥0.80): 1,479 trades = 10.6% of count but
**44.5% of volume**. Median 17 shares, median price 0.910, p90 $147.

## 5. Size ladder derived from the above

| price tier | notional | rationale |
|---|---:|---|
| 0.80–0.90 | $15 | matches median late+high ticket ($15.67) |
| 0.90–0.95 | $30 | ramp |
| 0.95–0.98 | $60 | ramp |
| 0.98–1.01 | $200 | matches his $204 average in this bucket |

Implemented as `Config.size_ladder_usdc` with `size_scale` to run at a fraction.

## 6. Config deltas applied to the bot

| Knob | Was | Now | Why |
|---|---|---|---|
| `seconds_before_close` | 35 | **120** | his volume median is t_rem 104s |
| `loser_floor` | 0.85 | **0.80** | his band starts at 0.80 |
| `max_entry_price` | 0.98 | **0.99** | 0.98–0.99 is 35% of his dollars |
| entries per market | 1 | **25** | he averages 23.8 |
| size | fixed 5 sh | **ladder** | he scales up into convergence |
| `max_open_positions` | 1 | **50** | he holds 33–40 concurrently |

## 7. The thing the May analysis did not model: fees

`btc_5min_market_spec.md:107` documents `crypto_fees_v2`:

```
taker_fee = shares * 0.07 * p * (1-p)     # takerOnly
```

We are always taker (FOK BUY), so we always pay it. Holding to resolution,
per share: a win returns `(1-p) - f`, a loss costs `p + f`, giving
`EV = w - p - f`. So:

> **breakeven win rate = p + 0.07·p·(1−p)**

| entry | fee/share | need win rate |
|---|---:|---:|
| 0.85 | $0.0089 | 85.9% |
| 0.90 | $0.0063 | 90.6% |
| 0.94 | $0.0040 | 94.4% |
| 0.98 | $0.0014 | 98.1% |

Fees eat ~6–7% of gross edge across our band. Any simulation that ignores them
overstates PnL by that much — enough to flip the sign. Implemented in
`bot/fees.py`; the dashboard grades every price bucket against its own
breakeven.

## 8. Caveats

- 2-day window. Enough to characterise cadence/sizing, **not** enough for win
  rate or PnL — he trades ~292 markets/day and variance at 55–59% win rates
  needs weeks.
- I measured **his entries**, not his outcomes. I did not join to resolutions
  in this pass, so no PnL or win rate is claimed here. The May analysis
  (+$19,065 / 59% / 6.5 days) is the reference for those and is pre-fee.
- `bonereader_public_intel.md` §0 still applies: `0xeebde7a0…` is
  **@bonereaper**, *not* the more famous `0xd84c2b6d…` @bonereader. Press
  about the latter does not describe this wallet.
- Copying entry *shape* does not copy his edge. Per the intel file, the
  publicly inferred edge is latency arb vs Binance/Chainlink — infrastructure
  we do not have. This bot reproduces where and how big he buys, not how fast.
