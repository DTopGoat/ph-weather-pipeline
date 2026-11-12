"""Export the Gold layer to small static JSON files, record data-quality results, and
write pipeline_health.json for the app's health panel.

Reads dbt artifacts from target/ (run_results.json from `dbt build`, sources.json from
`dbt source freshness`) and the DuckDB warehouse.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import duckdb

MANILA = timezone(timedelta(hours=8))
HOURLY_HISTORY_DAYS = 7
DAILY_HISTORY_DAYS = 30


def iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_manila(dt):
    return dt.astimezone(MANILA).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def summarize_tests(run_results):
    """Count dbt test outcomes from run_results.json. Models/seeds are counted separately."""
    tests = {"pass": 0, "fail": 0, "warn": 0, "error": 0, "skipped": 0}
    nodes = {"success": 0, "error": 0, "skipped": 0}
    details = []
    for r in (run_results or {}).get("results", []):
        uid = r.get("unique_id", "")
        status = r.get("status")
        if uid.startswith("test."):
            key = "skipped" if status == "skipped" else status
            tests[key] = tests.get(key, 0) + 1
            details.append({
                "test_name": uid.split(".")[2] if uid.count(".") >= 2 else uid,
                "test_type": "dbt_test",
                "status": status,
                "failures": r.get("failures") or 0,
                "message": r.get("message"),
            })
        elif uid.startswith(("model.", "seed.")):
            nodes[status if status in nodes else "error"] += 1
    return tests, nodes, details


def summarize_freshness(sources):
    out = []
    for r in (sources or {}).get("results", []):
        out.append({
            "source": r.get("unique_id", "").replace("source.ph_weather.", ""),
            "status": r.get("status"),
            "max_loaded_at": r.get("max_loaded_at"),
            "age_minutes": round((r.get("max_loaded_at_time_ago_in_s") or 0) / 60, 1),
        })
    return out


def columnar(rows, cols):
    """Column-oriented JSON keeps the files small: {"col": [v1, v2, ...]}."""
    return {c: [r[i] for r in rows] for i, c in enumerate(cols)}


def fmt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M")
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def query(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return cols, [[fmt(v) for v in row] for row in cur.fetchall()]


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"), default=str)


def record_dq(con, run_id, checked_at, details, freshness):
    con.execute("create schema if not exists ops")
    con.execute(
        """create table if not exists ops.dq_results (
            run_id varchar, checked_at timestamp, test_name varchar, test_type varchar,
            status varchar, failures integer, message varchar)"""
    )
    rows = [[run_id, checked_at, d["test_name"], d["test_type"], d["status"], d["failures"], d["message"]]
            for d in details]
    rows += [[run_id, checked_at, f"freshness_{f['source']}", "source_freshness", f["status"], 0,
              f"age {f['age_minutes']} min"] for f in freshness]
    if rows:
        con.executemany("insert into ops.dq_results values (?, ?, ?, ?, ?, ?, ?)", rows)
    # keep 30 days of DQ history
    con.execute("delete from ops.dq_results where checked_at < ? - interval 30 day", [checked_at])


def export(db_path, out_dir, target_dir, ingest_summary_path, now=None):
    now = now or datetime.now(timezone.utc)
    run_results = load_json(os.path.join(target_dir, "run_results.json"))
    sources = load_json(os.path.join(target_dir, "sources.json"))
    ingest = load_json(ingest_summary_path) or {}
    tests, nodes, details = summarize_tests(run_results)
    freshness = summarize_freshness(sources)

    con = duckdb.connect(db_path)
    try:
        run_id = ingest.get("run_id") or "manual"
        record_dq(con, run_id, now.replace(tzinfo=None), details, freshness)

        cols, cities = query(con, "select * from gold.dim_city order by latitude desc")
        write(os.path.join(out_dir, "cities.json"), [dict(zip(cols, r)) for r in cities])

        latest_loaded = con.execute("select max(loaded_at) from gold.fct_weather_hourly").fetchone()[0]

        # Current conditions: the latest non-forecast hour per city.
        cols, current = query(con, """
            select h.*, c.city_name, c.region
            from gold.fct_weather_hourly h join gold.dim_city c using (city_id)
            where not h.is_forecast
            qualify row_number() over (partition by h.city_id order by h.observed_at_local desc) = 1
            order by c.latitude desc
        """)
        write(os.path.join(out_dir, "current.json"), [dict(zip(cols, r)) for r in current])

        hourly_cols = ["observed_at_local", "is_forecast", "temperature_c", "apparent_temperature_c",
                       "relative_humidity_pct", "precipitation_mm", "wind_speed_kmh", "weather_code",
                       "heat_index_c", "pm2_5_ugm3", "pm10_ugm3", "us_aqi"]
        daily_cols = ["observed_date_local", "is_forecast_day", "hours_observed", "temp_min_c", "temp_max_c",
                      "temp_avg_c", "heat_index_max_c", "heat_category_max", "precipitation_total_mm",
                      "wind_max_kmh", "humidity_avg_pct", "pm2_5_avg_ugm3", "us_aqi_max", "aqi_category_max",
                      "weather_code_max", "weather_description"]
        for city in cities:
            city_id = city[0]
            _, hourly = query(con, f"""
                select {', '.join(hourly_cols)} from gold.fct_weather_hourly
                where city_id = ? and observed_at_local >= (now() at time zone 'Asia/Manila') - interval {HOURLY_HISTORY_DAYS} day
                order by observed_at_local""", [city_id])
            _, daily = query(con, f"""
                select {', '.join(daily_cols)} from gold.fct_weather_daily
                where city_id = ? and observed_date_local >= current_date - {DAILY_HISTORY_DAYS}
                order by observed_date_local""", [city_id])
            write(os.path.join(out_dir, "city", f"{city_id}.json"), {
                "city_id": city_id,
                "hourly": columnar(hourly, hourly_cols),
                "daily": columnar(daily, daily_cols),
            })

        counts = {}
        for name, table in [("bronze_weather", "bronze.raw_weather_hourly"),
                            ("bronze_air_quality", "bronze.raw_air_quality_hourly"),
                            ("silver_weather", "silver.stg_weather_hourly"),
                            ("silver_air_quality", "silver.stg_air_quality_hourly"),
                            ("gold_hourly", "gold.fct_weather_hourly"),
                            ("gold_daily", "gold.fct_weather_daily")]:
            counts[name] = con.execute(f"select count(*) from {table}").fetchone()[0]

        _, runs = query(con, """
            select run_id, finished_at, weather_rows, air_quality_rows, status
            from bronze.ingest_runs order by finished_at desc limit 48""")
        dq_rows = details + [{"test_name": f"freshness_{f['source']}", "test_type": "source_freshness",
                              "status": f["status"], "failures": 0, "message": f"age {f['age_minutes']} min"}
                             for f in freshness]
    finally:
        con.close()

    write(os.path.join(out_dir, "dq_results.json"), {"checked_at_utc": iso_utc(now), "results": dq_rows})

    gh_run = None
    if os.environ.get("GITHUB_RUN_ID"):
        gh_run = "{}/{}/actions/runs/{}".format(
            os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
            os.environ.get("GITHUB_REPOSITORY"), os.environ["GITHUB_RUN_ID"])
    fresh_status = "pass"
    for f in freshness:
        if f["status"] in ("error", "runtime error"):
            fresh_status = "error"
        elif f["status"] == "warn" and fresh_status == "pass":
            fresh_status = "warn"
    health = {
        "status": "healthy" if tests["fail"] == 0 and tests["error"] == 0 and nodes["error"] == 0
        and fresh_status != "error" else "degraded",
        "last_run_utc": iso_utc(now),
        "last_run_manila": iso_manila(now),
        "latest_data_loaded_utc": iso_utc(latest_loaded.replace(tzinfo=timezone.utc)) if latest_loaded else None,
        "run_id": ingest.get("run_id"),
        "github_run_url": gh_run,
        "rows_loaded": {"weather": ingest.get("weather_rows", 0), "air_quality": ingest.get("air_quality_rows", 0)},
        "bronze_rows_pruned": ingest.get("bronze_rows_pruned", 0),
        "cities": ingest.get("cities"),
        "tests": tests,
        "models": nodes,
        "freshness": {"status": fresh_status, "sources": freshness},
        "layer_row_counts": counts,
        "recent_runs": [dict(zip(["run_id", "finished_at_utc", "weather_rows", "air_quality_rows", "status"], r))
                        for r in runs],
    }
    write(os.path.join(out_dir, "pipeline_health.json"), health)
    return health


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default=os.environ.get("DUCKDB_PATH", "warehouse/weather.duckdb"))
    p.add_argument("--out", default="build/site/data")
    p.add_argument("--target", default="target")
    p.add_argument("--ingest-summary", default="build/ingest_summary.json")
    a = p.parse_args(argv)
    health = export(a.db, a.out, a.target, a.ingest_summary)
    print(json.dumps({k: health[k] for k in ("status", "last_run_manila", "tests", "layer_row_counts")}, indent=2))


if __name__ == "__main__":
    main()
