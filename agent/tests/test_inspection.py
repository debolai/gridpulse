from datetime import datetime

from conftest import req

from gridpulse_agent.inspection import caveats, coverage_request, has_data

LATEST = datetime(2026, 10, 12, 9)


def test_a_row_of_nulls_is_no_data():
    columns = ["balancing_authority", "demand"]
    assert not has_data({"columns": ["demand"], "rows": [[None]]}, ["demand"])
    assert not has_data({"columns": columns, "rows": []}, ["demand"])
    assert not has_data({"columns": columns, "rows": [["PJM", None]]}, ["demand"])
    assert has_data({"columns": columns, "rows": [["PJM", None], ["MISO", 0.0]]}, ["demand"])


def test_coverage_keeps_ba_filters_and_maps_scopes_to_bas():
    request = req(
        metrics=["coincident_peak_demand"],
        filters=[{"dimension": "demand_scope__scope_code", "values": ["CAL"]}],
    )
    cov = coverage_request(request)
    assert cov.metrics == ["demand_hours_valid", "expected_hours"]
    assert cov.group_by == ["balancing_authority"]
    assert [(f.dimension, f.values) for f in cov.filters] == [
        ("balancing_authority__region", ["CAL"])
    ]
    assert (cov.start, cov.end) == (request.start, request.end)


def test_coverage_scope_mapping():
    def mapped(values, op="in"):
        f = {"dimension": "demand_scope__scope_code", "op": op, "values": values}
        return [(f.dimension, f.values) for f in coverage_request(req(filters=[f])).filters]

    assert mapped(["Western"]) == [("balancing_authority__interconnection", ["Western"])]
    assert mapped(["US48"]) == []  # every BA
    assert mapped(["Eastern", "CAL"]) == []  # can't OR two dimensions: every BA
    assert mapped(["CAL"], op="not in") == []


def test_coverage_drops_filters_that_dont_apply():
    request = req(
        filters=[
            {"dimension": "balancing_authority", "values": ["CISO"]},
            {"dimension": "fuel_type__is_renewable", "values": ["true"]},
        ]
    )
    assert [f.dimension for f in coverage_request(request).filters] == ["balancing_authority"]


def test_completeness_is_a_ratio_of_sums_and_names_the_weakest_ba():
    rows = [["PJM", 720, 720], ["MISO", 600, 720], ["ISNE", 719, 720]]
    out = caveats(req(), rows, LATEST, 30)
    # (720 + 600 + 719) / 2160 = 94.398%, rounded down.
    assert out[0] == "Data: 94.3% of expected BA-hours have valid demand (lowest: MISO, 83.3%)."
    uneven = caveats(req(), [["A", 10, 10], ["B", 0, 90]], LATEST, 30)
    assert uneven[0].startswith("Data: 10% of expected")  # not (100% + 0%) / 2 = 50%


def test_percentages_round_down_so_gaps_never_read_as_complete():
    out = caveats(req(), [["PJM", 9999, 10000]], LATEST, 30)
    assert out[0] == "Data: 99.9% of expected BA-hours have valid demand."


def test_window_past_the_latest_hour_and_inside_the_revision_window():
    october = req(start="2026-10-01T00:00:00Z", end="2026-11-01T00:00:00Z")
    out = caveats(october, [["PJM", 270, 270]], LATEST, 30)
    assert out[1] == (
        "Latest hour loaded: 2026-10-12 09:00 UTC; the window runs past it, "
        "so its last part has no data yet."
    )
    assert out[2].startswith("Hours after 2026-09-12 are recent; EIA may still revise them")


def test_old_windows_get_no_revision_caveat():
    out = caveats(req(start="2026-07-01T00:00:00Z", end="2026-08-01T00:00:00Z"), [], LATEST, 30)
    assert out == [
        "Data: no hours were expected from these BAs in this window.",
        "Latest hour loaded: 2026-10-12 09:00 UTC.",
    ]


def test_unknown_freshness_and_coverage_are_said_out_loud():
    assert caveats(req(), None, None, 30) == [
        "Couldn't check data completeness.",
        "Couldn't check data freshness.",
    ]
