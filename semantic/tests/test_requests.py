from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from gridpulse_semantic.requests import Filter, MetricRequest, render_where

ENTITIES = {"balancing_authority"}


def test_time_window_is_half_open_typed_and_hourly():
    req = MetricRequest(
        metrics=["demand"],
        start=datetime(2026, 9, 1, tzinfo=UTC),
        end=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert render_where(req, ENTITIES) == [
        "{{ TimeDimension('metric_time', 'hour') }} >= TIMESTAMP '2026-09-01 00:00:00'",
        "{{ TimeDimension('metric_time', 'hour') }} < TIMESTAMP '2026-10-01 00:00:00'",
    ]


def test_entity_and_dimension_filters_render_differently():
    req = MetricRequest(
        metrics=["demand"],
        filters=[
            Filter(dimension="balancing_authority", values=["PJM"]),
            Filter(
                dimension="balancing_authority__interconnection",
                op="in",
                values=["Eastern", "ERCOT"],
            ),
        ],
    )
    assert render_where(req, ENTITIES) == [
        "{{ Entity('balancing_authority') }} = 'PJM'",
        "{{ Dimension('balancing_authority__interconnection') }} IN ('Eastern', 'ERCOT')",
    ]


def test_values_are_escaped_not_injected():
    req = MetricRequest(
        metrics=["demand"],
        filters=[Filter(dimension="balancing_authority__ba_name", values=["x' OR '1'='1"])],
    )
    (clause,) = render_where(req, ENTITIES)
    assert clause.endswith("= 'x'' OR ''1''=''1'")


@pytest.mark.parametrize(
    "bad",
    [
        {"metrics": []},
        {"metrics": ["demand; drop table x"]},
        {"metrics": ["demand"], "group_by": ["metric_time__day) --"]},
        {"metrics": ["demand"], "order_by": ["-demand desc"]},
        {"metrics": ["demand"], "limit": 100_000},
        {"metrics": ["demand"], "start": "2026-09-02T00:00:00Z", "end": "2026-09-01T00:00:00Z"},
        {"metrics": ["demand"], "filters": [{"dimension": "x", "op": "=", "values": ["a", "b"]}]},
        {"metrics": ["demand"], "filters": [{"dimension": "x", "op": "like", "values": ["a"]}]},
    ],
)
def test_rejects_unsafe_or_malformed_requests(bad):
    with pytest.raises(ValidationError):
        MetricRequest.model_validate(bad)


def test_non_utc_times_are_rejected():
    plus_one = timezone(timedelta(hours=1))
    with pytest.raises(ValidationError):
        MetricRequest(metrics=["demand"], start=datetime(2026, 9, 1, tzinfo=plus_one))
