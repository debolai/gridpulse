"""fuel-type-data and interchange-data: real recorded responses through the same client and
run path as region-data."""

from datetime import UTC, datetime

import httpx
import pytest
import respx
from eia_fixtures import recorded_meta, recorded_pages
from pydantic import ValidationError
from test_eia_client import END, START, make_client

from gridpulse_ingestion.eia.models import FuelTypeRow, InterchangeRow
from gridpulse_ingestion.eia.routes import FUEL_TYPE_DATA, INTERCHANGE_DATA, ROUTES
from gridpulse_ingestion.run import to_record
from gridpulse_ingestion.storage import raw_table_schema

NEW_ROUTES = [FUEL_TYPE_DATA, INTERCHANGE_DATA]


def serve(route, pages):
    by_offset, offset = {}, 0
    for page in pages:
        by_offset[offset] = page
        offset += len(page["response"]["data"])
    url = f"https://api.eia.gov/v2/{route.path}"
    return respx.mock.get(url).mock(
        side_effect=lambda req: httpx.Response(200, json=by_offset[int(req.url.params["offset"])])
    )


@pytest.mark.parametrize("route", NEW_ROUTES, ids=lambda r: r.name)
@respx.mock
def test_paginates_real_responses_with_the_route_sort_and_facet(route):
    pages_in = recorded_pages(route.name)
    mock = serve(route, pages_in)
    pages = list(make_client().fetch_window(route, START, END, ("ERCO", "PJM")))

    assert sum(len(p.rows) for p in pages) == recorded_meta(route.name)["total"]
    assert mock.call_count == len(pages_in) > 1
    params = mock.calls[0].request.url.params
    assert [params[f"sort[{i}][column]"] for i in range(3)] == list(route.sort_columns)
    assert params.get_list(f"facets[{route.facet}][]") == ["ERCO", "PJM"]


@pytest.mark.parametrize("route", NEW_ROUTES, ids=lambda r: r.name)
def test_every_recorded_row_becomes_a_raw_record(route):
    rows = [r for page in recorded_pages(route.name) for r in page["response"]["data"]]
    schema_names = {f.name for f in raw_table_schema(route).fields}
    now = datetime(2026, 10, 13, tzinfo=UTC)
    records = [to_record(route, r, run_id="r", ingested_at=now, api_version="2") for r in rows]
    assert all(set(rec) == schema_names for rec in records)
    assert len({rec["_record_hash"] for rec in records}) == len(records)  # hash identifies a row


def test_fuel_rows_cover_the_mix_and_accept_new_codes():
    rows = [r for page in recorded_pages("fuel-type-data") for r in page["response"]["data"]]
    codes = {FuelTypeRow.model_validate(r).fueltype for r in rows}
    assert {"NG", "NUC", "WND", "SUN"} <= codes
    # A code EIA adds later (as with battery types in 2024) must not stop the pipeline.
    assert FuelTypeRow.model_validate({**rows[0], "fueltype": "NEWX"}).fueltype == "NEWX"


def test_interchange_keeps_the_sign():
    rows = [r for page in recorded_pages("interchange-data") for r in page["response"]["data"]]
    values = [float(InterchangeRow.model_validate(r).value) for r in rows if r["value"]]
    assert min(values) < 0 < max(values)  # imports and exports both present, sign untouched


@pytest.mark.parametrize(
    ("model", "field", "bad"),
    [
        (FuelTypeRow, "fueltype", "natural gas"),  # a name, not a code
        (FuelTypeRow, "respondent", ""),
        (InterchangeRow, "toba", "pjm"),
    ],
)
def test_rejects_malformed_codes(model, field, bad):
    route = next(r for r in ROUTES.values() if r.model is model)
    row = recorded_pages(route.name)[0]["response"]["data"][0]
    with pytest.raises(ValidationError):
        model.model_validate({**row, field: bad})
