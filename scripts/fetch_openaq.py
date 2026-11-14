"""Fetch hourly air quality measurements from the OpenAQ v3 API into a CSV file."""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv

BASE = "https://api.openaq.org/v3"
ALLOWED = {"pm25", "pm10", "no2", "o3", "so2", "co"}
COLS = [
    "location_id", "station_name", "sensor_id", "parameter", "unit",
    "measured_at", "value", "latitude", "longitude", "city", "source",
]


def api_get(path, key, params=None):
    r = requests.get(BASE + path, headers={"X-API-Key": key}, params=params or {}, timeout=45)
    if r.status_code == 429:
        raise RuntimeError("OpenAQ HTTP 429: rate limit reached; please wait and retry.")
    r.raise_for_status()
    time.sleep(1.05)  # Stay well below OpenAQ's 60 req/min limit
    return r.json()


def dt_utc(obj, field):
    raw = (obj.get(field) or {}).get("utc")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def get_locations(key, iso, scan):
    items, page = [], 1
    while len(items) < scan:
        payload = api_get("/locations", key, {
            "iso": iso, "limit": 100, "page": page,
            "order_by": "id", "sort_order": "desc",
        })
        batch = payload.get("results", [])
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    items = items[:scan]
    items.sort(key=lambda x: dt_utc(x, "datetimeLast") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items


def discover(key, locations, cutoff, max_sensors):
    selected, checked = [], 0
    for loc in locations:
        if len(selected) >= max_sensors:
            break
        last = dt_utc(loc, "datetimeLast")
        if last and last < cutoff:
            continue
        checked += 1
        latest = api_get(f"/locations/{loc['id']}/latest", key, {
            "limit": 100, "page": 1, "datetime_min": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }).get("results", [])
        sensor_map = {int(s["id"]): s for s in (loc.get("sensors") or []) if s.get("id") is not None}
        for row in latest:
            sid, when = row.get("sensorsId"), dt_utc(row, "datetime")
            if sid is None or when is None or when < cutoff:
                continue
            sensor = sensor_map.get(int(sid))
            if not sensor:
                continue
            param = (sensor.get("parameter") or {}).get("name", "").lower()
            if param not in ALLOWED:
                continue
            selected.append((loc, sensor, when))
            print(f"  Selected {loc.get('name') or loc['id']} | sensor={sid} | {param} | latest={when.isoformat()}")
            if len(selected) >= max_sensors:
                break
    print(f"Checked {checked} locations potentially having recent data.")
    return selected


def fetch_history(key, loc, sensor, start, end, pages):
    sid = sensor["id"]
    for resource, source in (("hours", "OpenAQ-hours"), ("measurements", "OpenAQ")):
        result = []
        for page in range(1, pages + 1):
            data = api_get(f"/sensors/{sid}/{resource}", key, {
                "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": 1000, "page": page,
            }).get("results", [])
            for item in data:
                period = item.get("period") or {}
                when = dt_utc(period, "datetimeFrom")
                value = item.get("value")
                if when is None or value is None:
                    continue
                param = sensor.get("parameter") or {}
                coords = loc.get("coordinates") or {}
                country = loc.get("country") or {}
                result.append({
                    "location_id": int(loc["id"]), "station_name": loc.get("name") or str(loc["id"]),
                    "sensor_id": int(sid), "parameter": param.get("name", "unknown").lower(),
                    "unit": param.get("units", "unknown"), "measured_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "value": value, "latitude": coords.get("latitude") or 0,
                    "longitude": coords.get("longitude") or 0,
                    "city": loc.get("locality") or country.get("name") or "Unknown", "source": source,
                })
            if len(data) < 1000:
                break
        if result:
            return result
    return []


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--iso", default="VN")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--scan-locations", type=int, default=100)
    p.add_argument("--max-sensors", type=int, default=12)
    p.add_argument("--pages-per-sensor", type=int, default=4)
    p.add_argument("--out", default="data/openaq_measurements.csv")
    a = p.parse_args()
    key = os.getenv("OPENAQ_API_KEY", "")
    if not key or key == "PASTE_YOUR_KEY_HERE":
        sys.exit("Missing OPENAQ_API_KEY in .env")
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=a.days)
    print(f"Searching {a.iso} stations with measurements from {start.date()} to {end.date()}...")
    locations = get_locations(key, a.iso.upper(), a.scan_locations)
    print(f"Scanned metadata for {len(locations)} locations.")
    selected = discover(key, locations, start, a.max_sensors)
    if not selected:
        print("No sensors found with measurements in this window. Try --days 365 or another country.")
        return
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLS)
        writer.writeheader()
        for loc, sensor, _ in selected:
            rows = fetch_history(key, loc, sensor, start, end, a.pages_per_sensor)
            writer.writerows(rows)
            total += len(rows)
            print(f"  Sensor {sensor['id']}: {len(rows)} historical records")
    print(f"Completed: {total} records | {len(selected)} sensors | {out.resolve()}")
    if total == 0:
        print("Recent /latest entries exist, but historical endpoints returned empty; try increasing --days or using /measurements instead of /hours.")


if __name__ == "__main__":
    main()
