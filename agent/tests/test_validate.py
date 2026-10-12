import pytest
from conftest import req

from gridpulse_agent.validate import validate


def check(request, catalog):
    return validate(request, catalog, max_window_days=400, max_rows=1000)


def test_valid_requests_pass(catalog):
    assert check(req(group_by=["balancing_authority", "metric_time__day"]), catalog) == []
    assert check(req(group_by=["grid_hour__hour_local"]), catalog) == []
    assert (
        check(
            req(
                filters=[
                    {"dimension": "balancing_authority__interconnection", "values": ["Western"]}
                ]
            ),
            catalog,
        )
        == []
    )


def test_unknown_metric_lists_the_allowed_ones(catalog):
    (error,) = check(req(metrics=["revenue"]), catalog)
    assert "revenue" in error and "demand" in error


def test_hidden_building_block_metrics_are_not_allowed(catalog):
    assert check(req(metrics=["expected_hours"]), catalog)


def test_dimension_not_shared_by_all_metrics(catalog):
    # data_completeness lives on the coverage model, which has no local-hour dimension
    errors = check(
        req(metrics=["demand", "data_completeness"], group_by=["grid_hour__hour_local"]), catalog
    )
    assert any("grid_hour__hour_local" in e for e in errors)


@pytest.mark.parametrize(
    "overrides",
    [
        {"metrics": ["peak_demand"]},
        {"metrics": ["peak_demand"], "group_by": ["balancing_authority__interconnection"]},
        {
            "metrics": ["peak_demand"],
            "filters": [
                {"dimension": "balancing_authority", "op": "in", "values": ["PJM", "MISO"]}
            ],
        },
    ],
)
def test_peak_demand_across_bas_is_blocked(catalog, overrides):
    errors = check(req(**overrides), catalog)
    assert any("single BA-hour" in e for e in errors)


@pytest.mark.parametrize(
    "overrides",
    [
        {"metrics": ["peak_demand"], "group_by": ["balancing_authority"]},
        {
            "metrics": ["peak_demand"],
            "filters": [{"dimension": "balancing_authority", "values": ["PJM"]}],
        },
    ],
)
def test_peak_demand_per_ba_is_fine(catalog, overrides):
    assert check(req(**overrides), catalog) == []


def test_window_limits(catalog):
    assert check(req(start="2026-10-01T00:00:00Z", end="2026-09-01T00:00:00Z"), catalog)
    assert check(req(start="2024-01-01T00:00:00Z", end="2026-01-01T00:00:00Z"), catalog)
