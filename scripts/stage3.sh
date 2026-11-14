#!/bin/zsh
# Stage 3: replace existing data with the large dataset, reconcile, benchmark, inspect resource usage, and run analytics.
# Run from the project root with .venv activated:   zsh scripts/stage3.sh
# All output is recorded in results/stage3.log
set -e
set -o pipefail
export PYTHONUNBUFFERED=1
LOG=results/stage3.log
BIG=data/openaq_measurements_large.csv
cql() { docker exec aq-cassandra cqlsh --request-timeout=600 -e "$1"; }
ch()  { docker exec aq-clickhouse clickhouse-client --query "$1" "${@:2}"; }
exec > >(grep --line-buffered -v -e NotOpenSSLWarning -e "warnings.warn" | tee "$LOG") 2>&1

echo "===== 1. Start Docker containers and wait until ready ($(date +%H:%M:%S)) ====="
docker compose up -d
for c in aq-cassandra aq-clickhouse; do
  for i in {1..60}; do
    s=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $c)
    [[ "$s" == "healthy" || "$s" == "running" ]] && break; sleep 5
  done
  echo "$c: $s"
done
for i in {1..60}; do cql "SELECT now() FROM system.local" >/dev/null 2>&1 && break; echo "  waiting for Cassandra CQL..."; sleep 5; done
echo "Cassandra is ready."

echo "\n===== 2. Existing row counts (before truncation) ====="
ch "SELECT source, count() FROM air_quality.measurements GROUP BY source ORDER BY source FORMAT PrettyCompact"
echo "File to ingest: $BIG ($(wc -l < $BIG | tr -d ' ') lines including header)"
echo -n "\nDELETE existing data in BOTH tables and reload? Type yes and press Enter: "
read ans < /dev/tty
[[ "$ans" == "yes" ]] || { echo "Aborted, no changes made."; exit 1; }

echo "\n===== 3. Truncate existing data (keep schemas and volumes) ====="
cql "TRUNCATE air_quality.measurements_by_station_day;"
ch "TRUNCATE TABLE air_quality.measurements"
ch "SELECT 'ClickHouse remaining', count() FROM air_quality.measurements FORMAT TSV"

echo "\n===== 4. Ingest data ($(date +%H:%M:%S)) ====="
python scripts/ingest_csv.py --file data/sample_synthetic.csv
python scripts/ingest_csv.py --file $BIG | awk '/Completed/ || NR % 100 == 0'
echo "Ingestion finished at $(date +%H:%M:%S)"

echo "\n===== 5. Reconciliation ====="
ch "SELECT source, count() AS rows FROM air_quality.measurements GROUP BY source ORDER BY source FORMAT PrettyCompact"
echo "Cassandra full-table COUNT(*) (may take 10–60 seconds):"
cql "SELECT COUNT(*) FROM air_quality.measurements_by_station_day;"
echo "Partition (4946812, pm25, 2026-10-02):"
cql "SELECT COUNT(*) FROM air_quality.measurements_by_station_day WHERE location_id=4946812 AND parameter='pm25' AND measurement_date='2026-10-02';"
ch "SELECT 'ClickHouse', count() FROM air_quality.measurements WHERE location_id=4946812 AND parameter='pm25' AND toDate(measured_at)='2026-10-02' AND source='OpenAQ-hours' FORMAT TSV"

echo "\n===== 6. Benchmark (same parameters as Run B) ====="
python scripts/benchmark.py --location-id 4946812 --parameter pm25 --date 2026-10-02 --repeats 50 --out results/benchmark_large.csv
python - <<'EOF'
import math, pandas as pd
d = pd.read_csv("results/benchmark_large.csv")
for (db, wl), g in d.groupby(["database", "workload"]):
    v = g.sort_values("run").latency_ms.tolist(); s = sorted(v); n = len(s)
    p95 = s[math.ceil(0.95 * n) - 1]
    print(f"{db} {wl}: n={n} | run1={v[0]:.2f} | min={s[0]:.2f} | median={pd.Series(s).median():.2f} "
          f"| mean={sum(s)/n:.2f} | p95={p95:.2f} | max={s[-1]:.2f} ms")
EOF

echo "\n===== 7. Resource usage ====="
sleep 20
docker exec aq-cassandra nodetool flush air_quality
docker exec aq-cassandra nodetool tablestats air_quality.measurements_by_station_day | grep -E "Space used \(total\)|Number of partitions|SSTable count|Compacted partition maximum bytes|Compacted partition mean bytes" || true
ch "SELECT count() AS active_parts, sum(rows) AS rows, formatReadableSize(sum(data_compressed_bytes)) AS compressed, formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed, round(sum(data_uncompressed_bytes)/sum(data_compressed_bytes),1) AS ratio, uniqExact(partition) AS partitions FROM system.parts WHERE database='air_quality' AND table='measurements' AND active FORMAT PrettyCompact"
ch "SELECT name, formatReadableSize(data_compressed_bytes) c, formatReadableSize(data_uncompressed_bytes) u, round(data_uncompressed_bytes/data_compressed_bytes,1) r FROM system.columns WHERE database='air_quality' AND table='measurements' ORDER BY data_compressed_bytes DESC FORMAT PrettyCompact"
docker stats --no-stream --format "{{.Name}}: RAM {{.MemUsage}} | CPU {{.CPUPerc}}"
docker system df -v | grep -i -E "VOLUME NAME|cassandra|clickhouse" || true
ls -lh $BIG

echo "\n===== 8. Analytics ====="
ch "SELECT city, parameter, count() AS rows, round(avg(value),2) AS avg, round(min(value),2) AS min, round(max(value),2) AS max FROM air_quality.measurements WHERE source='OpenAQ-hours' GROUP BY city, parameter ORDER BY city, parameter FORMAT PrettyCompact" --time
ch "SELECT toYYYYMM(measured_at) AS month, city, round(avg(value),2) AS pm25_avg, count() AS rows FROM air_quality.measurements WHERE source='OpenAQ-hours' AND parameter='pm25' GROUP BY month, city ORDER BY month, city FORMAT CSVWithNames" > results/pm25_monthly.csv
echo "Saved results/pm25_monthly.csv ($(wc -l < results/pm25_monthly.csv | tr -d ' ') lines)"
ch "SELECT city, count() AS station_days, countIf(d > 50) AS over_qcvn_50, countIf(d > 15) AS over_who_15, round(100*countIf(d > 50)/count(),1) AS pct_over_qcvn FROM (SELECT city, location_id, toDate(measured_at) AS day, avg(value) AS d FROM air_quality.measurements WHERE source='OpenAQ-hours' AND parameter='pm25' GROUP BY city, location_id, day) GROUP BY city ORDER BY city FORMAT PrettyCompact"

echo "\n===== DONE $(date +%H:%M:%S) — share results/stage3.log ====="
