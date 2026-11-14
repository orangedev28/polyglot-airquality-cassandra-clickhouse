"""Read a normalized air-quality CSV and dual-write batches to Cassandra and ClickHouse."""

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import DatabaseWriter


def rows(path):
    required = {
        "location_id", "station_name", "sensor_id", "parameter", "unit",
        "measured_at", "value", "latitude", "longitude", "city", "source",
    }
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        missing = required - set(rd.fieldnames or [])
        if missing:
            raise ValueError(f"Missing CSV columns: {missing}")
        for r in rd:
            if not r["value"]:
                continue
            try:
                r["location_id"] = int(r["location_id"])
                r["sensor_id"] = int(r["sensor_id"])
                r["value"] = float(r["value"])
                r["latitude"] = float(r["latitude"] or 0)
                r["longitude"] = float(r["longitude"] or 0)
                r["measured_at"] = datetime.fromisoformat(r["measured_at"].replace("Z", "+00:00"))
                yield r
            except (ValueError, TypeError):
                continue


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True)
    p.add_argument("--batch-size", type=int, default=500)
    a = p.parse_args()

    db = DatabaseWriter()
    batch = []
    total = 0
    t = time.perf_counter()
    try:
        for r in rows(a.file):
            batch.append(r)
            if len(batch) >= a.batch_size:
                db.insert_batch(batch)
                total += len(batch)
                batch = []
                print(f"Ingested {total} rows")
        if batch:
            db.insert_batch(batch)
            total += len(batch)
    finally:
        db.close()

    elapsed = time.perf_counter() - t
    rate = total / elapsed if elapsed else 0
    print(f"Completed {total} rows in {elapsed:.2f}s; average dual-write rate {rate:.1f} rows/s")


if __name__ == "__main__":
    main()
