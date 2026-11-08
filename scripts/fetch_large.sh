#!/bin/zsh
# Tải dữ liệu lớn VN + TH + KH, tuần tự, an toàn với hạn mức OpenAQ (60/phút, 2.000/giờ).
# Ước tính tối đa ~1.600 lời gọi, ~35 phút. Dừng ngay nếu một nước lỗi (ví dụ HTTP 429).
# Chạy từ thư mục project, đã bật .venv:   zsh scripts/fetch_large.sh
set -e
set -o pipefail
START=$(date +%s)

run () {   # $1 = mã nước, $2 = scan-locations, $3 = max-sensors
  echo "\n===== $1 | bắt đầu $(date +%H:%M:%S) ====="
  python scripts/fetch_openaq.py --iso "$1" --days 365 --scan-locations "$2" \
    --max-sensors "$3" --pages-per-sensor 10 --out "data/large_$1.csv" 2>&1 \
    | grep -v -e NotOpenSSLWarning -e "warnings.warn" | tee "results/fetch_$1.log"
}

run VN 100 43
run TH 700 100
run KH 100 16

echo "\n===== Gộp và kiểm tra ====="
python - <<'EOF'
import os, pandas as pd
parts = []
for c in ["VN", "TH", "KH"]:
    d = pd.read_csv(f"data/large_{c}.csv"); print(c, len(d), "dòng"); parts.append(d)
df = pd.concat(parts, ignore_index=True)
f = "data/openaq_measurements_large.csv"; df.to_csv(f, index=False)
df["measured_at"] = pd.to_datetime(df.measured_at)
print("\nSố dòng:", len(df), "| File MB:", round(os.path.getsize(f)/1e6, 1))
print("Trạm:", df.location_id.nunique(), "| Cảm biến:", df.sensor_id.nunique())
print("Thời gian:", df.measured_at.min(), "->", df.measured_at.max())
print("Giá trị thiếu:", df.value.isna().sum(), "| Giá trị âm:", (df.value < 0).sum())
print("Khóa trùng:", df.duplicated(["location_id","parameter","measured_at","sensor_id"]).sum())
print("Nguồn:", df.source.value_counts().to_dict())
df["d"] = df.measured_at.dt.date
part = df.groupby(["location_id","parameter","d"]).size()
print("Số partition:", len(part), "| Dòng/partition lớn nhất:", part.max())
print("\nĐơn vị theo chỉ số:"); print(df.groupby(["parameter","unit"]).size().to_string())
print("\n15 city nhiều dòng nhất:"); print(df.city.value_counts().head(15).to_string())
EOF

echo "\nTổng thời gian: $(( ($(date +%s) - START) / 60 )) phút" | tee -a results/fetch_TH.log
