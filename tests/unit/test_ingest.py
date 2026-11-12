from datetime import datetime, timedelta

import duckdb
import pytest
import requests

from ingest import fetch
from ingest.cities import CITIES


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def no_sleep(_):
    pass


def test_get_json_retries_on_5xx_then_succeeds():
    session = FakeSession([FakeResponse(503), requests.ConnectionError("boom"), FakeResponse(200, {"ok": 1})])
    assert fetch.get_json(session, "u", {}, retries=3, sleep=no_sleep) == {"ok": 1}
    assert session.calls == 3


def test_get_json_does_not_retry_on_400():
    session = FakeSession([FakeResponse(400, text="bad param"), FakeResponse(200, {"ok": 1})])
    with pytest.raises(fetch.FetchError, match="400"):
        fetch.get_json(session, "u", {}, retries=3, sleep=no_sleep)
    assert session.calls == 1


def test_get_json_gives_up_after_retries():
    session = FakeSession([FakeResponse(429)] * 3)
    with pytest.raises(fetch.FetchError, match="giving up"):
        fetch.get_json(session, "u", {}, retries=3, sleep=no_sleep)


def test_flatten_hourly_builds_rows():
    payload = {"hourly": {"time": ["2026-11-12T00:00", "2026-11-12T01:00"], "pm2_5": [5.0, None], "us_aqi": [20, 21]}}
    rows = fetch.flatten_hourly(payload, ["pm2_5", "us_aqi"])
    assert rows == [
        {"local_time": "2026-11-12T00:00", "pm2_5": 5.0, "us_aqi": 20},
        {"local_time": "2026-11-12T01:00", "pm2_5": None, "us_aqi": 21},
    ]


def test_flatten_hourly_rejects_missing_variables():
    with pytest.raises(fetch.FetchError, match="missing"):
        fetch.flatten_hourly({"hourly": {"time": []}}, ["pm2_5"])


def test_build_params_uses_manila_timezone():
    p = fetch.build_params(CITIES[0], ["temperature_2m"], 1, 7)
    assert p["timezone"] == "Asia/Manila" and p["past_days"] == 1 and p["forecast_days"] == 7


def test_insert_is_append_only_and_prune_respects_retention():
    con = duckdb.connect()
    fetch.ensure_bronze(con)
    rows = [{"local_time": "2026-11-12T00:00", "pm2_5": 1.0, "pm10": 2.0, "us_aqi": 3}]
    now = datetime.utcnow()
    fetch.insert_rows(con, "bronze.raw_air_quality_hourly", "r1", now - timedelta(days=20), "cebu", rows, fetch.AIR_VARS)
    fetch.insert_rows(con, "bronze.raw_air_quality_hourly", "r2", now, "cebu", rows, fetch.AIR_VARS)
    assert con.execute("select count(*) from bronze.raw_air_quality_hourly").fetchone()[0] == 2
    deleted = fetch.prune_bronze(con, retention_days=14)
    assert deleted == 1
    assert con.execute("select run_id from bronze.raw_air_quality_hourly").fetchall() == [("r2",)]


def test_cities_have_unique_ids_and_ph_coordinates():
    ids = [c["city_id"] for c in CITIES]
    assert len(ids) == len(set(ids)) == 6
    for c in CITIES:
        assert 4 <= c["latitude"] <= 21 and 116 <= c["longitude"] <= 127


def test_cities_match_dbt_seed():
    import csv
    with open("seeds/cities.csv") as fh:
        seed_ids = {r["city_id"] for r in csv.DictReader(fh)}
    assert seed_ids == {c["city_id"] for c in CITIES}
