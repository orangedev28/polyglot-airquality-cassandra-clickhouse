# Polyglot persistence cho giám sát chất lượng không khí: Apache Cassandra + ClickHouse

Đồ án cuối kỳ môn **GCOS134 – Các hệ cơ sở dữ liệu** (HUTECH, 2026).

Nguyên mẫu kiến trúc đa hệ CSDL (polyglot persistence):

- **Apache Cassandra 5.0** – workload vận hành: tra cứu số đo theo *trạm + chỉ số + ngày*.
- **ClickHouse 25.8** – workload phân tích: tổng hợp lịch sử theo *thành phố + chỉ số + thời gian*.
- **Python** – thu thập dữ liệu OpenAQ, kiểm tra chất lượng và ghi kép (dual-write) cùng một tập sự kiện vào hai CSDL, mỗi CSDL dùng lược đồ riêng.

Hai CSDL **không** được so sánh như hai lựa chọn thay thế cho cùng một việc; mỗi hệ được đánh giá trên đúng workload mà nó phụ trách.

## Kiến trúc

```text
OpenAQ API v3 (hours) / CSV synthetic
        │
scripts/fetch_openaq.py ──► data/openaq_measurements.csv
        │
scripts/ingest_csv.py  (DatabaseWriter, ghi theo lô)
        ├──► Cassandra   air_quality.measurements_by_station_day   (vận hành)
        └──► ClickHouse  air_quality.measurements                  (phân tích)
```

Ghi kép **không phải** giao dịch phân tán nguyên tử: mỗi lô ghi Cassandra trước, ClickHouse sau.

## Dữ liệu trong repo

| Tệp | Nội dung |
|---|---|
| `data/openaq_measurements.csv` | 23.022 bản ghi OpenAQ theo giờ – 4 trạm, 12 cảm biến, 5 chỉ số (pm25, pm10, no2, so2, o3), 2026-08-02 → 2026-10-31 (UTC), `source = OpenAQ-hours` |
| `data/sample_synthetic.csv` | 240 bản ghi **mô phỏng** – 2 trạm (1001, 1002), `source = SYNTHETIC_SAMPLE`, chỉ dùng kiểm thử luồng |
| `results/benchmark.csv` | Lần đo A: 20 lần chạy |
| `results/benchmark_openaq.csv` | Lần đo B: 50 lần chạy |

Mọi phân tích dữ liệu thật phải lọc `source = 'OpenAQ-hours'`.

## Yêu cầu

- Docker Desktop (hoặc Docker Engine + Compose).
- Python 3.9 trở lên (đã chạy thực tế với Python 3.9.6 trên macOS).
- RAM khuyến nghị ≥ 8 GB. Cassandra được cố định heap 1 GB (`MAX_HEAP_SIZE`) trong `docker-compose.yml`.

## 1. Khởi động hai CSDL

```bash
docker compose up -d
docker compose ps                      # chờ cả hai container ở trạng thái healthy
docker exec -it aq-cassandra cqlsh -e "DESCRIBE KEYSPACES"
docker exec -it aq-clickhouse clickhouse-client --query "SELECT 1"
```

## 2. Cài môi trường Python

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                   # điền OPENAQ_API_KEY của bạn vào .env
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

> `.env` chứa API key và đã được loại khỏi Git qua `.gitignore`. Không chia sẻ tệp này.

## 3. Lược đồ

Lược đồ nằm trong `sql/cassandra_schema.cql` và `sql/clickhouse_schema.sql`. `app/database.py` cũng tự tạo keyspace/database và bảng nếu chưa có, nên có thể bỏ qua bước tạo thủ công.

- Cassandra: `PRIMARY KEY ((location_id, parameter, measurement_date), measured_at, sensor_id)`, `CLUSTERING ORDER BY (measured_at DESC)`. `measurement_date` là **ngày UTC**.
- ClickHouse: `MergeTree`, `PARTITION BY toYYYYMM(measured_at)`, `ORDER BY (parameter, city, measured_at, location_id, sensor_id)`.

## 4. Thu thập dữ liệu thật từ OpenAQ (tùy chọn – repo đã có sẵn CSV)

Lấy API key tại https://explore.openaq.org/ và điền vào `.env`. Lệnh đã dùng cho dữ liệu trong repo:

```bash
python scripts/fetch_openaq.py --iso VN --days 90 \
  --scan-locations 100 --max-sensors 12 --pages-per-sensor 4
```

Tham số: `--iso`, `--days`, `--scan-locations`, `--max-sensors`, `--pages-per-sensor`, `--out`. Script nghỉ ~1 giây giữa các lời gọi API và dừng khi gặp HTTP 429.

