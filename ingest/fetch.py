"""Fetch hourly weather and air quality from Open-Meteo and append to the Bronze layer.

Bronze is append-only: every run inserts the raw hourly rows it received, tagged
with the run id and a UTC load timestamp. Deduplication happens downstream in dbt.

Usage:
    python -m ingest.fetch                 # normal hourly run (past 1 day + 7-day forecast)
    python -m ingest.fetch --past-days 30  # backfill up to 92 days of recent history
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import duckdb
import requests

from ingest.cities import CITIES

log = logging.getLogger("ingest")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

WEATHER_VARS = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "weather_code",
]
AIR_VARS = ["pm2_5", "pm10", "us_aqi"]

USER_AGENT = "ph-weather-pipeline/1.0 (+https://github.com/DTopGoat/ph-weather-pipeline)"


class FetchError(RuntimeError):
    pass


def get_json(session, url, params, retries=4, backoff=2.0, timeout=30, sleep=time.sleep):
    """GET a JSON payload, retrying on network errors, 429 and 5xx with exponential backoff."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = FetchError(f"HTTP {resp.status_code} from {url}")
            else:
                # 4xx other than 429 means a bad request; retrying will not help.
                raise FetchError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
        except requests.RequestException as exc:
            last_error = exc
        if attempt < retries:
            wait = backoff ** attempt
            log.warning("attempt %s/%s failed (%s); retrying in %.0fs", attempt, retries, last_error, wait)
            sleep(wait)
    raise FetchError(f"giving up on {url} after {retries} attempts: {last_error}")


def flatten_hourly(payload, variables):
    """Turn Open-Meteo's column-oriented `hourly` block into a list of row dicts."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    missing = [v for v in variables if v not in hourly]
    if missing:
        raise FetchError(f"response missing hourly variables: {missing}")
    rows = []
    for i, ts in enumerate(times):
        row = {"local_time": ts}
        for var in variables:
            values = hourly[var]
            row[var] = values[i] if i < len(values) else None
        rows.append(row)
    return rows


def build_params(city, variables, past_days, forecast_days):
    return {
        "latitude": city["latitude"],
        "longitude": city["longitude"],
        "hourly": ",".join(variables),
        "past_days": past_days,
        "forecast_days": forecast_days,
        "timezone": "Asia/Manila",
    }


BRONZE_DDL = """
create schema if not exists bronze;
create table if not exists bronze.raw_weather_hourly (
    run_id varchar, loaded_at timestamp, city_id varchar, local_time varchar,
    temperature_2m double, apparent_temperature double, relative_humidity_2m double,
    precipitation double, wind_speed_10m double, weather_code double
);
create table if not exists bronze.raw_air_quality_hourly (
    run_id varchar, loaded_at timestamp, city_id varchar, local_time varchar,
    pm2_5 double, pm10 double, us_aqi double
);
create table if not exists bronze.ingest_runs (
    run_id varchar, started_at timestamp, finished_at timestamp,
    weather_rows integer, air_quality_rows integer, cities integer, past_days integer, status varchar
);
"""


def ensure_bronze(con):
    con.execute(BRONZE_DDL)


def insert_rows(con, table, run_id, loaded_at, city_id, rows, variables):
    if not rows:
        return 0
    cols = ["run_id", "loaded_at", "city_id", "local_time", *variables]
    data = [[run_id, loaded_at, city_id, r["local_time"], *[r[v] for v in variables]] for r in rows]
    placeholders = ",".join(["?"] * len(cols))
    con.executemany(f"insert into {table} ({','.join(cols)}) values ({placeholders})", data)
    return len(data)


def prune_bronze(con, retention_days):
    """Keep Bronze bounded: drop raw loads older than the retention window.

    Silver keeps the deduplicated history forever, so pruning raw loads only
    removes superseded duplicates of hours that Silver already holds.
    """
    deleted = 0
    for table in ("bronze.raw_weather_hourly", "bronze.raw_air_quality_hourly"):
        before = con.execute(f"select count(*) from {table}").fetchone()[0]
        con.execute(
            f"delete from {table} where loaded_at < (now() at time zone 'UTC') - interval ({retention_days}) day"
        )
        deleted += before - con.execute(f"select count(*) from {table}").fetchone()[0]
    return deleted


def run(db_path, past_days=1, forecast_days=7, retention_days=14, session=None):
    session = session or requests.Session()
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    weather_rows = air_rows = 0

    # Fetch everything first so a failed API call never leaves a half-written run in Bronze.
    fetched = []
    for city in CITIES:
        w = get_json(session, FORECAST_URL, build_params(city, WEATHER_VARS, past_days, forecast_days))
        a = get_json(session, AIR_QUALITY_URL, build_params(city, AIR_VARS, past_days, min(forecast_days, 7)))
        fetched.append((city["city_id"], flatten_hourly(w, WEATHER_VARS), flatten_hourly(a, AIR_VARS)))
        log.info("%s: %s weather rows, %s air rows", city["city_id"], len(fetched[-1][1]), len(fetched[-1][2]))

    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    con = duckdb.connect(db_path)
    try:
        ensure_bronze(con)
        con.execute("begin")
        for city_id, wrows, arows in fetched:
            weather_rows += insert_rows(con, "bronze.raw_weather_hourly", run_id, loaded_at, city_id, wrows, WEATHER_VARS)
            air_rows += insert_rows(con, "bronze.raw_air_quality_hourly", run_id, loaded_at, city_id, arows, AIR_VARS)
        pruned = prune_bronze(con, retention_days)
        finished = datetime.now(timezone.utc).replace(tzinfo=None)
        con.execute(
            "insert into bronze.ingest_runs values (?, ?, ?, ?, ?, ?, ?, ?)",
            [run_id, started, finished, weather_rows, air_rows, len(fetched), past_days, "success"],
        )
        con.execute("commit")
    finally:
        con.close()
    summary = {
        "run_id": run_id,
        "loaded_at_utc": loaded_at.isoformat() + "Z",
        "weather_rows": weather_rows,
        "air_quality_rows": air_rows,
        "cities": len(fetched),
        "bronze_rows_pruned": pruned,
    }
    log.info("ingest summary: %s", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("DUCKDB_PATH", "warehouse/weather.duckdb"))
    parser.add_argument("--past-days", type=int, default=1, help="hours of recent history to request (0-92 days)")
    parser.add_argument("--forecast-days", type=int, default=7)
    parser.add_argument("--retention-days", type=int, default=14, help="days of raw Bronze loads to keep")
    parser.add_argument("--summary-out", default="build/ingest_summary.json")
    args = parser.parse_args(argv)
    if not 0 <= args.past_days <= 92:
        parser.error("--past-days must be between 0 and 92")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    summary = run(args.db, args.past_days, args.forecast_days, args.retention_days)
    os.makedirs(os.path.dirname(args.summary_out) or ".", exist_ok=True)
    with open(args.summary_out, "w") as fh:
        json.dump(summary, fh, indent=2)


if __name__ == "__main__":
    main()
