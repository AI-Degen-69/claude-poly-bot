#!/usr/bin/env python3
"""Fetch all Bonereaper trades, positions, and activity from Polymarket APIs."""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ADDR = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
OUT = Path(__file__).resolve().parent / "bonereader_raw"
OUT.mkdir(parents=True, exist_ok=True)

def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            print(f"HTTPError {e.code} on {url}, retry {i+1}")
            time.sleep(2)
        except Exception as e:
            print(f"Error {e} on {url}, retry {i+1}")
            time.sleep(2)
    return None

def paginate(base, key="offset", page=500, max_pages=200, label="trades"):
    """Paginate with offset."""
    all_items = []
    for p in range(max_pages):
        offset = p * page
        url = f"{base}&{key}={offset}&limit={page}"
        data = fetch(url)
        if not data:
            print(f"  page {p}: empty/none, stopping")
            break
        if isinstance(data, list):
            n = len(data)
        else:
            print(f"  page {p}: unexpected type {type(data)}")
            break
        all_items.extend(data)
        print(f"  page {p} offset={offset}: {n} items (total={len(all_items)})")
        if n < page:
            break
        time.sleep(0.15)
    return all_items

print(f"[1/3] Fetching all trades for {ADDR}")
trades = paginate(f"https://data-api.polymarket.com/trades?user={ADDR}", page=500, max_pages=400, label="trades")
print(f"Total trades: {len(trades)}")
(OUT / "trades_all.json").write_text(json.dumps(trades))

print(f"[2/3] Fetching positions")
positions = paginate(f"https://data-api.polymarket.com/positions?user={ADDR}", page=500, max_pages=50, label="positions")
print(f"Total positions: {len(positions)}")
(OUT / "positions_all.json").write_text(json.dumps(positions))

print(f"[3/3] Fetching activity")
activity = paginate(f"https://data-api.polymarket.com/activity?user={ADDR}", page=500, max_pages=400, label="activity")
print(f"Total activity: {len(activity)}")
(OUT / "activity_all.json").write_text(json.dumps(activity))

# value
val = fetch(f"https://data-api.polymarket.com/value?user={ADDR}")
(OUT / "value.json").write_text(json.dumps(val))
print(f"Value: {val}")

print("DONE")
