#!/usr/bin/env python3
"""Fetch resolution data for all BTC 5-min markets the trader touched."""
import json, time, urllib.request, urllib.error
from pathlib import Path

OUT = Path(__file__).resolve().parent / "bonereader_raw"

def fetch(url, retries=2):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None

d = json.load(open(OUT / "activity_full.json"))
slugs = sorted({r['slug'] for r in d if r.get('slug','').startswith('btc-updown-5m') and r.get('type')=='TRADE'})
print(f"{len(slugs)} unique btc-5m slugs to fetch")

resolutions = {}
existing_file = OUT / "resolutions.json"
if existing_file.exists():
    resolutions = json.loads(existing_file.read_text())
    print(f"loaded {len(resolutions)} existing")

remaining = [s for s in slugs if s not in resolutions]
print(f"to fetch: {len(remaining)}")

for i, slug in enumerate(remaining):
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    data = fetch(url)
    if data and len(data) > 0:
        ev = data[0]
        mkt = (ev.get('markets') or [{}])[0]
        outcome_prices = mkt.get('outcomePrices', '["",""]')
        try:
            op = json.loads(outcome_prices)
        except:
            op = ["", ""]
        resolutions[slug] = {
            'closed': ev.get('closed'),
            'endDate': ev.get('endDate'),
            'closedTime': mkt.get('closedTime'),
            'outcomePrices': op,  # [Up, Down]
            'volume': ev.get('volume'),
            'conditionId': mkt.get('conditionId'),
            'umaEndDate': mkt.get('umaEndDate'),
        }
    else:
        resolutions[slug] = None
    if (i+1) % 50 == 0:
        print(f"  {i+1}/{len(remaining)} resolved={sum(1 for v in resolutions.values() if v)}")
        (OUT / "resolutions.json").write_text(json.dumps(resolutions))
    time.sleep(0.05)

(OUT / "resolutions.json").write_text(json.dumps(resolutions))
print(f"DONE. Total resolutions: {len(resolutions)}, with data: {sum(1 for v in resolutions.values() if v)}")
