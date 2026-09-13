"""
hourly_snapshot.py

STEP 2 of 2. Run this once per hour, every hour, for 7 days straight
(168 runs total) - ideally via Windows Task Scheduler so you don't have to
manually trigger it around the clock (see setup notes provided separately).

Each run takes one "point-in-time" snapshot of every asset in universe.csv
(the fixed list built by build_universe.py) and appends one row per asset
to the output CSV, tagged with the current UTC hour.

Rules this script follows, matching what was requested:
    - Universe is FIXED (read from universe.csv) - never re-ranked mid-week.
    - If an asset has no data this hour (delisted, temporarily unavailable),
      it still gets a row - with BLANK values, never zero.
    - Numbers are written exactly as the API returns them - no rounding.
    - No derived/calculated columns (no velocity, no % change) are added.
    - Checks the output file before writing, so running this twice in the
      same hour never creates duplicate asset_id + timestamp_utc rows.

Requirements:
    pip install requests pandas

Usage (run this exact command every hour, on the hour):
    python hourly_snapshot.py --universe universe.csv --out crypto_hourly_snapshots.csv
"""

import argparse
import os
import time
import requests
import pandas as pd
from datetime import datetime, timezone

BASE = "https://api.coingecko.com/api/v3"
BATCH_SIZE = 250

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


def already_have(out_path, timestamp):
    if not os.path.exists(out_path):
        return set()
    try:
        existing = pd.read_csv(out_path, usecols=["asset_id", "timestamp_utc"])
        return set(existing.loc[existing["timestamp_utc"] == timestamp, "asset_id"])
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", default="universe.csv")
    parser.add_argument("--out", default="crypto_hourly_snapshots.csv")
    args = parser.parse_args()

    universe = pd.read_csv(args.universe)
    all_ids = universe["asset_id"].tolist()
    timestamp = current_hour_utc()

    done_ids = already_have(args.out, timestamp)
    if done_ids:
        print(f"{len(done_ids)} assets already captured for {timestamp}, skipping those.")

    remaining = [a for a in all_ids if a not in done_ids]
    if not remaining:
        print(f"Nothing to do - {timestamp} is already fully captured.")
        return
    print(f"Snapshot for {timestamp}: {len(remaining)} assets to fetch.")

    found_data = {}
    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i + BATCH_SIZE]
        data = safe_get(f"{BASE}/coins/markets", {
            "vs_currency": "usd",
            "ids": ",".join(batch),
            "per_page": BATCH_SIZE,
            "page": 1,
            "sparkline": "false",
        })
        if data:
            for c in data:
                found_data[c["id"]] = c
        print(f"  batch {i // BATCH_SIZE + 1}: got {len(data) if data else 0} of {len(batch)}")
        time.sleep(2)

    rows = []
    for _, u in universe[universe["asset_id"].isin(remaining)].iterrows():
        c = found_data.get(u["asset_id"])
        rows.append({
            "timestamp_utc": timestamp,
            "asset_id": u["asset_id"],
            "symbol": u["symbol"],
            "name": u["name"],
            "source_rank": c.get("market_cap_rank") if c else None,
            "price_usd": c.get("current_price") if c else None,
            "market_cap_usd": c.get("market_cap") if c else None,
            "volume_24h_usd": c.get("total_volume") if c else None,
            "high_24h_usd": c.get("high_24h") if c else None,
            "low_24h_usd": c.get("low_24h") if c else None,
            "ath_usd": c.get("ath") if c else None,
            "atl_usd": c.get("atl") if c else None,
            "circulating_supply": c.get("circulating_supply") if c else None,
        })

    df = pd.DataFrame(rows, columns=FIELDS)
    file_exists = os.path.exists(args.out)
    df.to_csv(args.out, mode="a", header=not file_exists, index=False)
    print(f"Appended {len(df)} rows for {timestamp} to {args.out}")


if __name__ == "__main__":
    main()
