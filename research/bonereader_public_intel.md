# Public Intel: "Bonereader" / "Bonereaper" on Polymarket

Compiled 2026-05-12. Skeptical pass on web sources. Treat single-source claims (especially Medium / Substack) as marketing-adjacent unless corroborated.

---

## 0. CRITICAL NAMING / ADDRESS DISAMBIGUATION

The query refers to "Bonereader" at `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`. Public sources show **two distinct wallets / handles** with near-identical names:

| Handle | Address | Joined | Coverage |
|---|---|---|---|
| **@bonereader** | `0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9` | Jan 2026 | Heavy (Senal tweet, Cointrenches, Substack, etc.) |
| **@bonereaper** | `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` (the address in your question) | Mar 2026 | Light; same strategy profile |

The wallet you supplied is **@bonereaper** (reaper, not reader). Polymarket's profile page resolves the address to that handle. Predicts.guru profile of `0xeebde7a0...` reports: **$673,736 PnL, $85.0M total volume, 55.4% win rate, 30,530 markets, 40 open positions worth ~$15.8K, "Medium" risk** — that profile pattern is the same archetype as @bonereader (high-frequency BTC micro-grinder) but on a different wallet. Possible explanations:

1. Same operator running parallel wallets (common to split capital, evade rate limits, A/B strategies).
2. Copycat trader using the lookalike handle for credibility.
3. Migration to a new wallet after fee regime change (see Section 4).

None of the public articles directly name `0xeebde7a0...`. All the "Bonereader" press is about the older wallet. **Treat strategy notes below as transferring to the @bonereaper wallet by inference, not by direct attribution.**

---

## 1. What is publicly claimed about the trading style

Consistent across Cointrenches, Substack (Polymarket Whale Watchers / Eli Brown), Senal's X post, and predicts.guru:

- Markets: almost exclusively **BTC 5-minute** and **BTC 15-minute Up/Down** binaries. Some ETH and one SOL position mentioned on `0xeebde7a0...`.
- Trade count: tens of thousands of resolved positions; @bonereader averaged ~652 resolved positions/day. @bonereaper: 30,530 markets cumulative (lower volume because it joined later).
- Position size: small (sub-$300 typical for @bonereader), open exposure at any moment tiny (@bonereader ~$16.77 of open positions cited, meaning positions resolve almost immediately and capital recycles fast).
- "Zombie bot" origin story: @bonereader was reportedly left running on a cheap VPS and printed $330K over two months "without human input" before its creator scaled it. This is from a paywalled Substack — single-source, anecdotal, plausibly embellished.
- April 2026 monthly P&L for @bonereader: +$614,057 on $3.886M volume; #2 on Polymarket's crypto monthly leaderboard.

## 2. Public claims about HOW it gets edge

No source has a screenshot of source code or a thread from the operator themselves. All "how" claims are **inferred by third-party analysts**, not stated by Bonereader. The dominant inferred narrative:

> **Latency arbitrage** between Polymarket's binary price and live BTC spot on Binance/Coinbase.

Mechanism as written up:

- Binance/Coinbase WebSocket spot updates land in ~milliseconds.
- Chainlink BTC/USD price feed (which Polymarket uses for resolution and that the implicit oracle drives) updates roughly every 10–30 s, or on a 0.5% deviation trigger, with ~0.3–0.5 s on-chain propagation.
- Between the exchange tick and Polymarket order-book re-pricing there is a window where the binary is mispriced relative to the (about-to-be-realized) outcome. Reported reaction time of human/slow-bot order book on Polymarket is ~55 s; a low-latency bot owns this window.
- Inferred net edge for @bonereader: ~4.8% per trade (back-computed from $614K / $3.886M monthly).

Other strategies named in the "4 strategies" Medium piece (not specifically tied to Bonereader): AMM-style maker provision, AI/news arbitrage, correlation arb across linked markets, HFT momentum trading. The Yahoo Finance piece names other operators (Igor Mikerin profile of a $2.2M/2-month bot; "Dexter's Lab" highlighting $313 → $414K bot; "0xEthan" on thin-book front-running). None of those name Bonereader.

## 3. Direct quotes / primary-source content from the operator

**I found none.** Specifically:

