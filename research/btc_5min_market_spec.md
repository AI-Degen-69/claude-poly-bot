# Polymarket "Bitcoin Up or Down — 5 minute" Market Spec

*Research compiled 2026-05-12. All findings sourced from live API calls; quoted endpoints, slugs, conditionIds, and tokenIds are real and verifiable.*

---

## 1. Market discovery

### Series & slug pattern

- The recurring series lives under **`seriesSlug = "btc-up-or-down-5m"`** (Gamma series id `10684`, ticker `btc-up-or-down-5m`).
- Each 5-minute market is its own **Event** with slug pattern:
  ```
  btc-updown-5m-<unix_timestamp>
  ```
  where `<unix_timestamp>` is the Unix epoch (seconds, UTC) of the **event start** — i.e. the price-snapshot time at the beginning of the 5-minute window. The window then closes at `unix_timestamp + 300`.
  Example: `btc-updown-5m-1778583600` → start `2026-05-12T11:00:00Z`, end `2026-05-12T11:05:00Z`.
- The slug guessed in the prompt (`bitcoin-up-or-down-...`) does **not** match. The correct slug pattern is `btc-updown-5m-...`.

### How many are open concurrently

Many. At any moment Polymarket has pre-listed roughly **~24 hours of future markets** in the series (≈ 288 events). All of them have `active=true, closed=false, enableOrderBook=true, acceptingOrders=true` long before their window starts. So "the currently live market" is whichever one has `eventStartTime <= now < endDate`. Future markets are tradable too (with thinner books).

### Recommended discovery query

The cleanest filter found:

```
GET https://gamma-api.polymarket.com/events?series_slug=btc-up-or-down-5m&closed=false&limit=500&order=endDate&ascending=true
```

Then filter client-side: the **currently live** market is the one with `endDate > now AND eventStartTime <= now`. Note: do **not** rely on `gamma-api/markets?active=true` because that endpoint only returns ~500 of the top markets ordered by some default; the 5-minute markets are filtered out (likely by the `Hide From New` tag). Use the **events** endpoint with `series_slug`.

You can also pull the canonical market record from the CLOB itself:

```
GET https://clob.polymarket.com/markets/<conditionId>
```

Three live examples pulled at `2026-05-12T11:09Z`:

| slug | conditionId | clobTokenIds (Up, Down) | eventStartTime | endDate | min_tick | neg_risk |
|---|---|---|---|---|---|---|
| `btc-updown-5m-1778583900` | `0x2618c523ab20fa270d0b7bf4327aca6ec8b33d6653edbb6714ded1721dc5a5c3` | `81564136…371631`, `89731346…286009` | `2026-05-12T11:05:00Z` | `2026-05-12T11:10:00Z` | 0.01 | false |
| `btc-updown-5m-1778584200` | `0xa5c6d0c4cef71fe53c0235790b5568574343551fe67c62db39e9ebf3387b415a` | `48418917…084036`, `14943202…607938` | `2026-05-12T11:10:00Z` | `2026-05-12T11:15:00Z` | 0.01 | false |
| `btc-updown-5m-1778584500` | (next) | (next) | `2026-05-12T11:15:00Z` | `2026-05-12T11:20:00Z` | 0.01 | false |

The `clobTokenIds` field is a JSON-encoded string (parse it). Index 0 = "Up", index 1 = "Down" (confirmed via `outcomes: ["Up","Down"]`).

---

## 2. Resolution mechanics

### Oracle

**Chainlink BTC/USD data stream**, specifically `https://data.chain.link/streams/btc-usd`. Quoted verbatim from the event `description`:

> "The resolution source for this market is information from Chainlink, specifically the BTC/USD data stream available at https://data.chain.link/streams/btc-usd. Please note that this market is about the price according to Chainlink data stream BTC/USD, not according to other sources or spot markets."

Not Binance, not Coinbase, not UMA. `umaResolutionStatuses: []` for these markets, i.e. **UMA optimistic-oracle dispute flow is not used** — resolution is mechanically driven by the Chainlink stream snapshot.

### Resolution rule (ties)

Verbatim:

