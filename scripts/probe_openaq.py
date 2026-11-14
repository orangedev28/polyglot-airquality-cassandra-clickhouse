"""Inspect OpenAQ data coverage for a country before downloading.
Reads metadata only (/v3/locations), costing ~1–3 API calls. Never prints the API key.
Run: python scripts/probe_openaq.py --iso VN
"""
import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

ALLOWED = {"pm25", "pm10", "no2", "o3", "so2", "co"}


def utc(obj, field):
    raw = (obj.get(field) or {}).get("utc")
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--iso", default="VN")
    p.add_argument("--days", type=int, default=365)
    a = p.parse_args()
    key = os.getenv("OPENAQ_API_KEY", "")
    if not key or key == "PASTE_YOUR_KEY_HERE":
        sys.exit("Missing OPENAQ_API_KEY in .env")

    locs, page = [], 1
    while True:
        r = requests.get(
            "https://api.openaq.org/v3/locations",
            headers={"X-API-Key": key},
            params={"iso": a.iso, "limit": 1000, "page": page},
            timeout=60,
        )
        r.raise_for_status()
        if page == 1:
            print("Remaining rate limit this minute:", r.headers.get("x-ratelimit-remaining"))
        batch = r.json().get("results", [])
        locs += batch
        if len(batch) < 1000:
            break
        page += 1
        time.sleep(1.05)

    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    active = [l for l in locs if (utc(l, "datetimeLast") or cutoff - timedelta(1)) >= cutoff]
    print(f"\nTotal {a.iso} locations: {len(locs)} | active within last {a.days} days: {len(active)}")
    print("Reference monitors (isMonitor) / low-cost sensors:",
          sum(1 for l in active if l.get("isMonitor")), "/", sum(1 for l in active if not l.get("isMonitor")))
    print("By provider:", dict(Counter((l.get("provider") or {}).get("name", "?") for l in active).most_common(8)))
    print("By locality (city):", dict(Counter(l.get("locality") or "(empty → country name)" for l in active).most_common(10)))

    sensors = [(l, s) for l in active for s in (l.get("sensors") or [])
               if ((s.get("parameter") or {}).get("name", "").lower() in ALLOWED)]
    print(f"Sensors in the 6 allowed parameters across active locations: {len(sensors)}")
    print("By parameter:", dict(Counter(s["parameter"]["name"].lower() for _, s in sensors)))

    print("\n15 most recently updated locations:")
    for l in sorted(active, key=lambda x: utc(x, "datetimeLast"), reverse=True)[:15]:
        first, last = utc(l, "datetimeFirst"), utc(l, "datetimeLast")
        n = sum(1 for s in (l.get("sensors") or []) if (s.get("parameter") or {}).get("name", "").lower() in ALLOWED)
        print(f"  {l['id']:>9} | {(l.get('name') or '')[:32]:<32} | {(l.get('locality') or '-')[:14]:<14} | "
              f"{n} sensors | {first.date() if first else '?'} → {last.date() if last else '?'}")


if __name__ == "__main__":
    main()
