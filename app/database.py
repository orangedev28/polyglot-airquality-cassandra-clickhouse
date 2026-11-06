from datetime import datetime, timezone
from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent_with_args
import clickhouse_connect
from app.config import *

KS = "air_quality"
class DatabaseWriter:
    def __init__(self):
        self.cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
        self.session = self.cluster.connect()
        self.session.execute(f"CREATE KEYSPACE IF NOT EXISTS {KS} WITH replication = {{'class':'SimpleStrategy','replication_factor':1}}")
        self.session.set_keyspace(KS)
        self.session.execute('''
          CREATE TABLE IF NOT EXISTS measurements_by_station_day (
            location_id bigint, parameter text, measurement_date date,
            measured_at timestamp, sensor_id bigint, station_name text,
            value double, unit text, latitude double, longitude double,
            city text, source text,
            PRIMARY KEY ((location_id, parameter, measurement_date), measured_at, sensor_id)
          ) WITH CLUSTERING ORDER BY (measured_at DESC, sensor_id ASC)
        ''')
        self.ins = self.session.prepare('''
          INSERT INTO measurements_by_station_day
          (location_id,parameter,measurement_date,measured_at,sensor_id,station_name,value,unit,latitude,longitude,city,source)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ''')
        self.ch = clickhouse_connect.get_client(host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD)
        self.ch.command(f"CREATE DATABASE IF NOT EXISTS {CLICKHOUSE_DATABASE}")
        self.ch.command(f'''
          CREATE TABLE IF NOT EXISTS {CLICKHOUSE_DATABASE}.measurements (
            location_id UInt64, station_name String, sensor_id UInt64,
            parameter LowCardinality(String), unit LowCardinality(String),
            measured_at DateTime64(3,'UTC'), value Float64, latitude Float64,
            longitude Float64, city LowCardinality(String), source LowCardinality(String),
            ingested_at DateTime('UTC') DEFAULT now()
          ) ENGINE=MergeTree PARTITION BY toYYYYMM(measured_at)
          ORDER BY (parameter,city,measured_at,location_id,sensor_id)
        ''')

    def insert_batch(self, rows):
        ch_rows = []
        cql_args = []
        for r in rows:
            dt = r["measured_at"]
            if isinstance(dt, str): dt = datetime.fromisoformat(dt.replace("Z","+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            cql_args.append((int(r["location_id"]), r["parameter"], dt.date(), dt,
                int(r["sensor_id"]), r["station_name"], float(r["value"]), r["unit"],
                float(r["latitude"]), float(r["longitude"]), r["city"], r["source"]))
            ch_rows.append([int(r["location_id"]),r["station_name"],int(r["sensor_id"]),
                r["parameter"],r["unit"],dt,float(r["value"]),float(r["latitude"]),
                float(r["longitude"]),r["city"],r["source"]])
        if cql_args:
            execute_concurrent_with_args(self.session, self.ins, cql_args,
                concurrency=50, raise_on_first_error=True)
        if ch_rows:
            self.ch.insert(f"{CLICKHOUSE_DATABASE}.measurements", ch_rows,
                column_names=["location_id","station_name","sensor_id","parameter","unit",
                "measured_at","value","latitude","longitude","city","source"])

    def close(self):
        self.session.shutdown()
        self.cluster.shutdown()
        self.ch.close()