- No Twitter/X account belonging to the operator. `@BoneReader` on X exists but is "Ms. Margo," a Chippewa Native/Aztec psychic — unrelated.
- No Reddit thread where the operator self-identifies.
- No GitHub repo attributable to the operator (multiple unrelated repos exist that claim to *replicate* Bonereader-style strategies: `aulekator/Polymarket-BTC-15-Minute-Trading-Bot`, `JonathanPetersonn/oracle-lag-sniper`, `ThinkEnigmatic/polymarket-bot-arena`, `ent0n29/polybot`, `FrondEnt/PolymarketBTC15mAssistant`, `MrFadiAi/Polymarket-bot`. None named or endorsed by Bonereader; quality and authenticity not vetted here.).
- Coverage is wholly third-party — chain-watching analysts (`SenalHQ` on X, `polymarketanalytics.com`, `predicts.guru`, the "Polymarket Whale Watchers" Substack, Cointrenches blog).

All "how Bonereader works" content is **outside-in inference from on-chain trade timestamps**, not testimony.

## 4. Are these markets beatable? Public consensus (skeptical read)

**Yes, historically — but a regime change happened.** From financemagnates and the KuCoin/TradingView/Cointelegraph mentions:

- Polymarket introduced a **dynamic taker fee** on 15-minute crypto markets (and according to multiple sources, similar logic is hitting 5m markets). Fee is highest near 50/50 odds — i.e. exactly where pure latency arb lives — peaking around **~3.15% on a $0.50 contract**.
- Fee revenue funds the **Maker Rebates Program** (~20% rebate in crypto markets, paid daily in USDC, $1 min payout). This explicitly transfers economic surplus from latency takers to makers.
- One Medium/Reddit thread states the previously-famous "$515K/month, 99% win rate" oracle-lag bot is now "completely obsolete because fees are now higher than the exploitable spread." Plausible directionally; the specific number unverifiable.
- The Medium piece on edges argues last-second (T-10s to T-30s) directional entries are still the highest-accuracy moment but at the cost of paying a richer price.

So the consensus is roughly:
1. Pre-fee era: pure latency taker arb worked, was crowded, and several wallets printed seven figures.
2. Post-fee era: the surviving edge has shifted to **liquidity provision capturing maker rebates**, plus refined last-second directional/Monte-Carlo bets entered with tight execution. Pure cross-venue taker arb is reportedly dead at retail scale, though large/colo'd operators may still skim.
3. Order flow toxicity: an HFT bot ecosystem now anchors order flow in these binaries; manual/retail flow likely faces adverse selection. (Asserted in multiple Mediums, not measured rigorously in any public study I found.)

## 5. Data on oracle delay, MM behavior, order flow toxicity

- **Oracle / Chainlink mechanics**: Chainlink Data Streams now power Polymarket's 5-minute settlement (BlockEden forum post, theblock.co coverage). Heartbeat ~10–30 s, deviation trigger ~0.5%. Snapshot resolution at exact end timestamp.
- **Real-time data socket**: Polymarket publishes an RTDS crypto-prices feed (docs.polymarket.com) — i.e. the platform itself standardized fast price access, partly democratizing what was previously a latency edge.
- **Maker rebate program**: docs.polymarket.com and help.polymarket.com pages confirm category-tiered rebates (crypto 20%, sports/politics 25%, finance up to 50%) proportional to your share of maker volume per market.
- **No academic / rigorous toxicity study** surfaced. Everything on "order flow toxicity" in these markets is Medium-blog speculation.

## 6. Bottom line for your trading question

What I would actually trust:
1. The wallet at `0xeebde7a0...` is real, is "@bonereaper," and is a high-frequency BTC micro-grinder with ~$674K cumulative PnL on ~$85M turnover and a ~55.4% win rate. That's a thin but real per-trade edge multiplied by massive throughput. Source: predicts.guru directly reading on-chain.
2. The naming overlap with the more famous "@bonereader" (`0xd84c2b6d...`) is either a deliberate sibling/copycat operation or noise. **Do not assume `0xeebde7a0...` is the wallet the Substack/Cointrenches stories are about** — they aren't.
3. The publicly *claimed* edge — latency arb vs. Binance/Coinbase with Chainlink as the slow leg — is structurally plausible and matches the trade cadence, but is **inferred, not confirmed**, and the post-fee environment specifically targets this strategy with fees that frequently exceed the historic spread.
4. Going forward, public consensus says the surviving edges are: maker-rebate-funded passive quoting, last-30-second directional with calibrated Monte-Carlo, and cross-market correlation arbitrage. The "easy" lap-Chainlink-by-300ms trade is widely declared obsolete; whether @bonereaper's still-positive 2026 PnL contradicts that is unknown without bucketing the trades by date relative to the fee rollout.

