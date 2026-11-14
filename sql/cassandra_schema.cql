-- Operational schema: partitioned by (location_id, parameter, measurement_date) for single-partition lookups
CREATE KEYSPACE IF NOT EXISTS air_quality WITH replication = {'class':'SimpleStrategy','replication_factor':1};
USE air_quality;
CREATE TABLE IF NOT EXISTS measurements_by_station_day (
 location_id bigint, parameter text, measurement_date date, measured_at timestamp,
 sensor_id bigint, station_name text, value double, unit text, latitude double,
 longitude double, city text, source text,
 PRIMARY KEY ((location_id,parameter,measurement_date),measured_at,sensor_id)
) WITH CLUSTERING ORDER BY (measured_at DESC,sensor_id ASC);