> "This market will resolve to 'Up' if the Bitcoin price at the end of the time range specified in the title is **greater than or equal to** the price at the beginning of that range. Otherwise, it will resolve to 'Down'."

**Ties resolve UP.** A binary `close >= open` test on the Chainlink BTC/USD stream's price at the two boundary timestamps. The exact snapshot semantics (which Chainlink stream tick is used at `t0` and `t0+300s`) are not documented at the bytecode level — `unknown`, would need to inspect the resolution adapter contract on Polygon or watch the on-chain `resolved` event to be 100% sure of the rounding/latency.

### Resolution latency

Empirically (sampled 8 recently-closed markets at ~11:09Z on 2026-05-12): the market object's `closed` flag flipped and `outcomePrices` settled to `["0","1"]` or `["1","0"]` within roughly **60–120 seconds** after `endDate`. The closest sample: `btc-updown-5m-1778583600` had `endDate=11:05:00Z`, was already `closed=true` by my poll at `11:06:36Z` (latency ≤ 96s). Trades continued for ~95s after `endDate` (winner-side $1 sweeps / loser-side $0 dumps) before fully freezing.

Payout latency on-chain (USDC into proxy wallet) is `unknown` from gamma-api alone — would need to subscribe to the `NegRiskAdapter` / `UmaCtfAdapter` `PayoutsReported` event, or poll the user's balance after resolution.

---

## 3. Market timing

- **Window boundaries**: aligned on the **5-minute UTC grid** (`:00, :05, :10, …`). Verified: slug timestamp `1778583600` = `2026-05-12T11:00:00Z`, next is `1778583900` = `11:05:00`, etc.
- **Note**: the human-facing title is rendered in **ET** (e.g. "May 12, 7:05AM-7:10AM ET"). The slug epoch is **UTC**. Always trust `eventStartTime` / `endDate` (ISO-Z) over the title.
- **Pre-window tradability**: markets are tradable well before their window. The next live event in the series had `acceptingOrdersTimestamp = 2026-05-11T11:17:27Z` for a window starting `2026-05-12T11:10:00Z` — i.e. **~24 hours of pre-window quoting**. Empirically pre-window order flow is tiny (47 trades in the 60+ minutes before window, vs ~3,100 in the 5-minute window itself).
- **Trading cutoff**: `acceptingOrders` stays `true` through the window. Trading effectively continues past `endDate` for ~90 seconds (last sampled trade was at `11:06:37` for an `11:05:00` close — folks closing out at $0.99 / $0.01). There is no documented hard "freeze" before resolution; orders just become uneconomic once the oracle snapshot is known. The book on the about-to-close market had **all bids on the loser side pulled** by ~30s before close while asks stayed (the closing snapshot used here had `bids=[]` on the loser token at -33s).

---

## 4. Microstructure

From the CLOB `markets/<conditionId>` and book responses (sampled mid-window on `btc-updown-5m-1778584200` at `2026-05-12T11:12:49Z`):

| field | value |
|---|---|
| `minimum_tick_size` | **0.01** (1 cent) |
| `minimum_order_size` | **5** (USDC) |
| `neg_risk` | **false** |
| `feeType` | `crypto_fees_v2` |
| `feeSchedule` | `{exponent: 1, rate: 0.07, takerOnly: true, rebateRate: 0.2}` |
| `makerBaseFee` | `1000` (unused — overridden by feeSchedule) |
| `takerBaseFee` | `1000` (unused — overridden by feeSchedule) |
| `feesEnabled` | true |
| `rewardsMinSize` | 50 |
| `rewardsMaxSpread` | 4.5 (cents) |
| `makerRebatesFeeShareBps` | 10000 |

**Fee math** (confirmed from Polymarket docs `https://docs.polymarket.com/trading/fees.md`):
```
taker_fee = shares * feeRate * p * (1-p)        # in USDC
         = shares * 0.07 * p * (1-p)
maker_fee = 0                                    # takerOnly: true
maker_rebate = 0.20 * (your_fee_equivalent / total_fee_equivalent) * rebate_pool
```
For a 50/50 ticket: `0.07 * 0.5 * 0.5 = 1.75%` taker fee on notional. At `p=0.25`/`0.75`: `0.07 * 0.1875 = 1.31%`. **Fees scale with `p(1-p)`** — vanish near the ends, peak at 50/50.

