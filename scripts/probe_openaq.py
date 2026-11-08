"""Khảo sát phạm vi dữ liệu OpenAQ của một quốc gia trước khi tải.
Chỉ đọc metadata (/v3/locations), tốn khoảng 1–3 lời gọi API. Không in API key.
Chạy: python scripts/probe_openaq.py --iso VN
"""
import argparse, os, sys, time
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
        sys.exit("Thiếu OPENAQ_API_KEY trong .env")

    locs, page = [], 1
    while True:
        r = requests.get("https://api.openaq.org/v3/locations", headers={"X-API-Key": key},
                         params={"iso": a.iso, "limit": 1000, "page": page}, timeout=60)
        r.raise_for_status()
        if page == 1:
            print("Hạn mức còn lại trong phút này:", r.headers.get("x-ratelimit-remaining"))
        batch = r.json().get("results", [])
        locs += batch
        if len(batch) < 1000: break
        page += 1; time.sleep(1.05)

    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    active = [l for l in locs if (utc(l, "datetimeLast") or cutoff - timedelta(1)) >= cutoff]
    print(f"\nTổng location {a.iso}: {len(locs)} | còn dữ liệu trong {a.days} ngày gần nhất: {len(active)}")
    print("Trạm tham chiếu (isMonitor) / cảm biến giá rẻ:",
          sum(1 for l in active if l.get("isMonitor")), "/", sum(1 for l in active if not l.get("isMonitor")))
    print("Theo nhà cung cấp:", dict(Counter((l.get("provider") or {}).get("name", "?") for l in active).most_common(8)))
    print("Theo locality (city):", dict(Counter(l.get("locality") or "(trống → tên quốc gia)" for l in active).most_common(10)))

    sensors = [(l, s) for l in active for s in (l.get("sensors") or [])
               if ((s.get("parameter") or {}).get("name", "").lower() in ALLOWED)]
    print(f"Cảm biến thuộc 6 chỉ số trong các location còn hoạt động: {len(sensors)}")
    print("Theo chỉ số:", dict(Counter(s["parameter"]["name"].lower() for _, s in sensors)))

    print("\n15 location cập nhật gần nhất:")
    for l in sorted(active, key=lambda x: utc(x, "datetimeLast"), reverse=True)[:15]:
        first, last = utc(l, "datetimeFirst"), utc(l, "datetimeLast")
        n = sum(1 for s in (l.get("sensors") or []) if (s.get("parameter") or {}).get("name", "").lower() in ALLOWED)
        print(f"  {l['id']:>9} | {(l.get('name') or '')[:32]:<32} | {(l.get('locality') or '-')[:14]:<14} | "
              f"{n} cảm biến | {first.date() if first else '?'} → {last.date() if last else '?'}")

if __name__ == "__main__":
    main()
