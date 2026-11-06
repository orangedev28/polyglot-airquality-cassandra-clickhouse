import os
from dotenv import load_dotenv
load_dotenv()
def env(k, default=None): return os.getenv(k, default)
OPENAQ_API_KEY = env("OPENAQ_API_KEY", "")
CASSANDRA_HOST = env("CASSANDRA_HOST", "127.0.0.1")
CASSANDRA_PORT = int(env("CASSANDRA_PORT", "9042"))
CLICKHOUSE_HOST = env("CLICKHOUSE_HOST", "127.0.0.1")
CLICKHOUSE_PORT = int(env("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = env("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = env("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DATABASE = env("CLICKHOUSE_DATABASE", "air_quality")
