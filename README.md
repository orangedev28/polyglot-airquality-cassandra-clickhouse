# Polyglot Persistence for Air Quality Monitoring: Apache Cassandra + ClickHouse

Final project for **GCOS134 – Database Systems**, part of the **Master's Program in Information Technology** (Ho Chi Minh City University of Technology – HUTECH, 2026).

A polyglot persistence architecture prototype:

- **Apache Cassandra 5.0** – operational workload: point/partition lookups of measurements by *station + parameter + date*.
- **ClickHouse 25.8** – analytical workload: historical aggregations by *city + parameter + time*.
- **Python** – OpenAQ data ingestion, quality checks, and dual-write of the same event stream into both databases, each using a schema tailored to its access pattern.

The two databases are **not** compared as interchangeable alternatives for the same task; each system is evaluated on the specific workload it is designed to handle.

## Architecture

```text
OpenAQ API v3 (hours) / synthetic CSV
        │
scripts/fetch_openaq.py ──► data/openaq_measurements.csv
        │
scripts/ingest_csv.py  (DatabaseWriter, batched dual-write)
        ├──► Cassandra   air_quality.measurements_by_station_day   (operational)
        └──► ClickHouse  air_quality.measurements                  (analytical)

app/web.py (Flask, read-only) ──► tabs: Station Lookup (Cassandra) · Analytics (ClickHouse) · Reconciliation
```

Dual-write is **not** an atomic distributed transaction: each batch writes to Cassandra first, then to ClickHouse.

## Repository Data & Benchmark Artifacts

| File | Description |
|---|---|
| `data/openaq_measurements.csv` | 23,022 hourly OpenAQ records – 4 stations, 12 sensors, 5 parameters (`pm25`, `pm10`, `no2`, `so2`, `o3`), `2026-08-02` → `2026-10-31` (UTC), `source = OpenAQ-hours` |
| `data/sample_synthetic.csv` | 240 **synthetic** records – 2 stations (`1001`, `1002`), `source = SYNTHETIC_SAMPLE`, for pipeline testing only |
| `results/benchmark.csv` | Run A: 20 repeats |
| `results/benchmark_openaq.csv` | Run B: 50 repeats |
| `results/benchmark_large.csv` | Run C (Stage 3): 50 repeats on the 504,646-row VN + TH + KH dataset (`results/stage3.log`) |

All real-data analytics must filter on `source = 'OpenAQ-hours'`.

## Requirements

- Docker Desktop (or Docker Engine + Compose).
- Python 3.9 or higher (tested with Python 3.9.6 on macOS).
- Recommended RAM ≥ 8 GB. Cassandra heap is pinned to 1 GB (`MAX_HEAP_SIZE`) in `docker-compose.yml`.

## 1. Start Both Databases

```bash
docker compose up -d
docker compose ps                      # wait until both containers are healthy
docker exec -it aq-cassandra cqlsh -e "DESCRIBE KEYSPACES"
docker exec -it aq-clickhouse clickhouse-client --query "SELECT 1"
```

## 2. Set Up the Python Environment

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                   # add your OPENAQ_API_KEY to .env
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

> `.env` stores your API key and is excluded from Git via `.gitignore`. Do not share or commit this file.

## 3. Schemas

Schemas are defined in `sql/cassandra_schema.cql` and `sql/clickhouse_schema.sql`. `app/database.py` also creates the keyspace/database and tables automatically if they do not exist, so manual schema creation is optional.

- Cassandra: `PRIMARY KEY ((location_id, parameter, measurement_date), measured_at, sensor_id)`, `CLUSTERING ORDER BY (measured_at DESC, sensor_id ASC)`. `measurement_date` is the **UTC date**.
- ClickHouse: `MergeTree`, `PARTITION BY toYYYYMM(measured_at)`, `ORDER BY (parameter, city, measured_at, location_id, sensor_id)`.

## 4. Fetch Real Data from OpenAQ (Optional – CSVs Included)

Obtain an API key at https://explore.openaq.org/ and add it to `.env`. Command used to fetch the default dataset in this repository:

```bash
python scripts/fetch_openaq.py --iso VN --days 90 \
  --scan-locations 100 --max-sensors 12 --pages-per-sensor 4
```

Options: `--iso`, `--days`, `--scan-locations`, `--max-sensors`, `--pages-per-sensor`, `--out`. The script sleeps ~1 second between API calls and stops immediately on HTTP 429.

Note: the `city` field is populated from each station's `locality`; stations without a `locality` fall back to the country name (e.g., `Vietnam`).

Additional helper scripts for exploring and building the larger multi-country dataset (excluded from Git via `.gitignore`):

- `scripts/probe_openaq.py --iso VN` – inspect available OpenAQ locations and sensors for a country.
- `zsh scripts/fetch_large.sh` – fetch hourly data across Vietnam (`VN`), Thailand (`TH`), and Cambodia (`KH`) and merge into `data/openaq_measurements_large.csv` (504,646 rows).
- `python scripts/merge_check.py` – merge per-country CSVs and run data quality / partition checks (`results/merge_check.log`).

