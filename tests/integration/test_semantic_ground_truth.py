"""A4 check: every metric served by the semantic API equals an independently written SQL query
on a fixed window. A metric can be valid YAML and still compute the wrong thing; this catches it.

Needs the local lake with the sample loaded and `make dbt-build` run (marts + semantic manifest).
"""

import math
from datetime import UTC, datetime

import pytest
import trino
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
WINDOW_SQL = (
    "period_utc >= TIMESTAMP '2026-09-01 00:00:00' AND period_utc < TIMESTAMP '2026-10-01 00:00:00'"
)


@pytest.fixture(scope="module")
def api():
    from gridpulse_semantic.app import app

    return TestClient(app)


@pytest.fixture(scope="module")
def sql():
    cur = trino.dbapi.connect(host="localhost", port=8080, user="test", catalog="lake").cursor()

    def run(query: str) -> dict:
        cur.execute(query)
        return {row[0]: row[1] for row in cur.fetchall()}

    return run


def by_ba(api, metric: str, **extra) -> dict:
    body = {
        "metrics": [metric],
        "group_by": ["balancing_authority"],
        "start": START.isoformat(),
        "end": END.isoformat(),
        **extra,
    }
    resp = api.post("/query", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return {row[0]: row[1] for row in data["rows"]}


def assert_same(api_values: dict, sql_values: dict):
    assert set(api_values) == set(sql_values) and api_values
    for key, expected in sql_values.items():
        assert math.isclose(api_values[key], expected, rel_tol=1e-9), (
            key,
            api_values[key],
            expected,
        )


def test_demand(api, sql):
    expected = sql(
        f"SELECT ba_code, sum(demand_mwh) FROM marts.fct_grid_hourly WHERE {WINDOW_SQL} GROUP BY 1"
    )
    assert_same(by_ba(api, "demand"), expected)


def test_peak_demand(api, sql):
    expected = sql(
        f"SELECT ba_code, max(demand_mwh) FROM marts.fct_grid_hourly WHERE {WINDOW_SQL} GROUP BY 1"
    )
    assert_same(by_ba(api, "peak_demand"), expected)


def test_forecast_error_mape(api, sql):
    expected = sql(
        f"""SELECT ba_code, avg(abs(demand_mwh - demand_forecast_mwh) / demand_mwh * 100)
        FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND demand_mwh > 0 AND demand_forecast_mwh IS NOT NULL GROUP BY 1"""
    )
    assert_same(by_ba(api, "forecast_error_mape"), expected)


def test_forecast_bias(api, sql):
    expected = sql(
        f"""SELECT ba_code, avg(demand_forecast_mwh - demand_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND demand_mwh IS NOT NULL AND demand_forecast_mwh IS NOT NULL
        GROUP BY 1"""
    )
    assert_same(by_ba(api, "forecast_bias"), expected)


def test_data_completeness_is_a_ratio_of_sums(api, sql):
    expected = sql(
        f"""SELECT ba_code, cast(count_if(is_demand_reported) AS double) / count(*)
        FROM marts.fct_grid_coverage_hourly WHERE {WINDOW_SQL} GROUP BY 1"""
    )
    assert_same(by_ba(api, "data_completeness"), expected)


def test_demand_month_to_date_shows_end_of_day_running_total(api, sql):
    expected = sql(
        """SELECT cast(day_utc AS varchar), mtd FROM (
             SELECT cast(period_utc AS date) AS day_utc,
                    sum(sum(demand_mwh)) OVER (
                      PARTITION BY date_trunc('month', cast(period_utc AS date))
                      ORDER BY cast(period_utc AS date)) AS mtd
             FROM marts.fct_grid_hourly
             WHERE ba_code = 'PJM' AND period_utc >= TIMESTAMP '2026-08-01 00:00:00'
               AND period_utc < TIMESTAMP '2026-09-04 00:00:00'
             GROUP BY 1)
           WHERE day_utc >= DATE '2026-08-29'"""
    )
    resp = api.post(
        "/query",
        json={
            "metrics": ["demand_month_to_date"],
            "group_by": ["metric_time__day"],
            "filters": [{"dimension": "balancing_authority", "values": ["PJM"]}],
            "start": "2026-08-29T00:00:00Z",
            "end": "2026-09-04T00:00:00Z",
        },
    )
    assert resp.status_code == 200, resp.text
    got = {row[0][:10]: row[1] for row in resp.json()["rows"]}
    assert_same(got, expected)


def test_unknown_metric_is_rejected_with_guidance(api):
    resp = api.post("/query", json={"metrics": ["revenue"]})
    assert resp.status_code == 422
    assert "GET /metrics" in resp.text


def test_second_identical_query_is_served_from_cache(api):
    body = {"metrics": ["demand"], "start": START.isoformat(), "end": END.isoformat()}
    first = api.post("/query", json=body).json()
    second = api.post("/query", json=body).json()
    assert second["cached"] is True and second["rows"] == first["rows"]


def test_catalog_exposes_agent_allow_list(api):
    agent = {m["name"] for m in api.get("/metrics", params={"agent_only": True}).json()}
    assert {"demand", "peak_demand", "forecast_error_mape", "data_completeness"} <= agent
    assert "expected_hours" not in agent  # building blocks stay hidden from the agent


def test_cache_refresh_invalidates_results(api):
    body = {"metrics": ["demand"], "start": START.isoformat(), "end": END.isoformat()}
    api.post("/query", json=body)
    version = api.post("/cache/refresh").json()["data_version"]
    after = api.post("/query", json=body).json()
    assert after["cached"] is False and after["data_version"] == version
