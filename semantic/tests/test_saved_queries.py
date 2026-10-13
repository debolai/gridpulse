import pytest

from gridpulse_semantic.engine import group_by_name


@pytest.mark.parametrize(
    ("spec", "name"),
    [
        ("Entity('balancing_authority')", "balancing_authority"),
        ("Dimension('fuel_type__fuel_category')", "fuel_type__fuel_category"),
        ("TimeDimension('metric_time', 'day')", "metric_time__day"),
        ("TimeDimension('metric_time','month')", "metric_time__month"),
    ],
)
def test_saved_query_group_by_becomes_a_request_name(spec, name):
    assert group_by_name(spec) == name


def test_unknown_group_by_shapes_are_refused():
    with pytest.raises(ValueError, match="unsupported"):
        group_by_name("Metric('demand', group_by=['balancing_authority'])")