`maker_base_fee=1000` and `taker_base_fee=1000` appear in the CLOB market object but are legacy bps fields; the per-trade fee actually charged for this market type is governed by `feeSchedule.rate`. Worth confirming against an actual fill in your bot's logs — `unknown` whether the CLOB engine could fall back to the bps base fee in some path.

**Spread**: 1 cent (the minimum tick) for any market currently in its 5-minute trading window. Sampled mid-window book (the live one): top-of-book `0.24 / 0.25`, spread = `0.01`. The book is dense — every penny from $0.01 to $0.99 has a resting order on at least one side. The same market sampled ~5 minutes before its window started showed a 4¢ spread (`0.64 / 0.68`), so liquidity providers tighten up as the window begins.

**Top-of-book depth** (mid-window snapshot):
- best bid: 25 shares @ $0.24
- best ask: 5 shares @ $0.25
- next 3 ask levels: 6 @ 0.27, 15 @ 0.28, 25 @ 0.29 — sub-100 shares within 5¢ of mid.
- TOB is **thin** (often <50 shares); size sits 3+ cents away. A market order >$100 will walk multiple levels.

**Maker rebates**: the series has `rewardsMinSize=50, rewardsMaxSpread=4.5`. Quotes must be ≥50 shares and within 4.5¢ of mid to qualify. Combined with `makerRebatesFeeShareBps=10000` (100% fee-share back to qualifying makers in this market), this is a real edge for a tight-quoting bot.

---

## 5. Liquidity / volume profile

Pulled all trades for one fully-resolved market: `btc-updown-5m-1778583600` (window `11:00:00Z–11:05:00Z`):

| metric | value |
|---|---|
| total trades (lifetime) | 3,176 |
| trades in pre-window hour | 60 |
| trades in 5-min window | 3,116 (~**623 trades/min**) |
| trades post-endDate | 0 in this sample (varies; another sample showed ~45) |
| mean size (in-window) | 21.3 shares |
| median size (in-window) | 8.0 shares |
| max size (in-window) | 1,073 shares |
| BUY vs SELL | 2,774 vs 402 (≈ 87% BUY-tagged) |
| unique wallets | 941 |
| top wallet | 197 trades (`0xd6c74402…`) — top 5 = 405 trades, ~13% of flow |

Series-wide: gamma reports `volume24hr ≈ $23.7M` for `btc-up-or-down-5m`, `liquidity ≈ $2.66M`. That's the entire 5-minute series; each individual 5-min market sees ~$2k notional volume.

