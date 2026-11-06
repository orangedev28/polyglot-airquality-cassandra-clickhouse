import argparse,csv,random
from pathlib import Path
from datetime import datetime,timedelta,timezone
def main():
    p=argparse.ArgumentParser(); p.add_argument("--rows",type=int,default=10000); p.add_argument("--out",default="data/synthetic_measurements.csv"); a=p.parse_args()
    cols=["location_id","station_name","sensor_id","parameter","unit","measured_at","value","latitude","longitude","city","source"]
    stations=[(1001,"Trạm trung tâm","Ho Chi Minh City",10.776,106.700),(1002,"Trạm phía Đông","Ho Chi Minh City",10.801,106.750),(1003,"Trạm Hà Nội","Ha Noi",21.028,105.854)]
    params=[("pm25","µg/m³",25),("pm10","µg/m³",44),("no2","µg/m³",18),("o3","µg/m³",30)]
    random.seed(42); start=datetime.now(timezone.utc)-timedelta(days=30); out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for i in range(a.rows):
            st=stations[i%len(stations)]; param,unit,mean=params[(i//len(stations))%len(params)]
            ts=start+timedelta(minutes=15*(i//(len(stations)*len(params))))
            w.writerow({"location_id":st[0],"station_name":st[1],"sensor_id":st[0]*10+params.index((param,unit,mean)),
                "parameter":param,"unit":unit,"measured_at":ts.isoformat().replace("+00:00","Z"),
                "value":round(max(.1,random.gauss(mean,mean*.22)),3),"latitude":st[3],"longitude":st[4],
                "city":st[2],"source":"SYNTHETIC"})
    print(f"Đã tạo {a.rows} bản ghi tổng hợp tại {out}; đây KHÔNG phải dữ liệu quan trắc thật.")
if __name__=="__main__": main()