## 5. Ingest Data into Both Databases

```bash
python scripts/ingest_csv.py --file data/sample_synthetic.csv --batch-size 100     # pipeline test
python scripts/ingest_csv.py --file data/openaq_measurements.csv --batch-size 500  # real OpenAQ data
```

> ⚠️ **Ingest each file only once into an empty database.** Cassandra upserts by primary key, whereas ClickHouse `MergeTree` does **not** deduplicate—re-running ingestion will duplicate rows in ClickHouse.

To replace existing data with the large dataset, run the full Stage 3 workflow (truncates both tables, ingests, reconciles, benchmarks, and logs resource stats to `results/stage3.log`):

```bash
zsh scripts/stage3.sh
```

## 6. Verification

```bash
# ClickHouse: breakdown by source (expect 23,022 OpenAQ-hours + 240 SYNTHETIC_SAMPLE)
docker exec -it aq-clickhouse clickhouse-client --query "
SELECT source, count(), uniqExact(location_id), uniqExact(sensor_id)
FROM air_quality.measurements GROUP BY source ORDER BY source"

# Reconcile a single partition across both systems (expect 24 on both)
docker exec -it aq-cassandra cqlsh -e "SELECT COUNT(*) FROM air_quality.measurements_by_station_day WHERE location_id=4946812 AND parameter='pm25' AND measurement_date='2026-10-02'"
docker exec -it aq-clickhouse clickhouse-client --query "SELECT count() FROM air_quality.measurements WHERE source='OpenAQ-hours' AND location_id=4946812 AND parameter='pm25' AND toDate(measured_at)='2026-10-02'"
```

Avoid full-table `COUNT(*)` on Cassandra; always query with the full partition key and without `ALLOW FILTERING`.

## 7. Benchmark

`scripts/benchmark.py` measures client-side latency (`time.perf_counter()`), running sequentially with no warm-up:

- **W1 – Cassandra:** `SELECT measured_at, value ... WHERE location_id=? AND parameter=? AND measurement_date=? LIMIT 500`
- **W2 – ClickHouse:** `count/avg/max` aggregation by `city, parameter, date` over `OpenAQ-hours` records for the same date.

Recorded runs in this repository:

```bash
# Run A
python scripts/benchmark.py --location-id 4946813 --parameter no2 --date 2026-08-19 --repeats 20
# Run B
python scripts/benchmark.py --location-id 4946812 --parameter pm25 --date 2026-10-02 --repeats 50 \
  --out results/benchmark_openaq.csv
```

Median results (MacBook Pro M1 Max, Docker Desktop, single-node per database):

- **Run A (20 repeats):** Cassandra `1.66 ms`, ClickHouse `3.67 ms`
- **Run B (50 repeats):** Cassandra `0.90 ms`, ClickHouse `3.84 ms`
- **Run C (50 repeats, 504,646-row dataset via `stage3.sh`):** Cassandra `1.22 ms`, ClickHouse `4.72 ms`

> The two queries represent **different workloads** and must not be used to declare one database faster overall. Output CSVs do not store `--location-id/--parameter/--date` flags—record the exact command executed.

Plot the median latency chart (requires `pandas` and `matplotlib`):

```bash
python scripts/plot_results.py         # reads results/benchmark.csv → results/latency_chart.png
```

## 8. Local Read-Only Web App

```bash
pip install -r requirements.txt        # includes flask
python app/web.py                      # open http://127.0.0.1:5050
```

Three tabs:

1. **Station Lookup – Cassandra:** select station, parameter, and date (UTC) → reads a single partition, displaying the table, hourly chart, and query latency.
2. **Analytics – ClickHouse:** select date range → aggregates by city × parameter with a daily average chart (always filters `source = 'OpenAQ-hours'`).
3. **Reconciliation:** counts the same partition in both Cassandra and ClickHouse, reporting match or mismatch.

The app is **read-only** and performs no writes. Port `5050` is used by default because macOS AirPlay Receiver often occupies port `5000` (override via the `WEB_PORT` environment variable). Chart.js 4.4.1 (MIT license) is bundled in `app/static/` for offline use. Displayed latencies reflect single-request client-side timings and do not replace the benchmark in Section 7.

## 9. Stop the System

```bash
docker compose stop        # stop containers, keep data
docker compose down        # remove containers, KEEP data volumes
# docker compose down -v   # ⚠️ ALSO DELETES all database volumes/data
```

## Known Limitations

- Single node per database, Cassandra `RF = 1`: does not evaluate high availability, fault tolerance, or horizontal scaling.
- Dual-write is non-atomic; re-running ingestion introduces duplicate rows in ClickHouse.
- Limited sample size (~23k rows in the committed CSV; ~505k rows in Stage 3) with uneven sensor coverage (one NO₂ sensor has only 17 rows) and unstandardized `city` values.
- Sequential benchmark without concurrency; at this scale, measured latency mainly reflects per-call fixed overhead.

## References

- OpenAQ API: https://docs.openaq.org/
- Apache Cassandra: https://cassandra.apache.org/doc/
- ClickHouse: https://clickhouse.com/docs/
