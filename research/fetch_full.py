#!/usr/bin/env python3
"""Fetch full history using activity endpoint with timestamp windowing."""
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
            if e.code in (400, 404):
                return None
            time.sleep(2)
        except Exception as e:
            print(f"err {e}"); time.sleep(2)
    return None

# Walk backwards in time using `end` parameter
all_activity = []
seen_tx = set()
end = int(time.time())  # start near now
# We know data exists from ~1777445474 (April 29) and earlier - let's go back many days
# Use end-based windowing
empty_streak = 0
iterations = 0
max_iters = 200
last_min_ts = None

while iterations < max_iters:
    url = f"https://data-api.polymarket.com/activity?user={ADDR}&limit=500&end={end}"
    data = fetch(url)
    if not data:
        print(f"iter {iterations} end={end}: no data, breaking")
        break
    new_items = 0
    min_ts = end
    for item in data:
        ts = item.get("timestamp", 0)
        tx = item.get("transactionHash", "") + "_" + str(item.get("asset", "")) + "_" + str(item.get("type", "")) + "_" + str(ts) + "_" + str(item.get("side",""))
        if tx not in seen_tx:
            seen_tx.add(tx)
            all_activity.append(item)
            new_items += 1
        if ts and ts < min_ts:
            min_ts = ts
    print(f"iter {iterations} end={end}: {len(data)} fetched, {new_items} new (total {len(all_activity)}), min_ts={min_ts}")
    if new_items == 0:
        empty_streak += 1
        if empty_streak >= 2:
            break
        end = min_ts - 1
    else:
        empty_streak = 0
        if min_ts >= end:
            end = end - 86400  # step back a day
        else:
            end = min_ts  # use min ts as new end (inclusive boundary is fine, dedupe handles overlap)
    iterations += 1
    time.sleep(0.1)
    if last_min_ts is not None and min_ts == last_min_ts:
        # stuck
        end = min_ts - 1
    last_min_ts = min_ts

print(f"Total activity records: {len(all_activity)}")
(OUT / "activity_full.json").write_text(json.dumps(all_activity))
print("saved.")
