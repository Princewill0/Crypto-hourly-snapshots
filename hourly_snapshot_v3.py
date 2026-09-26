"""
hourly_snapshot_v3.py

CORRECTED VERSION. Unlike the earlier fixed-universe approach, this pulls
the CURRENT top N assets by market cap fresh on every single run - so if
a coin's market cap grows into the top 2500 between one hour and the next,
it starts appearing; if a coin falls out of the top 2500 (or gets delisted
entirely), it simply stops appearing in new rows. Past hours' rows for
that asset are never touched or deleted, so its full history up to the
point it dropped out stays intact in the file - that's what "preserve
assets that enter, exit, or become delisted" means in practice: the
data itself shows the entering/exiting, rather than the pipeline forcing
a fixed guest list.

This also removes the earlier universe.csv duplicate-pagination bug, since
there's no longer a separately-built, separately-queried universe file -
everything comes straight from one live ranked pull each run, with a
safety de-dupe applied before saving regardless.

Requirements:
    pip install requests pandas

Usage (run this exact command every hour, same as before):
    python hourly_snapshot_v3.py --n 2500 --out crypto_hourly_snapshots.csv
"""

import argparse
import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone

BASE = "https://api.coingecko.com/api/v3"
PER_PAGE = 250

FIELDS = [
    "timestamp_utc", "asset_id", "symbol", "name", "source_rank",
    "price_usd", "market_cap_usd", "volume_24h_usd",
    "high_24h_usd", "low_24h_usd", "ath_usd", "atl_usd", "circulating_supply",
]


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


def current_hour_utc():
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")


def fetch_current_top_n(n):
    """Pull the CURRENT top n assets by market cap, live, this run."""
    rows = []
    pages = (n // PER_PAGE) + 1
    for page in range(1, pages + 1):
        data = safe_get(f"{BASE}/coins/markets", {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": PER_PAGE,
            "page": page,
            "sparkline": "false",
        })
        if not data:
            break
        rows.extend(data)
        time.sleep(2)
        if len(rows) >= n:
            break
    return rows[:n]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=2500)
    parser.add_argument("--out", default="crypto_hourly_snapshots.csv")
    args = parser.parse_args()

    timestamp = current_hour_utc()
    print(f"Fetching current top {args.n} by market cap for {timestamp}...")
    raw = fetch_current_top_n(args.n)
    print(f"Got {len(raw)} assets.")

    rows = []
    for c in raw:
        rows.append({
            "timestamp_utc": timestamp,
            "asset_id": c.get("id"),
            "symbol": c.get("symbol"),
            "name": c.get("name"),
            "source_rank": c.get("market_cap_rank"),
            "price_usd": c.get("current_price"),
            "market_cap_usd": c.get("market_cap"),
            "volume_24h_usd": c.get("total_volume"),
            "high_24h_usd": c.get("high_24h"),
            "low_24h_usd": c.get("low_24h"),
            "ath_usd": c.get("ath"),
            "atl_usd": c.get("atl"),
            "circulating_supply": c.get("circulating_supply"),
        })

    df = pd.DataFrame(rows, columns=FIELDS)
    # safety de-dupe within this run, in case of pagination overlap
    df = df.drop_duplicates(subset=["asset_id"], keep="first")

    # skip if this exact hour was already written (e.g. accidental re-run)
    if os.path.exists(args.out):
        existing = pd.read_csv(args.out, usecols=["timestamp_utc"])
        if (existing["timestamp_utc"] == timestamp).any():
            print(f"{timestamp} already present in {args.out} - skipping to avoid duplicates.")
            return

    file_exists = os.path.exists(args.out)
    df.to_csv(args.out, mode="a", header=not file_exists, index=False)
    print(f"Appended {len(df)} rows for {timestamp} to {args.out}")


if __name__ == "__main__":
    main()
