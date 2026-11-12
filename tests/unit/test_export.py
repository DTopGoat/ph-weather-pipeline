from datetime import datetime, timezone

from scripts import export_gold


def test_summarize_tests_counts_only_tests():
    run_results = {"results": [
        {"unique_id": "model.ph_weather.stg_weather_hourly", "status": "success"},
        {"unique_id": "seed.ph_weather.cities", "status": "success"},
        {"unique_id": "test.ph_weather.not_null_x.abc", "status": "pass", "failures": 0},
        {"unique_id": "test.ph_weather.accepted_range_y.def", "status": "fail", "failures": 3, "message": "Got 3"},
        {"unique_id": "test.ph_weather.z.ghi", "status": "warn", "failures": 1},
    ]}
    tests, nodes, details = export_gold.summarize_tests(run_results)
    assert tests["pass"] == 1 and tests["fail"] == 1 and tests["warn"] == 1
    assert nodes["success"] == 2
    assert {d["test_name"] for d in details} == {"not_null_x", "accepted_range_y", "z"}


def test_summarize_tests_handles_missing_artifact():
    tests, nodes, details = export_gold.summarize_tests(None)
    assert sum(tests.values()) == 0 and details == []


def test_summarize_freshness():
    sources = {"results": [{"unique_id": "source.ph_weather.bronze.raw_weather_hourly", "status": "pass",
                            "max_loaded_at": "2026-11-12T09:00:00", "max_loaded_at_time_ago_in_s": 600}]}
    out = export_gold.summarize_freshness(sources)
    assert out == [{"source": "bronze.raw_weather_hourly", "status": "pass",
                    "max_loaded_at": "2026-11-12T09:00:00", "age_minutes": 10.0}]


def test_columnar_and_time_formatting():
    rows = [["a", 1], ["b", 2]]
    assert export_gold.columnar(rows, ["k", "v"]) == {"k": ["a", "b"], "v": [1, 2]}
    assert export_gold.fmt(datetime(2026, 11, 12, 7, 0)) == "2026-11-12T07:00"


def test_manila_conversion():
    dt = datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc)
    assert export_gold.iso_manila(dt) == "2026-11-13T07:30:00+08:00"
    assert export_gold.iso_utc(dt) == "2026-11-12T23:30:00Z"
