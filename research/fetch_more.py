#!/usr/bin/env python3
"""Extend activity history backwards."""
import json, time, urllib.request, urllib.error
from pathlib import Path

ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
OUT = Path(__file__).resolve().parent / "bonereader_raw"

def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): return None
            time.sleep(2)
        except Exception:
            time.sleep(2)
    return None

existing = json.load(open(OUT / "activity_full.json"))
print(f"existing: {len(existing)}")
seen_tx = set()
for item in existing:
    k = item.get("transactionHash","") + "_" + str(item.get("asset","")) + "_" + str(item.get("type","")) + "_" + str(item.get("timestamp","")) + "_" + str(item.get("side",""))
    seen_tx.add(k)
all_activity = list(existing)

# start from earliest
end = min(r['timestamp'] for r in existing if r.get('timestamp'))
print(f"resuming from end={end}")

# go back another ~5 days
target = end - 5*86400
iterations = 0
while end > target and iterations < 1500:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=500&end={end}"
    data = fetch(url)
    if not data:
        break
    new_items = 0
    min_ts = end
    for item in data:
        ts = item.get("timestamp",0)
        k = item.get("transactionHash","") + "_" + str(item.get("asset","")) + "_" + str(item.get("type","")) + "_" + str(ts) + "_" + str(item.get("side",""))
        if k not in seen_tx:
            seen_tx.add(k); all_activity.append(item); new_items += 1
        if ts and ts < min_ts: min_ts = ts
    if iterations % 20 == 0:
        print(f"iter {iterations} end={end}: new={new_items} total={len(all_activity)} min_ts={min_ts}")
    if min_ts >= end:
        end -= 3600
    else:
        end = min_ts
    if new_items == 0:
        end -= 3600
    iterations += 1
    time.sleep(0.08)

print(f"Total: {len(all_activity)}")
(OUT / "activity_full.json").write_text(json.dumps(all_activity))
print("saved.")
