from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gridpulse_ingestion.eia.models import RegionDataRow
from gridpulse_ingestion.ratelimit import TokenBucket

ROW = {
    "period": "2026-10-01T00",
    "respondent": "PJM",
    "respondent-name": "PJM Interconnection, LLC",
    "type": "D",
    "type-name": "Demand",
    "value": "103443",
    "value-units": "megawatthours",
}


def test_every_recorded_row_validates(region_pages):
    rows = [r for page in region_pages for r in page["response"]["data"]]
    parsed = [RegionDataRow.model_validate(r) for r in rows]
    assert {p.type for p in parsed} == {"D", "DF", "NG", "TI"}


def test_keeps_value_as_string_and_derives_utc():
    row = RegionDataRow.model_validate(ROW)
    assert row.value == "103443"
    assert row.period_utc == datetime(2026, 10, 1, 0, tzinfo=UTC)


def test_null_value_is_allowed():
    assert RegionDataRow.model_validate({**ROW, "value": None}).value is None


def test_unknown_fields_are_kept_not_rejected():
    row = RegionDataRow.model_validate({**ROW, "new-field": "x"})
    assert row.extra_fields == {"new-field": "x"}


@pytest.mark.parametrize(
    "bad",
    [
        {k: v for k, v in ROW.items() if k != "respondent"},  # missing required field
        {k: v for k, v in ROW.items() if k != "value"},  # value must be present (may be null)
        {**ROW, "type": "XX"},  # unknown series code
        {**ROW, "value": "n/a"},  # non-numeric value
        {**ROW, "period": "2026-10-01"},  # not an hourly period
    ],
)
def test_rejects_breaking_rows(bad):
    with pytest.raises(ValidationError):
        RegionDataRow.model_validate(bad)


def test_token_bucket_spaces_requests():
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    bucket = TokenBucket(rate_per_second=2.0, clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        bucket.acquire()

    # First request is free; the next four wait 0.5 s each at 2 requests/second.
    assert now[0] == pytest.approx(2.0)
    assert len(slept) == 4
