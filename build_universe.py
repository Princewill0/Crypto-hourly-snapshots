"""
build_universe.py

STEP 1 of 2. Run this ONCE, before you start hourly collection.

It locks in the list of ~2500 assets you'll track every hour for the next
7 days ("one consistent universe-building method" = current market-cap-rank
order, decided once, not re-picked fresh each hour). This is what lets you
later see an asset drop out (delisted) instead of it just quietly getting
swapped for whatever coin is now ranked #2500.

Requirements:
    pip install requests pandas

Usage:
    python build_universe.py --n 2500 --out universe.csv
"""

import argparse
import time
import requests
import pandas as pd

BASE = "https://api.coingecko.com/api/v3"


def safe_get(url, params, max_retries=6):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            wait = 10 * (attempt + 1)
            print(f"  network error ({type(e).__name__}), waiting {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"  rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        print(f"  request failed ({resp.status_code})")
        return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2500)
    parser.add_argument("--out", default="universe.csv")
    args = parser.parse_args()

    per_page = 250
    pages = (args.n // per_page) + 1
    rows = []
    for page in range(1, pages + 1):
        data = safe_get(f"{BASE}/coins/markets", {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
        })
        if not data:
            break
        for c in data:
            rows.append({
                "asset_id": c["id"],
                "symbol": c["symbol"],
                "name": c["name"],
                "initial_rank": c.get("market_cap_rank"),
            })
        print(f"page {page}: {len(data)} coins (total so far: {len(rows)})")
        time.sleep(2)
        if len(rows) >= args.n:
            break

    df = pd.DataFrame(rows[:args.n])
    df.to_csv(args.out, index=False)
    print(f"Saved {len(df)} assets to {args.out}")
    print("This file is your fixed universe - do not regenerate it mid-week,")
    print("or you'll break the 'consistent universe' requirement.")


if __name__ == "__main__":
    main()
