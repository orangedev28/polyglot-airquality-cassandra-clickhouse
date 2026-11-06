import argparse,csv,time,statistics,sys
from pathlib import Path
from datetime import date,timedelta
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cassandra.cluster import Cluster
import clickhouse_connect
from app.config import *
def measure(fn,n):
    out=[]
    for _ in range(n):
        t=time.perf_counter(); fn(); out.append((time.perf_counter()-t)*1000)
    return out
def main():
    p=argparse.ArgumentParser(); p.add_argument("--location-id",type=int,default=1001); p.add_argument("--parameter",default="pm25")
    p.add_argument("--date",required=True,help="Ngày có dữ liệu, định dạng YYYY-MM-DD"); p.add_argument("--repeats",type=int,default=10)
    p.add_argument("--out",default="results/benchmark.csv"); a=p.parse_args()
    day=date.fromisoformat(a.date); cluster=Cluster([CASSANDRA_HOST],port=CASSANDRA_PORT); ss=cluster.connect("air_quality")
    ch=clickhouse_connect.get_client(host=CLICKHOUSE_HOST,port=CLICKHOUSE_PORT,username=CLICKHOUSE_USER,password=CLICKHOUSE_PASSWORD)
    q=ss.prepare("SELECT measured_at,value FROM measurements_by_station_day WHERE location_id=? AND parameter=? AND measurement_date=? LIMIT 500")
    def cass(): list(ss.execute(q,(a.location_id,a.parameter,day)))
    def click():
        ch.query(f"SELECT city,parameter,toDate(measured_at),count(),avg(value),max(value) FROM {CLICKHOUSE_DATABASE}.measurements WHERE source = 'OpenAQ-hours' AND measured_at >= toDateTime('{day} 00:00:00','UTC') AND measured_at < toDateTime('{day+timedelta(days=1)} 00:00:00','UTC') GROUP BY city,parameter,toDate(measured_at)")
    rec=[]
    for name,work,fn in [("Cassandra","Tra cứu theo trạm + chỉ số + ngày",cass),("ClickHouse","Tổng hợp theo thành phố + chỉ số + ngày",click)]:
        vals=measure(fn,a.repeats); print(f"{name}: median {statistics.median(vals):.2f} ms")
        rec.extend([[name,work,i+1,round(v,3)] for i,v in enumerate(vals)])
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["database","workload","run","latency_ms"]); w.writerows(rec)
    ss.shutdown(); cluster.shutdown(); ch.close(); print("Kết quả:",out)
    print("Hai truy vấn phản ánh workload khác nhau, không dùng để tuyên bố DB nào nhanh hơn toàn diện.")
if __name__=="__main__": main()
