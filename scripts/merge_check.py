"""Gộp data/large_VN.csv, large_TH.csv, large_KH.csv thành data/openaq_measurements_large.csv và kiểm tra.
Chạy: python scripts/merge_check.py   (kết quả lưu thêm vào results/merge_check.log)
"""
import os, sys
import pandas as pd

out_lines = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); out_lines.append(s)

parts = []
for c in ["VN", "TH", "KH"]:
    f = f"data/large_{c}.csv"
    if not os.path.exists(f):
        p(f"(bỏ qua {c}: chưa có {f})"); continue
    d = pd.read_csv(f); d["country"] = c
    p(f"{c}: {len(d)} dòng | {d.sensor_id.nunique()} cảm biến | {d.location_id.nunique()} trạm")
    parts.append(d)
if not parts: sys.exit("Không có file nào để gộp")
df = pd.concat(parts, ignore_index=True)
f = "data/openaq_measurements_large.csv"
df.drop(columns="country").to_csv(f, index=False)

df["measured_at"] = pd.to_datetime(df.measured_at)
p("\nSố dòng:", len(df), "| File MB:", round(os.path.getsize(f) / 1e6, 1))
p("Trạm:", df.location_id.nunique(), "| Cảm biến:", df.sensor_id.nunique())
p("Thời gian:", df.measured_at.min(), "->", df.measured_at.max())
p("Giá trị thiếu:", df.value.isna().sum(), "| Giá trị âm:", (df.value < 0).sum())
p("Khóa trùng:", df.duplicated(["location_id", "parameter", "measured_at", "sensor_id"]).sum())
p("Nguồn:", df.source.value_counts().to_dict())
df["d"] = df.measured_at.dt.date
part = df.groupby(["location_id", "parameter", "d"]).size()
p("Số partition:", len(part), "| Dòng/partition lớn nhất:", part.max(),
  "| Số partition > 24 dòng:", int((part > 24).sum()))
p("\nĐơn vị theo chỉ số:"); p(df.groupby(["parameter", "unit"]).size().to_string())
p("\nDòng theo nước × chỉ số:"); p(df.groupby(["country", "parameter"]).size().unstack(fill_value=0).to_string())
p("\n15 city nhiều dòng nhất:"); p(df.city.value_counts().head(15).to_string())
p("\nSố city khác nhau:", df.city.nunique())
p("Số tháng (phân vùng ClickHouse):", df.measured_at.dt.strftime("%Y%m").nunique())
open("results/merge_check.log", "w", encoding="utf-8").write("\n".join(out_lines) + "\n")
