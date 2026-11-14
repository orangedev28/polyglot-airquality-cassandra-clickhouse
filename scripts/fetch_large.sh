#!/bin/zsh
# Fetch the large multi-country dataset (VN + TH + KH) sequentially, staying within OpenAQ rate limits (60/min, 2,000/hr).
# Estimated max ~1,600 API calls (~35 minutes). Fails fast if any country errors out (e.g., HTTP 429).
# Run from the project root with .venv activated:   zsh scripts/fetch_large.sh
set -e
set -o pipefail
START=$(date +%s)

run () {   # $1 = country ISO code, $2 = scan-locations, $3 = max-sensors
  echo "\n===== $1 | started $(date +%H:%M:%S) ====="
  python scripts/fetch_openaq.py --iso "$1" --days 365 --scan-locations "$2" \
    --max-sensors "$3" --pages-per-sensor 10 --out "data/large_$1.csv" 2>&1 \
    | grep -v -e NotOpenSSLWarning -e "warnings.warn" | tee "results/fetch_$1.log"
}

run VN 100 43
run TH 700 100
run KH 100 16

echo "\n===== Merge and validate ====="
python - <<'EOF'
import os, pandas as pd
parts = []
for c in ["VN", "TH", "KH"]:
    d = pd.read_csv(f"data/large_{c}.csv"); print(c, len(d), "rows"); parts.append(d)
df = pd.concat(parts, ignore_index=True)
f = "data/openaq_measurements_large.csv"; df.to_csv(f, index=False)
df["measured_at"] = pd.to_datetime(df.measured_at)
print("\nTotal rows:", len(df), "| File MB:", round(os.path.getsize(f)/1e6, 1))
print("Stations:", df.location_id.nunique(), "| Sensors:", df.sensor_id.nunique())
print("Time range:", df.measured_at.min(), "->", df.measured_at.max())
print("Missing values:", df.value.isna().sum(), "| Negative values:", (df.value < 0).sum())
print("Duplicate keys:", df.duplicated(["location_id","parameter","measured_at","sensor_id"]).sum())
print("Sources:", df.source.value_counts().to_dict())
df["d"] = df.measured_at.dt.date
part = df.groupby(["location_id","parameter","d"]).size()
print("Total partitions:", len(part), "| Max rows/partition:", part.max())
print("\nUnits by parameter:"); print(df.groupby(["parameter","unit"]).size().to_string())
print("\nTop 15 cities by row count:"); print(df.city.value_counts().head(15).to_string())
EOF

echo "\nTotal elapsed time: $(( ($(date +%s) - START) / 60 )) minutes" | tee -a results/fetch_TH.log
