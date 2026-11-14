"""Local read-only web application for the Polyglot Persistence project: Cassandra + ClickHouse.
(Final project for GCOS134 – Database Systems, Master's Program in Information Technology, HUTECH, 2026.)

Run:    python app/web.py            → open http://127.0.0.1:5050
Tab 1 – Station Lookup : operational workload → Cassandra (reads a single partition)
Tab 2 – Analytics      : analytical workload  → ClickHouse (GROUP BY on OpenAQ data)
Tab 3 – Reconciliation : counts the same partition across both systems

This app performs NO writes and therefore cannot cause duplicate rows in ClickHouse.
Port 5050 is used by default because macOS AirPlay Receiver often occupies port 5000.
"""
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, Response, jsonify, request  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402
from cassandra.cluster import Cluster  # noqa: E402
import clickhouse_connect  # noqa: E402
from app.config import (  # noqa: E402
    CASSANDRA_HOST, CASSANDRA_PORT, CLICKHOUSE_HOST, CLICKHOUSE_PORT,
    CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DATABASE,
)

SOURCE = "OpenAQ-hours"
PARAMETERS = {"pm25", "pm10", "no2", "so2", "o3", "co"}
TABLE = f"{CLICKHOUSE_DATABASE}.measurements"

app = Flask(__name__)
_conn = {}


# ----------------------------------------------------------------- connections
def cassandra():
    """Shared Cassandra session, initialized lazily on first use."""
    if "cs" not in _conn:
        cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT)
        session = cluster.connect("air_quality")
        _conn["cluster"] = cluster
        _conn["cs"] = session
        _conn["q_station"] = session.prepare(
            "SELECT measured_at, sensor_id, value, unit, source "
            "FROM measurements_by_station_day "
            "WHERE location_id=? AND parameter=? AND measurement_date=? LIMIT 500")
        _conn["q_count"] = session.prepare(
            "SELECT COUNT(*) FROM measurements_by_station_day "
            "WHERE location_id=? AND parameter=? AND measurement_date=?")
    return _conn["cs"]


def clickhouse():
    """Shared ClickHouse client, initialized lazily on first use."""
    if "ch" not in _conn:
        _conn["ch"] = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD,
            autogenerate_session_id=False)
    return _conn["ch"]


def timed(fn):
    """Execute fn and return (result, elapsed_ms) measured client-side."""
    t = time.perf_counter()
    out = fn()
    return out, round((time.perf_counter() - t) * 1000, 2)


def ch_query(sql, params):
    res = clickhouse().query(sql, parameters=params)
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


# ----------------------------------------------------------------- input validation
class BadRequest(Exception):
    pass


def arg_int(name):
    try:
        return int(request.args[name])
    except (KeyError, ValueError):
        raise BadRequest(f"Parameter {name} must be an integer")


def arg_param():
    p = request.args.get("parameter", "")
    if p not in PARAMETERS:
        raise BadRequest("Invalid parameter")
    return p


def arg_date(name):
    try:
        return date.fromisoformat(request.args[name])
    except (KeyError, ValueError):
        raise BadRequest(f"Parameter {name} must use YYYY-MM-DD format")


