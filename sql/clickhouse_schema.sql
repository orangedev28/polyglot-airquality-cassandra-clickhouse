-- Analytical schema: MergeTree partitioned by month and ordered for city/parameter time-series aggregations
CREATE DATABASE IF NOT EXISTS air_quality;
CREATE TABLE IF NOT EXISTS air_quality.measurements (
 location_id UInt64, station_name String, sensor_id UInt64,
 parameter LowCardinality(String), unit LowCardinality(String),
 measured_at DateTime64(3,'UTC'), value Float64, latitude Float64,
 longitude Float64, city LowCardinality(String), source LowCardinality(String),
 ingested_at DateTime('UTC') DEFAULT now()
) ENGINE=MergeTree PARTITION BY toYYYYMM(measured_at)
ORDER BY (parameter,city,measured_at,location_id,sensor_id);
