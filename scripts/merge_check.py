"""Merge data/large_VN.csv, large_TH.csv, and large_KH.csv into data/openaq_measurements_large.csv and validate.
Run: python scripts/merge_check.py   (output is also saved to results/merge_check.log)
"""
import os
import sys
import pandas as pd

out_lines = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    out_lines.append(s)


parts = []
for c in ["VN", "TH", "KH"]:
    f = f"data/large_{c}.csv"
    if not os.path.exists(f):
        p(f"(skipped {c}: {f} not found)")
        continue
    d = pd.read_csv(f)
    d["country"] = c
    p(f"{c}: {len(d)} rows | {d.sensor_id.nunique()} sensors | {d.location_id.nunique()} stations")
    parts.append(d)
if not parts:
    sys.exit("No CSV files found to merge")

df = pd.concat(parts, ignore_index=True)
f = "data/openaq_measurements_large.csv"
df.drop(columns="country").to_csv(f, index=False)

df["measured_at"] = pd.to_datetime(df.measured_at)
p("\nTotal rows:", len(df), "| File MB:", round(os.path.getsize(f) / 1e6, 1))
p("Stations:", df.location_id.nunique(), "| Sensors:", df.sensor_id.nunique())
p("Time range:", df.measured_at.min(), "->", df.measured_at.max())
p("Missing values:", df.value.isna().sum(), "| Negative values:", (df.value < 0).sum())
p("Duplicate keys:", df.duplicated(["location_id", "parameter", "measured_at", "sensor_id"]).sum())
p("Sources:", df.source.value_counts().to_dict())
df["d"] = df.measured_at.dt.date
part = df.groupby(["location_id", "parameter", "d"]).size()
p("Total partitions:", len(part), "| Max rows/partition:", part.max(),
  "| Partitions > 24 rows:", int((part > 24).sum()))
p("\nUnits by parameter:")
p(df.groupby(["parameter", "unit"]).size().to_string())
p("\nRows by country x parameter:")
p(df.groupby(["country", "parameter"]).size().unstack(fill_value=0).to_string())
p("\nTop 15 cities by row count:")
p(df.city.value_counts().head(15).to_string())
p("\nDistinct cities:", df.city.nunique())
p("Distinct months (ClickHouse partitions):", df.measured_at.dt.strftime("%Y%m").nunique())
open("results/merge_check.log", "w", encoding="utf-8").write("\n".join(out_lines) + "\n")