@app.errorhandler(BadRequest)
def _bad(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(Exception)
def _err(e):
    if isinstance(e, HTTPException):
        return e
    return jsonify(error=f"{type(e).__name__}: {e}"), 500


# ----------------------------------------------------------------- API
@app.get("/api/meta")
def api_meta():
    """Catalog of stations, parameters, and date ranges available in OpenAQ data (read from ClickHouse)."""
    rows, ms = timed(lambda: ch_query(
        f"SELECT location_id, any(station_name) AS station_name, any(city) AS city, "
        f"arraySort(groupUniqArray(parameter)) AS parameters, "
        f"toString(min(toDate(measured_at))) AS first_day, toString(max(toDate(measured_at))) AS last_day "
        f"FROM {TABLE} WHERE source = {{src:String}} GROUP BY location_id ORDER BY location_id",
        {"src": SOURCE}))
    for r in rows:
        r["location_id"] = int(r["location_id"])
        r["station_name"] = r["station_name"].strip()
        r["parameters"] = list(r["parameters"])
    return jsonify(stations=rows, latency_ms=ms)


@app.get("/api/station")
def api_station():
    """W1 – operational workload: matches the benchmark query, reading 1 Cassandra partition."""
    loc, par, day = arg_int("location_id"), arg_param(), arg_date("date")
    session = cassandra()
    rows, ms = timed(lambda: list(session.execute(_conn["q_station"], (loc, par, day))))
    data = [{"measured_at": r.measured_at.strftime("%Y-%m-%d %H:%M"), "sensor_id": int(r.sensor_id),
             "value": r.value, "unit": r.unit, "source": r.source} for r in rows]
    return jsonify(partition=[loc, par, day.isoformat()], rows=data, count=len(data), latency_ms=ms,
                   cql="SELECT measured_at, sensor_id, value, unit, source FROM measurements_by_station_day "
                       "WHERE location_id=? AND parameter=? AND measurement_date=? LIMIT 500")


@app.get("/api/analytics")
def api_analytics():
    """W2 – analytical workload on ClickHouse, always filtering source = 'OpenAQ-hours'."""
    start, end = arg_date("start"), arg_date("end")
    if end < start:
        raise BadRequest("End date must be on or after start date")
    p = {"src": SOURCE, "d1": start.isoformat(), "d2": (end + timedelta(days=1)).isoformat()}
    where = ("WHERE source = {src:String} AND measured_at >= toDateTime({d1:String}, 'UTC') "
             "AND measured_at < toDateTime({d2:String}, 'UTC')")
    summary, ms1 = timed(lambda: ch_query(
        f"SELECT city, parameter, count() AS records, round(avg(value), 2) AS avg_value, "
        f"round(min(value), 2) AS min_value, round(max(value), 2) AS max_value "
        f"FROM {TABLE} {where} GROUP BY city, parameter ORDER BY city, parameter", p))
    daily, ms2 = timed(lambda: ch_query(
        f"SELECT toString(toDate(measured_at)) AS day, city, parameter, round(avg(value), 2) AS avg_value "
        f"FROM {TABLE} {where} GROUP BY day, city, parameter ORDER BY day, city, parameter", p))
    for r in summary:
        r["records"] = int(r["records"])
    return jsonify(summary=summary, daily=daily, latency_ms={"summary": ms1, "daily": ms2},
                   total_records=sum(r["records"] for r in summary))


@app.get("/api/reconcile")
def api_reconcile():
    """Reconciliation: count the same partition (station, parameter, UTC date) across both systems."""
    loc, par, day = arg_int("location_id"), arg_param(), arg_date("date")
    session = cassandra()
    cs_rows, ms_cs = timed(lambda: list(session.execute(_conn["q_count"], (loc, par, day))))
    cs_count = int(cs_rows[0][0]) if cs_rows else 0
    ch_rows, ms_ch = timed(lambda: ch_query(
        f"SELECT count() AS n FROM {TABLE} WHERE source = {{src:String}} AND location_id = {{loc:UInt64}} "
        f"AND parameter = {{par:String}} AND toDate(measured_at) = toDate({{day:String}})",
        {"src": SOURCE, "loc": loc, "par": par, "day": day.isoformat()}))
    ch_count = int(ch_rows[0]["n"]) if ch_rows else 0
    return jsonify(partition=[loc, par, day.isoformat()], cassandra=cs_count, clickhouse=ch_count,
                   match=cs_count == ch_count, latency_ms={"cassandra": ms_cs, "clickhouse": ms_ch})


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


# ----------------------------------------------------------------- UI
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Air Quality Monitoring – Cassandra + ClickHouse</title>
<script src="/static/chart.umd.js"></script><!-- Chart.js 4.4.1 (MIT), bundled for offline use -->
<style>
:root{--ink:#1b2b38;--ink2:#24465c;--muted:#5f6f7a;--line:#d9e1e7;--bg:#f4f7f9;--card:#fff;--cas:#2a78d6;--ch:#e07a2e;--ok:#2f8a5b;--bad:#c24e4e}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--ink2);color:#fff;padding:18px 28px}header h1{margin:0;font-size:20px}header p{margin:4px 0 0;color:#cfdde6;font-size:13px}
nav{display:flex;gap:6px;padding:14px 28px 0}nav button{border:0;background:#e3eaef;color:var(--ink2);padding:10px 16px;border-radius:8px 8px 0 0;font-size:14px;cursor:pointer;font-weight:600}
nav button.on{background:var(--card);box-shadow:0 -1px 0 var(--line)}
main{padding:0 28px 28px}.panel{display:none;background:var(--card);border-radius:0 10px 10px 10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)}.panel.on{display:block}
.row{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:14px}label{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:4px}
select,input{padding:7px 9px;border:1px solid var(--line);border-radius:6px;font-size:14px;min-width:150px}
button.go{background:var(--ink2);color:#fff;border:0;border-radius:6px;padding:9px 18px;font-size:14px;cursor:pointer}
.tag{display:inline-block;padding:3px 9px;border-radius:12px;font-size:12px;font-weight:600;color:#fff}.cas{background:var(--cas)}.chh{background:var(--ch)}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 14px}.kpi{background:var(--bg);border-radius:8px;padding:10px 14px;min-width:140px}.kpi b{display:block;font-size:22px}.kpi span{font-size:12px;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}th{background:#eef3f6}td.n,th.n{text-align:right}
.grid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:18px}@media(max-width:900px){.grid{grid-template-columns:1fr}}
.scroll{max-height:360px;overflow:auto}code{background:#eef3f6;padding:2px 5px;border-radius:4px;font-size:12px}.note{font-size:12px;color:var(--muted)}
.err{color:var(--bad);font-weight:600}.match{font-size:20px;font-weight:700}.match.ok{color:var(--ok)}.match.bad{color:var(--bad)}
.cbox{position:relative;height:320px}.kpi .tag{color:#fff;font-size:12px;margin-bottom:6px}.vs{display:flex;gap:16px;align-items:stretch;flex-wrap:wrap}.vs .kpi{min-width:200px}
</style></head><body>
<header><h1>Air Quality Monitoring – Polyglot Persistence</h1>
<p>Cassandra for operational lookups · ClickHouse for historical analytics · OpenAQ data (source = OpenAQ-hours) · read-only app</p></header>
<nav><button class="on" data-t="t1">1 · Station Lookup</button><button data-t="t2">2 · Analytics</button><button data-t="t3">3 · Cross-System Reconciliation</button></nav>
<main>
<section id="t1" class="panel on">
  <p><span class="tag cas">Cassandra</span> Queries by full partition key <code>(location_id, parameter, measurement_date)</code> – reads exactly 1 partition. Dates are in UTC.</p>
  <div class="row"><label>Station<select id="s_loc"></select></label><label>Parameter<select id="s_par"></select></label>
  <label>Date (UTC)<input type="date" id="s_day"></label><button class="go" id="s_go">Lookup</button></div>
  <div id="s_out"></div>
</section>
<section id="t2" class="panel">
  <p><span class="tag chh">ClickHouse</span> Ad-hoc aggregation by city × parameter without separate summary tables. Always filters <code>source = 'OpenAQ-hours'</code>.</p>
  <div class="row"><label>Start date<input type="date" id="a_d1"></label><label>End date<input type="date" id="a_d2"></label>
  <label>Chart parameter<select id="a_par"></select></label><button class="go" id="a_go">Analyze</button></div>
  <div id="a_out"></div>
</section>
<section id="t3" class="panel">
  <p>Counts the same partition in <span class="tag cas">Cassandra</span> and <span class="tag chh">ClickHouse</span> – checks whether the two systems diverge due to non-atomic dual-write.</p>
  <div class="row"><label>Station<select id="r_loc"></select></label><label>Parameter<select id="r_par"></select></label>
  <label>Date (UTC)<input type="date" id="r_day"></label><button class="go" id="r_go">Reconcile</button></div>
  <div id="r_out"></div>
</section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (x, d) => Number(x).toLocaleString("en-US", {minimumFractionDigits: d||0, maximumFractionDigits: d||0});
let META = [], charts = {};
document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("nav button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === b.dataset.t));
});
async function api(url) {
  const r = await fetch(url); const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText); return j;
}
function chart(id, cfg) {
  if (charts[id]) charts[id].destroy();
  if (typeof Chart === "undefined") return; // offline without Chart.js: render table only
  charts[id] = new Chart($(id), cfg);
}
function fillStations(locSel, parSel) {
  locSel.innerHTML = META.map((s) => `<option value="${s.location_id}">${s.location_id} – ${esc(s.station_name)} (${esc(s.city)})</option>`).join("");
  const sync = () => { const s = META.find((x) => String(x.location_id) === locSel.value);
    parSel.innerHTML = (s ? s.parameters : []).map((p) => `<option>${p}</option>`).join(""); };
  locSel.onchange = sync; sync();
}
function setVal(sel, v) { if ([...sel.options].some((o) => o.value === v)) sel.value = v; }
async function init() {
  try {
    const m = await api("/api/meta"); META = m.stations;
    if (!META.length) throw new Error("No OpenAQ data found in ClickHouse");
    fillStations($("s_loc"), $("s_par")); fillStations($("r_loc"), $("r_par"));
    setVal($("s_loc"), "4946812"); $("s_loc").onchange(); setVal($("s_par"), "pm25");
    setVal($("r_loc"), "4946812"); $("r_loc").onchange(); setVal($("r_par"), "pm25");
    const first = META.map((s) => s.first_day).sort()[0], last = META.map((s) => s.last_day).sort().slice(-1)[0];
    ["s_day", "r_day"].forEach((id) => { $(id).min = first; $(id).max = last; $(id).value = "2026-10-02" >= first && "2026-10-02" <= last ? "2026-10-02" : last; });
    $("a_d1").value = first; $("a_d2").value = last;
    const pars = [...new Set(META.flatMap((s) => s.parameters))].sort();
    $("a_par").innerHTML = pars.map((p) => `<option>${p}</option>`).join(""); setVal($("a_par"), "pm25");
  } catch (e) { document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="err">Failed to load station catalog: ${esc(e.message)}</p>`); }
}
$("s_go").onclick = async () => {
  const out = $("s_out"); out.innerHTML = "Querying…";
  try {
    const q = new URLSearchParams({location_id: $("s_loc").value, parameter: $("s_par").value, date: $("s_day").value});
    const j = await api("/api/station?" + q);
    const rows = [...j.rows].reverse(); // Cassandra returns newest first; reverse to plot chronologically
    out.innerHTML = `<div class="kpis"><div class="kpi"><b>${fmt(j.latency_ms, 2)} ms</b><span>query latency (client-side)</span></div>
      <div class="kpi"><b>${j.count}</b><span>rows in partition</span></div>
      <div class="kpi"><b>${esc(j.partition.join(" · "))}</b><span>partition key</span></div></div>
      ${j.count ? `<div class="grid"><div class="cbox"><canvas id="s_chart"></canvas></div><div class="scroll"><table>
      <tr><th>measured_at (UTC)</th><th>sensor_id</th><th class="n">value</th><th>unit</th></tr>
      ${j.rows.map((r) => `<tr><td>${r.measured_at}</td><td>${r.sensor_id}</td><td class="n">${fmt(r.value, 2)}</td><td>${esc(r.unit)}</td></tr>`).join("")}
      </table></div></div>` : `<p class="note">No data in this partition – choose another date.</p>`}
      <p class="note">CQL: <code>${esc(j.cql)}</code></p>`;
    if (j.count) chart("s_chart", {type: "line", data: {labels: rows.map((r) => r.measured_at.slice(11)),
      datasets: [{label: `${j.partition[1]} (${rows[0].unit})`, data: rows.map((r) => r.value), borderColor: "#2a78d6", backgroundColor: "#2a78d6", tension: .25, pointRadius: 3}]},
      options: {maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {x: {title: {display: true, text: "Hour (UTC)"}, ticks: {maxRotation: 0}}, y: {beginAtZero: true, title: {display: true, text: "µg/m³"}}}}});
  } catch (e) { out.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
};
$("a_go").onclick = async () => {
  const out = $("a_out"); out.innerHTML = "Querying…";
  try {
    const j = await api("/api/analytics?" + new URLSearchParams({start: $("a_d1").value, end: $("a_d2").value}));
    const par = $("a_par").value, colors = ["#e07a2e", "#2a78d6", "#4e8f6e", "#6b5ca5"];
    const days = [...new Set(j.daily.map((d) => d.day))];
    const cities = [...new Set(j.daily.filter((d) => d.parameter === par).map((d) => d.city))];
    out.innerHTML = `<div class="kpis"><div class="kpi"><b>${fmt(j.latency_ms.summary, 2)} ms</b><span>summary query</span></div>
      <div class="kpi"><b>${fmt(j.latency_ms.daily, 2)} ms</b><span>daily breakdown query</span></div>
      <div class="kpi"><b>${fmt(j.total_records)}</b><span>records aggregated</span></div></div>
      <div class="grid"><div><div class="cbox"><canvas id="a_chart"></canvas></div><p class="note">Daily average of ${esc(par)}; the “Vietnam” group represents stations without city metadata.</p></div>
      <div class="scroll"><table><tr><th>city</th><th>parameter</th><th class="n">records</th><th class="n">avg</th><th class="n">min</th><th class="n">max</th></tr>
      ${j.summary.map((r) => `<tr><td>${esc(r.city)}</td><td>${r.parameter}</td><td class="n">${fmt(r.records)}</td><td class="n">${fmt(r.avg_value, 2)}</td><td class="n">${fmt(r.min_value, 2)}</td><td class="n">${fmt(r.max_value, 2)}</td></tr>`).join("")}
      </table></div></div>`;
    chart("a_chart", {type: "line", data: {labels: days, datasets: cities.map((c, i) => ({label: c, borderColor: colors[i % 4], backgroundColor: colors[i % 4], pointRadius: 0, tension: .2,
      data: days.map((d) => { const x = j.daily.find((r) => r.day === d && r.city === c && r.parameter === par); return x ? x.avg_value : null; })}))},
      options: {maintainAspectRatio: false, spanGaps: true, scales: {y: {beginAtZero: true, title: {display: true, text: "µg/m³"}}, x: {ticks: {maxTicksLimit: 8, maxRotation: 0}}}}});
  } catch (e) { out.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
};
$("r_go").onclick = async () => {
  const out = $("r_out"); out.innerHTML = "Reconciling…";
  try {
    const q = new URLSearchParams({location_id: $("r_loc").value, parameter: $("r_par").value, date: $("r_day").value});
    const j = await api("/api/reconcile?" + q);
    out.innerHTML = `<div class="vs"><div class="kpi"><span class="tag cas">Cassandra</span><b>${j.cassandra} rows</b><span>COUNT(*) in partition · ${fmt(j.latency_ms.cassandra, 2)} ms</span></div>
      <div class="kpi"><span class="tag chh">ClickHouse</span><b>${j.clickhouse} rows</b><span>count() filtered OpenAQ-hours · ${fmt(j.latency_ms.clickhouse, 2)} ms</span></div>
      <div class="kpi"><span>Result</span><b class="match ${j.match ? "ok" : "bad"}">${j.match ? "Match ✓" : "Mismatch ✗"}</b><span>${esc(j.partition.join(" · "))}</span></div></div>
      <p class="note">${j.match ? "Both systems are consistent for this partition." : "Systems diverge – possibly due to a failed write or duplicate ingestion into ClickHouse."}</p>`;
  } catch (e) { out.innerHTML = `<p class="err">${esc(e.message)}</p>`; }
};
init();
</script></body></html>"""


if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "5050"))
    print(f"Open in browser: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=False)
