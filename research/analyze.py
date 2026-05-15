#!/usr/bin/env python3
"""Analyze Bonereaper's BTC 5-min strategy."""
import json, statistics, datetime
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent / "bonereader_raw"
acts = json.load(open(OUT / "activity_full.json"))
res = json.load(open(OUT / "resolutions.json"))
positions = json.load(open(OUT / "positions_all.json"))
value = json.load(open(OUT / "value.json"))

print("=== DATASET ===")
ts_all = [r['timestamp'] for r in acts if r.get('timestamp')]
print(f"records: {len(acts)}")
print(f"span: {datetime.datetime.utcfromtimestamp(min(ts_all))} UTC to {datetime.datetime.utcfromtimestamp(max(ts_all))} UTC")
print(f"days: {(max(ts_all)-min(ts_all))/86400:.2f}")

# Filter BTC 5m trades
btc5m = [r for r in acts if r.get('slug','').startswith('btc-updown-5m') and r.get('type')=='TRADE']
print(f"\nBTC 5-min TRADE records: {len(btc5m)}")
slugs = {r['slug'] for r in btc5m}
print(f"unique BTC 5-min markets: {len(slugs)}")

# helper: parse slug -> market_open_ts
def slug_open(slug):
    try: return int(slug.split('-')[-1])
    except: return None

# Trade volumes
total_usdc = sum(r.get('usdcSize', 0) for r in btc5m)
total_shares = sum(r.get('size', 0) for r in btc5m)
print(f"\n=== VOLUME (BTC 5-min) ===")
print(f"total USDC volume: ${total_usdc:,.0f}")
print(f"total share volume: {total_shares:,.0f}")
print(f"avg USDC per trade: ${total_usdc/len(btc5m):.2f}")
print(f"avg shares per trade: {total_shares/len(btc5m):.1f}")

# Side bias (buy outcome distribution)
sides = Counter(r['side'] for r in btc5m)
outcomes = Counter(r['outcome'] for r in btc5m)
print(f"\n=== SIDE/OUTCOME ===")
print(f"side: {sides}")
print(f"outcome: {outcomes}")

# Buys split by outcome
buy_outcomes = Counter(r['outcome'] for r in btc5m if r['side']=='BUY')
sell_outcomes = Counter(r['outcome'] for r in btc5m if r['side']=='SELL')
print(f"BUY outcomes: {buy_outcomes}")
print(f"SELL outcomes: {sell_outcomes}")

# net directional exposure across all trades
def net_dir(r):
    # If BUY Up -> +size; BUY Down -> -size; SELL Up -> -size; SELL Down -> +size
    s = r['size']
    if r['side']=='BUY':
        return s if r['outcome']=='Up' else -s
    else:
        return -s if r['outcome']=='Up' else s
net = sum(net_dir(r) for r in btc5m)
print(f"net directional shares (up-down): {net:,.0f}")

# Entry timing relative to market open
print("\n=== ENTRY TIMING (seconds into 5-min window) ===")
sec_in = []
for r in btc5m:
    open_ts = slug_open(r['slug'])
    if open_ts:
        s = r['timestamp'] - open_ts
        if -120 <= s <= 360:  # market opens ~before slug ts? sanity bound
            sec_in.append(s)