## 7. Caveats / null results

- No primary-source statement from the operator anywhere.
- No verified screenshots of code or signals.
- All P&L figures sourced from third-party on-chain dashboards (polymarketanalytics.com, predicts.guru, Polymarket's own leaderboard). These agree well enough on the headline numbers.
- The two large narrative pieces (Cointrenches; "Zombie Bot $330K" Substack) read like content-marketing built around on-chain stats; treat color commentary as flavor, not fact.
- No mention in any source I found of `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` specifically other than as the @bonereaper profile on Polymarket itself and predicts.guru.

## 8. Sources

Primary / on-chain:
- Polymarket profile (bonereaper, your address): https://polymarket.com/profile/0xeebde7a0e019a63e6b476eb425505b7b3e6eba30
- Polymarket profile (bonereader, the famous one): https://polymarket.com/@bonereader
- predicts.guru on `0xeebde7a0...`: https://www.predicts.guru/checker/0xeebde7a0e019a63e6b476eb425505b7b3e6eba30
- predicts.guru on `0xd84c2b6d...`: https://www.predicts.guru/checker/0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9
- polymarketanalytics.com: https://polymarketanalytics.com/traders/0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9
- Senal X post citing bonereader: https://x.com/SenalHQ/status/2025544286037742018

Strategy / commentary (treat with skepticism):
- Cointrenches profile: https://cointrenches.io/bonereader-polymarket-crypto-micro-bot-profile/
- Substack ($330K Zombie, paywalled): https://polymarketwhalewatchers.substack.com/p/the-330k-zombie-why-bonereader-refused
- Medium "Unlocking Edges in 5-Minute Crypto" (Benjamin-Cup): https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196
- Medium "MIT quant 0.3s loophole" (promotes MidasAI tool): https://medium.com/coinmonks/an-mit-quant-found-a-0-3-second-loophole-in-prediction-markets-and-built-a-bot-to-exploit-it-dd95b0bfa457
- Medium "4 Polymarket strategies bots use": https://medium.com/illumination/beyond-simple-arbitrage-4-polymarket-strategies-bots-actually-profit-from-in-2026-ddacc92c5b4f
- QuantVPS Binance-to-Polymarket arb writeup: https://www.quantvps.com/blog/binance-to-polymarket-arbitrage-strategies
- Yahoo/Finance Magnates "Arbitrage bots dominate Polymarket": https://finance.yahoo.com/news/arbitrage-bots-dominate-polymarket-millions-100000888.html

Fee / oracle structure (primary docs and reporting):
- Polymarket Maker Rebates: https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program
- Polymarket RTDS crypto prices: https://docs.polymarket.com/developers/RTDS/RTDS-crypto-prices
- Finance Magnates on dynamic taker fees killing latency arb: https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/
- Chainlink Data Streams powering 5-min settlement: https://blockeden.xyz/forum/t/deep-dive-how-chainlink-data-streams-power-polymarkets-5-minute-settlement-oracle-architecture-for-high-frequency-prediction-markets/786
- The Block on Polymarket adopting Chainlink: https://www.theblock.co/post/370444/polymarket-turns-to-chainlink-oracles-for-resolution-of-price-focused-bets

Bot code (not vetted, not endorsed by Bonereader):
- aulekator/Polymarket-BTC-15-Minute-Trading-Bot: https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot
- JonathanPetersonn/oracle-lag-sniper: https://github.com/JonathanPetersonn/oracle-lag-sniper
- ThinkEnigmatic/polymarket-bot-arena: https://github.com/ThinkEnigmatic/polymarket-bot-arena
- Archetapp gist (5-min bot): https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69