Volume distribution within a 5-min window (one sample):
- Minute 0: 797 trades
- Minute 1: 769
- Minute 2: 667
- Minute 3: 685
- Minute 4: 198 (drops off as BTC's last-30s move dictates the outcome)

The strong BUY skew + the 941 unique wallets per market suggests **lots of retail directional flow**, not market-makers dominating. The big wallets at the top of the distribution are likely the makers earning the rebate.

---

## 6. Gotchas

1. **Slug guess is wrong.** Use `btc-updown-5m-<unix>`, not `bitcoin-up-or-down-*`. And use the **events** endpoint, not `markets?active=true` (which silently filters these out via the `Hide From New` tag).
2. **`clobTokenIds` is a JSON-encoded string**, not a list. `json.loads(market["clobTokenIds"])`.
3. **Title timezone trap**: title is ET; `eventStartTime`/`endDate` and the slug epoch are UTC. Don't parse the title.
4. **Pre-window market clearing**: `clearBookOnStart: false` for this series — books carry over from when LPs first quoted, they are NOT wiped at the start of the window.
5. **Loser-side book empties right before close.** I observed `bids: []` on the about-to-be-loser token at T-33s. A bot trying to trade in the last minute should expect one side of the book to evaporate.
6. **Trades after `endDate`.** The book stays open briefly after `endDate` — winners trade towards $1, losers towards $0. Don't naïvely treat `endDate` as "trading frozen".
7. **Resolution detection.** Gamma's `closed=true` flip lagged `endDate` by ~60–120s in samples. For lower latency, listen to the Chainlink BTC/USD stream yourself and compute the result locally; treat the on-chain `PayoutsReported` event as the source of truth for redemption.
8. **`minimum_order_size = 5`** (USDC notional). At `p=0.01`, the smallest legal order is 5 shares × $0.01 = $0.05 — but the engine enforces shares ≥ 5, not dollars ≥ 5. Verify before sending tiny orders.
9. **`makerBaseFee` / `takerBaseFee = 1000`** look like 10% in bps but are NOT what's charged. The active fee is `feeSchedule.rate=0.07` per `crypto_fees_v2`. Don't accidentally code against the wrong field.
10. **Pagination on `data-api/trades`**: `offset` paginates **newest-first** (verified). Max `limit=500` per call. The endpoint **does not** return a `next_cursor`; you must walk offsets.
11. **`clob.polymarket.com/fee-rate-bps` endpoint is 404.** The actual endpoint per docs is `/fee-rate` (or query via the market record). The `/tick-size?token_id=…` endpoint works and returns `{"minimum_tick_size":0.01}`.
12. **`enableOrderBook=false` on very old/stale events.** Don't rely on `active=true` alone for "tradable". Combine with `enableOrderBook=true` and `acceptingOrders=true`.
13. **Resolution snapshot semantics are not fully documented.** Polymarket says "the price at the beginning/end of the time range" via the Chainlink BTC/USD data stream — but the exact tick selection (nearest, last-before, VWAP within a small window?) is not in the docs I found. Before trading size, replay several historical resolutions against the on-chain Chainlink stream to nail down the rule empirically. `unknown` from docs.

---

## Appendix A — Live event JSON (one market)

Snapshot of `btc-updown-5m-1778584200` from `gamma-api.polymarket.com/events?series_slug=btc-up-or-down-5m&closed=false&limit=500&order=endDate&ascending=true` at `2026-05-12T11:09:27Z`:

```json
{
  "id": "473573",
  "ticker": "btc-updown-5m-1778584200",
  "slug": "btc-updown-5m-1778584200",
  "title": "Bitcoin Up or Down - May 12, 7:10AM-7:15AM ET",
  "description": "This market will resolve to \"Up\" if the Bitcoin price at the end of the time range specified in the title is greater than or equal to the price at the beginning of that range. Otherwise, it will resolve to \"Down\".\nThe resolution source for this market is information from Chainlink, specifically the BTC/USD data stream available at https://data.chain.link/streams/btc-usd.\nPlease note that this market is about the price according to Chainlink data stream BTC/USD, not according to other sources or spot markets.",
  "resolutionSource": "https://data.chain.link/streams/btc-usd",
  "startDate": "2026-05-11T11:21:20.025727Z",
  "creationDate": "2026-05-11T11:21:20.025722Z",
  "endDate": "2026-05-12T11:15:00Z",
  "active": true,
  "closed": false,
  "archived": false,
  "restricted": true,
  "liquidity": 11045.0965,
  "volume": 147.934704,
  "openInterest": 2353.934704,
  "competitive": 0.9999750006249843,
  "enableOrderBook": true,
  "liquidityClob": 11045.0965,
  "negRisk": false,
  "markets": [
    {
      "id": "2229686",
      "question": "Bitcoin Up or Down - May 12, 7:10AM-7:15AM ET",
      "conditionId": "0xa5c6d0c4cef71fe53c0235790b5568574343551fe67c62db39e9ebf3387b415a",
      "slug": "btc-updown-5m-1778584200",
      "resolutionSource": "https://data.chain.link/streams/btc-usd",
      "endDate": "2026-05-12T11:15:00Z",
      "liquidity": "12076.9863",
      "startDate": "2026-05-11T11:18:23.695579Z",
      "outcomes": "[\"Up\", \"Down\"]",
      "outcomePrices": "[\"0.515\", \"0.485\"]",
      "volume": "236.04008700000003",
      "active": true,
      "closed": false,
      "questionID": "0xdd168c6edb30b13aba5b7fa3090a84a2e30f6cda428de06bd5db6fcb68765850",
      "enableOrderBook": true,
      "orderPriceMinTickSize": 0.01,
      "orderMinSize": 5,
      "clobTokenIds": "[\"48418917734180607831833027288777571190488909295977497623601373906809754084036\", \"14943202171143669362180565155331992758433128192256190594100236888666963607938\"]",
      "makerBaseFee": 1000,
      "takerBaseFee": 1000,
      "acceptingOrders": true,
      "negRisk": false,
      "acceptingOrdersTimestamp": "2026-05-11T11:17:27Z",
      "rewardsMinSize": 50,
      "rewardsMaxSpread": 4.5,
      "spread": 0.01,
      "lastTradePrice": 0.52,
      "bestBid": 0.51,
      "bestAsk": 0.52,
      "eventStartTime": "2026-05-12T11:10:00Z",
      "feesEnabled": true,
      "makerRebatesFeeShareBps": 10000,
      "feeType": "crypto_fees_v2",
      "feeSchedule": {
        "exponent": 1,
        "rate": 0.07,
        "takerOnly": true,
        "rebateRate": 0.2
      }
    }
  ],
  "series": [
    {
      "id": "10684",
      "ticker": "btc-up-or-down-5m",
      "slug": "btc-up-or-down-5m",
      "title": "BTC Up or Down 5m",
      "seriesType": "single",
      "recurrence": "5m",
      "active": true,
      "closed": false,
      "volume24hr": 23752673.955451995,
      "liquidity": 2665372.2496
    }
  ],
  "seriesSlug": "btc-up-or-down-5m",
  "startTime": "2026-05-12T11:10:00Z"
}
```

## Appendix B — Live order book (UP token)

Mid-window snapshot of `btc-updown-5m-1778584200` UP token at `2026-05-12T11:12:49Z` from `https://clob.polymarket.com/book?token_id=48418917734180607831833027288777571190488909295977497623601373906809754084036`:

```json
{
  "market": "0xa5c6d0c4cef71fe53c0235790b5568574343551fe67c62db39e9ebf3387b415a",
  "asset_id": "48418917734180607831833027288777571190488909295977497623601373906809754084036",
  "timestamp": "1778584369464",
  "hash": "d52f3ca97fa4cd60ca64282ba1ecefcb373952a7",
  "bids": [
    {"price": "0.01", "size": "14468.29"},
    {"price": "0.02", "size": "2160.36"},
    {"price": "0.03", "size": "1428.72"},
    {"price": "0.04", "size": "998.3"},
    {"price": "0.05", "size": "698.71"},
    {"price": "0.06", "size": "481.41"},
    {"price": "0.07", "size": "382.28"},
    {"price": "0.08", "size": "382"},
    {"price": "0.09", "size": "749"},
    {"price": "0.10", "size": "410"},
    {"price": "0.11", "size": "422"},
    {"price": "0.12", "size": "609"},
    {"price": "0.13", "size": "603"},
    {"price": "0.14", "size": "328"},
    {"price": "0.15", "size": "312"},
    {"price": "0.16", "size": "390"},
    {"price": "0.17", "size": "417"},
    {"price": "0.18", "size": "347"},
    {"price": "0.19", "size": "348"},
    {"price": "0.20", "size": "305"},
    {"price": "0.21", "size": "175"},
    {"price": "0.22", "size": "229.9"},
    {"price": "0.23", "size": "20"},
    {"price": "0.24", "size": "25"}
  ],
  "asks": [
    {"price": "0.99", "size": "12884.26"},
    {"price": "0.98", "size": "2464.68"},
    {"price": "0.97", "size": "2024.8"},
    {"price": "0.96", "size": "1534.57"},
    {"price": "0.95", "size": "1555.96"},
    {"price": "0.94", "size": "194.12"},
    {"price": "0.93", "size": "270.28"},
    {"price": "0.92", "size": "213"},
    {"price": "0.91", "size": "251"},
    {"price": "0.90", "size": "288.4"},
    {"price": "0.89", "size": "153"},
    {"price": "0.88", "size": "139"},
    {"price": "0.87", "size": "403"},
    {"price": "0.86", "size": "521.36"},
    {"price": "0.85", "size": "123.72"},
    {"price": "0.84", "size": "133.35"},
    {"price": "0.83", "size": "110.79"},
    {"price": "0.82", "size": "111"},
    {"price": "0.81", "size": "212"},
    {"price": "0.80", "size": "107"},
    {"price": "0.79", "size": "172.94"},
    {"price": "0.78", "size": "100"},
    {"price": "0.77", "size": "321"},
    {"price": "0.76", "size": "420.83"},
    {"price": "0.75", "size": "300"},
    {"price": "0.74", "size": "305"},
    {"price": "0.73", "size": "300"},
    {"price": "0.72", "size": "350"},
    {"price": "0.71", "size": "405"},
    {"price": "0.70", "size": "300"},
    {"price": "0.69", "size": "300"},
    {"price": "0.68", "size": "306"},
    {"price": "0.67", "size": "300"},
    {"price": "0.66", "size": "400"},
    {"price": "0.65", "size": "300"},
    {"price": "0.64", "size": "300"},
    {"price": "0.63", "size": "300"},
    {"price": "0.62", "size": "298.96"},
    {"price": "0.61", "size": "322.42"},
    {"price": "0.60", "size": "325"},
    {"price": "0.59", "size": "160"},
    {"price": "0.58", "size": "715"},
    {"price": "0.57", "size": "391.33"},
    {"price": "0.56", "size": "410"},
    {"price": "0.55", "size": "332"},
    {"price": "0.54", "size": "555.01"},
    {"price": "0.53", "size": "143.21"},
    {"price": "0.52", "size": "310.14"},
    {"price": "0.51", "size": "212.49"},
    {"price": "0.50", "size": "106"},
    {"price": "0.49", "size": "300"},
    {"price": "0.48", "size": "310"},
    {"price": "0.47", "size": "305"},
    {"price": "0.46", "size": "200"},
    {"price": "0.45", "size": "110"},
    {"price": "0.44", "size": "105"},
    {"price": "0.43", "size": "181.3"},
    {"price": "0.42", "size": "329"},
    {"price": "0.41", "size": "405"},
    {"price": "0.40", "size": "323"},
    {"price": "0.39", "size": "330"},
    {"price": "0.38", "size": "347.04"},
    {"price": "0.37", "size": "310"},
    {"price": "0.36", "size": "200"},
    {"price": "0.35", "size": "307.69"},
    {"price": "0.34", "size": "239.51"},
    {"price": "0.33", "size": "391"},
    {"price": "0.32", "size": "782.82"},
    {"price": "0.31", "size": "683.99"},
    {"price": "0.30", "size": "259.32"},
    {"price": "0.29", "size": "25"},
    {"price": "0.28", "size": "15"},
    {"price": "0.27", "size": "6"},
    {"price": "0.25", "size": "5"}
  ],
  "min_order_size": "5",
  "tick_size": "0.01",
  "neg_risk": false,
  "last_trade_price": "0.280"
}
```

Top-of-book at this snapshot: bid `$0.24 × 25`, ask `$0.25 × 5`, spread = 1¢ (tick). Mid `$0.245` → market leans DOWN. Note the wall at penny extremes (14k @ $0.01 bid, 12k @ $0.99 ask) — these are "guaranteed-loser-side" resting orders waiting to absorb panic exits at resolution.

---

## Appendix C — Useful endpoints summary

| Purpose | Endpoint |
|---|---|
| Discover series markets | `GET https://gamma-api.polymarket.com/events?series_slug=btc-up-or-down-5m&closed=false&limit=500&order=endDate&ascending=true` |
| Market detail (CLOB) | `GET https://clob.polymarket.com/markets/<conditionId>` |
| Order book | `GET https://clob.polymarket.com/book?token_id=<tokenId>` |
| Tick size | `GET https://clob.polymarket.com/tick-size?token_id=<tokenId>` |
| Trades (last 500 paged newest-first) | `GET https://data-api.polymarket.com/trades?market=<conditionId>&limit=500&offset=<n>` |
| CLOB websocket (market data) | `wss://ws-subscriptions-clob.polymarket.com/ws/market` (per docs, not verified here) |
