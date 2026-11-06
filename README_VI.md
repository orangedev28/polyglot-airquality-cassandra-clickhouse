# Starter dự án: Cassandra + ClickHouse cho giám sát chất lượng không khí

## Mục tiêu
Prototype kiến trúc đa hệ CSDL (polyglot persistence):
- **Apache Cassandra:** workload vận hành; truy vấn đo đạc theo trạm + chất ô nhiễm + ngày.
- **ClickHouse:** workload phân tích; tổng hợp lịch sử theo thành phố, chất ô nhiễm và thời gian.
- **Python:** tải/chuẩn hóa CSV và ghi cùng bộ sự kiện vào cả hai DB theo mô hình riêng.

Hai DB không được so sánh như hai lựa chọn thay thế cùng mục đích. Ta đánh giá mức phù hợp với từng workload và độ phức tạp tích hợp.

## A. Yêu cầu
- Docker Desktop hoặc Docker Engine + Compose.
- Python 3.10–3.12.
- RAM khuyến nghị tối thiểu 8 GB. Nếu máy yếu, giảm lượng dữ liệu và giới hạn heap của Cassandra trong `docker-compose.yml`.

## B. Chạy database
Mở terminal tại thư mục dự án:
```bash
docker compose up -d
docker compose ps
```
Chờ Cassandra khởi động (lần đầu thường cần vài phút). Kiểm tra:
```bash
docker exec -it aq-cassandra cqlsh -e "DESCRIBE KEYSPACES"
docker exec -it aq-clickhouse clickhouse-client --query "SELECT 1"
```

## C. Cài Python
Windows PowerShell:
```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## D. Lấy dữ liệu thật từ OpenAQ
Đăng ký API key tại https://explore.openaq.org/ rồi điền vào `.env`. Không chia sẻ key công khai.
```bash
python scripts/fetch_openaq.py --iso VN --days 30 --max-locations 8 --max-sensors 12 --pages-per-sensor 2
```
Nếu số bản ghi ít/không có:
- tăng `--days` lên 90 hoặc 180;
- tăng `--max-locations`;
- thử `--iso TH` hoặc `--iso IN` nếu Việt Nam chưa đủ trạm/phép đo, và ghi rõ phạm vi địa lý trong báo cáo.

OpenAQ chỉ lưu những dữ liệu đã được nền tảng thu thập/công khai; không đảm bảo tất cả các trạm tại Việt Nam có dữ liệu lịch sử đầy đủ. Tệp CSV phải được kiểm tra trước khi nạp DB. Ghi nhận OpenAQ và nguồn dữ liệu gốc theo thông tin attribution/license trả về.

## E. Chạy ngay bằng dữ liệu thử nghiệm
Nếu chưa có API key hoặc đợi khảo sát dữ liệu, tạo dữ liệu giả lập:
```bash
python scripts/generate_synthetic.py --rows 10000
```
Nó tạo `data/synthetic_measurements.csv`. Đây là **dữ liệu mô phỏng**, không được trình bày như dữ liệu quan trắc thật. Có thể tăng lên 100.000 hoặc 1.000.000 dòng tùy cấu hình máy.

## F. Nạp CSV vào cả hai DB
```bash
python scripts/ingest_csv.py --file data/synthetic_measurements.csv --batch-size 500
```
Hoặc:
```bash
python scripts/ingest_csv.py --file data/openaq_measurements.csv --batch-size 500
```

## G. Kiểm tra dữ liệu
ClickHouse:
```bash
docker exec -it aq-clickhouse clickhouse-client --query "SELECT count(), min(measured_at), max(measured_at) FROM air_quality.measurements"
```
Cassandra: truy vấn một partition cụ thể, không chạy COUNT(*) toàn bảng làm benchmark:
```bash
docker exec -it aq-cassandra cqlsh -e "SELECT measured_at,value FROM air_quality.measurements_by_station_day WHERE location_id=1001 AND parameter='pm25' LIMIT 10"
```

## H. Benchmark
Chọn ngày thực sự có dữ liệu trong CSV:
```bash
python scripts/benchmark.py --location-id 1001 --parameter pm25 --date 2026-10-11 --repeats 10
```
Kết quả lưu ở `results/benchmark.csv`. Thay ngày, location ID, parameter theo dữ liệu của bạn.
- Cassandra: point/time-window lookup bằng partition key.
- ClickHouse: aggregation theo thành phố/chất ô nhiễm/ngày.

Hai truy vấn đại diện hai workload khác nhau; không diễn giải thời gian đo là phép so sánh công bằng trực tiếp. Báo cáo nên trình bày số liệu kèm workload, cấu hình máy, dataset và số lần chạy. Benchmark bổ sung cùng logic nghiệp vụ/end-to-end có thể làm sau khi bản cơ bản chạy được.

## I. Các điểm kỹ thuật cần trình bày trong báo cáo
- Cassandra: partition key `(location_id, parameter, measurement_date)` và clustering theo thời gian; thiết kế theo access pattern.
- ClickHouse: MergeTree, partition theo tháng và sorting key phục vụ lọc/phân tích chuỗi thời gian.
- Kiến trúc dual-write: một sự kiện được gửi đến hai DB, nhưng không có transaction nguyên tử giữa chúng; cần nhận diện trường hợp một DB ghi thành công còn DB kia thất bại. Nếu còn thời gian, bổ sung retry và đối soát.
- Bản Compose mặc định chỉ chạy một node mỗi DB, Cassandra replication factor = 1; không tuyên bố đã chứng minh HA, fault tolerance hay distributed scaling.
- Ghi rõ phần dữ liệu OpenAQ và dữ liệu mô phỏng, tránh trộn hai nguồn mà không gắn nhãn.

## J. Kế hoạch đến 08/11/2026
31/10: dựng DB, kiểm tra API và dữ liệu.
01/11: chốt dataset, làm sạch và kiểm tra chất lượng.
02/11: chốt schema, nạp dữ liệu.
03/11: hoàn thiện truy vấn vận hành + analytics.
04–05/11: benchmark và lưu số liệu.
06/11: phân tích, biểu đồ.
07/11: hoàn thiện báo cáo, demo.
08/11: kiểm tra và nộp.

## Tài liệu chính thức
- OpenAQ API: https://docs.openaq.org/
- OpenAQ API key: https://docs.openaq.org/using-the-api/api-key
- OpenAQ rate limits: https://docs.openaq.org/using-the-api/rate-limits
- OpenAQ measurements: https://docs.openaq.org/resources/measurements
- Cassandra: https://cassandra.apache.org/doc/
- ClickHouse: https://clickhouse.com/docs/