Lưu ý: trường `city` lấy từ `locality` của trạm; trạm không có `locality` sẽ nhận tên quốc gia (`Vietnam`).

## 5. Nạp dữ liệu vào cả hai CSDL

```bash
python scripts/ingest_csv.py --file data/sample_synthetic.csv --batch-size 100     # kiểm thử luồng
python scripts/ingest_csv.py --file data/openaq_measurements.csv --batch-size 500  # dữ liệu thật
```

> ⚠️ **Chỉ nạp mỗi tệp một lần vào CSDL trống.** Cassandra ghi đè theo khóa chính, nhưng ClickHouse `MergeTree` **không** khử trùng lặp – chạy lại sẽ nhân đôi dữ liệu ở ClickHouse.

## 6. Kiểm chứng

```bash
# ClickHouse: tách theo nguồn (kỳ vọng 23.022 OpenAQ-hours + 240 SYNTHETIC_SAMPLE)
docker exec -it aq-clickhouse clickhouse-client --query "
SELECT source, count(), uniqExact(location_id), uniqExact(sensor_id)
FROM air_quality.measurements GROUP BY source ORDER BY source"

# Đối soát một phân vùng giữa hai hệ (kỳ vọng cùng trả về 24)
docker exec -it aq-cassandra cqlsh -e "SELECT COUNT(*) FROM air_quality.measurements_by_station_day WHERE location_id=4946812 AND parameter='pm25' AND measurement_date='2026-10-02'"
docker exec -it aq-clickhouse clickhouse-client --query "SELECT count() FROM air_quality.measurements WHERE source='OpenAQ-hours' AND location_id=4946812 AND parameter='pm25' AND toDate(measured_at)='2026-10-02'"
```

Không dùng `COUNT(*)` toàn bảng trên Cassandra; luôn truy vấn theo đủ partition key và không dùng `ALLOW FILTERING`.

## 7. Benchmark

`scripts/benchmark.py` đo độ trễ phía ứng dụng (`time.perf_counter()`), chạy tuần tự, không warm-up:

- **W1 – Cassandra:** `SELECT measured_at, value ... WHERE location_id=? AND parameter=? AND measurement_date=? LIMIT 500`
- **W2 – ClickHouse:** tổng hợp `count/avg/max` theo `city, parameter, ngày` cho dữ liệu `OpenAQ-hours` của cùng ngày.

Hai lần đo trong báo cáo:

```bash
# Lần đo A
python scripts/benchmark.py --location-id 4946813 --parameter no2 --date 2026-08-19 --repeats 20
# Lần đo B
python scripts/benchmark.py --location-id 4946812 --parameter pm25 --date 2026-10-02 --repeats 50 \
  --out results/benchmark_openaq.csv
```

Kết quả (median): A – Cassandra 1,66 ms, ClickHouse 3,67 ms; B – Cassandra 0,90 ms, ClickHouse 3,84 ms (MacBook Pro M1 Max, Docker Desktop, mỗi hệ 1 node).

> Hai truy vấn đại diện **hai workload khác nhau**; không dùng để kết luận CSDL nào nhanh hơn. Tệp kết quả không tự lưu tham số `--location-id/--parameter/--date` – hãy ghi lại lệnh đã chạy.

Vẽ biểu đồ median (cần pandas, matplotlib):

```bash
python scripts/plot_results.py         # đọc results/benchmark.csv → results/latency_chart.png
```

## 8. Dừng hệ thống

```bash
docker compose stop        # dừng, giữ dữ liệu
docker compose down        # xóa container, GIỮ volume dữ liệu
# docker compose down -v   # ⚠️ XÓA LUÔN dữ liệu của hai CSDL
```

## Giới hạn đã biết

- Mỗi CSDL chạy 1 node, Cassandra RF = 1: không đánh giá HA, chịu lỗi hay mở rộng ngang.
- Ghi kép không nguyên tử; chạy lại ingestion gây trùng lặp ở ClickHouse.
- Dữ liệu nhỏ (~23 nghìn dòng), độ phủ không đều (một cảm biến NO₂ chỉ 17 bản ghi); trường `city` chưa chuẩn hóa.
- Benchmark tuần tự, không tải đồng thời; độ trễ ở quy mô này chủ yếu là chi phí cố định mỗi lời gọi.

## Tài liệu

- OpenAQ API: https://docs.openaq.org/
- Apache Cassandra: https://cassandra.apache.org/doc/
- ClickHouse: https://clickhouse.com/docs/
