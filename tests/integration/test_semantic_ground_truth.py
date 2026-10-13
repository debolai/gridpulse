"""A4 check: every metric served by the semantic API equals an independently written SQL query
on a fixed window. A metric can be valid YAML and still compute the wrong thing; this catches it.

Needs the local lake with the sample loaded and `make dbt-build` run (marts + semantic manifest).
Metrics leave out values flagged suspect or invalid by default, so the reference queries apply
the same rule from the quality-status columns; the sample has no flagged values, so
test_flagged_values_are_left_out plants one.
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
def cursor():
    return trino.dbapi.connect(host="localhost", port=8080, user="test", catalog="lake").cursor()


@pytest.fixture(scope="module")
def sql(cursor):
    def run(query: str) -> dict:
        cursor.execute(query)
        return {row[0]: row[1] for row in cursor.fetchall()}

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
        f"""SELECT ba_code, sum(demand_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND demand_quality_status = 'ok' GROUP BY 1"""
    )
    assert_same(by_ba(api, "demand"), expected)


def test_peak_demand(api, sql):
    expected = sql(
        f"""SELECT ba_code, max(demand_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND demand_quality_status = 'ok' GROUP BY 1"""
    )
    assert_same(by_ba(api, "peak_demand"), expected)


def test_forecast_error_mape(api, sql):
    expected = sql(
        f"""SELECT ba_code, avg(abs(demand_mwh - demand_forecast_mwh) / demand_mwh * 100)
        FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND demand_mwh > 0
          AND demand_quality_status = 'ok' AND demand_forecast_quality_status = 'ok' GROUP BY 1"""
    )
    assert_same(by_ba(api, "forecast_error_mape"), expected)


def test_forecast_bias(api, sql):
    expected = sql(
        f"""SELECT ba_code, avg(demand_forecast_mwh - demand_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL}
          AND demand_quality_status = 'ok' AND demand_forecast_quality_status = 'ok' GROUP BY 1"""
    )
    assert_same(by_ba(api, "forecast_bias"), expected)


def test_data_completeness_is_a_ratio_of_sums(api, sql):
    # Valid hours come from the grid fact's quality status, not the coverage mart's flag.
    expected = sql(
        f"""SELECT c.ba_code, cast(count_if(g.demand_quality_status = 'ok') AS double) / count(*)
        FROM marts.fct_grid_coverage_hourly c
        LEFT JOIN marts.fct_grid_hourly g ON g.ba_code = c.ba_code AND g.period_utc = c.period_utc
        WHERE {WINDOW_SQL.replace("period_utc", "c.period_utc")} GROUP BY 1"""
    )
    assert_same(by_ba(api, "data_completeness"), expected)


def test_net_generation(api, sql):
    expected = sql(
        f"""SELECT ba_code, sum(net_generation_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} AND net_generation_quality_status = 'ok' GROUP BY 1"""
    )
    assert_same(by_ba(api, "net_generation"), expected)


def test_generation_by_fuel_category(api, sql):
    expected = sql(
        f"""SELECT f.ba_code || '/' || d.fuel_category, sum(f.generation_mwh)
        FROM marts.fct_generation_by_fuel_hourly f
        JOIN marts.dim_fuel_type d ON d.fuel_code = f.fuel_code
        WHERE {WINDOW_SQL} GROUP BY 1"""
    )
    resp = api.post(
        "/query",
        json={
            "metrics": ["generation_by_fuel"],
            "group_by": ["balancing_authority", "fuel_type__fuel_category"],
            "start": START.isoformat(),
            "end": END.isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    got = {f"{ba}/{category}": value for ba, category, value in resp.json()["rows"]}
    assert_same(got, expected)


def test_renewable_share_is_a_ratio_of_sums(api, sql):
    expected = sql(
        f"""SELECT f.ba_code,
            sum(CASE WHEN d.is_renewable THEN f.generation_mwh END) / sum(f.generation_mwh)
        FROM marts.fct_generation_by_fuel_hourly f
        JOIN marts.dim_fuel_type d ON d.fuel_code = f.fuel_code
        WHERE {WINDOW_SQL} GROUP BY 1"""
    )
    got = by_ba(api, "renewable_share")
    assert_same(got, expected)
    # Guard against the classic mistake: the average of hourly shares is a different number.
    hourly_mean = sql(
        f"""SELECT ba_code, avg(share) FROM (
            SELECT f.ba_code, f.period_utc,
                sum(CASE WHEN d.is_renewable THEN f.generation_mwh END) / sum(f.generation_mwh)
                    AS share
            FROM marts.fct_generation_by_fuel_hourly f
            JOIN marts.dim_fuel_type d ON d.fuel_code = f.fuel_code
            WHERE {WINDOW_SQL} GROUP BY 1, 2)
        GROUP BY 1"""
    )
    assert any(not math.isclose(got[ba], hourly_mean[ba], rel_tol=1e-3) for ba in got)


def test_renewable_flag_filter(api, sql):
    expected = sql(
        f"""SELECT f.ba_code, sum(f.generation_mwh) FROM marts.fct_generation_by_fuel_hourly f
        JOIN marts.dim_fuel_type d ON d.fuel_code = f.fuel_code
        WHERE {WINDOW_SQL} AND NOT d.is_renewable GROUP BY 1"""
    )
    filters = [{"dimension": "fuel_type__is_renewable", "values": ["false"]}]
    assert_same(by_ba(api, "generation_by_fuel", filters=filters), expected)


def test_net_imports_flips_the_interchange_sign(api, sql):
    expected = sql(
        f"""SELECT ba_code, -sum(total_interchange_mwh) FROM marts.fct_grid_hourly
        WHERE {WINDOW_SQL} GROUP BY 1"""
    )
    assert_same(by_ba(api, "net_imports"), expected)


# Written from BA-hours, not from fct_demand_scope_hourly, so it checks the mart as well.
COINCIDENT_SQL = f"""SELECT interconnection, max(total) FROM (
    SELECT b.interconnection, g.period_utc, sum(g.demand_mwh) AS total
    FROM marts.fct_grid_hourly g
    JOIN marts.dim_balancing_authority b ON b.ba_code = g.ba_code
    WHERE {WINDOW_SQL} AND g.demand_quality_status = 'ok' GROUP BY 1, 2)
GROUP BY 1"""


def coincident_by_interconnection(api, **extra) -> dict:
    resp = api.post(
        "/query",
        json={
            "metrics": ["coincident_peak_demand"],
            "group_by": ["demand_scope__scope_code"],
            "filters": [
                {"dimension": "demand_scope__scope_type", "values": ["interconnection"]},
                *extra.pop("filters", []),
            ],
            "start": START.isoformat(),
            "end": END.isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    return {row[0]: row[1] for row in resp.json()["rows"]}


def test_coincident_peak_is_the_max_of_combined_hours(api, sql):
    got = coincident_by_interconnection(api)
    assert_same(got, sql(COINCIDENT_SQL))
    own_peaks = sql(
        f"""SELECT b.interconnection, sum(p) FROM (
            SELECT ba_code, max(demand_mwh) AS p FROM marts.fct_grid_hourly
            WHERE {WINDOW_SQL} GROUP BY 1) x
        JOIN marts.dim_balancing_authority b ON b.ba_code = x.ba_code GROUP BY 1"""
    )
    # BAs peak at different hours, so the combined peak sits below the sum of their own peaks
    # wherever an interconnection has more than one BA.
    assert got["Eastern"] < own_peaks["Eastern"]


def test_coincident_peak_can_skip_incomplete_hours(api, sql):
    expected = sql(
        f"""SELECT scope_code, max(demand_mwh) FROM marts.fct_demand_scope_hourly
        WHERE {WINDOW_SQL} AND scope_type = 'interconnection' AND is_complete GROUP BY 1"""
    )
    complete = [{"dimension": "demand_scope__is_complete", "values": ["true"]}]
    assert_same(coincident_by_interconnection(api, filters=complete), expected)


def test_cooling_degree_hours(api, sql):
    expected = sql(
        f"""SELECT ba_code, sum(CASE WHEN temperature_c > 18.3 THEN temperature_c - 18.3 ELSE 0 END)
        FROM marts.fct_grid_hourly WHERE {WINDOW_SQL} AND temperature_c IS NOT NULL GROUP BY 1"""
    )
    assert_same(by_ba(api, "cooling_degree_hours"), expected)


def test_revision_rate_counts_revised_values_among_rechecked_ones(api, sql):
    # Written from the revision audit and the raw observations, not from fct_value_checks_hourly.
    expected = sql(
        """WITH obs AS (
             SELECT 'region-data' AS route, ba_code, series_code AS item, period_utc,
                 ingested_at_utc
             FROM staging.stg_eia__region_data
             UNION ALL
             SELECT 'fuel-type-data', ba_code, fuel_code, period_utc, ingested_at_utc
             FROM staging.stg_eia__fuel_type_data
             UNION ALL
             SELECT 'interchange-data', from_ba_code, to_ba_code, period_utc, ingested_at_utc
             FROM staging.stg_eia__interchange_data),
           rechecked AS (
             SELECT route, ba_code, item, period_utc FROM obs
             GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT ingested_at_utc) >= 2),
           revised AS (
             SELECT DISTINCT route, ba_code, item_code AS item, period_utc
             FROM marts.fct_data_revisions)
           SELECT c.ba_code, cast(count(r.ba_code) AS double) / count(*)
           FROM rechecked c LEFT JOIN revised r
             ON r.route = c.route AND r.ba_code = c.ba_code AND r.item = c.item
             AND r.period_utc = c.period_utc
           GROUP BY 1"""
    )
    resp = api.post(
        "/query", json={"metrics": ["revision_rate"], "group_by": ["balancing_authority"]}
    )
    assert resp.status_code == 200, resp.text
    got = {row[0]: row[1] for row in resp.json()["rows"]}
    assert_same(got, expected)
    assert any(rate > 0 for rate in got.values())  # the re-pulls found real revisions


def test_demand_month_to_date_shows_end_of_day_running_total(api, sql):
    expected = sql(
        """SELECT cast(day_utc AS varchar), mtd FROM (
             SELECT cast(period_utc AS date) AS day_utc,
                    sum(sum(demand_mwh)) OVER (
                      PARTITION BY date_trunc('month', cast(period_utc AS date))
                      ORDER BY cast(period_utc AS date)) AS mtd
             FROM marts.fct_grid_hourly
             WHERE ba_code = 'PJM' AND demand_quality_status = 'ok'
               AND period_utc >= TIMESTAMP '2026-08-01 00:00:00'
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
    # Exact on purpose: a metric joining or leaving the agent's allow-list shows up in review.
    agent = {m["name"] for m in api.get("/metrics", params={"agent_only": True}).json()}
    assert agent == {
        "demand",
        "peak_demand",
        "forecast_error_mape",
        "data_completeness",
        "net_generation",
        "generation_by_fuel",
        "renewable_share",
        "net_imports",
        "coincident_peak_demand",
        "cooling_degree_hours",
        "revision_rate",
        "flagged_values",
        "forecast_bias",
        "renewable_generation",
        "demand_month_to_date",
    }
    # Building blocks of ratios stay hidden: expected_hours, demand_hours_reported,
    # demand_hours_valid, values_rechecked, values_revised.


def test_agent_saved_queries_run_as_plain_requests(api):
    saved = api.get("/saved-queries", params={"agent_only": True}).json()
    assert {q["name"] for q in saved} >= {"daily_demand_by_ba", "monthly_system_peaks"}
    window = {"start": START.isoformat(), "end": END.isoformat()}
    for q in saved:
        body = {"metrics": q["metrics"], "group_by": q["group_by"], **window}
        resp = api.post("/query", json=body)
        assert resp.status_code == 200 and resp.json()["rows"], (q["name"], resp.text)


def test_results_say_what_was_left_out(api):
    body = {
        "metrics": ["demand", "net_imports"],
        "start": START.isoformat(),
        "end": END.isoformat(),
    }
    notes = api.post("/query", json=body).json()["notes"]
    assert len(notes) == 1 and "flagged" in notes[0]  # net_imports has no quality note


SPIKE_KEY = "ba_code = 'PJM' AND period_utc = TIMESTAMP '2026-09-15 18:00:00'"


def test_flagged_values_are_left_out(api, cursor, sql):
    """Plant a flagged 10x spike in one PJM hour (restored afterwards): every metric must ignore
    it, while flagged_values counts it."""

    def pjm(metric: str) -> float:
        api.post("/cache/refresh")
        return by_ba(api, metric)["PJM"]

    cursor.execute(
        f"SELECT demand_mwh, demand_quality_status FROM marts.fct_grid_hourly WHERE {SPIKE_KEY}"
    )
    ((value, status),) = cursor.fetchall()
    assert status == "ok"
    before = {m: pjm(m) for m in ("demand", "peak_demand", "forecast_error_mape", "flagged_values")}
    assert value * 10 > before["peak_demand"]  # unfiltered, the spike would be the peak
    try:
        cursor.execute(
            "UPDATE marts.fct_grid_hourly SET demand_mwh = demand_mwh * 10, "
            f"demand_quality_status = 'suspect' WHERE {SPIKE_KEY}"
        )
        cursor.fetchall()
        assert pjm("peak_demand") == before["peak_demand"]
        assert math.isclose(pjm("demand"), before["demand"] - value, rel_tol=1e-12)
        assert pjm("forecast_error_mape") != before["forecast_error_mape"]  # hour dropped
        assert pjm("flagged_values") == before["flagged_values"] + 1
    finally:
        cursor.execute(
            f"UPDATE marts.fct_grid_hourly SET demand_mwh = {value!r}, "
            f"demand_quality_status = 'ok' WHERE {SPIKE_KEY}"
        )
        cursor.fetchall()
        api.post("/cache/refresh")
    assert sql(
        f"SELECT demand_mwh, demand_quality_status FROM marts.fct_grid_hourly WHERE {SPIKE_KEY}"
    ) == {value: "ok"}


def test_cache_refresh_invalidates_results(api):
    body = {"metrics": ["demand"], "start": START.isoformat(), "end": END.isoformat()}
    api.post("/query", json=body)
    version = api.post("/cache/refresh").json()["data_version"]
    after = api.post("/query", json=body).json()
    assert after["cached"] is False and after["data_version"] == version


def test_agent_inspection_queries_match_sql(api, sql):
    """The agent's coverage and freshness checks, through the real API, equal hand SQL."""
    from gridpulse_agent.contract import MetricRequest
    from gridpulse_agent.semantic_client import SemanticClient

    client = SemanticClient("http://testserver", http=api)
    request = MetricRequest.model_validate(
        {
            "metrics": ["coincident_peak_demand"],
            "filters": [{"dimension": "demand_scope__scope_code", "values": ["Eastern"]}],
            "start": START.isoformat(),
            "end": END.isoformat(),
        }
    )
    expected = sql(
        f"""SELECT c.ba_code, count_if(g.demand_quality_status = 'ok')
        FROM marts.fct_grid_coverage_hourly c
        JOIN marts.dim_balancing_authority b ON b.ba_code = c.ba_code
        LEFT JOIN marts.fct_grid_hourly g ON g.ba_code = c.ba_code AND g.period_utc = c.period_utc
        WHERE {WINDOW_SQL.replace("period_utc", "c.period_utc")} AND b.interconnection = 'Eastern'
        GROUP BY 1"""
    )
    rows = client.coverage(request)
    assert {ba: valid for ba, valid, _ in rows} == expected
    latest = sql(
        "SELECT 1, max(period_utc) FROM marts.fct_grid_hourly WHERE demand_mwh IS NOT NULL"
    )
    assert client.latest_hour() == latest[1]


def test_agent_region_lookup_lists_every_active_ba(api, sql):
    """The clarify rule's BA -> region list covers the whole reference, not just BAs with data."""
    from gridpulse_agent.semantic_client import SemanticClient

    got = {b["code"]: b["region"] for b in SemanticClient("http://t", http=api).ba_regions()}
    expected = sql(
        "SELECT ba_code, region_code FROM marts.dim_balancing_authority "
        "WHERE retirement_date IS NULL"
    )
    assert got == expected and len(got) > 50