print(f"samples: {len(sec_in)}")
print(f"min/median/mean/max: {min(sec_in)}/{statistics.median(sec_in)}/{statistics.mean(sec_in):.1f}/{max(sec_in)}")
# Histogram by 30s bins
bins = Counter()
for s in sec_in:
    b = (s // 30) * 30
    bins[b] += 1
print("Histogram (30s bins, seconds-into-window):")
for b in sorted(bins):
    pct = 100*bins[b]/len(sec_in)
    bar = '#' * int(pct/2)
    print(f"  {b:>4}-{b+30:>3}s: {bins[b]:>6} ({pct:5.1f}%) {bar}")

# Price at entry
prices = [r['price'] for r in btc5m]
print(f"\n=== ENTRY PRICE ===")
print(f"min/median/mean/max price: {min(prices):.3f}/{statistics.median(prices):.3f}/{statistics.mean(prices):.3f}/{max(prices):.3f}")
# bucketed
pbins = Counter()
for p in prices:
    pb = round(p*10)/10
    pbins[pb] += 1
print("Price distribution (0.1 bins):")
for pb in sorted(pbins):
    pct = 100*pbins[pb]/len(prices)
    print(f"  {pb:.1f}: {pbins[pb]:>6} ({pct:5.1f}%) {'#'*int(pct/2)}")

# Trade size distribution (USDC)
sizes_usdc = sorted([r.get('usdcSize',0) for r in btc5m])
print(f"\n=== TRADE SIZE (USDC notional) ===")
def pct(arr, q):
    i = int(q*len(arr)/100)
    return arr[min(i, len(arr)-1)]
for q in [10, 25, 50, 75, 90, 95, 99]:
    print(f"  p{q}: ${pct(sizes_usdc,q):.2f}")
print(f"  max: ${sizes_usdc[-1]:.2f}")
# Buckets
size_buckets = Counter()
for s in sizes_usdc:
    if s < 1: size_buckets['<$1']+=1
    elif s < 5: size_buckets['$1-5']+=1
    elif s < 20: size_buckets['$5-20']+=1
    elif s < 100: size_buckets['$20-100']+=1
    elif s < 500: size_buckets['$100-500']+=1
    else: size_buckets['$500+']+=1
print(f"size buckets: {dict(size_buckets)}")

# Trades per market - exit behavior
print(f"\n=== TRADES PER MARKET ===")
per_market = Counter(r['slug'] for r in btc5m)
trades_per = sorted(per_market.values())
print(f"avg trades/market: {sum(trades_per)/len(trades_per):.1f}")
print(f"median: {statistics.median(trades_per)}")
print(f"max: {max(trades_per)}")
# How many markets has only BUY vs has SELL
mkt_has_sell = defaultdict(lambda: {'buy': False, 'sell': False})
for r in btc5m:
    mkt_has_sell[r['slug']][r['side'].lower()] = True
has_sell_count = sum(1 for v in mkt_has_sell.values() if v['sell'])
print(f"markets with any SELL: {has_sell_count}/{len(mkt_has_sell)} ({100*has_sell_count/len(mkt_has_sell):.1f}%)")

# Concurrency: markets active per 5-min window
print(f"\n=== CONCURRENCY & FREQUENCY ===")
# Group by approximate market open (=slug timestamp)
markets_by_day = defaultdict(set)
for r in btc5m:
    day = datetime.datetime.utcfromtimestamp(r['timestamp']).strftime('%Y-%m-%d')
    markets_by_day[day].add(r['slug'])
for day in sorted(markets_by_day):
    print(f"  {day}: {len(markets_by_day[day])} markets traded")

# Trades per hour
hour_counts = Counter()
for r in btc5m:
    h = datetime.datetime.utcfromtimestamp(r['timestamp']).strftime('%Y-%m-%d %H:00')
    hour_counts[h] += 1
hours = sorted(hour_counts.values())
print(f"trades/hour: avg={sum(hours)/len(hours):.0f} med={statistics.median(hours):.0f} max={max(hours)}")

# Hour-of-day pattern (UTC)
hod = Counter()
for r in btc5m:
    h = datetime.datetime.utcfromtimestamp(r['timestamp']).hour
    hod[h] += 1
print("\nTrades by hour-of-day UTC:")
for h in range(24):
    pct_h = 100*hod[h]/len(btc5m)
    print(f"  {h:02d}: {hod[h]:>6} ({pct_h:5.2f}%) {'#'*int(pct_h)}")

# Maker vs taker: in raw activity we don't have an explicit flag but MAKER_REBATE type exists
maker_rebates = [r for r in acts if r.get('type')=='MAKER_REBATE']
print(f"\nMAKER_REBATE events in window: {len(maker_rebates)}")
# Check if any field hints at maker vs taker on trades
sample_trade = btc5m[0]
print(f"trade fields: {sorted(sample_trade.keys())}")

# === PROFITABILITY (BTC 5-min) ===
print(f"\n=== PROFITABILITY (BTC 5-min, resolved markets) ===")
# Per market: sum(buy USDC) per outcome, sum(sell USDC) per outcome
# Net shares held at close per outcome = sum(BUY size) - sum(SELL size)
# Payout = winning_shares * 1.0 (resolution price = "1" for winning outcome)
# PnL = payout + sells_received - buys_paid

mkt_pnl = {}
for slug, group in defaultdict(list).__class__.__call__(lambda: None).__class__():
    pass

# group trades by market
by_market = defaultdict(list)
for r in btc5m:
    by_market[r['slug']].append(r)

total_pnl = 0.0
total_buy_cost = 0.0
total_sell_proceeds = 0.0
total_payout = 0.0
win_count = 0
lose_count = 0
unresolved = 0
no_position = 0
mkt_results = []

for slug, trades in by_market.items():
    rd = res.get(slug)
    if not rd or not rd.get('closed') or not rd.get('outcomePrices'):
        unresolved += 1
        continue
    op = rd['outcomePrices']
    # op is [up_price, down_price] - one is "1" one is "0"
    try:
        up_res = float(op[0]); down_res = float(op[1])
    except:
        unresolved += 1
        continue
    if not ((up_res == 1.0 and down_res == 0.0) or (up_res == 0.0 and down_res == 1.0)):
        unresolved += 1
        continue
    winner = 'Up' if up_res == 1.0 else 'Down'

    # Sum buys/sells per outcome
    buy_up_shares = sum(r['size'] for r in trades if r['side']=='BUY' and r['outcome']=='Up')
    buy_down_shares = sum(r['size'] for r in trades if r['side']=='BUY' and r['outcome']=='Down')
    sell_up_shares = sum(r['size'] for r in trades if r['side']=='SELL' and r['outcome']=='Up')
    sell_down_shares = sum(r['size'] for r in trades if r['side']=='SELL' and r['outcome']=='Down')

    buy_up_usdc = sum(r.get('usdcSize',0) for r in trades if r['side']=='BUY' and r['outcome']=='Up')
    buy_down_usdc = sum(r.get('usdcSize',0) for r in trades if r['side']=='BUY' and r['outcome']=='Down')
    sell_up_usdc = sum(r.get('usdcSize',0) for r in trades if r['side']=='SELL' and r['outcome']=='Up')
    sell_down_usdc = sum(r.get('usdcSize',0) for r in trades if r['side']=='SELL' and r['outcome']=='Down')

    held_up = buy_up_shares - sell_up_shares
    held_down = buy_down_shares - sell_down_shares
    # Payout: each held share of winner pays $1
    payout_up = max(0, held_up) * (1 if winner=='Up' else 0)
    payout_down = max(0, held_down) * (1 if winner=='Down' else 0)
    payout = payout_up + payout_down

    cost = buy_up_usdc + buy_down_usdc - sell_up_usdc - sell_down_usdc
    pnl = payout - cost
    total_pnl += pnl
    total_buy_cost += buy_up_usdc + buy_down_usdc
    total_sell_proceeds += sell_up_usdc + sell_down_usdc
    total_payout += payout

    if held_up < 0.1 and held_down < 0.1:
        no_position += 1
    else:
        if pnl > 0: win_count += 1
        else: lose_count += 1

    mkt_results.append({
        'slug': slug, 'winner': winner, 'pnl': pnl,
        'held_up': held_up, 'held_down': held_down,
        'cost': cost, 'payout': payout,
        'n_trades': len(trades),
    })

print(f"resolved markets analyzed: {len(mkt_results)}")
print(f"unresolved/skipped: {unresolved}")
print(f"won: {win_count}, lost: {lose_count}, flat (no position held to close): {no_position}")
print(f"win rate (among held-to-close): {100*win_count/max(1,win_count+lose_count):.1f}%")
print(f"total buy cost: ${total_buy_cost:,.0f}")
print(f"total sell proceeds: ${total_sell_proceeds:,.0f}")
print(f"total payout (winning resolution): ${total_payout:,.0f}")
print(f"NET PnL (BTC 5-min): ${total_pnl:,.0f}")
print(f"PnL per market (avg): ${total_pnl/max(1,len(mkt_results)):.2f}")

# Avg pnl when won vs lost
wins_pnl = [m['pnl'] for m in mkt_results if m['pnl']>0]
loss_pnl = [m['pnl'] for m in mkt_results if m['pnl']<=0]
print(f"avg winning pnl: ${statistics.mean(wins_pnl):.2f}, n={len(wins_pnl)}")
print(f"avg losing pnl:  ${statistics.mean(loss_pnl):.2f}, n={len(loss_pnl)}")

# Net account value snapshot
print(f"\n=== ACCOUNT VALUE ===")
print(f"current portfolio value: {value}")

# Contrarian: when he enters, is the YES (Up) price below or above 0.5?
# Compute price-side weighted by USDC: did he buy "cheap" (<0.3) or "expensive" (>0.7)?
buy_price_dist = Counter()
for r in btc5m:
    if r['side']=='BUY':
        p = r['price']
        if p < 0.1: buy_price_dist['<0.10']+=1
        elif p < 0.3: buy_price_dist['0.10-0.30']+=1
        elif p < 0.5: buy_price_dist['0.30-0.50']+=1
        elif p < 0.7: buy_price_dist['0.50-0.70']+=1
        elif p < 0.9: buy_price_dist['0.70-0.90']+=1
        else: buy_price_dist['>=0.90']+=1
print(f"\nBUY price distribution: {dict(buy_price_dist)}")

# Time between trades / burst pattern
print(f"\n=== INTER-TRADE TIMING ===")
sorted_t = sorted([r['timestamp'] for r in btc5m])
gaps = [sorted_t[i+1]-sorted_t[i] for i in range(len(sorted_t)-1)]
print(f"median gap: {statistics.median(gaps)}s")
print(f"mean gap: {statistics.mean(gaps):.2f}s")
gap_bins = Counter()
for g in gaps:
    if g==0: gap_bins['0s (same sec)']+=1
    elif g<=1: gap_bins['1s']+=1
    elif g<=5: gap_bins['2-5s']+=1
    elif g<=30: gap_bins['6-30s']+=1
    else: gap_bins['>30s']+=1
print(f"inter-trade gap buckets: {dict(gap_bins)}")

# Save analysis
out_summary = {
    'span_start': datetime.datetime.utcfromtimestamp(min(ts_all)).isoformat(),
    'span_end': datetime.datetime.utcfromtimestamp(max(ts_all)).isoformat(),
    'btc_5min_trades': len(btc5m),
    'btc_5min_markets': len(slugs),
    'total_usdc_volume': total_usdc,
    'avg_usdc_per_trade': total_usdc/len(btc5m),
    'avg_shares_per_trade': total_shares/len(btc5m),
    'side_counts': dict(sides),
    'outcome_counts': dict(outcomes),
    'buy_outcome_counts': dict(buy_outcomes),
    'sell_outcome_counts': dict(sell_outcomes),
    'entry_sec_median': statistics.median(sec_in),
    'entry_sec_mean': statistics.mean(sec_in),
    'price_median': statistics.median(prices),
    'price_mean': statistics.mean(prices),
    'win_count': win_count, 'lose_count': lose_count, 'no_position': no_position,
    'win_rate': 100*win_count/max(1,win_count+lose_count),
    'total_pnl_btc5m': total_pnl,
    'total_buy_cost': total_buy_cost,
    'total_sell_proceeds': total_sell_proceeds,
    'total_payout': total_payout,
    'resolved_markets': len(mkt_results),
    'pnl_per_market_avg': total_pnl/max(1,len(mkt_results)),
    'size_buckets': dict(size_buckets),
    'gap_median_s': statistics.median(gaps),
    'gap_mean_s': statistics.mean(gaps),
    'current_portfolio_value': value,
    'btc_5min_entry_histogram_30s': {str(b): bins[b] for b in sorted(bins)},
    'buy_price_distribution': dict(buy_price_dist),
    'markets_with_sells': has_sell_count,
    'markets_total': len(mkt_has_sell),
}
(OUT.parent / "analysis_summary.json").write_text(json.dumps(out_summary, indent=2, default=str))
print(f"\nsaved summary -> {OUT.parent/'analysis_summary.json'}")
