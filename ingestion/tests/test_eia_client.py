import json
from datetime import UTC, datetime

import httpx
import pytest
import respx
from tenacity import wait_none

from gridpulse_ingestion.eia.client import (
    EIAAPIError,
    EIAClient,
    IncompleteExtractError,
    RetryableStatusError,
)
from gridpulse_ingestion.eia.routes import REGION_DATA

URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
START = datetime(2026, 10, 1, 0, tzinfo=UTC)
END = datetime(2026, 10, 1, 12, tzinfo=UTC)
KEY = "test-key-should-never-leak"


class NoWait:
    def acquire(self) -> None:
        pass


def make_client(**kwargs) -> EIAClient:
    return EIAClient(KEY, page_size=40, limiter=NoWait(), wait=wait_none(), **kwargs)


def serve_pages(mock: respx.MockRouter, pages: list[dict]) -> respx.Route:
    by_offset, offset = {}, 0
    for page in pages:
        by_offset[offset] = page
        offset += len(page["response"]["data"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=by_offset[int(request.url.params["offset"])])

    return mock.get(URL).mock(side_effect=handler)


@respx.mock
def test_paginates_real_responses_to_the_reported_total(region_pages, region_meta):
    route = serve_pages(respx.mock, region_pages)
    pages = list(make_client().fetch_window(REGION_DATA, START, END, ("ERCO", "PJM")))

    assert [len(p.rows) for p in pages] == [40, 40, 16]
    assert sum(len(p.rows) for p in pages) == region_meta["total"] == pages[-1].total
    assert [p.offset for p in pages] == [0, 40, 80]
    assert route.call_count == 3


@respx.mock
def test_request_uses_total_sort_order_and_inclusive_end(region_pages):
    route = serve_pages(respx.mock, region_pages)
    list(make_client().fetch_window(REGION_DATA, START, END, ("ERCO", "PJM")))

    params = route.calls[0].request.url.params
    # Window [00, 12) is sent as start=00, end=11 because EIA's `end` is inclusive.
    assert params["start"] == "2026-10-01T00"
    assert params["end"] == "2026-10-01T11"
    assert [params[f"sort[{i}][column]"] for i in range(3)] == ["period", "respondent", "type"]
    assert params.get_list("facets[respondent][]") == ["ERCO", "PJM"]
    assert params["length"] == "40"


@respx.mock
def test_short_page_fails_the_completeness_check(region_pages):
    truncated = json.loads(json.dumps(region_pages))
    truncated[2]["response"]["data"] = truncated[2]["response"]["data"][:10]
    truncated.append({**truncated[2], "response": {**truncated[2]["response"], "data": []}})
    serve_pages(respx.mock, truncated)

    with pytest.raises(IncompleteExtractError):
        list(make_client().fetch_window(REGION_DATA, START, END))


@respx.mock
def test_retries_throttling_then_succeeds(region_pages):
    single = json.loads(json.dumps(region_pages[0]))
    single["response"]["total"] = "40"
    route = respx.mock.get(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(503), httpx.Response(200, json=single)]
    )

    pages = list(make_client().fetch_window(REGION_DATA, START, END))

    assert route.call_count == 3
    assert len(pages[0].rows) == 40


@respx.mock
def test_gives_up_after_max_attempts_without_leaking_the_key():
    respx.mock.get(URL).mock(return_value=httpx.Response(429))

    with pytest.raises(RetryableStatusError) as exc_info:
        list(make_client(max_attempts=3).fetch_window(REGION_DATA, START, END))

    assert respx.mock.calls.call_count == 3
    assert KEY not in str(exc_info.value)


@respx.mock
def test_api_error_is_not_retried():
    route = respx.mock.get(URL).mock(
        return_value=httpx.Response(400, json={"error": "Invalid facet", "code": 400})
    )

    with pytest.raises(EIAAPIError, match="Invalid facet") as exc_info:
        list(make_client().fetch_window(REGION_DATA, START, END))

    assert route.call_count == 1
    assert KEY not in str(exc_info.value)


@respx.mock
def test_reads_top_level_warnings(region_pages):
    serve_pages(respx.mock, region_pages)
    page = next(make_client().fetch_window(REGION_DATA, START, END))
    assert page.warnings[0]["warning"] == "incomplete return"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 10, 1, 0), datetime(2026, 10, 1, 1)),  # naive
        (datetime(2026, 10, 1, 0, 30, tzinfo=UTC), datetime(2026, 10, 1, 2, tzinfo=UTC)),
        (END, START),
    ],
)
def test_rejects_bad_windows(start, end):
    with pytest.raises(ValueError):
        list(make_client().fetch_window(REGION_DATA, start, end))
